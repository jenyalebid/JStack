#!/usr/bin/env bash
# Resolve a session id to its transcript and its seat.
#
# Prints two eval-able lines:  JSONL=<path>  SEAT=<agent>/<submode>
# Exit 1 with empty values when no transcript exists for the id.
#
# The seat must match how the SessionStart injector reads entries back — the
# first path segment under the agent directory, with the agent root itself
# meaning "chat". A seat resolved any other way writes where nothing reads.
set -u

SID="${1:?usage: resolve-seat.sh <session-id> [session-cwd]}"
BASE="${2:-$PWD}"

AGENT_TITLE=$(basename "$(dirname "$BASE")")
AGENT=$(echo "$AGENT_TITLE" | tr '[:upper:]' '[:lower:]')

JSONL=$(find "$HOME/.claude/projects" -name "${SID}.jsonl" -print -quit 2>/dev/null)
if [ -z "$JSONL" ]; then
  echo "JSONL="
  echo "SEAT="
  exit 1
fi

CWD=$(jq -r 'select(.cwd) | .cwd' "$JSONL" | head -1)
REL="${CWD#*/"$AGENT_TITLE"}"; REL="${REL#/}"
SUBMODE="${REL%%/*}"; SUBMODE="${SUBMODE:-chat}"

echo "JSONL=$JSONL"
echo "SEAT=$AGENT/$SUBMODE"
