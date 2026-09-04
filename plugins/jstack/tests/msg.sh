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
#   - send -> inbox -> read -> reply roundtrip, reply joins the thread
#   - attachments are copied into the RECEIVER's pad
#   - a task books a REAL wake (argv captured from a stub scheduler) and one
#     that cannot be booked files nothing at all
#   - THE CHANNEL: a task ties the spawned session to the sender's, the reply
#     goes back to the SESSION that asked rather than to its seat, the resume
#     wake is booked against that session's own workspace, delivery consumes
#     the reply and cancels the wake, and a channel that will not end stops
#     waking anyone
#   - a finished exchange writes itself into BOTH seats' timelines, once
#   - THE CREATOR LEG: `msg inject` binds a GitHub issue comment to the
#     session that created the issue, wakes it with the issue as the answer
#     path, is consumed by being shown, degrades to seat news when the
#     session's transcript is gone, and a chatty issue stops waking anyone
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

# A session id is now load-bearing — it is the far end of a channel — so the
# test pins its own instead of inheriting whatever session runs it, and owns a
# HOME so it can place (or withhold) the transcripts that make a session
# resumable.
export HOME="$TMP/home"; mkdir -p "$HOME"
ALICE_S=aaaaaaaa-1111-1111-1111-111111111111
BOB_S=bbbbbbbb-2222-2222-2222-222222222222
export CLAUDE_CODE_SESSION_ID="$ALICE_S"
# Belt and braces: no path through this test may reach the real registry, even
# one that runs an unstubbed scheduler.cli.
export SCHEDULER_HOME="$TMP/sched"
transcript() {   # $1 = session id, $2 = the cwd it started in
  local d="$HOME/.claude/projects/proj-$1"; mkdir -p "$d"
  printf '{"cwd":"%s","type":"user"}\n' "$2" > "$d/$1.jsonl"
}

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

# A reply aims at the session that asked. This one cannot reach it — no
# transcript exists for ALICE_S yet, so that session is not resumable — and the
# honest fallback is news for the seat rather than a channel that pretends.
JSTACK_MAIL_FROM=bob/chat out=$("$MSG" reply "$MID" "Answered." 2>&1) || fail "reply exit"
RID=$(SQL "SELECT MAX(id) FROM messages WHERE to_seat='alice/chat' AND subject='Answered.'" | grep -oE '[0-9]+')
[[ -n "$RID" ]] && pass "reply lands in sender's inbox" || fail "reply lands in sender's inbox"
[[ "$out" == *"no transcript left"* ]] \
  && pass "an unreachable session degrades to news, and says so" \
  || fail "an unreachable session degrades to news, and says so ($out)"
[[ "$(SQL "SELECT state, bound_session FROM messages WHERE id=$RID")" == "[('update', None)]" ]] \
  && pass "the degraded reply binds no session" || fail "the degraded reply binds no session"
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

# ------------------------------------------------ 4. a task opens a CHANNEL
# A task books a wake and ties the session it spawns to the session that sent
# it — it is NEVER typed into a session that is already running. A stub
# interpreter stands in for the scheduler so the booking is hermetic; its argv
# is kept so the call itself can be asserted, and it answers add-once with a
# job id the way the real CLI does under --json.
export WAKE_ARGV="$TMP/wake.argv"
cat > "$TMP/fakepy" <<'EOS'
#!/usr/bin/env python3
import hashlib, json, os, sys
argv = sys.argv[1:]
with open(os.environ["WAKE_ARGV"], "a") as f:
    f.write(" ".join(a.replace("\n", " ") for a in argv) + "\n")
if "add-once" in argv:
    print(json.dumps({"id": hashlib.md5(" ".join(argv).encode()).hexdigest()}))
