#!/usr/bin/env bash
# JStack live test — hooks/stop-inbox-guard.py, the "an open item cannot be
# walked past" enforcement.
#
# Hermetic: temp timeline dir, temp agent tree, temp review state. Verifies:
#   - a user-driven session with open mail is BLOCKED, once
#   - the same session stopping again is allowed (one block per message,
#     not one per turn) — but mail arriving LATER blocks again
#   - stop_hook_active is never blocked (no loop)
#   - a headless session unrelated to the inbox is NOT hijacked — this is the
#     whole reason messages are addressed to a seat
#   - a headless wake carrying [inbox:N] IS bound, and only to item N
#   - an item bare-deferred by a session does not block THAT session, and
#     still blocks the next one
#   - no mail / non-agent cwd / kill switch → allow, silently
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

cd "$AR/Alice/chat" || exit 1
"$MSG" send @bob "First item" >/dev/null
MID=$(python3 -c "import sqlite3;print(sqlite3.connect('$TMP/timeline/timeline.db').execute(\"SELECT MAX(id) FROM messages\").fetchone()[0])")
printf '%s\n' "{\"type\":\"user\",\"message\":{\"content\":\"[inbox:$MID] Message from alice/chat — handle it\"}}" > "$TMP/wake.jsonl"

# $1 = session id, $2 = transcript, $3 = cwd, $4... = extra json fields
run() {
  local sid="$1" tr="$2" cwd="$3" extra="${4:-}"
  echo "{\"session_id\":\"$sid\",\"transcript_path\":\"$tr\",\"cwd\":\"$cwd\"$extra}" | "$HOOK"
}
decision() { python3 -c "import json,sys; raw=sys.stdin.read().strip(); print(json.loads(raw)['decision'] if raw else 'allow')"; }

BOB="$AR/Bob/chat"

# 1. user session with open mail -> block
out=$(run s1 "$TMP/user.jsonl" "$BOB")
[[ "$(printf '%s' "$out" | decision)" == "block" ]] && pass "user session with mail is blocked" || fail "user session with mail is blocked"
[[ "$out" == *"First item"* ]] && pass "block names the item" || fail "block names the item"
[[ "$out" == *"msg done"* ]] && pass "block carries the closing command" || fail "block carries the closing command"

# 2. same session, same mail -> allowed (said once, not per turn)
[[ -z "$(run s1 "$TMP/user.jsonl" "$BOB")" ]] && pass "same session not blocked twice" || fail "same session not blocked twice"

# 3. mail arriving LATER in that same session blocks again (per-message marker)
"$MSG" send @bob "Second item" >/dev/null
out=$(run s1 "$TMP/user.jsonl" "$BOB")
[[ "$(printf '%s' "$out" | decision)" == "block" ]] && pass "new mail re-blocks the same session" || fail "new mail re-blocks the same session"
[[ "$out" == *"Second item"* && "$out" != *"First item"* ]] \
  && pass "re-block names only the new item" || fail "re-block names only the new item"

# 4. stop_hook_active -> never block (loop guard)
[[ -z "$(run s2 "$TMP/user.jsonl" "$BOB" ',"stop_hook_active":true')" ]] \
  && pass "stop_hook_active never blocks" || fail "stop_hook_active never blocks"

# 5. headless worker unrelated to the inbox -> NOT hijacked
[[ -z "$(run s3 "$TMP/cron.jsonl" "$BOB")" ]] \
  && pass "unrelated headless run is not hijacked" || fail "unrelated headless run is not hijacked"

# 6. headless wake for a specific item -> bound to that item only
out=$(run s4 "$TMP/wake.jsonl" "$BOB")
[[ "$(printf '%s' "$out" | decision)" == "block" ]] && pass "wake session is bound to its item" || fail "wake session is bound to its item"
[[ "$out" == *"First item"* && "$out" != *"Second item"* ]] \
  && pass "wake bound to ONLY its own item" || fail "wake bound to ONLY its own item"

# 6b. an item the session itself bare-deferred does not block that session,
#     and still blocks a different one — the guard names its own session id
#     rather than inheriting it, so "not this session" is a fact it can see
"$MSG" send @bob "Deferred item" >/dev/null
DID=$(python3 -c "import sqlite3;print(sqlite3.connect('$JSTACK_TIMELINE_DIR/timeline.db').execute(\"SELECT MAX(id) FROM messages WHERE subject='Deferred item'\").fetchone()[0])")
CLAUDE_CODE_SESSION_ID=s9 "$MSG" defer "$DID" --note "next session" >/dev/null
out=$(run s9 "$TMP/user.jsonl" "$BOB")
[[ "$out" != *"Deferred item"* ]] \
  && pass "bare defer does not block its own session" || fail "bare defer does not block its own session"
out=$(run s10 "$TMP/user.jsonl" "$BOB")
[[ "$out" == *"Deferred item"* ]] \
  && pass "bare defer still blocks the next session" || fail "bare defer still blocks the next session"

# 7. a seat with no mail -> allow
[[ -z "$(run s5 "$TMP/user.jsonl" "$AR/Alice/chat")" ]] && pass "no mail, no block" || fail "no mail, no block"

# 8. cwd outside the agent tree -> allow
[[ -z "$(run s6 "$TMP/user.jsonl" "/tmp")" ]] && pass "non-agent cwd allowed" || fail "non-agent cwd allowed"

# 9. kill switches
[[ -z "$(JSTACK_INBOX_GUARD_DISABLED=1 run s7 "$TMP/user.jsonl" "$BOB")" ]] && pass "kill switch honored" || fail "kill switch honored"
[[ -z "$(SKIP_SESSION_HOOK=1 run s8 "$TMP/user.jsonl" "$BOB")" ]] && pass "SKIP_SESSION_HOOK honored" || fail "SKIP_SESSION_HOOK honored"

# 10. malformed stdin never wedges a session
[[ -z "$(echo 'not json' | "$HOOK")" ]] && pass "malformed input allowed" || fail "malformed input allowed"

echo
if [[ $fails -eq 0 ]]; then echo "ALL PASS"; exit 0; else echo "$fails FAILED"; exit 1; fi
