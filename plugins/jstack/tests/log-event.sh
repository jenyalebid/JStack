#!/usr/bin/env bash
# JStack live test — bin/log_event timeline writer.
#
# Runs the real shipped script against a temp JSTACK_TIMELINE_DIR (hermetic —
# never touches the real timeline). Verifies the full CLI contract:
#   - block format: `HH:MM [source]` header + headline + `- ` bullets
#   - chronological insertion by --at (later call, earlier time → sorts first)
#   - --date writes the named day's file
#   - --pipeline-task consolidation: one live block per task, earliest ts kept
#   - exactly one blank line between blocks
#   - bad --at / missing args → exit 2
#
# Exit 0 = all pass, exit 1 = any fail.

set -u

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_EVENT="$PLUGIN_ROOT/bin/log_event"

TMP=$(mktemp -d /tmp/jstack-log-event-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT
export JSTACK_TIMELINE_DIR="$TMP"

fails=0
fail() { echo "FAIL: $1" >&2; fails=$((fails+1)); }
pass() { echo "ok: $1"; }

[[ -x "$LOG_EVENT" ]] || { echo "FAIL: $LOG_EVENT not executable" >&2; exit 1; }

DAY="2026-01-15"
FILE="$TMP/$DAY.md"

# 1. basic block append
"$LOG_EVENT" alice --at 10:00 --date "$DAY" "First thing shipped" >/dev/null || fail "basic append exit"
grep -q "^10:00 \[alice\]$" "$FILE" && grep -q "^First thing shipped$" "$FILE" \
  && pass "basic block format" || fail "basic block format"

# 2. details become bullets (incl. '- ' prefix normalization + whitespace collapse)
"$LOG_EVENT" alice --at 12:00 --date "$DAY" "Second thing" \
  --detail "plain bullet" --detail "- already prefixed" >/dev/null
grep -q "^- plain bullet$" "$FILE" && grep -q "^- already prefixed$" "$FILE" \
  && pass "detail bullets" || fail "detail bullets"

# 3. chronological insertion — 11:00 logged last must land between 10:00 and 12:00
"$LOG_EVENT" bob --at 11:00 --date "$DAY" "Middle thing" >/dev/null
order=$(grep -oE "^[0-9]{2}:[0-9]{2}" "$FILE" | tr '\n' ' ')
[[ "$order" == "10:00 11:00 12:00 " ]] \
  && pass "chronological insertion ($order)" || fail "chronological insertion (got: $order)"

# 4. exactly one blank line between blocks, none doubled
python3 - "$FILE" <<'PY' && pass "blank-line separation" || fail "blank-line separation"
import sys
text = open(sys.argv[1]).read()
sys.exit(1 if "\n\n\n" in text or not text.endswith("\n") else 0)
PY

# 5. pipeline-task consolidation: second call replaces first block, keeps earliest ts
"$LOG_EVENT" bob --at 09:00 --date "$DAY" --pipeline-task "wordy#87" "Build started" >/dev/null
"$LOG_EVENT" bob --date "$DAY" --pipeline-task "wordy#87" "Merged to v3" --detail "8 tasks" >/dev/null
count=$(grep -c "wordy#87" "$FILE")
[[ "$count" == "1" ]] && grep -q "wordy#87 — Merged to v3" "$FILE" \
  && grep -B1 "wordy#87 — Merged to v3" "$FILE" | grep -q "^09:00" \
  && pass "pipeline consolidation (1 block, earliest ts)" || fail "pipeline consolidation (count=$count)"

# 6. headline newline collapse
"$LOG_EVENT" carol --at 14:00 --date "$DAY" "line one
line two" >/dev/null
grep -q "^line one line two$" "$FILE" && pass "headline collapse" || fail "headline collapse"

# 7. bad --at rejected
"$LOG_EVENT" alice --at 9am --date "$DAY" "bad ts" >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "bad --at rejected" || fail "bad --at rejected"

# 8. missing args rejected
"$LOG_EVENT" alice >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "missing args rejected" || fail "missing args rejected"

echo
if [[ $fails -gt 0 ]]; then
  echo "log-event: $fails FAILED" >&2
  exit 1
fi
echo "log-event: all pass"
