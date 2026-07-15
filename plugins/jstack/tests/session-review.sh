#!/usr/bin/env bash
# JStack live test — bin/session-review-spawn engine.
#
# Imports the real shipped engine (hermetic: JSTACK_REVIEW_CONFIG pointed at a
# temp config so CFG never reads the machine's real one) and exercises the
# pure logic that gates every review:
#   - output validator: good output passes; missing section, evidence-free
#     sections, and log_event-claimed-but-file-didn't-grow all reject;
#     'no user turns' (+ known cron paraphrases) accepted for empty walks
#   - agent resolution: umbrella project dirs, project_dir_map, $HOME →
#     default_agent, non-reviewable miss
#   - claim dedup: second claim on a live pid loses; stale (dead-pid) claim
#     is taken over
#   - log line format matches the `SPAWN <sid8> → <agent>` dashboard contract
#
# Exit 0 = all pass, exit 1 = any fail.

set -u

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE="$PLUGIN_ROOT/bin/session-review-spawn"

[[ -x "$ENGINE" ]] || { echo "FAIL: $ENGINE not executable" >&2; exit 1; }

TMP=$(mktemp -d /tmp/jstack-review-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

python3 - "$ENGINE" "$TMP" <<'PY'
import importlib.util
import importlib.machinery
import json
import os
import sys
from pathlib import Path

engine_path, tmp = sys.argv[1], Path(sys.argv[2])

# Hermetic config BEFORE import (engine loads CFG at import time)
agent_root = tmp / "Agents"
for name in ("Alpha", "Beta"):
    (agent_root / name).mkdir(parents=True)
    (agent_root / name / "CLAUDE.md").write_text("# agent\n")
(agent_root / "NoClaudeMd").mkdir(parents=True)  # workspace without CLAUDE.md — not reviewable

cfg_path = tmp / "review.json"
cfg_path.write_text(json.dumps({
    "agent_root": str(agent_root),
    "default_agent": "alpha",
    "project_dir_map": {"-Users-x-Some-Project": "gamma"},
    "state_dir": str(tmp / "state"),
    "timeline_dir": str(tmp / "Timeline"),
}))
os.environ["JSTACK_REVIEW_CONFIG"] = str(cfg_path)

loader = importlib.machinery.SourceFileLoader("review_engine", engine_path)
spec = importlib.util.spec_from_loader("review_engine", loader)
eng = importlib.util.module_from_spec(spec)
loader.exec_module(eng)

fails = []
def check(name, cond):
    print(("ok: " if cond else "FAIL: ") + name)
    if not cond:
        fails.append(name)

# ---- validator ----------------------------------------------------------
GOOD = """## TRANSCRIPT_WALK
- turn 1 [10:02]: "fix the thing" → resolved-in-session → commit landed

## DOC_RECONCILE
- clean — examined: active.md (2 topic matches), active/ (1 file); all consistent.

## ACTIONS_TAKEN
- Edit active.md:4 — removed fossil entry

## TIMELINE
- log_event alpha --at 10:30 "Thing fixed"

## SUMMARY
Fixed the thing.
"""
CORE = eng.DEFAULTS["required_sections"]

ok, why = eng.validate_review_output(GOOD, CORE, timeline_grew=True)
check(f"good output passes ({why or 'ok'})", ok)

ok, why = eng.validate_review_output(GOOD.replace("## SUMMARY", "## WRAP"), CORE)
check("missing section rejected", not ok and "SUMMARY" in why)

ok, why = eng.validate_review_output(GOOD, CORE, timeline_grew=False)
check("log_event without file growth rejected", not ok and "did not grow" in why)

none_tl = GOOD.replace('- log_event alpha --at 10:30 "Thing fixed"',
                       "- none — routine maintenance")
ok, why = eng.validate_review_output(none_tl, CORE, timeline_grew=False)
check(f"timeline 'none — reason' passes without growth ({why or 'ok'})", ok)

empty_walk = GOOD.replace(
    '- turn 1 [10:02]: "fix the thing" → resolved-in-session → commit landed',
    "no user turns — cron-triggered session (skill payload only)")
ok, why = eng.validate_review_output(empty_walk, CORE, timeline_grew=True)
check("'no user turns' literal accepted", ok)

paraphrase = GOOD.replace(
    '- turn 1 [10:02]: "fix the thing" → resolved-in-session → commit landed',
    "cron-triggered wake, zero user prose in transcript")
ok, why = eng.validate_review_output(paraphrase, CORE, timeline_grew=True)
check("cron-spawn paraphrase accepted", ok)

bare_walk = GOOD.replace(
    '- turn 1 [10:02]: "fix the thing" → resolved-in-session → commit landed',
    "(nothing)")
ok, why = eng.validate_review_output(bare_walk, CORE, timeline_grew=True)
check("evidence-free TRANSCRIPT_WALK rejected", not ok)

extra = ["TRANSCRIPT_WALK", "J_LIST_LIVE", "DOC_RECONCILE", "ACTIONS_TAKEN", "TIMELINE", "SUMMARY"]
ok, why = eng.validate_review_output(GOOD, extra, timeline_grew=True)
check("host-extended section list enforced", not ok and "J_LIST_LIVE" in why)

# ---- timeline growth gate ------------------------------------------------
# log_event may file under a PRIOR day (--date of the last real message when a
# session ends days later) — the growth gate watches the store's max row id,
# so any new row counts whatever date it filed under.
import sqlite3 as _sq
tl_dir = tmp / "Timeline"
tl_dir.mkdir(parents=True, exist_ok=True)
_con = _sq.connect(tl_dir / "timeline.db")
_con.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY AUTOINCREMENT,"
             " date TEXT, time TEXT, agent TEXT, headline TEXT)")
