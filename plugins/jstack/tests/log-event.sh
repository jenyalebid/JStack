#!/usr/bin/env bash
# JStack live test — bin/log_event timeline writer.
#
# Runs the real shipped script against a temp JSTACK_TIMELINE_DIR (hermetic —
# never touches the real timeline). Verifies the full CLI contract:
#   - sqlite store is the ONLY artifact — no md file is ever written
#   - chronological order by --at; --date targets the named day
#   - --pipeline-task consolidation: one live row per task, earliest ts kept
#   - origin: direct|indirect — flag > JSTACK_TIMELINE_ORIGIN env > direct
#   - tags: a session→tag relation, minted deliberately, filtering every read
#   - bad --at / bad --origin / missing args → exit 2
#
# Exit 0 = all pass, exit 1 = any fail.

set -u

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_EVENT="$PLUGIN_ROOT/bin/log_event"

TMP=$(mktemp -d /tmp/jstack-log-event-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT
export JSTACK_TIMELINE_DIR="$TMP"

# Hermetic in the environment too, not just on disk. A write with no --session
# now falls back to $CLAUDE_CODE_SESSION_ID, so running this suite from inside a
# live session would silently stamp every "sessionless" row with the ambient id
# and quietly retire the cases that depend on there being none. The fallback
# gets its own test below, with the var set on purpose.
unset CLAUDE_CODE_SESSION_ID
# Same trap, second var: origin resolves flag > $JSTACK_TIMELINE_ORIGIN > direct,
# and cron/auto sessions export it as `indirect`. Inheriting it would flip the
# default-origin cases — a suite that passes for a typed session and fails for a
# cron one is a test that reports the runner, not the code. The env-default case
# sets it on purpose below.
unset JSTACK_TIMELINE_ORIGIN

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

# ---- tail --origin direct: the injection view --------------------------------
# Auto-session (indirect) rows never ride the human-driven view; legacy ''
# rows (pre-origin era) count as direct.
"$LOG_EVENT" hank/chat --at 09:00 --date "$DAY" "Human drove this" >/dev/null
"$LOG_EVENT" hank/chat --at 09:05 --date "$DAY" --origin indirect "Published by a cron" >/dev/null
python3 -c "import sqlite3; c=sqlite3.connect('$DB'); c.execute(\"INSERT INTO entries(date,time,agent,submode,headline,details,created_at,context,origin) VALUES('$DAY','09:10','hank','chat','Legacy pre-origin row','[]','x','','')\"); c.commit()"
t=$("$LOG_EVENT" tail hank/chat -n 10 --origin direct)
[[ "$t" == *"Human drove this"* && "$t" == *"Legacy pre-origin row"* && "$t" != *"Published by a cron"* ]] \
  && pass "tail --origin direct drops indirect, keeps legacy" || fail "tail --origin direct filter"
t=$("$LOG_EVENT" tail hank/chat -n 10)
[[ "$t" == *"Published by a cron"* ]] \
  && pass "unfiltered tail still shows indirect" || fail "unfiltered tail shows indirect"
"$LOG_EVENT" tail hank/chat --origin indirect >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "tail --origin rejects non-direct values" || fail "tail --origin value gate"

# ---- tail --sessions: the window counts sittings, not entries ----------------
# One session that logged three times is ONE unit and comes back whole; a row
# with no session id is its own session (legacy rows can't collapse into one
# bucket and eat the window).
"$LOG_EVENT" iris/chat --at 08:00 --date "$DAY" --session s-one "Iris session one" >/dev/null
"$LOG_EVENT" iris/chat --at 08:30 --date "$DAY" --session s-two "Iris two first" >/dev/null
"$LOG_EVENT" iris/chat --at 09:00 --date "$DAY" --session s-two "Iris two second" >/dev/null
"$LOG_EVENT" iris/chat --at 09:30 --date "$DAY" "Iris sessionless" >/dev/null
t=$("$LOG_EVENT" tail iris/chat --sessions 2)
[[ "$t" == *"Iris sessionless"* && "$t" == *"Iris two first"* && "$t" == *"Iris two second"* \
   && "$t" != *"Iris session one"* ]] \
  && pass "tail --sessions windows by session, whole sessions ride" \
  || fail "tail --sessions window ($t)"
t=$("$LOG_EVENT" tail iris/chat -n 2)
[[ "$t" == *"Iris two second"* && "$t" != *"Iris two first"* ]] \
  && pass "tail -n still counts entries" || fail "tail -n entry count ($t)"
t=$("$LOG_EVENT" tail iris/chat --sessions 99)
[[ "$t" == *"Iris session one"* ]] \
  && pass "tail --sessions beyond history returns all" || fail "tail --sessions overflow"

# ---- tags: a session→tag relation, and the gates that keep it small ---------
# The value of a tag is that a small shared vocabulary means the same thing to
# every writer. Everything below guards that: minting costs a description, an
# unrecognized name is refused rather than created, and a query against a name
# nobody defined errors instead of returning an empty list that reads as "we
# never worked on it".
"$LOG_EVENT" tag new jremote --description "the iOS remote app and its host board" >/dev/null 2>&1 \
  && pass "tag new creates" || fail "tag new creates"
"$LOG_EVENT" tag new infra --description "daemons, dashboard, scheduler" >/dev/null 2>&1
"$LOG_EVENT" tag new sloppy >/dev/null 2>&1
[[ $? -eq 2 && $(SQL "SELECT COUNT(*) FROM tags WHERE name='sloppy'") == "[(0,)]" ]] \
  && pass "tag new without --description refused, nothing created" || fail "tag new description gate"
"$LOG_EVENT" tag new jremote --description "duplicate" >/dev/null 2>&1
[[ $? -eq 2 && $(SQL "SELECT COUNT(*) FROM tags WHERE name='jremote'") == "[(1,)]" ]] \
  && pass "duplicate tag refused" || fail "duplicate tag refused"
"$LOG_EVENT" tag new "Not A Tag" --description "x" >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "malformed tag name refused" || fail "malformed tag name refused"

# The relation is session→tag, so entries reach their tags through session_id.
# One session spanning two seats is the case the whole feature exists for.
"$LOG_EVENT" kim/chat --at 07:00 --date "$DAY" --session tag-s1 "Kim on the remote" >/dev/null
"$LOG_EVENT" lee/chat --at 07:05 --date "$DAY" --session tag-s1 "Lee on the remote" >/dev/null
"$LOG_EVENT" kim/chat --at 07:10 --date "$DAY" --session tag-s2 "Kim on the daemons" >/dev/null
"$LOG_EVENT" tag set jremote --session tag-s1 >/dev/null
"$LOG_EVENT" tag set infra --session tag-s2 >/dev/null

"$LOG_EVENT" tag set nosuchthing --session tag-s1 >/dev/null 2>&1
[[ $? -eq 2 && $(SQL "SELECT COUNT(*) FROM tags WHERE name='nosuchthing'") == "[(0,)]" ]] \
  && pass "tag set refuses an unknown name instead of minting it" || fail "tag set auto-mint guard"

# A picker reads the vocabulary to offer it, and has to know which names are
# already on the session in hand — offering what is set is how a pick becomes a
# no-op the user has to notice for themselves.
out=$("$LOG_EVENT" tag list --session tag-s1)
[[ "$out" == *"● jremote"* && "$out" != *"● infra"* ]] \
  && pass "tag list marks what the session carries" || fail "tag list --session marker ($out)"
[[ $("$LOG_EVENT" tag list --session tag-s1 --json | grep -c '"carried": true') == 1 ]] \
  && pass "tag list --json carries the membership" || fail "tag list --json carried"
[[ "$(env -u CLAUDE_CODE_SESSION_ID "$LOG_EVENT" tag list)" != *"●"* ]] \
  && pass "no session, no marker column" || fail "tag list marks with no session"

out=$("$LOG_EVENT" tag show jremote)
[[ "$out" == *"Kim on the remote"* && "$out" == *"Lee on the remote"* && "$out" != *"daemons"* ]] \
  && pass "tag show spans seats, excludes other tags" || fail "tag show cross-seat ($out)"

out=$("$LOG_EVENT" tail kim/chat -n 10 --tag jremote)
[[ "$out" == *"Kim on the remote"* && "$out" != *"Kim on the daemons"* ]] \
  && pass "tail --tag filters through session_id" || fail "tail --tag ($out)"

# ---- editing the vocabulary: describe, rename, delete ----------------------
# A vocabulary worth sharing is one that can be corrected. Minting was the only
# verb for a while, which made every typo permanent and every retired subject a
# row nobody could remove — these three are the repairs, and the property that
# matters is which of them keep the filings: describe and rename do, delete is
# the one that throws them away and therefore the one with a gate.
# Fresh names throughout, so the read cases above keep the vocabulary they set up.
"$LOG_EVENT" tag new typoo --description "frist guess" >/dev/null 2>&1
"$LOG_EVENT" tag set typoo --session tag-edit-s1 >/dev/null 2>&1
"$LOG_EVENT" kim/chat --at 07:20 --date "$DAY" --session tag-edit-s1 "Kim on the typo" >/dev/null

"$LOG_EVENT" tag describe typoo --description "what actually belongs here" >/dev/null 2>&1
out=$("$LOG_EVENT" tag list)
[[ "$out" == *"what actually belongs here"* && "$out" != *"frist guess"* ]] \
  && pass "tag describe rewrites the sentence the next writer matches on" \
  || fail "tag describe ($out)"

"$LOG_EVENT" tag describe ghost --description "x" >/dev/null 2>&1
[[ $? -eq 2 && "$("$LOG_EVENT" tag list)" != *ghost* ]] \
  && pass "describing an unknown tag fails instead of minting it" \
  || fail "tag describe unknown-name mint guard"

"$LOG_EVENT" tag describe typoo --description "   " >/dev/null 2>&1
[[ $? -eq 2 && "$("$LOG_EVENT" tag list)" == *"what actually belongs here"* ]] \
  && pass "a blank description is refused, the old one stands" \
  || fail "tag describe blank gate"

# The property the whole rename exists for: sessions reach a tag by id, so a
# rename must carry every filing with it. A rename that dropped them would look
# identical in `tag list` and be found only by the read that came up empty.
"$LOG_EVENT" tag rename typoo typo-fixed >/dev/null 2>&1
out=$("$LOG_EVENT" tail --tag typo-fixed --sessions 10)
[[ "$out" == *"Kim on the typo"* ]] \
  && pass "tag rename carries the sessions filed under it" || fail "tag rename keeps filings ($out)"
[[ "$("$LOG_EVENT" tag list --session tag-edit-s1)" == *"● typo-fixed"* ]] \
  && pass "the renamed tag is still carried by its session" || fail "tag rename membership"

"$LOG_EVENT" tag rename typo-fixed infra >/dev/null 2>&1
[[ $? -eq 2 && "$("$LOG_EVENT" tag list)" == *typo-fixed* ]] \
  && pass "renaming onto an existing tag is refused, not merged" || fail "tag rename collision gate"

"$LOG_EVENT" tag rename typo-fixed "Not A Tag" >/dev/null 2>&1
[[ $? -eq 2 && "$("$LOG_EVENT" tag list)" == *typo-fixed* ]] \
  && pass "rename applies the same name rule as mint" || fail "tag rename name rule"

# Delete: the destructive one. Carried means it takes filings with it, so the
# count comes back with the refusal — the caller decides holding the number.
out=$("$LOG_EVENT" tag delete typo-fixed 2>&1)
[[ $? -eq 2 && "$out" == *"carried by 1 session"* && "$("$LOG_EVENT" tag list)" == *typo-fixed* ]] \
  && pass "deleting a carried tag refuses and reports what it would unfile" \
  || fail "tag delete carried gate ($out)"

"$LOG_EVENT" tag new unused-tag --description "nothing carries this" >/dev/null 2>&1
"$LOG_EVENT" tag delete unused-tag >/dev/null 2>&1
[[ $? -eq 0 && "$("$LOG_EVENT" tag list)" != *unused-tag* ]] \
  && pass "an uncarried tag deletes without --force" || fail "tag delete uncarried"

# session_tags declares ON DELETE CASCADE, but connect() sets no
# `PRAGMA foreign_keys=ON`, so sqlite never fires it. If the delete ever stops
# clearing membership by hand, these rows survive pointing at a tag id that is
# gone — invisible to every read, and waiting for an id to be reused.
"$LOG_EVENT" tag delete typo-fixed --force >/dev/null 2>&1
orphans=$(python3 -c "
import sqlite3; c = sqlite3.connect('$TMP/timeline.db')
print(c.execute('SELECT COUNT(*) FROM session_tags st'
                ' LEFT JOIN tags t ON t.id = st.tag_id WHERE t.id IS NULL').fetchone()[0])")
[[ "$("$LOG_EVENT" tag list)" != *typo-fixed* && "$orphans" == 0 ]] \
  && pass "--force deletes and leaves no membership row behind" \
  || fail "tag delete --force ($orphans orphan session_tags rows)"

"$LOG_EVENT" tag delete never-existed >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "deleting an unknown tag fails loudly" || fail "tag delete unknown"

# The subject read: a seatless tail is the window over a TAG instead of a seat,
# which is what a session pinned to a subject boots on. Two agents on one
# subject are one thread — so Lee's row must ride Kim's, and the seat has to be
# named on every line or the block reads as one agent's own history.
out=$("$LOG_EVENT" tail --tag jremote --sessions 10)
[[ "$out" == *"Kim on the remote"* && "$out" == *"Lee on the remote"* \
   && "$out" != *"daemons"* ]] \
  && pass "seatless tail --tag spans agents" || fail "seatless tail --tag ($out)"
[[ "$out" == *"[kim/chat]"* && "$out" == *"[lee/chat]"* ]] \
  && pass "subject read names the seat on each line" || fail "subject read seat labels ($out)"
# A seat read must NOT gain the label — it would repeat the seat just asked for.
[[ $("$LOG_EVENT" tail kim/chat -n 10) != *"[kim/chat]"* ]] \
  && pass "seat read stays unlabelled" || fail "seat read gained a label"
# Seatless with no tag is "everything, ever" — never what anyone meant.
"$LOG_EVENT" tail --sessions 5 >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "seatless tail with no tag refused" || fail "seatless tail no-tag gate"
"$LOG_EVENT" tail --tag ghosttag >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "seatless tail on an unknown tag errors" || fail "seatless unknown tag"
out=$("$LOG_EVENT" grep "Kim on" --tag infra)
[[ "$out" == *"daemons"* && "$out" != *"remote"* ]] \
  && pass "grep --tag filters" || fail "grep --tag ($out)"
out=$("$LOG_EVENT" recall "$DAY" all --tag jremote)
[[ "$out" == *"Lee on the remote"* && "$out" != *"daemons"* ]] \
  && pass "recall --tag filters" || fail "recall --tag ($out)"

# Silence for an undefined tag reads as "that never happened" — a different and
# much more misleading answer than "no such tag".
for verb in "tail kim/chat --tag" "grep Kim --tag" "recall $DAY all --tag"; do
  # shellcheck disable=SC2086
  "$LOG_EVENT" $verb ghosttag >/dev/null 2>&1
  [[ $? -eq 2 ]] || fail "unknown tag on '$verb' should exit 2"
done
"$LOG_EVENT" tail kim/chat --tag ghosttag 2>&1 | grep -q "no tag 'ghosttag'" \
  && pass "unknown tag errors on every read, and names itself" || fail "unknown tag message"

"$LOG_EVENT" tag set "#JRemote" --session tag-s3 >/dev/null 2>&1
[[ $(SQL "SELECT COUNT(*) FROM session_tags WHERE session_id='tag-s3'") == "[(1,)]" ]] \
  && pass "tag names normalize (#JRemote → jremote)" || fail "tag normalize"
"$LOG_EVENT" tag unset jremote --session tag-s3 >/dev/null 2>&1
[[ $(SQL "SELECT COUNT(*) FROM session_tags WHERE session_id='tag-s3'") == "[(0,)]" ]] \
  && pass "tag unset detaches" || fail "tag unset"

# A tag attached to no session can never be queried, so refuse rather than
# silently attach to the empty string.
"$LOG_EVENT" tag set jremote >/dev/null 2>&1
[[ $? -eq 2 ]] && pass "tag set with no session anywhere refused" || fail "tag set no-session gate"

# The write-side fallback. 16% of a recent month's rows carried no session_id —
# an agent typing the write by hand does not think to pass a uuid, and every one
# of those rows is unreachable by any tag. The explicit flag still wins: a caller
# writing on another session's behalf knows better than its own environment.
CLAUDE_CODE_SESSION_ID=env-sess "$LOG_EVENT" mo/chat --at 06:00 --date "$DAY" "From the env" >/dev/null
[[ $(SQL "SELECT session_id FROM entries WHERE headline='From the env'") == "[('env-sess',)]" ]] \
  && pass "write with no --session inherits CLAUDE_CODE_SESSION_ID" || fail "env session fallback"
CLAUDE_CODE_SESSION_ID=env-sess "$LOG_EVENT" mo/chat --at 06:05 --date "$DAY" --session flag-sess "Flag wins" >/dev/null
[[ $(SQL "SELECT session_id FROM entries WHERE headline='Flag wins'") == "[('flag-sess',)]" ]] \
  && pass "explicit --session beats the env var" || fail "explicit session precedence"

out=$("$LOG_EVENT" show "$(SQL "SELECT id FROM entries WHERE headline='Kim on the remote'" | tr -dc '0-9')")
[[ "$out" == *"tags: jremote"* ]] && pass "show prints the session's tags" || fail "show tags line ($out)"

# The relation must arrive on dbs that predate it — the same in-place upgrade
# the context/origin columns get, or every installed host stays tagless.
JSTACK_TIMELINE_DIR="$OLD" "$LOG_EVENT" tag new legacyok --description "arrived by migration" >/dev/null 2>&1
[[ $(python3 -c "import sqlite3; print(sqlite3.connect('$OLD/timeline.db').execute(\"SELECT name FROM tags\").fetchall())") == "[('legacyok',)]" ]] \
  && pass "tag tables migrate onto a pre-tag db" || fail "tag schema migration"

echo
if [[ $fails -gt 0 ]]; then
  echo "log-event: $fails FAILED" >&2
  exit 1
fi
echo "log-event: all pass"