EOS
chmod +x "$TMP/fakepy"
cat > "$JSTACK_REVIEW_CONFIG" <<EOF2
{"agent_root": "$AR", "mail": {"python": "$TMP/fakepy", "scheduler_home": "$TMP"}}
EOF2
transcript "$ALICE_S" "$AR/Alice/chat"       # Alice's session is now resumable
out=$("$MSG" send @bob "Do this now" --wake 2>&1)
TID=$(SQL "SELECT MAX(id) FROM messages WHERE subject='Do this now'" | grep -oE '[0-9]+')
[[ "$out" == *"session spawning at"* ]] \
  && pass "a task books its own session" || fail "a task books its own session"
grep -q "add-once" "$TMP/wake.argv" \
  && pass "the wake is a real scheduler booking" || fail "the wake is a real scheduler booking"
grep -q "\[inbox:$TID\]" "$TMP/wake.argv" \
  && pass "the wake carries the task as its prompt" || fail "the wake carries the task as its prompt"
# The tie: the sender's own session is on the row, the wake it booked is on the
# row, and the receiving session is NOT — it does not exist yet, and claiming
# one before it boots is the guess this column must never carry.
[[ "$(SQL "SELECT state, origin_session, bound_session FROM messages WHERE id=$TID")" \
   == "[('task', '$ALICE_S', None)]" ]] \
  && pass "a task records the session that sent it, and no receiver yet" \
  || fail "a task records the session that sent it, and no receiver yet"
[[ "$(SQL "SELECT wake_job <> '' FROM messages WHERE id=$TID")" == "[(1,)]" ]] \
  && pass "the booked wake is recorded on the task" || fail "the booked wake is recorded on the task"

# a wake runs in the seat's real DIRECTORY, cased as it is on disk. A seat
# string is lowercase and the workspace string is what the CLI hashes into a
# session's project dir, so a path rebuilt out of the lowercase name files the
# spawned session's transcript where the seat's own history never looks.
: > "$TMP/wake.argv"
"$MSG" send @self "self task" --wake >/dev/null 2>&1
grep -q -- "--workspace $AR/Alice/chat " "$TMP/wake.argv" \
  && pass "@self books the real cased workspace" || fail "@self books the real cased workspace"
python3 -c "import sqlite3;c=sqlite3.connect('$DB');c.execute(\"DELETE FROM messages WHERE subject='self task'\");c.commit()"

# THE anti-ambush rule: only the run woken for it can see it
"$MSG" pending-for bob/chat --session someone-else >/dev/null; [[ $? -eq 1 ]] \
  && pass "another session cannot see it" || fail "another session cannot see it"
CLAUDE_CODE_SESSION_ID=an-idle-session "$MSG" pending-for bob/chat >/dev/null; [[ $? -eq 1 ]] \
  && pass "a session with no task sees nothing" || fail "a session with no task sees nothing"
# nor does it leak through the update channel
[[ "$("$MSG" updates-for bob/chat)" != *"Do this now"* ]] \
  && pass "a task never arrives as an update" || fail "a task never arrives as an update"

# a spawned task is reachable by the id its run was woken with, and only that
# id — and the session that turns up for it is STAMPED, which is what closes
# the tie the sender is holding the other end of
"$MSG" pending-for bob/chat --session "$BOB_S" --woken "$TID" | grep -q "Do this now" \
  && pass "a woken run reaches its own task" || fail "a woken run reaches its own task"
[[ "$(SQL "SELECT bound_session FROM messages WHERE id=$TID")" == "[('$BOB_S',)]" ]] \
  && pass "the session that took it is stamped on the task" \
  || fail "the session that took it is stamped on the task"
[[ "$("$MSG" check "$TID")" == *"${BOB_S:0:8}"* ]] \
  && pass "check names the session doing the work" || fail "check names the session doing the work"

# ------------------------- the return leg: back to the SESSION, not the seat
: > "$TMP/wake.argv"
CLAUDE_CODE_SESSION_ID="$BOB_S" JSTACK_MAIL_FROM=bob/chat \
  "$MSG" reply "$TID" "Did it, here is the answer." >/dev/null
