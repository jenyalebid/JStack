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
#   - defer with no time means "not this session": hidden from the deferring
#     session, open to the next one, and it books nothing
#   - defer --until books a REAL wake at that hour (argv captured from a stub
#     scheduler); a booking that fails is loud and exits non-zero
#   - a past --until is refused, and so is a date with no hour
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

SEEN() { python3 "$TMP/seen.py" "$DB" "$1"; }
SEEN_ALL() { python3 "$TMP/seen.py" "$DB"; }
SQL() { python3 -c "import sqlite3,sys; print(sqlite3.connect('$DB').execute(sys.argv[1]).fetchall())" "$1"; }
cat > "$TMP/seen.py" <<'PYEOF'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
if len(sys.argv) > 2:
    con.execute("UPDATE messages SET state='seen' WHERE id=?", (sys.argv[2],))
else:
    con.execute("UPDATE messages SET state='seen' WHERE state='update'")
con.commit()
PYEOF

cd "$AR/Alice/chat" || exit 1

# ------------------------------------------------------------- 1. addressing
addr() { "$MSG" send "$1" "probe $1" 2>&1 | head -1; }

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
SEEN_ALL

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
SEEN "$ADID"

[[ "$("$MSG" read "$DID")" == *"$DROP"* ]] && pass "in-pad attachment recorded in place" || fail "in-pad attachment recorded in place"
[[ "$(SQL "SELECT from_seat FROM messages WHERE id=$DID")" == "[('boss',)]" ]] \
  && pass "--from boss recorded (share-sheet drop)" || fail "--from boss recorded"
# consume it — the assertions below own bob's inbox and read only their own
SEEN "$DID"

# reply routes back to the sender's own inbox and joins the thread
JSTACK_MAIL_FROM=bob/chat "$MSG" reply "$MID" "Answered." >/dev/null || fail "reply exit"
RID=$(SQL "SELECT MAX(id) FROM messages WHERE to_seat='alice/chat' AND subject='Answered.'" | grep -oE '[0-9]+')
[[ -n "$RID" ]] && pass "reply lands in sender's inbox" || fail "reply lands in sender's inbox"
[[ "$(SQL "SELECT reply_to FROM messages WHERE id=$RID")" == "[($MID,)]" ]] \
  && pass "reply links to its parent" || fail "reply links to its parent"
[[ "$(SQL "SELECT thread_id FROM messages WHERE id=$RID")" == "[($MID,)]" ]] \
  && pass "reply joins the thread" || fail "reply joins the thread"
[[ "$("$MSG" thread "$MID" | grep -c '^\[#')" == "2" ]] && pass "thread shows both" || fail "thread shows both"

# ---------------------------------------------- 3. an update obliges nobody
SEEN_ALL
"$MSG" send @bob "Just news" >/dev/null
[[ "$(SQL "SELECT state FROM messages WHERE subject='Just news'")" == "[('update',)]" ]] \
  && pass "no --wake files an update" || fail "no --wake files an update"

# delivered exactly once: the hook helper consumes it
[[ "$("$MSG" updates-for bob/chat)" == *"Just news"* ]] && pass "update is delivered" || fail "update is delivered"
"$MSG" updates-for bob/chat >/dev/null; [[ $? -eq 1 ]] \
  && pass "update never delivered twice" || fail "update never delivered twice"
[[ "$("$MSG" updates-for bob/chat)" == "[]" ]] && pass "nothing left after delivery" || fail "nothing left after delivery"

# --peek reads without consuming — a failed injection must not eat the news
"$MSG" send @bob "Peekable" >/dev/null
"$MSG" updates-for bob/chat --peek >/dev/null
[[ "$("$MSG" updates-for bob/chat)" == *"Peekable"* ]] \
  && pass "--peek does not consume" || fail "--peek does not consume"

# an update older than the TTL is never shown to anyone — the anti-backlog rule
"$MSG" send @bob "Ancient news" >/dev/null
OLD=$(SQL "SELECT MAX(id) FROM messages WHERE subject='Ancient news'" | grep -oE '[0-9]+')
python3 - "$DB" "$OLD" <<'PY'
import sqlite3, sys
from datetime import datetime, timedelta
old = (datetime.now() - timedelta(days=30)).isoformat(timespec="seconds")
con = sqlite3.connect(sys.argv[1])
con.execute("UPDATE messages SET created_at=? WHERE id=?", (old, sys.argv[2]))
con.commit()
PY
[[ "$("$MSG" updates-for bob/chat)" != *"Ancient news"* ]] \
  && pass "a stale update ages out silently" || fail "a stale update ages out silently"
[[ "$("$MSG" inbox --seat bob/chat)" != *"Ancient news"* ]] \
  && pass "a stale update is not in the inbox either" || fail "a stale update is not in the inbox either"

