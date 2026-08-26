#!/usr/bin/env bash
# JStack live test — bin/msg, the addressed agent-to-agent inbox.
#
# Runs the real shipped script against a temp JSTACK_TIMELINE_DIR and a temp
# agent tree (hermetic — never touches the real timeline or ~/Agents).
# Verifies the CLI contract:
#   - addressing: @agent -> agent/chat; hyphens walk down; a seat holding a
#     chat/ dir descends into it (@alice-social -> alice/social/chat)
#   - a directory that is not a seat (no CLAUDE.md) is refused at send time
#   - @boss is refused; an unknown agent is refused
#   - send -> inbox -> read -> reply roundtrip, reply lands in the sender's own
#     inbox and joins the thread
#   - done requires a note, records it, and removes the item from the inbox
#   - defer hides an item until its time, then it re-opens; a past --until is
#     refused
#   - attachments are copied into the RECEIVER's pad
#   - a wake that cannot be booked still files the message (exit 0)
#   - the timeline's own `entries` table is untouched
#
# Exit 0 = all pass, exit 1 = any fail.

set -u

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MSG="$PLUGIN_ROOT/bin/msg"
LOG_EVENT="$PLUGIN_ROOT/bin/log_event"

TMP=$(mktemp -d /tmp/jstack-msg-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT
export JSTACK_TIMELINE_DIR="$TMP/timeline"
DB="$TMP/timeline/timeline.db"

fails=0
fail() { echo "FAIL: $1" >&2; fails=$((fails+1)); }
pass() { echo "ok: $1"; }

[[ -x "$MSG" ]] || { echo "FAIL: $MSG not executable" >&2; exit 1; }

# ---------------------------------------------------------------- fake tree
AR="$TMP/agents"
for seat in Alice Alice/chat Alice/social Alice/social/chat Alice/pm \
            Bob Bob/chat Bob/service-call; do
  mkdir -p "$AR/$seat"; echo "# $seat" > "$AR/$seat/CLAUDE.md"
done
mkdir -p "$AR/Alice/pad" "$AR/Alice/scratch"     # storage, NOT seats

export JSTACK_REVIEW_CONFIG="$TMP/review.json"
cat > "$JSTACK_REVIEW_CONFIG" <<EOF
{"agent_root": "$AR"}
EOF

SQL() { python3 -c "import sqlite3,sys; print(sqlite3.connect('$DB').execute(sys.argv[1]).fetchall())" "$1"; }
cd "$AR/Alice/chat" || exit 1

# ------------------------------------------------------------- 1. addressing
addr() { "$MSG" send "$1" "probe $1" 2>&1 | tail -1; }

[[ "$(addr @bob)"              == *"→ bob/chat"*              ]] && pass "@bob -> bob/chat"                     || fail "@bob -> bob/chat"
[[ "$(addr @alice-social)"     == *"→ alice/social/chat"*     ]] && pass "@alice-social descends into chat/"    || fail "@alice-social descends into chat/"
[[ "$(addr @alice-pm)"         == *"→ alice/pm"*              ]] && pass "@alice-pm stays put (no pm/chat)"     || fail "@alice-pm stays put"
[[ "$(addr @bob-service-call)" == *"→ bob/service-call"*      ]] && pass "hyphenated seat dir resolves"         || fail "hyphenated seat dir resolves"
[[ "$(addr @self)"             == *"→ alice/chat"*            ]] && pass "@self is the sending seat"            || fail "@self is the sending seat"

# a dir with no CLAUDE.md is not a seat — a message there could never be read
out=$("$MSG" send @alice-pad "x" 2>&1); rc=$?
[[ $rc -ne 0 && "$out" == *"no seat"* ]] && pass "non-seat dir refused" || fail "non-seat dir refused (rc=$rc: $out)"

out=$("$MSG" send @nosuch "x" 2>&1); rc=$?
[[ $rc -ne 0 && "$out" == *"unknown agent"* ]] && pass "unknown agent refused" || fail "unknown agent refused"

out=$("$MSG" send @boss "x" 2>&1); rc=$?
[[ $rc -ne 0 && "$out" == *"not a mailbox"* ]] && pass "@boss refused" || fail "@boss refused"

# --------------------------------------------------- 2. send/read/reply loop
# The addressing probes above deliberately filed real messages. Close them so
# the lifecycle assertions below read an inbox they alone control.
python3 - "$DB" <<'PY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.execute("UPDATE messages SET state='done', resolution='addressing probe', "
            "resolved_by='test'")
