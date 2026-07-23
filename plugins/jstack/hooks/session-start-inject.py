#!/usr/bin/env python3
"""SessionStart hook — inject the seat's recent timeline history into new sessions.

A file on disk is not context in a session. This hook closes the loop on the
timeline (the single running memory): on session start it resolves the agent +
sub-mode from the session's cwd and injects that seat's last N timeline entries
as SessionStart additionalContext, so the session starts sighted instead of
cold. The WRITE half is the session-end engine (selfwrite/review) and the Stop
hook for auto sessions — both log via `log_event <agent/submode> ...`; the
injection reads back through `log_event tail`.

Injection fires ONLY into live, human-driven sessions — that is the point of
it: a person sitting down mid-history. Headless spawns (schedulers, watchers,
daemons running `claude --print`) never inject, for every seat, regardless of
config.

Which seats get injected, and how many entries, is host config — the
`timeline_inject` map in $JSTACK_REVIEW_CONFIG (~/.claude/jstack/review.json):

    "timeline_inject": {"alpha/chat": 10, "*/pm": 10, "*/social": 10}

Values are an int, or a legacy {"n": N, ...} dict (extra keys ignored). Match
is per-dir, nearest wins: at each depth exact "agent/seat" beats wildcard
"*/seat", then the seat's parent dir is tried ("alpha/social/chat" falls back
to "*/social"). Seats with no match anywhere up get nothing. No config key →
no injection anywhere (opt-in).

Seat resolution (MUST match the engine's resolve_submode and the Stop hook):
the session dir's full path under {agent_root}/{Name}, "/"-joined — seats are
directories, and each dir is its own seat (chat ≠ social/chat ≠ social); empty
(cwd == the agent root) → "chat", the default cockpit mode. Cockpit sessions
run at the agent root — they are NOT required to cd into chat/, so the
project-dir key (transcripts + memory) is never disturbed. The tail a seat
injects is its own dir plus ancestor dirs, never siblings (log_event tail
semantics). The "review" sub-mode is skipped.

Defensive: any error → silent exit 0, empty output. A SessionStart hook must
never block or corrupt a session. Stdlib only, no host dependency.
Kill switch: JSTACK_TIMELINE_INJECT_DISABLED=1 (legacy
JSTACK_CONTINUITY_INJECT_DISABLED honored too).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PLUGIN_BIN = Path(__file__).resolve().parent.parent / "bin"


def _config() -> dict:
    cfg_path = Path(
        os.environ.get(
            "JSTACK_REVIEW_CONFIG",
            str(Path.home() / ".claude" / "jstack" / "review.json"),
        )
    ).expanduser()
    try:
        data = json.loads(cfg_path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def resolve(cwd: Path, root: Path) -> tuple[str | None, str | None]:
    """(agent, submode) for a workspace session, else (None, None).

    submode is the session dir's full path under {root}/{Name} ("/"-joined —
    per-dir seats: social/chat is its own seat, distinct from chat and from
    social), or "chat" at the agent root. Recognized only when {Name}/CLAUDE.md
    exists — same gate the engine uses."""
    try:
        rel = cwd.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return None, None
    if not rel.parts:
        return None, None
    agent_dir = root / rel.parts[0]
    if not (agent_dir / "CLAUDE.md").is_file():
        return None, None
    submode = "/".join(p.lower() for p in rel.parts[1:]) or "chat"
    return agent_dir.name.lower(), submode


_NO_TTY = {"??", "?", "-", ""}


def _is_interactive() -> bool:
    """A human-driven session has a controlling terminal somewhere; headless
    spawns (schedulers, watchers, daemons running `claude --print`) sit in a
    launchd/init-rooted chain with none.

    The CLI spawns hooks detached from its controlling terminal, so opening
    /dev/tty inside a hook fails even when a human is driving — the terminal
    lives on the CLI process up the ancestry. Try /dev/tty (covers direct
    invocation), then walk parents via ps and count any ancestor holding a
    tty as interactive. JSTACK_ASSUME_INTERACTIVE=1 short-circuits to True —
    for hosts (or tests) whose spawn shape defeats the ancestry walk."""
    if os.environ.get("JSTACK_ASSUME_INTERACTIVE"):
        return True
    try:
        with open("/dev/tty"):
            return True
    except OSError:
        pass
    pid = os.getppid()
    for _ in range(8):
        if pid <= 1:
            return False
        try:
            out = subprocess.run(
                ["ps", "-o", "tty=,ppid=", "-p", str(pid)],
                capture_output=True, text=True, timeout=3,
            ).stdout.split()
        except (OSError, subprocess.SubprocessError):
            return False
        if len(out) < 2:
            return False
        if out[0] not in _NO_TTY:
            return True
        try:
            pid = int(out[1])
        except ValueError:
            return False
    return False


def inject_count(cfg: dict, agent: str, submode: str) -> int:
    """Entries to inject for a seat — per-dir, nearest match wins.

    At each depth the exact "agent/seat" key beats "*/seat"; no hit → try the
    seat's parent dir. Values are an int or a legacy {"n": N, ...} dict (extra
    keys ignored — whether to inject at all is the caller's live-session gate,
    not per-seat config)."""
    inject = cfg.get("timeline_inject")
    if not isinstance(inject, dict):
        return 0
    seat = submode
    while True:
        for key in (f"{agent}/{seat}", f"*/{seat}"):
            if key not in inject:
                continue
            val = inject[key]
            try:
                return int(val.get("n", 0)) if isinstance(val, dict) else int(val)
            except (TypeError, ValueError):
                return 0
        if "/" not in seat:
            return 0
        seat = seat.rsplit("/", 1)[0]


def tail(seat: str, n: int) -> str:
    try:
        r = subprocess.run(
            [str(PLUGIN_BIN / "log_event"), "tail", seat, "-n", str(n)],
            capture_output=True, text=True, timeout=8,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def build_context(agent: str, submode: str, entries: str, n: int) -> str:
    seat = f"{agent}/{submode}"
    return (
        "<jstack-timeline>\n"
        f"Injected on entry by JStack — the last timeline entries {seat} (your seat) "
        "wrote, oldest first. This is your own recent history: you are not starting "
        "cold. Build on it — don't re-discover, re-propose, or re-litigate what's "
        "already below. A `↳ verdict:` line is the independent review's call on that "
        "run — if its note names a move to avoid, pick differently.\n\n"
        f"{entries}\n"
        "</jstack-timeline>"
    )


def main() -> int:
    if os.environ.get("JSTACK_TIMELINE_INJECT_DISABLED") or \
            os.environ.get("JSTACK_CONTINUITY_INJECT_DISABLED"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    cwd = payload.get("cwd") or os.getcwd()

    cfg = _config()
    root = Path(cfg.get("agent_root") or "~/Agents").expanduser()
    agent, submode = resolve(Path(cwd), root)
    if agent is None or submode == "review":
        return 0

    n = inject_count(cfg, agent, submode)
    if n <= 0 or not _is_interactive():
        return 0
    entries = tail(f"{agent}/{submode}", n)
    if not entries:
        return 0

    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": build_context(agent, submode, entries, n),
                }
            }
        )
    )
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:  # never block a session
        raise SystemExit(0)
