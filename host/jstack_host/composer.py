"""Lifting an agent's input box out of the CLI, whole.

Compose's first version read the box off the terminal grid. That works for one
short line and quietly corrupts everything else, because the grid is a *view*
of the buffer and never the buffer:

* **The box scrolls inside itself.** Once it stops growing it shows a window
  onto the text. 200 words in an 80x24 pane render as seven rows starting at
  word 145 — words 1 to 144 are in the buffer and nowhere on screen.
* **A paste is folded into a chip.** The grid says `[Pasted text #1]`; the
  buffer holds the paste.

Reading a subset is survivable on its own. The take then deleted the whole box
on the strength of it, and the words that were never read were the words that
died. That is the bug this module exists to end.

**The agent already hands the buffer over.** `chat:externalEditor` (ctrl+G, or
ctrl+X ctrl+E) writes the live input buffer — expanded, complete, chips
resolved — to `claude-prompt-<uuid>.md` and runs `$VISUAL` on it, then reads
the file back when that editor exits 0. Managed sessions are spawned with
`VISUAL=bin/jremote-compose-editor`, a shim that parks the path here and waits
(`open_managed` sets `JREMOTE_COMPOSE_DIR` and `JREMOTE_SID` beside it).

So a lift is: press ctrl+G, read the parked file, write back what the box
should hold now, release the shim. Sub-second, and the box is only out of the
user's hands for that moment — this is deliberately not a checkout that holds
the editor open for as long as someone is typing on a phone.

Every failure path leaves the buffer exactly as the user typed it. No park
file, a dead session, a session spawned before the shim existed: the lift
reports that it did not happen and *nothing is deleted*. The caller falls back
to leaving the text in the CLI, which is the outcome that loses nothing.
"""

import subprocess
import time
from pathlib import Path

from .hostenv import state_dir

# Where the shim parks. Under the host's own state dir, so a second instance on
# this Mac (JREMOTE_STATE_DIR) parks separately from the first.
COMPOSE_DIR = state_dir() / "jremote_compose"

# The shim writes its park file the moment the agent execs it. What we are
# waiting out is the agent noticing the keypress, serialising the buffer and
# spawning — milliseconds, but a busy pane mid-render can take longer.
PARK_TIMEOUT = 4.0

# After release, the shim exits and the agent reloads. We wait for the park
# file to go so a second lift can't collide with the first one's editor.
RELEASE_TIMEOUT = 4.0

POLL = 0.05


def compose_dir() -> Path:
    return COMPOSE_DIR


def _park(sid: str) -> Path:
    return COMPOSE_DIR / f"{sid}.park"


def _release(sid: str) -> Path:
    return COMPOSE_DIR / f"{sid}.release"


def _clear(sid: str) -> None:
    """Drop a previous lift's leavings before starting a new one.

    A stale park file from a shim that timed out would otherwise be read as
    this lift's answer — pointing at a prompt file the agent has long since
    reloaded and moved past.
    """
    for p in (_park(sid), _release(sid)):
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def _pane_has_shim(name: str) -> bool:
    """Is there an engine in this pane that will hand its buffer to us?

    Asked of the live process's own environment, not of a table this process
    keeps: the env is set when the pane's shell launches the engine, so a
    session started before the shim existed — or one whose engine has been
    restarted by hand — answers no on its own account. `psutil` is already how
    this package reads a pane's env (`managed._is_phone_client`).
    """
    from . import managed

    r = subprocess.run(managed._t("list-panes", "-t", name, "-F", "#{pane_pid}"),
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False
    try:
        import psutil
    except ImportError:
        return False
    for line in r.stdout.split():
        try:
            shell = psutil.Process(int(line))
            for proc in [shell, *shell.children(recursive=True)]:
                if proc.environ().get("JREMOTE_SID"):
                    return True
        except (psutil.Error, ValueError):
            continue
    return False


def _wait(path: Path, exists: bool, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() == exists:
            return True
        time.sleep(POLL)
    return path.exists() == exists


def lift(sid: str, replacement: str = "") -> dict:
    """Take the session's input buffer, and leave `replacement` in its place.

    Returns `{"lifted": True, "text": <the whole buffer>}`, or
    `{"lifted": False, "reason": ...}` — and a False answer is a promise that
    the buffer was not touched.
    """
    from . import managed

    name = managed._name(sid)
    if not managed.is_open(sid) or name not in managed.open_names():
        return {"lifted": False, "reason": "session is not a managed session"}

    if not _pane_has_shim(name):
        # ctrl+G is not a safe key to press on spec. Without the shim the agent
        # runs whatever $VISUAL/$EDITOR resolves to — on this Mac that is
        # `cot -w`, which throws a CotEditor window onto the desk and blocks
        # the CLI inside it until a hand closes it. A session spawned before
        # the shim existed gets the honest refusal instead.
        return {"lifted": False, "reason": "this session was started without the "
                                           "compose handoff — restart it to lift"}

    COMPOSE_DIR.mkdir(parents=True, exist_ok=True)
    _clear(sid)

    r = subprocess.run(managed._t("send-keys", "-t", name, "C-g"),
                       capture_output=True, text=True)
    if r.returncode != 0:
        return {"lifted": False, "reason": (r.stderr or "send-keys failed").strip()}

    if not _wait(_park(sid), True, PARK_TIMEOUT):
        # No shim answered. Either the session predates it (spawned without
        # VISUAL), or the agent had a dialog up and swallowed the key. The
        # buffer is untouched either way; the ctrl+G may have been a no-op.
        return {"lifted": False, "reason": "the CLI did not hand over its input box"}

    try:
        prompt = Path(_park(sid).read_text().strip())
        text = prompt.read_text()
    except OSError as e:
        # Release anyway — a shim left parked holds the session on a blank
        # alternate screen. Exiting with the file unread restores the buffer.
        _release(sid).touch()
        return {"lifted": False, "reason": f"could not read the handed-over file: {e}"}

    try:
        prompt.write_text(replacement)
    except OSError as e:
        _release(sid).touch()
        return {"lifted": False, "reason": f"could not write the file back: {e}"}

    _release(sid).touch()
    _wait(_park(sid), False, RELEASE_TIMEOUT)
    return {"lifted": True, "text": text}
