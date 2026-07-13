#!/usr/bin/env python3
"""SessionStart hook — inject the seat's recent timeline history into new sessions.

A file on disk is not context in a session. This hook closes the loop on the
timeline (the single running memory): on session start it resolves the agent +
sub-mode from the session's cwd and injects that seat's last N timeline entries
as SessionStart additionalContext, so the session starts sighted instead of
cold. The WRITE half is the session-end engine (selfwrite/review) and the Stop
hook for auto sessions — both log via `log_event <agent/submode> ...`; the
injection reads back through `log_event tail`.

Which seats get injected, and how many entries, is host config — the
`timeline_inject` map in $JSTACK_REVIEW_CONFIG (~/.claude/jstack/review.json):

    "timeline_inject": {"alpha/chat": 10, "*/pm": 10,
                        "*/social": {"n": 10, "interactive_only": true}}

Match forms: exact "agent/submode" wins over wildcard "*/submode". Seats not
matched get nothing. No config key → no injection anywhere (opt-in).

Sub-mode resolution (MUST match the engine's resolve_submode and the Stop
hook): the first path component of cwd under {agent_root}/{Name}; empty (cwd ==
the agent root) → "chat", the default cockpit mode. Cockpit sessions run at the
agent root — they are NOT required to cd into chat/, so the project-dir key
(transcripts + memory) is never disturbed. The "review" sub-mode is skipped.

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

    submode is the first path segment under {root}/{Name}, or "chat" at the root.
    Recognized only when {Name}/CLAUDE.md exists — same gate the engine uses."""
    try:
        rel = cwd.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return None, None
    if not rel.parts:
        return None, None
    agent_dir = root / rel.parts[0]
    if not (agent_dir / "CLAUDE.md").is_file():
        return None, None
    submode = rel.parts[1] if len(rel.parts) >= 2 else "chat"
    return agent_dir.name.lower(), submode.lower()


def _is_interactive() -> bool:
    """A human-driven session has a controlling terminal; headless spawns
    (schedulers, watchers, daemons running `claude --print`) don't."""
    try:
        with open("/dev/tty"):
            return True
    except OSError:
        return False


def inject_count(cfg: dict, agent: str, submode: str) -> int:
    """Entries to inject for a seat. Map values are either a plain int (always
    inject) or {"n": N, "interactive_only": true} — inject only into sessions
    a human is driving, so high-frequency automated wakes (e.g. social reply
    wakes) run lean instead of booting N entries of baggage."""
    inject = cfg.get("timeline_inject")
    if not isinstance(inject, dict):
        return 0
    for key in (f"{agent}/{submode}", f"*/{submode}"):
        if key not in inject:
            continue
        val = inject[key]
        try:
            if isinstance(val, dict):
                if val.get("interactive_only") and not _is_interactive():
                    return 0
                return int(val.get("n", 0))
            return int(val)
        except (TypeError, ValueError):
            return 0
    return 0


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
    if n <= 0:
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
