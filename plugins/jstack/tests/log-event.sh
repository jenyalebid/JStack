#!/usr/bin/env bash
# JStack live test — bin/log_event timeline writer.
#
# Runs the real shipped script against a temp JSTACK_TIMELINE_DIR (hermetic —
# never touches the real timeline). Verifies the full CLI contract:
#   - sqlite store is the ONLY artifact — no md file is ever written
#   - chronological order by --at; --date targets the named day
#   - --pipeline-task consolidation: one live row per task, earliest ts kept
#   - origin: direct|indirect — flag > JSTACK_TIMELINE_ORIGIN env > direct
#   - bad --at / bad --origin / missing args → exit 2
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
DB="$TMP/timeline.db"
SQL() { python3 -c "import sqlite3,sys; print(sqlite3.connect('$DB').execute(sys.argv[1]).fetchall())" "$1"; }

# 1. basic append lands in the db
"$LOG_EVENT" alice --at 10:00 --date "$DAY" "First thing shipped" >/dev/null || fail "basic append exit"
[[ $(SQL "SELECT time, agent, headline FROM entries WHERE date='$DAY'") == "[('10:00', 'alice', 'First thing shipped')]" ]] \
  && pass "basic append stored" || fail "basic append stored"

# 2. the store is the ONLY artifact — no md file is ever written
count=$(ls "$TMP"/*.md 2>/dev/null | wc -l | tr -d ' ')
[[ "$count" == "0" ]] && pass "no md file written" || fail "no md file written ($count found)"

# 3. details normalized ('- ' prefix stripped, whitespace collapsed) and stored
"$LOG_EVENT" alice --at 12:00 --date "$DAY" "Second thing" \
  --detail "plain bullet" --detail "- already prefixed" >/dev/null
t=$("$LOG_EVENT" tail alice -n 5)
echo "$t" | grep -q "^- plain bullet$" && echo "$t" | grep -q "^- already prefixed$" \
  && pass "detail bullets" || fail "detail bullets"

# 4. chronological order — 11:00 logged last must sort between 10:00 and 12:00
"$LOG_EVENT" bob --at 11:00 --date "$DAY" "Middle thing" >/dev/null
order=$("$LOG_EVENT" recall "$DAY" | grep -oE "[0-9]{2}:[0-9]{2} \[" | grep -oE "^[0-9]{2}:[0-9]{2}" | tr '\n' ' ')
[[ "$order" == "10:00 11:00 12:00 " ]] \
  && pass "chronological order ($order)" || fail "chronological order (got: $order)"

# 5. pipeline-task consolidation: second call replaces first row, keeps earliest ts
"$LOG_EVENT" bob --at 09:00 --date "$DAY" --pipeline-task "appx#87" "Build started" >/dev/null
"$LOG_EVENT" bob --date "$DAY" --pipeline-task "appx#87" "Merged to v3" --detail "8 tasks" >/dev/null
rows=$(SQL "SELECT COUNT(*) FROM entries WHERE date='$DAY' AND pipeline_task='appx#87'")
[[ "$rows" == "[(1,)]" ]] \
  && [[ $(SQL "SELECT time, headline FROM entries WHERE pipeline_task='appx#87'") == *"09:00"*"Merged to v3"* ]] \
  && pass "pipeline consolidation (1 row, earliest ts)" || fail "pipeline consolidation (rows=$rows)"

# 6. headline newline collapse
"$LOG_EVENT" carol --at 14:00 --date "$DAY" "line one
line two" >/dev/null
"$LOG_EVENT" tail carol -n 1 | grep -q "line one line two" \
  && pass "headline collapse" || fail "headline collapse"

# 7. bad --at rejected
"$LOG_EVENT" alice --at 9am --date "$DAY" "bad ts" >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "bad --at rejected" || fail "bad --at rejected"

# 8. missing args rejected
"$LOG_EVENT" alice >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "missing args rejected" || fail "missing args rejected"

# ---- origin: direct / indirect ---------------------------------------------

# 9. default origin is direct
[[ $(SQL "SELECT origin FROM entries WHERE headline='First thing shipped'") == "[('direct',)]" ]] \
  && pass "origin defaults to direct" || fail "origin default"

# 10. --origin indirect stored
"$LOG_EVENT" botty --at 10:30 --date "$DAY" "Cron did a thing" --origin indirect >/dev/null
[[ $(SQL "SELECT origin FROM entries WHERE agent='botty'") == "[('indirect',)]" ]] \
  && pass "--origin indirect stored" || fail "--origin indirect"

# 11. JSTACK_TIMELINE_ORIGIN env sets the default; explicit flag beats env
JSTACK_TIMELINE_ORIGIN=indirect "$LOG_EVENT" envy --at 10:31 --date "$DAY" "Spawned work" >/dev/null
[[ $(SQL "SELECT origin FROM entries WHERE agent='envy'") == "[('indirect',)]" ]] \
  && pass "env origin default" || fail "env origin default"
JSTACK_TIMELINE_ORIGIN=indirect "$LOG_EVENT" envy2 --at 10:32 --date "$DAY" "Human insisted" --origin direct >/dev/null
[[ $(SQL "SELECT origin FROM entries WHERE agent='envy2'") == "[('direct',)]" ]] \
  && pass "flag beats env" || fail "flag beats env"

# 12. bad --origin rejected; bad env falls back to direct (never blocks a write)
"$LOG_EVENT" alice --at 10:33 --date "$DAY" "x" --origin sideways >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "bad --origin rejected" || fail "bad --origin rejected"
JSTACK_TIMELINE_ORIGIN=sideways "$LOG_EVENT" envy3 --at 10:34 --date "$DAY" "Bad env write" >/dev/null
[[ $(SQL "SELECT origin FROM entries WHERE agent='envy3'") == "[('direct',)]" ]] \
  && pass "bad env origin falls back to direct" || fail "bad env origin"

# 13. pipeline consolidation carries origin too
"$LOG_EVENT" bob --date "$DAY" --pipeline-task "appx#87" "Deployed" --origin indirect >/dev/null
[[ $(SQL "SELECT origin FROM entries WHERE pipeline_task='appx#87'") == "[('indirect',)]" ]] \
  && pass "pipeline row carries origin" || fail "pipeline origin"

# ---- seats, tail, verdicts ---------------------------------------------------

# 14. agent/submode source: stores split columns; --session binds
"$LOG_EVENT" alpha/chat --at 15:00 --date "$DAY" "Seat-tagged entry" --session sess-123 >/dev/null
[[ $(SQL "SELECT agent, submode, session_id FROM entries WHERE headline='Seat-tagged entry'") == "[('alpha', 'chat', 'sess-123')]" ]] \
  && pass "agent/submode source + --session" || fail "agent/submode source + --session"

# 15. tail: seat-filtered, oldest→newest, -n honored
"$LOG_EVENT" alpha/chat --at 15:10 --date "$DAY" "Second seat entry" --detail "a bullet" >/dev/null
"$LOG_EVENT" alpha/pm --at 15:20 --date "$DAY" "Other seat entry" >/dev/null
t=$("$LOG_EVENT" tail alpha/chat -n 5)
echo "$t" | grep -q "Seat-tagged entry" && echo "$t" | grep -q "Second seat entry" \
  && ! echo "$t" | grep -q "Other seat entry" \
  && [[ $(echo "$t" | head -1) == *"Seat-tagged entry"* ]] \
  && pass "tail seat filter + order" || fail "tail seat filter + order"

# 16. tail bare agent matches all submodes; -n limits
t=$("$LOG_EVENT" tail alpha -n 2)
echo "$t" | grep -q "Other seat entry" && echo "$t" | grep -q "Second seat entry" \
  && ! echo "$t" | grep -q "Seat-tagged entry" \
  && pass "tail bare agent + -n limit" || fail "tail bare agent + -n limit"

# 17. verdict stamps the seat's latest entry; rides tail
"$LOG_EVENT" verdict alpha/chat blocked --note "waiting on a decision" >/dev/null
"$LOG_EVENT" tail alpha/chat -n 1 | grep -q "↳ verdict: blocked — waiting on a decision" \
  && pass "verdict on latest" || fail "verdict on latest"

# 18. verdict rejects bad values / unknown seat
"$LOG_EVENT" verdict alpha/chat wonderful --note x >/dev/null 2>&1
[[ $? -eq 2 ]] || fail "bad verdict value rejected"
"$LOG_EVENT" verdict nobody/void blocked --note x >/dev/null 2>&1
[[ $? -eq 1 ]] && pass "verdict validation" || fail "verdict validation (unknown seat)"

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

# 21. --context: on-demand depth — in the db, absent from default tail
#     (injection stays lean), surfaced by tail --json (with id + session_id + origin)
"$LOG_EVENT" alpha/chat --at 15:30 --date "$DAY" "Entry with depth" \
  --detail "a visible bullet" --context "long freeform recall notes, survives transcript deletion" >/dev/null
J=$("$LOG_EVENT" tail alpha/chat -n 5 --json)
! "$LOG_EVENT" tail alpha/chat -n 5 | grep -q "long freeform recall" \
  && echo "$J" | grep -q "long freeform recall" \
  && echo "$J" | grep -q '"session_id": "sess-123"' \
  && echo "$J" | grep -q '"origin": "direct"' \
  && echo "$J" | grep -q '"id":' \
  && pass "context: db-only, --json carries id/session/origin/context" || fail "context isolation"

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
out=$("$LOG_EVENT" grep "first thing")
echo "$out" | grep -q "First thing shipped" && echo "$out" | grep -q "$DAY" \
  && echo "$out" | grep -q "\[alice\]" && echo "$out" | grep -qE "^#[0-9]+ " \
  && pass "grep: cross-day, case-insensitive" || fail "grep basics"
"$LOG_EVENT" grep "freeform recall" | grep -q "Entry with depth" \
  && pass "grep: matches context field" || fail "grep context match"
"$LOG_EVENT" grep "no-such-string-anywhere" >/dev/null
[[ $? -eq 1 ]] && pass "grep: no match exit 1" || fail "grep no-match exit"

# 24. grep filters: --seat narrows to the seat, --since drops earlier days
out=$("$LOG_EVENT" grep "seat entry" --seat alpha/chat)
echo "$out" | grep -q "Second seat entry" && ! echo "$out" | grep -q "Other seat entry" \
  && pass "grep: --seat filter" || fail "grep --seat"
"$LOG_EVENT" grep "First thing" --since 2026-02-01 >/dev/null
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

# 25. schema upgrade: a pre-context, pre-origin db (real dbs on installed hosts)
#     gains both columns on first connect — write with --context/--origin works,
#     legacy rows read back with origin ''
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
  --context "written after ALTER" --origin indirect >/dev/null 2>&1 || fail "upgrade write errored"
up=$(python3 -c "import sqlite3; print(sqlite3.connect('$OLD/timeline.db').execute(\"SELECT origin, context FROM entries WHERE headline='Post-upgrade row'\").fetchall())")
legacy=$(python3 -c "import sqlite3; print(sqlite3.connect('$OLD/timeline.db').execute(\"SELECT origin FROM entries WHERE headline='Pre-upgrade row'\").fetchall())")
[[ "$up" == *"indirect"*"written after ALTER"* && "$legacy" == "[('',)]" ]] \
  && pass "schema upgrade: old db gains context+origin" || fail "schema upgrade (got $up / $legacy)"

# 26a. recall <date>: full blocks for a day, all seats, chronological, with #ids and origin
out=$("$LOG_EVENT" recall "$DAY")
echo "$out" | grep -q "First thing shipped" && echo "$out" | grep -q "Seat-tagged entry" \
  && echo "$out" | grep -q "\[alice\]" && echo "$out" | grep -q "\[alpha/chat\]" \
  && echo "$out" | grep -qE "^#[0-9]+ $DAY 10:00" \
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
"$LOG_EVENT" delta --at 08:00 --date 2026-01-10 "Earlier-day entry" >/dev/null
out=$("$LOG_EVENT" recall "2026-01-10..$DAY" all)
echo "$out" | grep -q "Earlier-day entry" && echo "$out" | grep -q "First thing shipped" \
  && pass "recall range" || fail "recall range"
"$LOG_EVENT" recall 2001-01-01 >/dev/null
[[ $? -eq 1 ]] && pass "recall empty day exit 1" || fail "recall empty day exit"
"$LOG_EVENT" recall jan-24 >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "recall bad date exit 2" || fail "recall bad date exit"

# 27. bare write — no --at, no --date: lands today, stamped now (machine-local)
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

# 28. retired subcommands are gone: render/migrate must error, not silently no-op
"$LOG_EVENT" render >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "render retired" || fail "render retired"
"$LOG_EVENT" migrate >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "migrate retired" || fail "migrate retired"

# 29. seat gate — a non-seat first positional must never become a timeline agent
#     (real corruption shapes: hallucinated 'add' verb, flag-as-agent, swallowed flags)
err=$("$LOG_EVENT" add "alpha/chat Did a thing" 2>&1 >/dev/null)
[[ $? -eq 2 && "$err" == *"did you mean: log_event alpha/chat"* ]] \
  && pass "write verb rejected with seat hint" || fail "write verb rejected"
[[ $(SQL "SELECT COUNT(*) FROM entries WHERE agent='add'") == "[(0,)]" ]] \
  && pass "no 'add' agent row written" || fail "'add' agent row leaked"
"$LOG_EVENT" --at 10:00 alpha "Flag first" >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "flag-as-seat rejected" || fail "flag-as-seat rejected"
"$LOG_EVENT" "Alpha Team" "Bad charset" >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "bad seat charset rejected" || fail "bad seat charset rejected"
err=$("$LOG_EVENT" alpha --at 10:05 --date "$DAY" "Headline" --body "swallowed" 2>&1 >/dev/null)
[[ $? -eq 2 && "$err" == *"unknown flag --body"* ]] \
  && pass "unknown write flag rejected" || fail "unknown write flag rejected"
[[ $(SQL "SELECT COUNT(*) FROM entries WHERE headline LIKE '%--body%'") == "[(0,)]" ]] \
  && pass "no flag text swallowed into headline" || fail "flag text swallowed"
"$LOG_EVENT" alpha/social/chat --at 10:06 --date "$DAY" "Deep seat write" >/dev/null \
  || fail "deep seat write exit"
[[ $(SQL "SELECT agent, submode FROM entries WHERE headline='Deep seat write'") == "[('alpha', 'social/chat')]" ]] \
  && pass "multi-slash submode still writes" || fail "multi-slash submode write"

echo
if [[ $fails -gt 0 ]]; then
  echo "log-event: $fails FAILED" >&2
  exit 1
fi
echo "log-event: all pass"
