"""The app is the terminal on the desk — open a session as a jRemote thread.

The dashboard's chat buttons used to spawn iTerm windows; iTerm is now an
on-demand viewer, and the jRemote app is where a session opens. Every button
creates its session *managed* (registered-first, on the board — that part is
`managed.py`'s), then hands the sid here to put a thread window in front of
The user:

- **On the Mac** (`open_thread`): `open` the app with a `jremote://session/…`
  link — Launch Services starts it if it isn't running, and the app opens the
  thread as its own window.
- **Anywhere else** (`thread_url`): the endpoint returns the same link and the
  dashboard page navigates to it, so the app on whatever device the user is
  holding opens the thread. This replaced the `.command`-download flow.

The link carries the agent identity (base id, display name, emoji) so the
app's window stands up without waiting for a board sync.
"""

import subprocess
from pathlib import Path
from urllib.parse import quote, urlencode

APP = "/Applications/jRemote.app"


def _identity(cwd: str) -> tuple[str, str, str]:
    """(agent_base, name, emoji) for a workspace path — the board's own
    resolution (`board.identity`), keyed off the cwd instead of a project
    dir. ('', '', '') for a non-agent directory."""
    from .hostenv import active_agents, project_dir_to_agent
    loc = str(Path(cwd).expanduser()).rstrip("/")
    parsed = project_dir_to_agent(loc.replace("/", "-").replace(".", "-"))
    if not parsed:
        return "", "", ""
    base = parsed[0]
    cfg = active_agents().get(base, {})
    return base, cfg.get("name") or base.capitalize(), cfg.get("emoji", "")


def create(cwd: str, sid: str | None = None, resume: bool = False,
           extra: str = "", prelude: str = "", name: str = "") -> str:
    """The buttons' create: a fresh (or materialized) managed session in
    `cwd`, registered-first and windowless — the board row is the visibility,
    the caller decides which device shows a window. Returns the sid.

    `extra`/`prelude` are `open_managed`'s pass-throughs (model flags, an
    argv first-prompt, an env prefix) — the caller quotes them for the
    pane's shell. A session already open is left as it is (`open_managed`
    is idempotent)."""
    import uuid
    from . import board_watch, managed
    sid = sid or str(uuid.uuid4())
    managed.record_open(sid, _identity(cwd)[0], name=name)
    managed.open_managed(sid, cwd, resume=resume, extra=extra, prelude=prelude)
    board_watch.poke()
    return sid


def thread_url(sid: str, cwd: str = "") -> str:
    """The `jremote://session/…` link that opens `sid` in the app."""
    base, name, emoji = _identity(cwd) if cwd else ("", "", "")
    params = {k: v for k, v in
              (("agent", base), ("name", name), ("emoji", emoji)) if v}
    # `quote_via=quote`: a space is `%20`, never `+`. The app parses a plain
    # URI query, where `+` is a literal plus — a display name with a space
    # would arrive with one in it.
    query = f"?{urlencode(params, quote_via=quote)}" if params else ""
    return f"jremote://session/{sid}{query}"


def open_url(url: str) -> bool:
    """Hand a `jremote://` link to the Mac's jRemote app. True when `open`
    took it. Pinned to the /Applications copy so a stale derivedData build
    can never claim the link; falls back to plain Launch Services if that
    copy is missing."""
    for cmd in (["open", "-a", APP, url], ["open", url]):
        try:
            if subprocess.run(cmd, capture_output=True, timeout=10).returncode == 0:
                return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def open_thread(sid: str, cwd: str = "") -> bool:
    """Open `sid` as a thread window in the Mac's jRemote app."""
    return open_url(thread_url(sid, cwd))
