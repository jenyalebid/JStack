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
#   - resume-delta boundary: computed from the reviewed offset (never-reviewed
#     → None; content past the offset doesn't move it); delta note lands in
#     the selfwrite prompt only when a boundary exists
#   - stale-dub sweep: dead-owner selfwrite dubs reaped, live-owner dubs kept
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
    delta_note="",
)
check("selfwrite prompt formats + names seat source", "log_event alpha/chat" in sw)
check("selfwrite prompt links the session",          "--session abcd1234-...." in sw)
check("selfwrite prompt does NOT name continuity",   "continuity" not in sw)
check("selfwrite prompt names the review stamp",     "stamp abcd1234-.... assistant" in sw)
check("first-review prompt has no delta scope",      "RESUME DELTA" not in sw)
# The tag is assigned by the turn that still knows what the session was about,
# and it must read from the vocabulary before writing to it — a prompt that
# names `tag set` without `tag list` mints a private tag every session.
check("selfwrite prompt reads the tag list first",   "log_event tag list" in sw)
check("selfwrite prompt tags the ORIGINAL session",
      "tag set <name> --session abcd1234-...." in sw)
# Steps renumber when one is added; a duplicate number sends the writer looking
# for a step that isn't there.
check("selfwrite steps are numbered once each",
      [sw.count(f"\n{n}. ") for n in (1, 2, 3)] == [1, 1, 1])

# Hosts without the dashboard's review_sessions.py get NO stamp step — the
# prompt must not instruct a command that does not exist on that machine.
sw_bare = eng.SELFWRITE_PROMPT.format(
    marker=eng.SELFWRITE_MARKER, agent="alpha", agent_title="Alpha",
    submode="chat", session_id="abcd1234-....", stamp_step="", delta_note="",
)
check("stampless prompt omits the host-only command", "review_sessions" not in sw_bare)
check("stampless prompt keeps the timeline step",     "log_event alpha/chat" in sw_bare)

# A session reviewed at a previous end (resumed, ended again) gets the
# engine-computed boundary injected — the entry scopes to the delta after it.
sw_delta = eng.SELFWRITE_PROMPT.format(
    marker=eng.SELFWRITE_MARKER, agent="alpha", agent_title="Alpha",
    submode="chat", session_id="abcd1234-....", stamp_step="",
    delta_note=eng.SELFWRITE_DELTA_NOTE.format(boundary="2026-07-15 10:30"),
)
check("resume-delta prompt names the boundary",
      "RESUME DELTA" in sw_delta and "2026-07-15 10:30" in sw_delta)

# ---- resume-delta boundary (mechanical, from the reviewed offset) --------
# The boundary is the last user/assistant timestamp WITHIN the recorded
# offset — the span the previous review covered. Offset 0 (never reviewed)
# → None; content past the offset must not move the boundary.
first = _json.dumps({"type": "user", "timestamp": "2026-07-15T17:00:00Z",
                     "message": {"content": "do the thing"}}) + "\n"
second = _json.dumps({"type": "assistant", "timestamp": "2026-07-15T19:30:00Z",
                      "message": {"content": [{"type": "text", "text": "done"}]}}) + "\n"
bf = Path(eng.CFG["state_dir"]) / "boundary.jsonl"
bf.write_text(first + second)
check("boundary: never reviewed → None",
      eng.last_reviewed_boundary(bf, 0) is None)
b1 = eng.last_reviewed_boundary(bf, len(first.encode()))
from datetime import datetime as _dt, timezone as _tz
want = _dt.fromisoformat("2026-07-15T17:00:00+00:00").astimezone().strftime("%Y-%m-%d %H:%M")
check(f"boundary: offset-scoped to the reviewed span ({b1})", b1 == want)
b2 = eng.last_reviewed_boundary(bf, len((first + second).encode()))
want2 = _dt.fromisoformat("2026-07-15T19:30:00+00:00").astimezone().strftime("%Y-%m-%d %H:%M")
check(f"boundary: full span reads the last message ({b2})", b2 == want2)

# ---- stale-dub sweep -----------------------------------------------------
# A selfwrite dub whose owning engine died mid-spawn must be reaped by the
# next engine run; a dub whose owner is alive must be left alone.
dubs = eng._dubs_dir()
dead_dub = tmp / "dead-dub.jsonl";  dead_dub.write_text("{}\n")
live_dub = tmp / "live-dub.jsonl";  live_dub.write_text("{}\n")
(dubs / "dead-dub-id").write_text(f"999999999 {dead_dub}\n")
(dubs / "live-dub-id").write_text(f"{os.getpid()} {live_dub}\n")
eng.sweep_stale_dubs()
check("stale dub swept (file + record)",
      not dead_dub.exists() and not (dubs / "dead-dub-id").exists())
check("live-owner dub untouched",
      live_dub.exists() and (dubs / "live-dub-id").exists())

# The SELFWRITE log line the engine emits must match the (updated) dashboard
# regex, which accepts SELFWRITE alongside legacy SPAWN.
eng._log("SELFWRITE abcd1234 → alpha/chat")
line = eng.CFG["log_file"].read_text().strip().splitlines()[-1]
m2 = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (?:SELFWRITE|SPAWN) (\w{8})\S* . (\w+)", line)
check("SELFWRITE log line matches dashboard regex", bool(m2) and m2.group(3) == "alpha")

# ---- black-hole detection ----------------------------------------------
# A session dir with no transcript = the CLI never persisted the session
# (e.g. leaked CLAUDE_CODE_CHILD_SESSION). Must be reported, not skipped.
fake_projects = tmp / "projects"
(fake_projects / "-Users-x-Agents-Alpha-chat" / "bh-session-id").mkdir(parents=True)
eng.CLAUDE_PROJECTS = fake_projects
check("black hole reported (session dir, no jsonl)",
      eng.report_blackhole("bh-session-id") is True)
check("BLACKHOLE line logged",
      "BLACKHOLE bh-sessi" in eng.CFG["log_file"].read_text())
check("no session dir → not a black hole",
      eng.report_blackhole("never-existed-id") is False)
# A session WITH a transcript never reaches report_blackhole via main (guarded
# by `not jsonl_path`), and a jsonl-less id with no dir stays a benign skip.

print()
if fails:
    print(f"session-review: {len(fails)} FAILED", file=sys.stderr)
    sys.exit(1)
print("session-review: all pass")
PY
