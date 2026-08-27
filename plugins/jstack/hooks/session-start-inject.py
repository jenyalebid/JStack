#!/usr/bin/env python3
"""SessionStart hook — inject the seat's recent timeline history into new sessions.

A file on disk is not context in a session. This hook closes the loop on the
timeline (the single running memory): on session start it resolves the agent +
sub-mode from the session's cwd and injects everything that seat's last N
SESSIONS wrote as SessionStart additionalContext, so the session starts sighted
instead of cold. The WRITE half is the session-end engine (selfwrite/review)
and the Stop hook for auto sessions — both log via `log_event <agent/submode>
...`; the injection reads back through `log_event tail --sessions`.

The window unit is the session, not the entry: "the last ten times I sat in
this seat" is what a person resuming actually means, and it holds steady when
a session writes more than one entry (pipeline consolidations, multi-topic
days) — an entry-counted window would quietly shorten the recalled history
exactly then. Rows with no session_id count as one session each.

Injection fires ONLY into live, human-driven sessions — that is the point of
it: a person sitting down mid-history. Headless spawns (schedulers, watchers,
daemons running `claude --print`) never inject, for every seat, regardless of
config. The content law is the mirror image: only `origin=direct` entries
ride the injection (`log_event tail --origin direct`) — auto sessions
neither receive injections nor appear in them.

Which seats get injected, and how many SESSIONS deep, is host config — the
`timeline_inject` map in $JSTACK_REVIEW_CONFIG (~/.claude/jstack/review.json):

    "timeline_inject": {"*/*": 10, "alpha/chat": 20, "*/pm": 5}

Values are an int session count, or a dict carrying it as {"sessions": N} (or
legacy {"n": N}; extra keys ignored — pre-session-window configs read as
session counts, which is the same number for the common one-entry session and
strictly more history otherwise, never less). Match
is per-dir, nearest wins: at each depth exact "agent/seat" beats wildcard
"*/seat", then the seat's parent dir is tried ("alpha/social/chat" falls back
to "*/social"). Finally `*/*` is the fleet default, so a newly-created seat
inherits injection without another registration edit. With no default, seats
with no match get nothing. No config key → no injection anywhere (opt-in).

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
    """Sessions to inject for a seat — per-dir, nearest match wins.

    At each depth the exact "agent/seat" key beats "*/seat"; no hit → try the
    seat's parent dir. Values are an int, or a dict carrying the count as
    "sessions" (legacy "n" honored — same key, now read as sessions; extra
    keys ignored — whether to inject at all is the caller's live-session
    gate, not per-seat config)."""
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
                if isinstance(val, dict):
                    return int(val.get("sessions", val.get("n", 0)))
                return int(val)
            except (TypeError, ValueError):
                return 0
        if "/" not in seat:
            try:
                val = inject.get("*/*", 0)
                if isinstance(val, dict):
                    return int(val.get("sessions", val.get("n", 0)))
                return int(val)
            except (TypeError, ValueError):
                return 0
        seat = seat.rsplit("/", 1)[0]


def tail(seat: str, n: int, as_json: bool = False) -> str:
    # --origin direct: the injection is a person sitting down mid-history —
    # it carries the seat's human-driven narrative only. Auto sessions
    # (origin=indirect: crons, publish wakes, spawned work) neither receive
    # injections (the live-session gate above) nor ride in them.
    cmd = [str(PLUGIN_BIN / "log_event"), "tail", seat, "--sessions", str(n),
           "--origin", "direct"]
    if as_json:
        cmd.append("--json")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def explain(seat: str) -> dict:
    """What a live session of `seat` would be injected, as data.

    THE answer for any consumer that needs to show or check the injection
    (dashboard markers, audits, tests): ask this instead of re-deriving the
    window from the timeline db. The config walk and the origin law live in
    exactly one place — a second implementation is a second truth, and the
    one that isn't the injector is the one that goes stale and lies.

    Liveness is deliberately NOT part of the answer: this is the
    hypothetical "if a person sat down in this seat right now", which is
    what a marker in a UI means. Shape:

        {"ok": bool, "seat": str, "sessions": int, "ids": [int, ...]}

    `sessions` is the configured window depth (0 = this seat injects
    nothing); `ids` are the entry ids inside it — more than one per session
    when a session logged more than once.

    ok=False means the answer could not be computed (log_event unreachable
    or unparseable) — a caller must render that as unknown, never as "these
    rows don't inject".
    """
    agent, _, submode = seat.partition("/")
    agent = agent.lower()
    submode = submode.lower() or "chat"
    out = {"ok": True, "seat": f"{agent}/{submode}", "sessions": 0, "ids": []}
    if not agent or submode == "review":
        return out
    out["sessions"] = n = inject_count(_config(), agent, submode)
    if n <= 0:
        return out
    raw = tail(out["seat"], n, as_json=True)
    if not raw:
        # No entries and a failed call are indistinguishable in the text
        # tail, so json mode is asked for explicitly: empty output here
        # means the call itself produced nothing.
        out["ok"] = False
        return out
    try:
        rows = json.loads(raw)
        out["ids"] = [int(r["id"]) for r in rows if r.get("id") is not None]
    except (json.JSONDecodeError, ValueError, TypeError, KeyError):
        out["ok"] = False
    return out


def inbox_updates(seat: str) -> list:
    """This seat's unseen updates. Reading them consumes them — an update is
    delivered exactly once, which is what keeps a mailbox from becoming a
    backlog. bin/msg is the only reader of that truth."""
    try:
        r = subprocess.run([str(PLUGIN_BIN / "msg"), "updates-for", seat],
                           capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.SubprocessError):
        return []
    if not r.stdout.strip():
        return []
    try:
        rows = json.loads(r.stdout)
        return rows if isinstance(rows, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def build_inbox(seat: str, rows: list) -> str:
    """Updates another seat sent — news, shown once, then gone.

    Deliberately NOT a queue and deliberately not urgent. Nothing here is
    owed to anyone: a request that needed doing would have arrived as a task,
    in the session it was sent to, not as something to find later."""
    lines = [
        "<jstack-updates>",
        f"{len(rows)} note{'s' if len(rows) != 1 else ''} sent to {seat} since "
        "your last session. Context only — nobody is waiting on any of it, "
        "there is nothing to close, and you will not see it again. Act on one "
        "only if it changes what you are about to do.",
        "",
    ]
    for r in rows:
        head = f"[#{r['id']}] from {r['from_seat']} · {str(r['created_at']).replace('T', ' ')}"
        if r.get("reply_to"):
            head += f" · answering your #{r['reply_to']}"
        lines.append(head)
        lines.append(f"  {r['subject']}")
        if r.get("body"):
            body = str(r["body"]).strip().splitlines()
            lines.extend("  " + ln for ln in body[:4])
            if len(body) > 4:
                lines.append(f"  … msg read {r['id']}")
        for att in json.loads(r.get("attachments") or "[]"):
            lines.append(f"  attached: {att}")
        lines.append("")
    lines.append("</jstack-updates>")
    return "\n".join(lines)


def build_context(agent: str, submode: str, entries: str, n: int) -> str:
    seat = f"{agent}/{submode}"
    return (
        "<jstack-timeline>\n"
        f"Injected on entry by JStack — everything {seat} (your seat) wrote across "
        f"its last {n} sessions, oldest first. This is your own recent history: "
        "you are not starting "
        "cold. Build on it — don't re-discover, re-propose, or re-litigate what's "
        "already below. A `↳ verdict:` line is the independent review's call on that "
        "run — if its note names a move to avoid, pick differently.\n\n"
        f"{entries}\n"
        "</jstack-timeline>"
    )


def main() -> int:
    # `--explain <agent/seat>` — machine mode, no stdin contract: prints the
    # injection answer for a seat as JSON (see explain()). Consumers that
    # display or verify injections call this; the kill switch below is a
    # session-time gate, not part of the answer.
    argv = sys.argv[1:]
    if argv and argv[0] == "--explain":
        seat = argv[1] if len(argv) > 1 else ""
        if not seat:
            print("--explain needs a seat (agent or agent/submode)",
                  file=sys.stderr)
            return 2
        print(json.dumps(explain(seat)))
        return 0

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

    # Both halves are for a person sitting down in the seat. A headless spawn
    # (cron, watcher, `claude --print`) gets neither: it was given its task,
    # and the seat's mail is not it. The one exception is a wake spawned FOR a
    # message — that carries the message inline in its own prompt, so it needs
    # no injection to see it.
    if not _is_interactive():
        return 0

    seat = f"{agent}/{submode}"
    blocks = []

    n = inject_count(cfg, agent, submode)
    if n > 0:
        entries = tail(seat, n)
        if entries:
            blocks.append(build_context(agent, submode, entries, n))

    # Updates last, and only if consuming them succeeded. They are news from
    # other seats, not work — so they sit below this seat's own history rather
    # than above it, and they are shown exactly once.
    if not os.environ.get("JSTACK_INBOX_INJECT_DISABLED"):
        rows = inbox_updates(seat)
        if rows:
            blocks.append(build_inbox(seat, rows))

    if not blocks:
        return 0

    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": "\n\n".join(blocks),
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
