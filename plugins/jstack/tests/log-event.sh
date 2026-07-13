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
"$LOG_EVENT" bob --at 09:00 --date "$DAY" --pipeline-task "appx#87" "Build started" >/dev/null
"$LOG_EVENT" bob --date "$DAY" --pipeline-task "appx#87" "Merged to v3" --detail "8 tasks" >/dev/null
count=$(grep -c "appx#87" "$FILE")
[[ "$count" == "1" ]] && grep -q "appx#87 — Merged to v3" "$FILE" \
  && grep -B1 "appx#87 — Merged to v3" "$FILE" | grep -q "^09:00" \
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

# ---- sqlite store surface --------------------------------------------------

DB="$TMP/timeline.db"
SQL() { python3 -c "import sqlite3,sys; print(sqlite3.connect('$DB').execute(sys.argv[1]).fetchall())" "$1"; }

# 9. db is the store: every md block above has a row (5 — consolidation collapsed two)
rows=$(SQL "SELECT COUNT(*) FROM entries WHERE date='$DAY'")
blocks=$(grep -cE "^[0-9]{2}:[0-9]{2} \[" "$FILE")
[[ "$rows" == "[($blocks,)]" ]] && pass "db rows match md blocks ($rows)" || fail "db rows match md blocks (rows=$rows blocks=$blocks)"

# 10. agent/submode source: renders [agent/submode], stores split columns
"$LOG_EVENT" alpha/chat --at 15:00 --date "$DAY" "Seat-tagged entry" --session sess-123 >/dev/null
grep -q "^15:00 \[alpha/chat\]$" "$FILE" \
  && [[ $(SQL "SELECT agent, submode, session_id FROM entries WHERE headline='Seat-tagged entry'") == "[('alpha', 'chat', 'sess-123')]" ]] \
  && pass "agent/submode source + --session" || fail "agent/submode source + --session"

# 11. tail: seat-filtered, oldest→newest, -n honored
"$LOG_EVENT" alpha/chat --at 15:10 --date "$DAY" "Second seat entry" --detail "a bullet" >/dev/null
"$LOG_EVENT" alpha/pm --at 15:20 --date "$DAY" "Other seat entry" >/dev/null
t=$("$LOG_EVENT" tail alpha/chat -n 5)
echo "$t" | grep -q "Seat-tagged entry" && echo "$t" | grep -q "Second seat entry" \
  && ! echo "$t" | grep -q "Other seat entry" \
  && [[ $(echo "$t" | head -1) == *"Seat-tagged entry"* ]] \
  && pass "tail seat filter + order" || fail "tail seat filter + order"

# 12. tail bare agent matches all submodes; -n limits
t=$("$LOG_EVENT" tail alpha -n 2)
echo "$t" | grep -q "Other seat entry" && echo "$t" | grep -q "Second seat entry" \
  && ! echo "$t" | grep -q "Seat-tagged entry" \
  && pass "tail bare agent + -n limit" || fail "tail bare agent + -n limit"

# 13. verdict stamps the seat's latest entry; rides tail, NOT the day md
"$LOG_EVENT" verdict alpha/chat blocked --note "waiting on a decision" >/dev/null
"$LOG_EVENT" tail alpha/chat -n 1 | grep -q "↳ verdict: blocked — waiting on a decision" \
  && ! grep -q "verdict" "$FILE" \
  && pass "verdict on latest, absent from md" || fail "verdict on latest, absent from md"

# 14. verdict rejects bad values / unknown seat
"$LOG_EVENT" verdict alpha/chat wonderful --note x >/dev/null 2>&1
[[ $? -eq 2 ]] || fail "bad verdict value rejected"
"$LOG_EVENT" verdict nobody/void blocked --note x >/dev/null 2>&1
[[ $? -eq 1 ]] && pass "verdict validation" || fail "verdict validation (unknown seat)"

# 15. migrate: legacy md (no db rows for that date) imports, re-render preserves content
LEGACY_DAY="2026-01-10"
LEGACY="$TMP/$LEGACY_DAY.md"
printf '08:00 [delta]\nLegacy block one\n- old bullet\n\n09:30 [gamma/social]\nLegacy block two\n' > "$LEGACY"
"$LOG_EVENT" migrate >/dev/null
rows=$(SQL "SELECT COUNT(*) FROM entries WHERE date='$LEGACY_DAY'")
grep -q "Legacy block one" "$LEGACY" && grep -q "^09:30 \[gamma/social\]$" "$LEGACY" \
  && [[ "$rows" == "[(2,)]" ]] \
  && pass "migrate imports legacy day" || fail "migrate imports legacy day (rows=$rows)"

# 16. migrate idempotent: second run skips populated dates
out=$("$LOG_EVENT" migrate)
echo "$out" | grep -q "$LEGACY_DAY: skipped" && pass "migrate idempotent" || fail "migrate idempotent"

# 17. first write to a legacy date absorbs the md instead of clobbering it
LEGACY2_DAY="2026-01-11"
printf '07:00 [epsilon]\nPre-db entry that must survive\n' > "$TMP/$LEGACY2_DAY.md"
"$LOG_EVENT" alice --at 12:00 --date "$LEGACY2_DAY" "Post-db entry" >/dev/null
grep -q "Pre-db entry that must survive" "$TMP/$LEGACY2_DAY.md" \
  && grep -q "Post-db entry" "$TMP/$LEGACY2_DAY.md" \
  && pass "legacy date absorbed on first write" || fail "legacy date absorbed on first write"

# 18. stray md block (foreign writer mid-upgrade, hand edit) absorbed, never clobbered
printf '\n13:00 [rogue]\nStray block written behind the db\n' >> "$TMP/$LEGACY2_DAY.md"
"$LOG_EVENT" alice --at 14:00 --date "$LEGACY2_DAY" "Later entry" >/dev/null
grep -q "Stray block written behind the db" "$TMP/$LEGACY2_DAY.md" \
  && grep -q "Later entry" "$TMP/$LEGACY2_DAY.md" \
  && [[ $(SQL "SELECT COUNT(*) FROM entries WHERE date='$LEGACY2_DAY' AND agent='rogue'") == "[(1,)]" ]] \
  && pass "stray md block absorbed into db" || fail "stray md block absorbed into db"

echo
if [[ $fails -gt 0 ]]; then
  echo "log-event: $fails FAILED" >&2
  exit 1
fi
echo "log-event: all pass"