AID=$(SQL "SELECT MAX(id) FROM messages WHERE subject='Did it, here is the answer.'" | grep -oE '[0-9]+')
[[ "$(SQL "SELECT state, resolved_by FROM messages WHERE id=$TID")" == "[('answered', 'bob/chat')]" ]] \
  && pass "replying answers the task" || fail "replying answers the task"
[[ "$("$MSG" read "$TID")" == *"Did it, here is the answer."* ]] \
  && pass "the answer is recorded on the task" || fail "the answer is recorded on the task"
[[ "$(SQL "SELECT state, bound_session FROM messages WHERE id=$AID")" == "[('reply', '$ALICE_S')]" ]] \
  && pass "the answer binds to the session that asked" || fail "the answer binds to the session that asked"
# and therefore NOT to the seat: whoever sits down in alice/chat next did not
# ask anything and is not handed someone else's answer
[[ "$("$MSG" updates-for alice/chat)" != *"Did it, here is the answer."* ]] \
  && pass "the answer is not news for the seat" || fail "the answer is not news for the seat"
grep -q -- "--resume-session $ALICE_S" "$TMP/wake.argv" \
  && pass "the return wake resumes the asking session" || fail "the return wake resumes the asking session"
grep -q -- "--workspace $AR/Alice/chat" "$TMP/wake.argv" \
  && pass "the return wake runs where that session started" || fail "the return wake runs where that session started"
"$MSG" pending-for bob/chat --session "$BOB_S" --woken "$TID" >/dev/null; [[ $? -eq 1 ]] \
  && pass "an answered task binds nothing" || fail "an answered task binds nothing"

# the asking session picks it up at its own stop — and doing so consumes it
# and drops the wake that was booked as the slower half of the race
"$MSG" pending-for alice/chat --session "$ALICE_S" | grep -q "Did it, here is the answer." \
  && pass "the asking session finds its answer" || fail "the asking session finds its answer"
: > "$TMP/wake.argv"
"$MSG" deliver "$AID" >/dev/null
[[ "$(SQL "SELECT state, consumed_at <> '' FROM messages WHERE id=$AID")" == "[('seen', 1)]" ]] \
  && pass "delivery consumes the answer" || fail "delivery consumes the answer"
JOB=$(SQL "SELECT wake_job FROM messages WHERE id=$AID" | grep -oE "'[a-f0-9]+'" | tr -d "'")
grep -q "scheduler.cli rm $JOB" "$TMP/wake.argv" \
  && pass "delivery cancels the wake it beat" || fail "delivery cancels the wake it beat"
"$MSG" pending-for alice/chat --session "$ALICE_S" >/dev/null; [[ $? -eq 1 ]] \
  && pass "an answer is delivered exactly once" || fail "an answer is delivered exactly once"

# a channel that will not end stops waking anyone. The messages still file and
# still read; nobody is spawned for them.
transcript "$BOB_S" "$AR/Bob/chat"
LAST=$AID
for i in 1 2 3 4 5 6 7 8; do
  if (( i % 2 )); then S="$ALICE_S"; F=alice/chat; else S="$BOB_S"; F=bob/chat; fi
  CLAUDE_CODE_SESSION_ID="$S" JSTACK_MAIL_FROM="$F" \
    "$MSG" reply "$LAST" "turn $i" >/dev/null 2>&1
  LAST=$(SQL "SELECT MAX(id) FROM messages WHERE subject='turn $i'" | grep -oE '[0-9]+')
done
: > "$TMP/wake.argv"
CLAUDE_CODE_SESSION_ID="$BOB_S" JSTACK_MAIL_FROM=bob/chat \
  out=$("$MSG" reply "$LAST" "one more thing" 2>&1)
[[ "$out" == *"turns deep"* ]] && pass "a runaway channel says it stopped waking" \
  || fail "a runaway channel says it stopped waking ($out)"
