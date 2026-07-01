#!/usr/bin/env python3
"""SessionStart hook — inject the agent's live memory into every new session.

Neither state.md nor continuity.md is read just because it exists on disk — a
file in the workspace is not context in the session. This hook closes that loop:
on session start it resolves the agent + sub-mode from the session's cwd and
injects, as SessionStart additionalContext,

  1. the agent's ``state.md``          — the active-items index (what's in flight), and
  2. the sub-mode's ``continuity.md``  — the running memory (what past runs did),

so the session starts sighted instead of cold. It is the READ half of the
post-session-review loop, whose WRITE half is the review's Phase D.

Sub-mode resolution (MUST match the review's Phase D writer and the engine's
resolve_submode): the first path component of cwd under {agent_root}/{Name};
empty (cwd == the agent root) → "chat", the default cockpit mode. Cockpit
sessions run at the agent root — they are NOT required to cd into chat/, so the
project-dir key (transcripts + memory) is never disturbed; "chat" is only the
label under which their continuity is stored ({Name}/chat/continuity.md).

The "review" sub-mode is skipped — the automated reviewer operates on the ended
session's transcript and reconciles state.md itself; it needs no injection.

Config: agent_root from $JSTACK_REVIEW_CONFIG (default ~/.claude/jstack/review.json),
falling back to ~/Agents — the same resolution the review engine uses. An agent
is recognized iff {agent_root}/{Name}/review/ exists (the reviewable marker).

Defensive: any error → silent exit 0, empty output. A SessionStart hook must
never block or corrupt a session. Stdlib only, no host dependency.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _agent_root() -> Path:
    cfg_path = Path(
        os.environ.get(
            "JSTACK_REVIEW_CONFIG",
            str(Path.home() / ".claude" / "jstack" / "review.json"),
        )
    ).expanduser()
    root = "~/Agents"
    try:
        data = json.loads(cfg_path.read_text())
        if isinstance(data, dict) and data.get("agent_root"):
            root = data["agent_root"]
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return Path(root).expanduser()


def resolve(cwd: Path, root: Path) -> tuple[Path | None, str | None]:
    """(agent_dir, submode) for a workspace session, else (None, None).

    submode is the first path segment under {root}/{Name}, or "chat" at the root.
    Recognized only when {Name}/review/ exists — same gate the engine uses."""
    try:
        rel = cwd.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return None, None
    if not rel.parts:
        return None, None
    agent_dir = root / rel.parts[0]
    if not (agent_dir / "review").is_dir():
        return None, None
    submode = rel.parts[1] if len(rel.parts) >= 2 else "chat"
    return agent_dir, submode


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def build_context(agent_dir: Path, submode: str) -> str:
    blocks = []
    state = _read(agent_dir / "state.md")
    if state:
        blocks.append(
            f"### {agent_dir.name} — state.md · the active-items index "
            f"(authoritative for what is in flight)\n\n{state}"
        )
    cont = _read(agent_dir / submode / "continuity.md")
    if cont:
        blocks.append(
            f"### {agent_dir.name} · {submode} — continuity.md · the running memory "
            f"(what prior runs did; you are not starting cold)\n\n{cont}"
        )
    if not blocks:
        return ""
    return (
        "<jstack-continuity>\n"
        "Injected on entry by JStack — your persistent working state for this agent. "
        "Read it before acting: state.md is the source of truth for what's open, and "
        "continuity.md is what prior runs already did (don't re-discover or re-propose it).\n\n"
        + "\n\n---\n\n".join(blocks)
        + "\n</jstack-continuity>"
    )


def main() -> int:
    if os.environ.get("JSTACK_CONTINUITY_INJECT_DISABLED"):
        return 0
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    cwd = payload.get("cwd") or os.getcwd()

    agent_dir, submode = resolve(Path(cwd), _agent_root())
    if agent_dir is None or submode == "review":
        return 0

    context = build_context(agent_dir, submode)
    if not context:
        return 0

    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
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