con.commit()
PY

echo "payload" > "$TMP/att.txt"
"$MSG" send @bob "Subject line here
Body line one.
Body line two." --file "$TMP/att.txt" >/dev/null || fail "send with body+attachment exit"
MID=$(SQL "SELECT MAX(id) FROM messages WHERE to_seat='bob/chat' AND subject='Subject line here'" | grep -oE '[0-9]+')

inbox=$("$MSG" inbox --seat bob/chat)
[[ "$inbox" == *"Subject line here"* ]] && pass "message lands in receiver inbox" || fail "message lands in receiver inbox"

body=$("$MSG" read "$MID")
[[ "$body" == *"Body line two."* ]] && pass "read shows the body" || fail "read shows the body"

# the attachment is copied to the RECEIVER's pad, not left on the sender's side
att=$(ls "$AR/Bob/chat/pad"/*att.txt 2>/dev/null | wc -l | tr -d ' ')
[[ "$att" == "1" ]] && pass "attachment copied into receiver's pad" || fail "attachment copied into receiver's pad"
[[ "$body" == *"$AR/Bob/chat/pad"* ]] && pass "attachment path recorded" || fail "attachment path recorded"

# a file ALREADY in the receiver's pad (a share-sheet drop lands there before
# the message is written) is recorded in place, never copied beside itself
DROP="$AR/Bob/chat/pad/20260101-000000-drop.png"
printf 'bytes' > "$DROP"
"$MSG" send @bob "Dropped screenshot" --file "$DROP" --from boss >/dev/null
[[ "$(ls "$AR/Bob/chat/pad" | grep -c 'drop.png')" == "1" ]] \
  && pass "in-pad attachment not duplicated" || fail "in-pad attachment not duplicated"
DID=$(SQL "SELECT MAX(id) FROM messages WHERE subject='Dropped screenshot'" | grep -oE '[0-9]+')
# and a file anywhere else under the receiving AGENT's tree (the share sheet
# drops into the agent-root pad, not the seat's) is likewise recorded in place
AGENTDROP="$AR/Bob/pad/20260101-000000-agentdrop.png"
mkdir -p "$AR/Bob/pad"; printf 'bytes' > "$AGENTDROP"
"$MSG" send @bob "Agent-root drop" --file "$AGENTDROP" --from boss >/dev/null
ADID=$(SQL "SELECT MAX(id) FROM messages WHERE subject='Agent-root drop'" | grep -oE '[0-9]+')
[[ "$("$MSG" read "$ADID")" == *"$AGENTDROP"* ]] \
  && pass "agent-tree attachment recorded in place" || fail "agent-tree attachment recorded in place"
[[ "$(find "$AR/Bob" -name '*agentdrop.png' | wc -l | tr -d ' ')" == "1" ]] \
  && pass "agent-tree attachment not duplicated" || fail "agent-tree attachment not duplicated"
JSTACK_MAIL_FROM=bob/chat "$MSG" done "$ADID" --note "drop test" >/dev/null

[[ "$("$MSG" read "$DID")" == *"$DROP"* ]] && pass "in-pad attachment recorded in place" || fail "in-pad attachment recorded in place"
[[ "$(SQL "SELECT from_seat FROM messages WHERE id=$DID")" == "[('boss',)]" ]] \
  && pass "--from boss recorded (share-sheet drop)" || fail "--from boss recorded"
# close it — the inbox assertions below own bob's inbox and must read only
# what they put there
JSTACK_MAIL_FROM=bob/chat "$MSG" done "$DID" --note "drop test" >/dev/null

# reply routes back to the sender's own inbox and joins the thread
JSTACK_MAIL_FROM=bob/chat "$MSG" reply "$MID" "Answered." >/dev/null || fail "reply exit"
RID=$(SQL "SELECT MAX(id) FROM messages WHERE to_seat='alice/chat' AND subject='Answered.'" | grep -oE '[0-9]+')
[[ -n "$RID" ]] && pass "reply lands in sender's inbox" || fail "reply lands in sender's inbox"
[[ "$(SQL "SELECT reply_to FROM messages WHERE id=$RID")" == "[($MID,)]" ]] \
  && pass "reply links to its parent" || fail "reply links to its parent"
[[ "$(SQL "SELECT thread_id FROM messages WHERE id=$RID")" == "[($MID,)]" ]] \
  && pass "reply joins the thread" || fail "reply joins the thread"
[[ "$("$MSG" thread "$MID" | grep -c '^\[#')" == "2" ]] && pass "thread shows both" || fail "thread shows both"

# ------------------------------------------------------------- 3. closing
out=$("$MSG" done "$MID" --note "" 2>&1); rc=$?
[[ $rc -ne 0 && "$out" == *"--note is required"* ]] && pass "close demands a record" || fail "close demands a record"

JSTACK_MAIL_FROM=bob/chat "$MSG" done "$MID" --note "Read it and shipped the fix." >/dev/null
[[ "$("$MSG" inbox --seat bob/chat)" == "(nothing)" ]] && pass "closed leaves the inbox" || fail "closed leaves the inbox"
[[ "$(SQL "SELECT state, resolution, resolved_by FROM messages WHERE id=$MID")" \
   == "[('done', 'Read it and shipped the fix.', 'bob/chat')]" ]] \
  && pass "resolution + closer recorded" || fail "resolution + closer recorded"

out=$("$MSG" done "$MID" --note "again" 2>&1); rc=$?
[[ $rc -eq 0 && "$out" == *"already closed"* ]] && pass "double close is a no-op" || fail "double close is a no-op"

# -------------------------------------------------------------- 4. deferring
"$MSG" send @bob "Later thing" >/dev/null
LID=$(SQL "SELECT MAX(id) FROM messages WHERE subject='Later thing'" | grep -oE '[0-9]+')

out=$("$MSG" defer "$LID" --until "2020-01-01 09:00" 2>&1); rc=$?
[[ $rc -ne 0 && "$out" == *"in the past"* ]] && pass "past defer refused" || fail "past defer refused"

"$MSG" defer "$LID" --until "2099-01-01 09:00" --note "blocked on X" >/dev/null
[[ "$("$MSG" inbox --seat bob/chat)" == "(nothing)" ]] && pass "deferred hides until due" || fail "deferred hides until due"
[[ "$("$MSG" read "$LID")" == *"blocked on X"* ]] && pass "defer reason kept" || fail "defer reason kept"

python3 -c "import sqlite3; sqlite3.connect('$DB').execute(\"UPDATE messages SET deferred_until='2020-01-01T09:00:00' WHERE id=$LID\").connection.commit()"
[[ "$("$MSG" inbox --seat bob/chat)" == *"Later thing"* ]] && pass "deferred re-opens when due" || fail "deferred re-opens when due"

# ------------------------------------------------------- 5. hook helper + wake
"$MSG" pending-for bob/chat >/dev/null; [[ $? -eq 0 ]] && pass "pending-for exit 0 with items" || fail "pending-for exit 0 with items"
"$MSG" pending-for alice/pm  >/dev/null; [[ $? -eq 1 ]] && pass "pending-for exit 1 when empty" || fail "pending-for exit 1 when empty"

# a wake that cannot be booked must still file the message — never lose mail
cat > "$JSTACK_REVIEW_CONFIG" <<EOF
{"agent_root": "$AR", "mail": {"scheduler_home": "/nonexistent", "python": "/nonexistent/python"}}
EOF
out=$("$MSG" send @bob "Wake that cannot book" --wake 2>&1); rc=$?
[[ $rc -eq 0 ]] && pass "broken wake still exits 0" || fail "broken wake still exits 0 (rc=$rc)"
[[ "$out" == *"warning"* ]] && pass "broken wake warns" || fail "broken wake warns"
[[ "$("$MSG" inbox --seat bob/chat)" == *"Wake that cannot book"* ]] \
  && pass "broken wake still files the message" || fail "broken wake still files the message"
cat > "$JSTACK_REVIEW_CONFIG" <<EOF
{"agent_root": "$AR"}
EOF

# ------------------------------------------------- 6. coexistence with timeline
"$LOG_EVENT" alice/chat --at 10:00 --date 2026-01-15 "A timeline entry" >/dev/null
[[ "$(SQL "SELECT COUNT(*) FROM entries")" == "[(1,)]" ]] && pass "timeline entries unaffected" || fail "timeline entries unaffected"
[[ "$("$LOG_EVENT" tail alice/chat -n 5)" == *"A timeline entry"* ]] && pass "log_event still reads its own table" || fail "log_event still reads its own table"

echo
if [[ $fails -eq 0 ]]; then echo "ALL PASS"; exit 0; else echo "$fails FAILED"; exit 1; fi