[[ ! -s "$TMP/wake.argv" ]] && pass "a runaway channel books nothing" || fail "a runaway channel books nothing"
[[ "$("$MSG" thread "$TID")" == *"one more thing"* ]] \
  && pass "but the message is still filed and readable" || fail "but the message is still filed and readable"

# -------------------------------------- 4b. inject — the GitHub creator leg
# A comment on a task issue is delivered like a reply: bound to the creator
# session, taken at its stop or fork-resumed, consumed by being shown. GitHub
# holds the conversation, so the answer path is the issue and a dead creator
# session degrades to seat news.
: > "$TMP/wake.argv"
"$MSG" inject "$ALICE_S" "Done, PR is up." --issue "Acme/widgets#7" --author acme-agent >/dev/null \
  || fail "inject exit"
IID=$(SQL "SELECT MAX(id) FROM messages WHERE state='inject'" | grep -oE '[0-9]+')
[[ -n "$IID" ]] && pass "inject files an inject-state row" || fail "inject files an inject-state row"
[[ "$(SQL "SELECT bound_session, to_seat FROM messages WHERE id=$IID")" == "[('$ALICE_S', 'alice/chat')]" ]] \
  && pass "the comment binds to the creator session, seat read off its transcript" \
  || fail "the comment binds to the creator session, seat read off its transcript"
grep -q -- "--resume-session $ALICE_S" "$TMP/wake.argv" \
  && pass "the inject wake resumes the creator session" || fail "the inject wake resumes the creator session"
grep -q "gh issue comment 7 -R Acme/widgets" "$TMP/wake.argv" \
  && pass "the wake's answer path is the issue, not msg" || fail "the wake's answer path is the issue, not msg"
grep -q "\[inbox:$IID\]" "$TMP/wake.argv" \
  && pass "the inject wake carries its routing marker" || fail "the inject wake carries its routing marker"

# the creator session finds it at its stop — and nobody else ever does
"$MSG" pending-for alice/chat --session "$ALICE_S" | grep -q "Done, PR is up." \
  && pass "the creator session finds the comment" || fail "the creator session finds the comment"
"$MSG" pending-for alice/chat --session some-stranger >/dev/null; [[ $? -eq 1 ]] \
  && pass "an injected comment ambushes nobody else" || fail "an injected comment ambushes nobody else"
: > "$TMP/wake.argv"
"$MSG" deliver "$IID" >/dev/null
[[ "$(SQL "SELECT state FROM messages WHERE id=$IID")" == "[('seen',)]" ]] \
  && pass "delivery consumes the comment" || fail "delivery consumes the comment"
IJOB=$(SQL "SELECT wake_job FROM messages WHERE id=$IID" | grep -oE "'[a-f0-9]+'" | tr -d "'")
grep -q "scheduler.cli rm $IJOB" "$TMP/wake.argv" \
  && pass "inject delivery cancels the wake it beat" || fail "inject delivery cancels the wake it beat"

# a chatty issue stops waking the creator — comments still file, still show
for i in 2 3 4 5 6 7 8; do
  "$MSG" inject "$ALICE_S" "note $i" --issue "Acme/widgets#7" --author acme-agent >/dev/null 2>&1
done
: > "$TMP/wake.argv"
out=$("$MSG" inject "$ALICE_S" "note 9" --issue "Acme/widgets#7" --author acme-agent 2>&1)
[[ "$out" == *"no wake was booked"* ]] \
  && pass "a chatty issue stops waking the creator" || fail "a chatty issue stops waking the creator ($out)"
[[ ! -s "$TMP/wake.argv" ]] && pass "past the ceiling nothing is booked" || fail "past the ceiling nothing is booked"
"$MSG" pending-for alice/chat --session "$ALICE_S" | grep -q "note 9" \
  && pass "past the ceiling the comment still shows at a stop" \
  || fail "past the ceiling the comment still shows at a stop"
