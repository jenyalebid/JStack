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

# 19. future --at on today is impossible — clamped to current local time
#     (the classic writer error: HH:MM copied from a UTC transcript timestamp)
TODAY=$(date +%Y-%m-%d)
NOW_MIN=$((10#$(date +%H) * 60 + 10#$(date +%M)))
if (( NOW_MIN >= 1435 )); then
  pass "future --at clamp (skipped: too close to midnight)"
  pass "future --date clamp (skipped: too close to midnight)"
else
  "$LOG_EVENT" clampy --at 23:59 --date "$TODAY" "Stamped from a UTC transcript" >/dev/null
  got=$(SQL "SELECT time FROM entries WHERE agent='clampy'")
  stored=${got:3:5}
  STORED_MIN=$((10#${stored:0:2} * 60 + 10#${stored:3:2}))
  diff=$((STORED_MIN - NOW_MIN))
  (( diff >= -1 && diff <= 2 )) \
    && pass "future --at clamped to now ($stored)" || fail "future --at clamped (got $stored, now_min=$NOW_MIN)"

  # 20. future --date is impossible too (UTC date rollover after ~5pm PT) — lands today, stamped now
  "$LOG_EVENT" clampy2 --at 00:15 --date 2099-01-01 "Dated tomorrow by UTC rollover" >/dev/null
  got=$(SQL "SELECT date FROM entries WHERE agent='clampy2'")
  [[ "$got" == *"$TODAY"* ]] \
    && pass "future --date clamped to today" || fail "future --date clamped (got $got)"
fi

# 21. --context: on-demand depth — in the db, absent from day md and default
#     tail (injection stays lean), surfaced by tail --json (with id + session_id)
"$LOG_EVENT" alpha/chat --at 15:30 --date "$DAY" "Entry with depth" \
  --detail "a visible bullet" --context "long freeform recall notes, survives transcript deletion" >/dev/null
J=$("$LOG_EVENT" tail alpha/chat -n 5 --json)
! grep -q "long freeform recall" "$FILE" \
  && ! "$LOG_EVENT" tail alpha/chat -n 5 | grep -q "long freeform recall" \
  && echo "$J" | grep -q "long freeform recall" \
  && echo "$J" | grep -q '"session_id": "sess-123"' \
  && echo "$J" | grep -q '"id":' \
  && pass "context: db-only, --json carries id/session/context" || fail "context isolation"

# 22. show <id>: the on-demand loader — full entry incl. context; unknown id → exit 1
ID=$(echo "$J" | python3 -c 'import json,sys; es=json.load(sys.stdin); print([e["id"] for e in es if e["headline"]=="Entry with depth"][0])')
out=$("$LOG_EVENT" show "$ID")
echo "$out" | grep -q "Entry with depth" && echo "$out" | grep -q "long freeform recall notes" \
  && echo "$out" | grep -q "a visible bullet" \
  && pass "show: full entry by id" || fail "show by id"
"$LOG_EVENT" show 999999 >/dev/null 2>&1
[[ $? -eq 1 ]] && pass "show: unknown id exit 1" || fail "show unknown id"

# 23. grep: substring search across days/seats (headline+details+context),
#     case-insensitive, output carries #id/date/seat; no match → exit 1
out=$("$LOG_EVENT" grep "legacy block")
echo "$out" | grep -q "Legacy block one" && echo "$out" | grep -q "2026-01-10" \
  && echo "$out" | grep -q "\[delta\]" && echo "$out" | grep -qE "^#[0-9]+ " \
  && pass "grep: cross-day, case-insensitive" || fail "grep basics"
"$LOG_EVENT" grep "freeform recall" | grep -q "Entry with depth" \
  && pass "grep: matches context field" || fail "grep context match"
"$LOG_EVENT" grep "no-such-string-anywhere" >/dev/null
[[ $? -eq 1 ]] && pass "grep: no match exit 1" || fail "grep no-match exit"

# 24. grep filters: --seat narrows to the seat, --since drops earlier days
out=$("$LOG_EVENT" grep "seat entry" --seat alpha/chat)
echo "$out" | grep -q "Second seat entry" && ! echo "$out" | grep -q "Other seat entry" \
  && pass "grep: --seat filter" || fail "grep --seat"
"$LOG_EVENT" grep "Legacy block" --since 2026-01-11 >/dev/null
[[ $? -eq 1 ]] && pass "grep: --since filter" || fail "grep --since"

# 24b. arg strictness: a stray token or unknown flag must ERROR (exit 2), never
#      be silently absorbed as the pattern/seat — a recall surface that answers
#      the wrong question is worse than one that errors
"$LOG_EVENT" grep "seat entry" -n 3 >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "grep: unknown flag rejected" || fail "grep unknown flag"
"$LOG_EVENT" grep seat entry >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "grep: stray positional rejected" || fail "grep stray positional"
"$LOG_EVENT" tail alpha/chat --oops >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "tail: unknown flag rejected" || fail "tail unknown flag"
"$LOG_EVENT" tail alpha beta >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "tail: second seat rejected" || fail "tail second seat"
"$LOG_EVENT" recall "$DAY" alpha extra >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "recall: stray positional rejected" || fail "recall stray positional"
"$LOG_EVENT" recall "$DAY" --oops >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "recall: unknown flag rejected" || fail "recall unknown flag"

# 25. schema upgrade: a pre-context db (real dbs on installed hosts) gains the
#     column on first connect — write with --context must not error
OLD="$TMP/oldschema"; mkdir -p "$OLD"
python3 - "$OLD/timeline.db" <<'PY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.execute("""CREATE TABLE entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL, time TEXT NOT NULL,
    agent TEXT NOT NULL, submode TEXT NOT NULL DEFAULT '', headline TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '[]', pipeline_task TEXT, session_id TEXT,
    verdict TEXT, verdict_note TEXT, created_at TEXT NOT NULL)""")
con.execute("INSERT INTO entries (date, time, agent, submode, headline, created_at)"
            " VALUES ('2026-01-05', '09:00', 'old', '', 'Pre-upgrade row', '2026-01-05T09:00:00')")
con.commit()
PY
JSTACK_TIMELINE_DIR="$OLD" "$LOG_EVENT" old --at 10:00 --date 2026-01-05 "Post-upgrade row" \
  --context "written after ALTER" >/dev/null 2>&1 || fail "upgrade write errored"
up=$(python3 -c "import sqlite3; print(sqlite3.connect('$OLD/timeline.db').execute(\"SELECT context FROM entries WHERE headline='Post-upgrade row'\").fetchall())")
[[ "$up" == *"written after ALTER"* ]] \
  && pass "schema upgrade: old db gains context column" || fail "schema upgrade (got $up)"

# 26a. recall <date>: full blocks for a day, all seats, chronological, with #ids
out=$("$LOG_EVENT" recall "$LEGACY_DAY")
echo "$out" | grep -q "Legacy block one" && echo "$out" | grep -q "Legacy block two" \
  && echo "$out" | grep -q "\[delta\]" && echo "$out" | grep -q "\[gamma/social\]" \
  && echo "$out" | grep -qE "^#[0-9]+ $LEGACY_DAY 08:00" \
  && [[ $(echo "$out" | grep -oE "0[89]:[0-9]{2}" | head -1) == "08:00" ]] \
  && pass "recall day: all seats, chronological" || fail "recall day"

# 26b. recall <date> <seat>: seat filter — exact seat narrows, bare agent spans seats,
#      verdicts ride (recall shows what injection would have shown that day)
out=$("$LOG_EVENT" recall "$DAY" alpha/chat)
echo "$out" | grep -q "Seat-tagged entry" && ! echo "$out" | grep -q "Other seat entry" \
  && echo "$out" | grep -q "↳ verdict: blocked" \
  && pass "recall seat filter + verdict rides" || fail "recall seat filter"
"$LOG_EVENT" recall "$DAY" alpha | grep -q "Other seat entry" \
  && pass "recall bare agent spans seats" || fail "recall bare agent"

# 26b2. recall --full: detailed recall — context blobs ride; default stays lean
! "$LOG_EVENT" recall "$DAY" alpha/chat | grep -q "long freeform recall" \
  && "$LOG_EVENT" recall "$DAY" alpha/chat --full | grep -q "long freeform recall" \
  && pass "recall --full carries context, default lean" || fail "recall --full"

# 26c. recall range from..to; 'all' explicit; no rows → exit 1; bad date → exit 2
out=$("$LOG_EVENT" recall "$LEGACY_DAY..$LEGACY2_DAY" all)
echo "$out" | grep -q "Legacy block one" && echo "$out" | grep -q "Pre-db entry that must survive" \
  && ! echo "$out" | grep -q "First thing shipped" \
  && pass "recall range" || fail "recall range"
"$LOG_EVENT" recall 2001-01-01 >/dev/null
[[ $? -eq 1 ]] && pass "recall empty day exit 1" || fail "recall empty day exit"
"$LOG_EVENT" recall jan-24 >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "recall bad date exit 2" || fail "recall bad date exit"

# 26. bare write — no --at, no --date: lands today, stamped now (machine-local)
NOW_MIN=$((10#$(date +%H) * 60 + 10#$(date +%M)))
if (( NOW_MIN >= 1435 )); then
  pass "bare-write defaults (skipped: too close to midnight)"
else
  "$LOG_EVENT" defaulty "Stamped by omission" >/dev/null
  got=$(SQL "SELECT date, time FROM entries WHERE agent='defaulty'")
  [[ "$got" == *"$TODAY"* ]] || fail "bare write date (got $got)"
  stored=$(echo "$got" | grep -oE "[0-9]{2}:[0-9]{2}")
  STORED_MIN=$((10#${stored:0:2} * 60 + 10#${stored:3:2}))
  diff=$((STORED_MIN - NOW_MIN))
  (( diff >= -1 && diff <= 2 )) \
    && pass "bare write defaults to today/now ($stored)" || fail "bare write time (got $stored)"
fi

echo
if [[ $fails -gt 0 ]]; then
  echo "log-event: $fails FAILED" >&2
  exit 1
fi
echo "log-event: all pass"
