#!/usr/bin/env python3
"""JStack Stop hook — a task handed to THIS session gets its answer.

A task is another agent's blocking request: they sent it with `--wake`, it was
delivered into this session, and they are waiting on the reply. Ending the
turn without answering leaves them waiting on something that will never come.
This hook is what makes the answer happen.

It binds one thing and one thing only: **tasks handed to this exact session** —
either typed into it live (the task records this session id) or the task this
session was spawned for (its first prompt carries `[inbox:N]`).

What it will never do is surface something that was merely sitting around.
Updates are not tasks and are never blocked on. A task belonging to another
session — one that was never delivered here — is invisible to this hook. So
opening a chat cannot make an agent go off doing whatever accumulated in a
mailbox: nothing accumulates, and nothing undelivered is discoverable.

Loop guards (all three):
  - `stop_hook_active` — the harness sets it while the model is continuing
    from a Stop-hook block. Never block again.
  - a per-session marker listing message ids already blocked on, so a long
    session gets one block per message, not one per turn.
  - the marker is written BEFORE the block is emitted; if it cannot be
    written, the hook allows rather than risk a loop.

Kill switch: JSTACK_INBOX_GUARD_DISABLED=1. Review spawns and other plumbing
set SKIP_SESSION_HOOK=1 — honored here.

Defensive: any error → silent allow. A Stop hook must never wedge a session.
Stdlib only, no host dependency.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_BIN = Path(__file__).resolve().parent.parent / "bin"
STATE_DIR = Path(os.environ.get(
    "JSTACK_REVIEW_STATE", str(Path.home() / ".claude" / "jstack" / "review-state")
)).expanduser() / "inbox-guarded"

#: The routing marker a wake carries in its first prompt (bin/msg _wake_prompt).
_WAKE_MARKER = re.compile(r"\[inbox:(\d+)\]")


def allow():
    sys.exit(0)


def _config() -> dict:
    path = Path(os.environ.get(
        "JSTACK_REVIEW_CONFIG",
        str(Path.home() / ".claude" / "jstack" / "review.json"),
    )).expanduser()
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def resolve_seat(cwd: str) -> "str|None":
    """agent/submode for a workspace session — the same seat resolution the
    SessionStart injector and the review engine use."""
    root = Path(_config().get("agent_root") or "~/Agents").expanduser()
    try:
        rel = Path(cwd).resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    if not rel.parts or not (root / rel.parts[0] / "CLAUDE.md").is_file():
        return None
    submode = "/".join(p.lower() for p in rel.parts[1:]) or "chat"
    return f"{rel.parts[0].lower()}/{submode}"


def open_items(seat: str, session_id: str = "", woken: str = "") -> list:
    """Tasks handed to THIS session and still unanswered.

    Both handles are passed explicitly rather than inherited: the session id
    matches a task typed in live, `woken` the task this run was spawned for.
    A task matching neither was never delivered here and is not ours."""
    argv = [str(PLUGIN_BIN / "msg"), "pending-for", seat]
    if session_id:
        argv += ["--session", session_id]
    if woken:
        argv += ["--woken", woken]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return []
    if not r.stdout.strip():
        return []
    try:
        rows = json.loads(r.stdout)
        return rows if isinstance(rows, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def first_prompt(jsonl_path: Path) -> str:
    """The session's opening user message — where a wake's routing marker is."""
    try:
        with jsonl_path.open() as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("type") != "user" or e.get("isMeta"):
                    continue
                msg = e.get("message") or {}
                content = msg.get("content")
                if isinstance(content, list):
                    content = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict))
                if isinstance(content, str) and content.strip():
                    return content
    except OSError:
        pass
    return ""


def already_blocked(session_id: str) -> set:
    try:
        return set((STATE_DIR / session_id).read_text().split())
    except OSError:
        return set()


def record_blocked(session_id: str, ids: set) -> bool:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        path = STATE_DIR / session_id
        prior = already_blocked(session_id)
        path.write_text("\n".join(sorted(prior | ids)))
        return True
    except OSError:
        return False


def build_reason(rows: list, seat: str) -> str:
    n = len(rows)
    lines = [
        f"{n} task{'s' if n != 1 else ''} {'were' if n != 1 else 'was'} handed to "
        f"this session and {'have' if n != 1 else 'has'} no answer yet. The sender "
        f"is blocked waiting on it — answer before the turn ends.",
        "",
    ]
    for r in rows:
        lines.append(f"[#{r['id']}] from {r['from_seat']}")
        lines.append(f"  {r['subject']}")
        if r.get("body"):
            body = r["body"].strip().splitlines()
            lines.extend("  " + ln for ln in body[:6])
            if len(body) > 6:
                lines.append(f"  … ({len(body) - 6} more lines — msg read {r['id']})")
        for att in json.loads(r.get("attachments") or "[]"):
            lines.append(f"  attached: {att}")
        lines.append("")
    lines += [
        "Do it, then answer — the reply IS the close, there is nothing else:",
        f'  {PLUGIN_BIN}/msg reply <id> "what you did, or the answer they wanted"',
        "",
        "If you cannot do it, say that in the reply and why. An answer that "
        "reports a refusal or a blocker is a real answer; silence is not.",
        "",
        "Then stop. This is the only thing you owe anyone here — do not go "
        "looking for other mail and do not start unrelated work.",
    ]
    return "\n".join(lines)


def main() -> None:
    if os.environ.get("SKIP_SESSION_HOOK") == "1":
        allow()
    if os.environ.get("JSTACK_INBOX_GUARD_DISABLED") == "1":
        allow()
    try:
        d = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError, ValueError):
        allow()

    if d.get("stop_hook_active"):
        allow()

    session_id = d.get("session_id") or ""
    seat = resolve_seat(d.get("cwd") or "")
    if not session_id or not seat:
        allow()

    transcript = Path(d.get("transcript_path") or "").expanduser()
    m = _WAKE_MARKER.search(first_prompt(transcript))
    rows = open_items(seat, session_id, m.group(1) if m else "")
    if not rows:
        allow()

    ids = {str(r["id"]) for r in rows}
    fresh = ids - already_blocked(session_id)
    if not fresh:
        allow()   # already blocked on every one of these — say it once, not per turn
    rows = [r for r in rows if str(r["id"]) in fresh]

    if not record_blocked(session_id, fresh):
        allow()   # can't guarantee once-only → never risk a loop

    print(json.dumps({"decision": "block", "reason": build_reason(rows, seat)}))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception:   # never wedge a session
        allow()