python3 -c "import sqlite3;c=sqlite3.connect('$DB');c.execute(\"UPDATE messages SET state='seen' WHERE state='inject'\");c.commit()"

# a dead creator session degrades to seat news — the comment is already
# permanent on the issue, so nothing pretends at a channel
out=$("$MSG" inject dead-sess-1 "Worker died, exit 143." --issue "Acme/widgets#9" --author acme-agent --seat alice/chat 2>&1) \
  || fail "degraded inject exit"
DGID=$(SQL "SELECT MAX(id) FROM messages WHERE subject LIKE 'Acme/widgets#9%'" | grep -oE '[0-9]+')
[[ "$out" == *"no transcript left"* ]] \
  && pass "a dead creator degrades to seat news, and says so" \
  || fail "a dead creator degrades to seat news, and says so ($out)"
[[ "$(SQL "SELECT state, bound_session FROM messages WHERE id=$DGID")" == "[('update', None)]" ]] \
  && pass "the degraded comment binds no session" || fail "the degraded comment binds no session"
[[ "$("$MSG" updates-for alice/chat)" == *"Worker died"* ]] \
  && pass "and lands as the seat's news" || fail "and lands as the seat's news"
out=$("$MSG" inject dead-sess-2 "x" --issue "Acme/widgets#9" --author x 2>&1); rc=$?
[[ $rc -ne 0 && "$out" == *"nowhere to deliver"* ]] \
  && pass "a dead creator with no seat fails loudly" || fail "a dead creator with no seat fails loudly"
out=$("$MSG" inject "$ALICE_S" "x" --issue "notaref" 2>&1); rc=$?
[[ $rc -ne 0 ]] && pass "a malformed issue ref is refused" || fail "a malformed issue ref is refused"

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

# --------------------------------------- 6. a finished exchange is on record
# `messages` is the channel; the timeline is what a seat did. An exchange worth
# waking a session for belongs in both seats' history — otherwise the only
# trace that one agent asked another for something lives in a table neither of
# them reads by habit. Exactly one entry per seat, written once, no matter how
# many turns the channel ran afterwards.
[[ "$(SQL "SELECT COUNT(*) FROM entries")" == "[(2,)]" ]] \
  && pass "a closed exchange writes one entry per seat" || fail "a closed exchange writes one entry per seat"
[[ "$("$LOG_EVENT" tail alice/chat -n 5)" == *"Asked bob/chat — Do this now"* ]] \
  && pass "the asking seat's history says it asked" || fail "the asking seat's history says it asked"
[[ "$("$LOG_EVENT" tail bob/chat -n 5)" == *"Answered alice/chat — Do this now"* ]] \
  && pass "the doing seat's history says it answered" || fail "the doing seat's history says it answered"
[[ "$("$LOG_EVENT" tail alice/chat -n 5)" == *"Did it, here is the answer."* ]] \
  && pass "the entry carries what came back" || fail "the entry carries what came back"
[[ "$(SQL "SELECT logged_at <> '' FROM messages WHERE id=$TID")" == "[(1,)]" ]] \
  && pass "the exchange is stamped as recorded" || fail "the exchange is stamped as recorded"

"$LOG_EVENT" alice/chat --at 10:00 --date 2026-01-15 "A timeline entry" >/dev/null
[[ "$(SQL "SELECT COUNT(*) FROM entries")" == "[(3,)]" ]] \
  && pass "log_event still writes its own table" || fail "log_event still writes its own table"
[[ "$("$LOG_EVENT" tail alice/chat -n 5)" == *"A timeline entry"* ]] \
  && pass "log_event still reads its own table" || fail "log_event still reads its own table"

echo
if [[ $fails -eq 0 ]]; then echo "ALL PASS"; exit 0; else echo "$fails FAILED"; exit 1; fi
