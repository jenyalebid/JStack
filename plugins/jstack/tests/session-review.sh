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
for name in ("Jarvis", "Lynda"):
    (agent_root / name / "review").mkdir(parents=True)
(agent_root / "NoReview").mkdir(parents=True)  # workspace without review/ — not reviewable

cfg_path = tmp / "review.json"
cfg_path.write_text(json.dumps({
    "agent_root": str(agent_root),
    "default_agent": "jarvis",
    "project_dir_map": {"-Users-x-Books-Project": "mario"},
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
- clean — examined: state.md (2 topic matches), active/ (1 file); all consistent.

## ACTIONS_TAKEN
- Edit state.md:4 — removed fossil entry

## TIMELINE
- log_event jarvis --at 10:30 "Thing fixed"

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

none_tl = GOOD.replace('- log_event jarvis --at 10:30 "Thing fixed"',
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
    "cron-triggered wake, zero boss prose in transcript")
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

# ---- agent resolution ---------------------------------------------------
agents = eng.reviewable_agents(agent_root)
check("reviewable = review/-dir convention", sorted(agents) == ["jarvis", "lynda"])

enc_root = str(agent_root).replace("/", "-").replace(".", "-")
def res(dirname):
    return eng.resolve_agent(dirname, agent_root, agents,
                             {"-Users-x-Books-Project": "lynda"}, "jarvis")

check("umbrella sub-mode resolves", res(f"{enc_root}-Jarvis-chat") == "jarvis")
check("umbrella root resolves", res(f"{enc_root}-Lynda") == "lynda")
check("deep mission path resolves", res(f"{enc_root}-Jarvis-missions-200-dau") == "jarvis")
check("non-reviewable workspace misses", res(f"{enc_root}-NoReview-chat") is None)
check("project_dir_map resolves", res("-Users-x-Books-Project") == "lynda")
home_enc = str(Path.home()).replace("/", "-").replace(".", "-")
check("home dir → default_agent", res(home_enc) == "jarvis")
check("unrelated dir misses", res("-Users-x-Random-Thing") is None)

# ---- claim dedup --------------------------------------------------------
check("first claim wins", eng.claim_session("test-sid-1"))
check("second claim loses (live pid)", not eng.claim_session("test-sid-1"))
stale = eng.CFG["state_dir"] / "claims" / "test-sid-2"
stale.parent.mkdir(parents=True, exist_ok=True)
stale.write_text("999999999\n")  # dead pid
check("stale claim taken over", eng.claim_session("test-sid-2"))

# ---- log format contract (dashboard parses SPAWN lines) -----------------
import re
eng._log("SPAWN abcd1234 → jarvis (attempt 1, workspace: review)")
line = eng.CFG["log_file"].read_text().strip().splitlines()[-1]
m = re.match(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) SPAWN (\w{8})\S* . (\w+)", line)
check("SPAWN log line matches dashboard regex", bool(m) and m.group(3) == "jarvis")

print()
if fails:
    print(f"session-review: {len(fails)} FAILED", file=sys.stderr)
    sys.exit(1)
print("session-review: all pass")
PY
