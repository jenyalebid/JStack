"""Per-agent switches for how an agent's SESSIONS behave.

The third resident of the app's agent settings page, and the boundary between
the three is what each one is about:

* `notify.py` — whether the user is told about this agent's sessions.
* `engines.py` — what a new session of this agent's spawns on.
* here — what a session of this agent's does while it is running.

Keyed on the BASE agent, the same rule the other two use: `ops-chat` and
`ops-service-call` are seats of one agent, and the settings page is a page
about the agent. Stored as a list per flag rather than a dict per agent, so an
agent that has never been touched has no row at all and the absent case is the
default by construction, not by a `.get(..., False)` someone has to remember.

A flag not in `FLAGS` is refused rather than stored. The cost of a typo that
stores cleanly is a switch in the app that appears to work and changes nothing
on the Mac — the failure this whole module exists to be readable about.
"""

import json
import threading

from . import hostenv

_STATE = hostenv.state_dir() / "jremote_agent_prefs.json"
_lock = threading.Lock()

#: Every flag this host knows, with what it means. The app renders whatever is
#: here; nothing else is storable.
#:
#: `compact_when_done` — let the delivery-compaction Stop hook take a boundary
#: when a turn ends with NOTHING open in the session's task store. Mid-task
#: compaction is not a preference and is not in here: it rescues a session that
#: stopped under its own weight, and the continue hands its docket straight
#: back. The finished delivery is the one the user objected to — nothing resumes,
#: so the session sits at its summary and the next person to open it is the user,
#: reading a compaction they never asked for over the turn they came back to read.
FLAGS = ("compact_when_done",)


def _load() -> dict:
    try:
        d = json.loads(_STATE.read_text())
    except (OSError, json.JSONDecodeError):
        d = {}
    for flag in FLAGS:
        d.setdefault(flag, [])
    return d


def _save(d: dict) -> None:
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    _STATE.write_text(json.dumps(d, indent=1))


def base_agent(agent_id: str) -> str:
    """The agent behind a seat id. `engines`' rule, asked rather than copied."""
    from . import engines
    return engines.base_agent((agent_id or "").lower())


def enabled(flag: str) -> set[str]:
    """The agents this flag is on for. An unknown flag is on for nobody."""
    if flag not in FLAGS:
        return set()
    return {base_agent(a) for a in _load()[flag]}


def is_on(flag: str, agent_id: str) -> bool:
    return bool(agent_id) and base_agent(agent_id) in enabled(flag)


def set_flag(flag: str, agent_id: str, on: bool) -> None:
    """Switch a flag for an agent. Unknown flag or empty agent: refused here.

    The router turns those into a 400 — a POST that stored nothing and answered
    200 would leave the app showing a switch the Mac never agreed to.
    """
    base = base_agent(agent_id)
    if flag not in FLAGS or not base:
        raise ValueError(f"unknown flag or agent: {flag!r} / {agent_id!r}")
    with _lock:
        d = _load()
        current = {base_agent(a) for a in d[flag]}
        current.add(base) if on else current.discard(base)
        d[flag] = sorted(current)
        _save(d)


def prefs() -> dict:
    """What the settings page reads: every flag, and who it is on for."""
    return {flag: sorted(enabled(flag)) for flag in FLAGS}
