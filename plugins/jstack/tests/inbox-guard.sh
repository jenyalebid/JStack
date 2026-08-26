#!/usr/bin/env bash
# JStack live test — hooks/stop-inbox-guard.py, "a task handed to THIS session
# gets its answer".
#
# Hermetic: temp timeline dir, temp agent tree, temp review state. Verifies:
#   - a session holding an unanswered task IS blocked, once, and stops clean
#     as soon as it replies
#   - THE anti-ambush rule: updates never block, and a task belonging to
#     another session is invisible — opening a chat cannot drag in whatever
#     was lying around
#   - a spawned run is bound by the [inbox:N] in its own prompt, and to
#     nothing else
#   - stop_hook_active / non-agent cwd / kill switches → allow, silently
#
# Exit 0 = all pass, exit 1 = any fail.

set -u

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$PLUGIN_ROOT/hooks/stop-inbox-guard.py"
MSG="$PLUGIN_ROOT/bin/msg"

TMP=$(mktemp -d /tmp/jstack-inbox-guard-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT
export JSTACK_TIMELINE_DIR="$TMP/timeline"
export JSTACK_REVIEW_STATE="$TMP/state"

fails=0
fail() { echo "FAIL: $1" >&2; fails=$((fails+1)); }
pass() { echo "ok: $1"; }

[[ -x "$HOOK" ]] || { echo "FAIL: $HOOK not executable" >&2; exit 1; }

AR="$TMP/agents"
for seat in Alice Alice/chat Bob Bob/chat; do
  mkdir -p "$AR/$seat"; echo "# $seat" > "$AR/$seat/CLAUDE.md"
done
export JSTACK_REVIEW_CONFIG="$TMP/review.json"
echo "{\"agent_root\": \"$AR\"}" > "$JSTACK_REVIEW_CONFIG"

# transcripts: a typed user session, an unrelated headless run, a wake
printf '%s\n' '{"type":"user","promptSource":"typed","message":{"content":"hi"}}' > "$TMP/user.jsonl"
printf '%s\n' '{"type":"user","message":{"content":"/social_compose account=x"}}' > "$TMP/cron.jsonl"

# a stub live-delivery rung so a task binds to a session we can name
cat > "$TMP/live" <<'EOS'
#!/bin/sh
echo sess-owner
EOS
chmod +x "$TMP/live"
cat > "$JSTACK_REVIEW_CONFIG" <<EOF2
{"agent_root": "$AR", "mail": {"deliver_live": ["$TMP/live", "{seat}", "{text}"]}}
EOF2

cd "$AR/Alice/chat" || exit 1
"$MSG" send @bob "First item" --wake >/dev/null
MID=$(python3 -c "import sqlite3;print(sqlite3.connect('$TMP/timeline/timeline.db').execute(\"SELECT MAX(id) FROM messages\").fetchone()[0])")
printf '%s\n' "{\"type\":\"user\",\"message\":{\"content\":\"[inbox:$MID] Message from alice/chat — handle it\"}}" > "$TMP/wake.jsonl"

# $1 = session id, $2 = transcript, $3 = cwd, $4... = extra json fields
run() {
  local sid="$1" tr="$2" cwd="$3" extra="${4:-}"
  echo "{\"session_id\":\"$sid\",\"transcript_path\":\"$tr\",\"cwd\":\"$cwd\"$extra}" | "$HOOK"
}
decision() { python3 -c "import json,sys; raw=sys.stdin.read().strip(); print(json.loads(raw)['decision'] if raw else 'allow')"; }


BOB="$AR/Bob/chat"

# 1. the session the task was handed to is blocked, once
out=$(run sess-owner "$TMP/user.jsonl" "$BOB")
[[ "$(printf '%s' "$out" | decision)" == "block" ]] && pass "session holding a task is blocked" || fail "session holding a task is blocked"
[[ "$out" == *"First item"* ]] && pass "block names the task" || fail "block names the task"
[[ "$out" == *"msg reply"* ]] && pass "block carries the reply command" || fail "block carries the reply command"
[[ "$out" == *"waiting"* ]] && pass "block says the sender is waiting" || fail "block says the sender is waiting"
[[ -z "$(run sess-owner "$TMP/user.jsonl" "$BOB")" ]] && pass "same session not blocked twice" || fail "same session not blocked twice"

# 2. THE anti-ambush rule — nobody else can be dragged into it
[[ -z "$(run some-other-session "$TMP/user.jsonl" "$BOB")" ]] \
  && pass "another user session is never ambushed" || fail "another user session is never ambushed"
[[ -z "$(run cron-worker "$TMP/cron.jsonl" "$BOB")" ]] \
  && pass "an unrelated headless run is never ambushed" || fail "an unrelated headless run is never ambushed"

# 3. updates never block anyone, ever
"$MSG" send @bob "Just a note" >/dev/null
"$MSG" send @bob "Another note" >/dev/null
[[ -z "$(run fresh-session "$TMP/user.jsonl" "$BOB")" ]] \
  && pass "updates never block a session" || fail "updates never block a session"

# 4. a spawned run is bound by the id in its own prompt — and only that
out=$(run spawned-run "$TMP/wake.jsonl" "$BOB")
[[ "$(printf '%s' "$out" | decision)" == "block" ]] && pass "a woken run is bound to its task" || fail "a woken run is bound to its task"
[[ "$out" == *"First item"* ]] && pass "bound to the right task" || fail "bound to the right task"
printf '%s\n' '{"type":"user","message":{"content":"[inbox:99999] nothing"}}' > "$TMP/badwake.jsonl"
[[ -z "$(run bad-wake "$TMP/badwake.jsonl" "$BOB")" ]] \
  && pass "a marker naming no live task allows" || fail "a marker naming no live task allows"

# 5. answering releases the session
JSTACK_MAIL_FROM=bob/chat "$MSG" reply "$MID" "Done, here it is." >/dev/null
[[ -z "$(run sess-owner-2 "$TMP/user.jsonl" "$BOB")" ]] \
  && pass "an answered task blocks nobody" || fail "an answered task blocks nobody"
[[ -z "$(run spawned-run-2 "$TMP/wake.jsonl" "$BOB")" ]] \
  && pass "an answered task releases its wake too" || fail "an answered task releases its wake too"

# 6. loop guards and switches
"$MSG" send @bob "Second task" --wake >/dev/null
[[ -z "$(run sess-owner "$TMP/user.jsonl" "$BOB" ',"stop_hook_active":true')" ]] \
  && pass "stop_hook_active never blocks" || fail "stop_hook_active never blocks"
[[ -z "$(run s6 "$TMP/user.jsonl" "/tmp")" ]] && pass "non-agent cwd allowed" || fail "non-agent cwd allowed"
[[ -z "$(JSTACK_INBOX_GUARD_DISABLED=1 run sess-owner "$TMP/user.jsonl" "$BOB")" ]] && pass "kill switch honored" || fail "kill switch honored"
[[ -z "$(SKIP_SESSION_HOOK=1 run sess-owner "$TMP/user.jsonl" "$BOB")" ]] && pass "SKIP_SESSION_HOOK honored" || fail "SKIP_SESSION_HOOK honored"
[[ -z "$(echo 'not json' | "$HOOK")" ]] && pass "malformed input allowed" || fail "malformed input allowed"

echo
if [[ $fails -eq 0 ]]; then echo "ALL PASS"; exit 0; else echo "$fails FAILED"; exit 1; fi
