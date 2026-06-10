#!/bin/bash
# JStack SessionEnd hook — spawn the post-session review engine, detached.
#
# Reads the hook's stdin JSON ({session_id, transcript_path, ...}) and hands
# both to bin/session-review-spawn, which does all gating (agent resolution,
# loop prevention, debounce, slots) and is safe to fire from multiple entry
# points — it claims each session atomically, so a host-level SessionEnd hook
# and this plugin hook never double-review.
#
# Review spawns run with SKIP_SESSION_HOOK=1 — honor it here (loop guard).
# Kill switch: JSTACK_REVIEW_DISABLED=1.

[ "$SKIP_SESSION_HOOK" = "1" ] && exit 0
[ "$JSTACK_REVIEW_DISABLED" = "1" ] && exit 0

INPUT=$(cat)

PARSED=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get("session_id", ""))
    print(d.get("transcript_path", ""))
except Exception:
    pass
' 2>/dev/null)

SESSION_ID=$(printf '%s\n' "$PARSED" | sed -n 1p)
TRANSCRIPT=$(printf '%s\n' "$PARSED" | sed -n 2p)

[ -z "$SESSION_ID" ] && exit 0

DIR="$(cd "$(dirname "$0")" && pwd)"

nohup "$DIR/../bin/session-review-spawn" "$SESSION_ID" "$TRANSCRIPT" \
    >/dev/null 2>&1 &

exit 0