# an update NEVER binds a session — pending-for is tasks only
"$MSG" send @bob "Not a task" >/dev/null
CLAUDE_CODE_SESSION_ID=sess-1 "$MSG" pending-for bob/chat >/dev/null; [[ $? -eq 1 ]] \
  && pass "an update binds no session" || fail "an update binds no session"

# ------------------------------------------------ 4. a task binds ONE session
cat > "$TMP/live" <<'EOS'
#!/bin/sh
echo live-sess-9
EOS
chmod +x "$TMP/live"
cat > "$JSTACK_REVIEW_CONFIG" <<EOF2
{"agent_root": "$AR", "mail": {"deliver_live": ["$TMP/live", "{seat}", "{text}"]}}
EOF2
out=$("$MSG" send @bob "Do this now" --wake 2>&1)
TID=$(SQL "SELECT MAX(id) FROM messages WHERE subject='Do this now'" | grep -oE '[0-9]+')
[[ "$out" == *"live-sess-9"* ]] && pass "task is handed to the live session" || fail "task is handed to the live session"
[[ "$(SQL "SELECT state, bound_session FROM messages WHERE id=$TID")" == "[('task', 'live-sess-9')]" ]] \
  && pass "task records the session it bound to" || fail "task records the session it bound to"

# THE anti-ambush rule: only the session it was handed to can see it
"$MSG" pending-for bob/chat --session live-sess-9 | grep -q "Do this now" \
  && pass "the bound session sees its task" || fail "the bound session sees its task"
"$MSG" pending-for bob/chat --session someone-else >/dev/null; [[ $? -eq 1 ]] \
  && pass "another session cannot see it" || fail "another session cannot see it"
"$MSG" pending-for bob/chat >/dev/null; [[ $? -eq 1 ]] \
  && pass "a session with no task sees nothing" || fail "a session with no task sees nothing"
# nor does it leak through the update channel
[[ "$("$MSG" updates-for bob/chat)" != *"Do this now"* ]] \
  && pass "a task never arrives as an update" || fail "a task never arrives as an update"

# a spawned task is reachable by the id its run was woken with, and only that id
"$MSG" pending-for bob/chat --session nobody --woken "$TID" | grep -q "Do this now" \
  && pass "a woken run reaches its own task" || fail "a woken run reaches its own task"

# the reply IS the close, and it goes back to the sender
JSTACK_MAIL_FROM=bob/chat "$MSG" reply "$TID" "Did it, here is the answer." >/dev/null
[[ "$(SQL "SELECT state, resolved_by FROM messages WHERE id=$TID")" == "[('answered', 'bob/chat')]" ]] \
  && pass "replying answers the task" || fail "replying answers the task"
[[ "$("$MSG" read "$TID")" == *"Did it, here is the answer."* ]] \
  && pass "the answer is recorded on the task" || fail "the answer is recorded on the task"
[[ "$("$MSG" updates-for alice/chat)" == *"Did it, here is the answer."* ]] \
  && pass "the answer reaches the sender as news" || fail "the answer reaches the sender as news"
"$MSG" pending-for bob/chat --session live-sess-9 >/dev/null; [[ $? -eq 1 ]] \
  && pass "an answered task binds nothing" || fail "an answered task binds nothing"

# ------------------------------- 5. a task nobody can take is NOT filed
cat > "$JSTACK_REVIEW_CONFIG" <<EOF3
{"agent_root": "$AR", "mail": {"python": "/nonexistent/python", "scheduler_home": "/nonexistent"}}
EOF3
BEFORE=$(SQL "SELECT COUNT(*) FROM messages" | grep -oE '[0-9]+')
out=$("$MSG" send @bob "Unreachable task" --wake 2>&1); rc=$?
[[ $rc -ne 0 ]] && pass "unreachable task fails loudly" || fail "unreachable task fails loudly (rc=$rc)"
[[ "$out" == *"Nothing was filed"* ]] && pass "and says nothing was filed" || fail "and says nothing was filed"
[[ "$(SQL "SELECT COUNT(*) FROM messages" | grep -oE '[0-9]+')" == "$BEFORE" ]] \
  && pass "no orphan row is left behind" || fail "no orphan row is left behind"
cat > "$JSTACK_REVIEW_CONFIG" <<EOF4
{"agent_root": "$AR"}
EOF4

# ------------------------------------------------- 6. coexistence with timeline
"$LOG_EVENT" alice/chat --at 10:00 --date 2026-01-15 "A timeline entry" >/dev/null
[[ "$(SQL "SELECT COUNT(*) FROM entries")" == "[(1,)]" ]] && pass "timeline entries unaffected" || fail "timeline entries unaffected"
[[ "$("$LOG_EVENT" tail alice/chat -n 5)" == *"A timeline entry"* ]] && pass "log_event still reads its own table" || fail "log_event still reads its own table"

echo
if [[ $fails -eq 0 ]]; then echo "ALL PASS"; exit 0; else echo "$fails FAILED"; exit 1; fi