_con.execute("INSERT INTO entries (date, time, agent, headline)"
             " VALUES ('2026-07-10', '09:00', 'x', 'old entry')")
_con.commit()
pre = eng._timeline_max_id(tl_dir)
_con.execute("INSERT INTO entries (date, time, agent, headline)"
             " VALUES ('2026-07-10', '15:39', 'x', 'late-filed entry')")
_con.commit()
_con.close()
post = eng._timeline_max_id(tl_dir)
check("prior-day row growth detected store-wide", post > pre)
check("missing timeline db → zero", eng._timeline_max_id(tmp / "NoSuchDir") == 0)

# ---- session limit (rate limit) ----------------------------------------
# A review spawn that only hit the Claude usage limit exits 1 with a one-line
# limit message. That is transient — not a review-content failure — so it must
# be recognized and NOT retried/escalated as a broken review (ISS-0076).
check("session-limit output recognized",
      eng.is_session_limit("You've hit your session limit · resets 7am (America/Los_Angeles)"))
check("normal review output not flagged as session-limit", not eng.is_session_limit(GOOD))

# ---- agent resolution ---------------------------------------------------
agents = eng.reviewable_agents(agent_root)
check("reviewable = root-CLAUDE.md convention", sorted(agents) == ["alpha", "beta"])

enc_root = str(agent_root).replace("/", "-").replace(".", "-")
def res(dirname):
    return eng.resolve_agent(dirname, agent_root, agents,
                             {"-Users-x-Some-Project": "beta"}, "alpha")

check("umbrella sub-mode resolves", res(f"{enc_root}-Alpha-chat") == "alpha")
check("umbrella root resolves", res(f"{enc_root}-Beta") == "beta")
check("deep mission path resolves", res(f"{enc_root}-Alpha-missions-200-dau") == "alpha")
check("non-reviewable workspace misses", res(f"{enc_root}-NoClaudeMd-chat") is None)
check("project_dir_map resolves", res("-Users-x-Some-Project") == "beta")
home_enc = str(Path.home()).replace("/", "-").replace(".", "-")
check("home dir → default_agent", res(home_enc) == "alpha")
check("unrelated dir misses", res("-Users-x-Random-Thing") is None)

# ---- claim dedup --------------------------------------------------------
check("first claim wins", eng.claim_session("test-sid-1"))
check("second claim loses (live pid)", not eng.claim_session("test-sid-1"))
stale = eng.CFG["state_dir"] / "claims" / "test-sid-2"
stale.parent.mkdir(parents=True, exist_ok=True)
stale.write_text("999999999\n")  # dead pid
check("stale claim taken over", eng.claim_session("test-sid-2"))

# ---- auto-session gate (user-engaged classifier) -------------------------
import json as _json

def _mk_jsonl(name, entries):
    f = Path(eng.CFG["state_dir"]) / name
    f.write_text("\n".join(_json.dumps(e) for e in entries) + "\n")
    return f

