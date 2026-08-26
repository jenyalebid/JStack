#!/usr/bin/env python3
"""JStack Stop hook — an open inbox item cannot be walked past.

The inbox is a priority channel: an addressed message must be acted on,
closed, or deferred — never quietly ignored. Injection at SessionStart states
that law; this hook is what makes it hold when a session reads the injection
and gets on with something else anyway.

Mechanism: block the stop once per (session, message) with the open items and
the exact commands that close them. The model handles them and stops for real.
A compliant session never sees this hook — it closed its items already.

Who it binds:

  * **User-driven sessions** — every open item for the seat. A person's
    session is the seat's cockpit and the inbox is the seat's mail.
  * **Headless sessions** — ONLY the one item the session was woken for
    (its first prompt carries `[inbox:N]`). A cron worker whose job is a
    social post must never be hijacked by mail addressed to the cockpit;
    that is the whole reason messages are addressed to a seat. But the wake
    that exists BECAUSE of message N still has to close N.

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


def open_items(seat: str, session_id: str = "") -> list:
    """Open items for the seat, as this session sees them.

    The session id is passed rather than inherited: a bare defer means "not
    this session", so a guard that could not name its own session would block
    on the item the agent just deferred."""
    argv = [str(PLUGIN_BIN / "msg"), "pending-for", seat]
    if session_id:
        argv += ["--session", session_id]
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


def is_user_engaged(jsonl_path: Path) -> bool:
    """Same discriminator the timeline Stop hook uses: promptSource="typed"
    or TUI mode entries — only a human at a terminal produces either."""
    try:
        with jsonl_path.open() as f:
            for line in f:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = e.get("type")
                if t in ("mode", "permission-mode"):
                    return True
                if (t == "user" and not e.get("isMeta")
                        and e.get("promptSource") == "typed"):
                    return True
    except OSError:
        return False   # unreadable → treat as headless: bind only a wake's own item
    return False


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
    lines = [
        f"Inbox — {len(rows)} open item{'s' if len(rows) != 1 else ''} addressed to "
        f"{seat}. These are not optional and they are not background reading: each "
        "one gets acted on, closed, or deferred before this session ends.",
        "",
    ]
    for r in rows:
        head = f"[#{r['id']}] from {r['from_seat']}"
        if r.get("wake"):
            head += " · WAKE (they need this now)"
        lines.append(head)
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
        "Do the thing the message asks for, then record it:",
        f'  {PLUGIN_BIN}/msg done <id> --note "what you actually did"',
        "",
        "Or, if it genuinely belongs later — a real blocker, not reluctance. "
        "Bare = the next session picks it up; a named hour books a wake to act "
        "then, so only name one when that hour is the point:",
        f'  {PLUGIN_BIN}/msg defer <id> --note "why"',
        f'  {PLUGIN_BIN}/msg defer <id> --until "YYYY-MM-DD HH:MM" --note "why"',
        "",
        "To answer the sender (they get it in their own inbox, or live if they're "
        "running):",
        f'  {PLUGIN_BIN}/msg reply <id> "..." [--wake]',
        "",
        "Then stop. Handle only the inbox here — do not start unrelated work.",
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

    rows = open_items(seat, session_id)
    if not rows:
        allow()

    transcript = Path(d.get("transcript_path") or "").expanduser()
    if not is_user_engaged(transcript):
        # Headless: bind ONLY the item this session was woken for. An
        # unrelated cron worker in this seat stops untouched.
        woken = _WAKE_MARKER.search(first_prompt(transcript))
        if not woken:
            allow()
        wid = woken.group(1)
        rows = [r for r in rows if str(r["id"]) == wid]
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
