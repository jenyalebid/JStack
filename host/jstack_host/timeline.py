"""The timeline's tag vocabulary — the subjects a session can be opened ON.

A seat answers "who", a date answers "when"; neither answers "everything we did
on X". The timeline's tag is that axis, and jRemote's use for it is the pinned
subject: a board pin that opens a session whose injected history is the TAG's,
across every agent that worked it, instead of the seat's own. The host's part
is small and entirely read-only — serve the vocabulary so the app can offer it,
and refuse a pin naming a tag nobody minted.

**Read-only, deliberately.** `bin/log_event` is the timeline's single writer;
this module never writes, never mints a tag, and never touches the sqlite file
directly. A second writer forks the source of truth, and a tag minted by a UI
would defeat the one property that makes tags worth having — a small vocabulary
that means the same thing to every writer.

**Optional, like every other borrowed screen.** The timeline belongs to JStack,
not to this package: a Mac running the host with no JStack install has no
vocabulary, and that is a normal answer, not a fault. `available()` says so and
the routes report absence rather than an empty list — "no tags exist" and "this
host cannot see tags" are different answers, and a picker that silently shows
zero rows for the second is a broken screen with nothing explaining why.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import plugin_paths

#: `log_event tag list` on a cold cache is a sqlite open plus one join. Bounded
#: anyway: a hung binary must never be able to hold a board request open.
_TIMEOUT = 8


def log_event_bin() -> Path | None:
    """The jstack `log_event` binary, or None on a host without JStack.

    Where the plugin lives is `plugin_paths`' one answer — dev checkout first
    on the machine that maintains it (answering from a stale cache there would
    show a vocabulary the writers have already moved past), the newest
    installed version anywhere else. This module only decides what absence
    means, which is: no vocabulary, not an empty one.
    """
    binary = plugin_paths.jstack_bin("log_event")
    return binary if binary.exists() else None


def available() -> bool:
    return log_event_bin() is not None


def tags() -> list[dict]:
    """The whole vocabulary — `[{name, description, sessions}, ...]`.

    Empty on any failure, which callers must read together with `available()`:
    this is the "no tags minted yet" answer, and the route is what turns a host
    that cannot answer at all into an explicit absence.
    """
    binary = log_event_bin()
    if binary is None:
        return []
    try:
        r = subprocess.run([str(binary), "tag", "list", "--json"],
                           capture_output=True, text=True, timeout=_TIMEOUT)
        if r.returncode != 0:
            return []
        rows = json.loads(r.stdout or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return []
    return [t for t in rows if isinstance(t, dict) and t.get("name")]


def normalize(name: str) -> str:
    """The same normalization `log_event` applies, so a pin stored here and the
    tag matched there are the same string."""
    return (name or "").strip().lower().lstrip("#")


def known(name: str) -> bool:
    """Is this a tag someone deliberately minted?

    The gate on every pin. A typo'd pin that were accepted would open a session
    on a subject with no history and no future — nothing to inject, and its own
    work filed under a name no other session will ever look for.
    """
    want = normalize(name)
    return bool(want) and any(t.get("name") == want for t in tags())