CRON_LINES = [
    {"type": "queue-operation", "operation": "enqueue", "content": "[cron:x] /social_reply"},
    {"type": "user", "message": {"content": "[cron:x Wake] /social_reply post=1"}},
    {"type": "last-prompt"},
    {"type": "assistant", "timestamp": "2026-07-02T20:00:00Z",
     "message": {"content": [{"type": "text", "text": "Done with this round — 5 replies posted."}]}},
]
f = _mk_jsonl("cron.jsonl", CRON_LINES)
check("cron session is not user-engaged", not eng.is_user_engaged(f))

f = _mk_jsonl("typed.jsonl", CRON_LINES + [
    {"type": "user", "promptSource": "typed", "message": {"content": "shorter, close it"}}])
check("typed prompt → user-engaged", eng.is_user_engaged(f))

f = _mk_jsonl("tui.jsonl", CRON_LINES + [{"type": "permission-mode"}])
check("TUI attach (permission-mode) → user-engaged", eng.is_user_engaged(f))

# ---- auto-review carve-out (timeline-critical crons) ---------------------
# Auto sessions are normally skipped (their timeline is written in-session by the
# Stop hook), EXCEPT the purpose-built recurring crons named here — they get the
# engine self-write instead (a purpose-prompted seat-tagged timeline line + the
# dashboard stamp). Same match form as reviewed_submodes: "agent/submode" or
# "*/submode".
AUTO_LIST = ["beta/pm", "gamma/nightly-review", "*/meta"]
check("auto-review: nightly PM cron carved in",
      eng.auto_reviewed("beta", "pm", AUTO_LIST))
check("auto-review: wildcard sub-mode carved in",
      eng.auto_reviewed("alpha", "meta", AUTO_LIST))
check("auto-review: ordinary social wake stays skipped",
      not eng.auto_reviewed("beta", "social", AUTO_LIST))
check("auto-review: empty/None allowlist reviews nothing auto",
      not eng.auto_reviewed("beta", "pm", None))
check("auto-review: None sub-mode never carved in",
      not eng.auto_reviewed("beta", None, AUTO_LIST))

# ---- log format contract (dashboard parses SPAWN lines) -----------------
import re
eng._log("SPAWN abcd1234 → alpha (attempt 1, workspace: review)")
line = eng.CFG["log_file"].read_text().strip().splitlines()[-1]
m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) SPAWN (\w{8})\S* . (\w+)", line)
check("SPAWN log line matches dashboard regex", bool(m) and m.group(3) == "alpha")

# ---- self-write path (default session_end_action) -----------------------
check("session_end_action defaults to selfwrite",
      eng.DEFAULTS.get("session_end_action") == "selfwrite")

# The one-turn resume prompt must format cleanly with all placeholders and
# name the three writes it drives.
sw = eng.SELFWRITE_PROMPT.format(
    marker=eng.SELFWRITE_MARKER, agent="alpha", agent_title="Alpha",
    submode="chat", session_id="abcd1234-....",
    stamp_step=eng.SELFWRITE_STAMP_STEP.format(session_id="abcd1234-...."),
)
check("selfwrite prompt formats + names seat source", "log_event alpha/chat" in sw)
check("selfwrite prompt links the session",          "--session abcd1234-...." in sw)
check("selfwrite prompt does NOT name continuity",   "continuity" not in sw)
check("selfwrite prompt names the review stamp",     "stamp abcd1234-.... assistant" in sw)

# Hosts without the dashboard's review_sessions.py get NO stamp step — the
# prompt must not instruct a command that does not exist on that machine.
sw_bare = eng.SELFWRITE_PROMPT.format(
    marker=eng.SELFWRITE_MARKER, agent="alpha", agent_title="Alpha",
    submode="chat", session_id="abcd1234-....", stamp_step="",
)
check("stampless prompt omits the host-only command", "review_sessions" not in sw_bare)
check("stampless prompt keeps the timeline step",     "log_event alpha/chat" in sw_bare)

# The SELFWRITE log line the engine emits must match the (updated) dashboard
# regex, which accepts SELFWRITE alongside legacy SPAWN.
eng._log("SELFWRITE abcd1234 → alpha/chat")
line = eng.CFG["log_file"].read_text().strip().splitlines()[-1]
m2 = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (?:SELFWRITE|SPAWN) (\w{8})\S* . (\w+)", line)
check("SELFWRITE log line matches dashboard regex", bool(m2) and m2.group(3) == "alpha")

print()
if fails:
    print(f"session-review: {len(fails)} FAILED", file=sys.stderr)
    sys.exit(1)
print("session-review: all pass")
PY
