#!/usr/bin/env bash
# JStack live test — SessionStart timeline injection hook.
#
# Calls the real hook (hooks/session-start-inject.py) with the real SessionStart
# JSON stdin contract against a hermetic fixture: a temp agents tree + temp
# timeline db seeded through the real bin/log_event, pointed at via
# JSTACK_REVIEW_CONFIG + JSTACK_TIMELINE_DIR. Verifies the behaviors that
# define the hook:
#   (a) agent-root cwd → "chat" seat; injects that seat's entries
#   (b) submode cwd    → that seat's entries only, other seats excluded
#   (c) legacy bare-agent rows (submode-less, pre-migration) ride seat tails
#   (d) -N cap honored (only the last N entries appear)
#   (e) verdict stamps ride the injection
#   (f) review submode → no output
#   (g) non-workspace cwd → no output
#   (h) seat not in timeline_inject → no output
#   (i) kill switch env → no output
#
# Exit 0 = all pass, 1 = any fail. Hermetic — never touches the real timeline.

set -u

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$PLUGIN_ROOT/hooks/session-start-inject.py"
LOG_EVENT="$PLUGIN_ROOT/bin/log_event"

[[ -f "$HOOK" ]] || { echo "FAIL: hook not found at $HOOK" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL: python3 not on PATH" >&2; exit 1; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/jstack-tlinjtest.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

ROOT="$TMP/Agents"
mkdir -p "$ROOT/Gamma/review" "$ROOT/Gamma/chat" "$ROOT/Gamma/pm" "$ROOT/Loner"
printf '# Gamma\n' > "$ROOT/Gamma/CLAUDE.md"
printf '# Loner — no CLAUDE.md dir\n' > "$ROOT/Loner/notes.md"

export JSTACK_TIMELINE_DIR="$TMP/Timeline"
CFG="$TMP/review.json"
printf '{ "agent_root": "%s", "timeline_inject": {"gamma/chat": 3, "*/pm": 5} }' "$ROOT" > "$CFG"

DAY="2026-01-15"
"$LOG_EVENT" gamma/chat --at 09:00 --date "$DAY" "Chat entry one" >/dev/null
"$LOG_EVENT" gamma/chat --at 10:00 --date "$DAY" "Chat entry two" --detail "a bullet" >/dev/null
"$LOG_EVENT" gamma/chat --at 11:00 --date "$DAY" "Chat entry three" >/dev/null
"$LOG_EVENT" gamma/chat --at 12:00 --date "$DAY" "Chat entry four" >/dev/null
"$LOG_EVENT" gamma/pm   --at 13:00 --date "$DAY" "PM entry" >/dev/null
"$LOG_EVENT" gamma      --at 08:00 --date "$DAY" "Legacy bare entry" >/dev/null
"$LOG_EVENT" verdict gamma/pm blocked --note "waiting on a decision" >/dev/null

fails=0
fail() { echo "FAIL: $1" >&2; fails=$((fails+1)); }
pass() { echo "ok: $1"; }

# Fire the hook with a given cwd; print the DECODED additionalContext ("" if none).
ctx() { printf '{"hook_event_name":"SessionStart","cwd":"%s","source":"startup"}' "$1" \
          | JSTACK_REVIEW_CONFIG="$CFG" python3 "$HOOK" \
          | python3 -c 'import json,sys
raw=sys.stdin.read().strip()
print(json.loads(raw)["hookSpecificOutput"]["additionalContext"] if raw else "")'; }

# (a) agent root → chat seat
out=$(ctx "$ROOT/Gamma")
echo "$out" | grep -q "gamma/chat (your seat)" && echo "$out" | grep -q "Chat entry four" \
  && pass "agent root resolves to chat seat" || fail "agent root resolves to chat seat"

# (b) seat isolation — chat injection carries no pm entries
echo "$out" | grep -q "PM entry" && fail "seat isolation (pm leaked into chat)" \
  || pass "seat isolation (pm not in chat)"

# (c) legacy bare-agent rows ride seat tails (within the cap window: see (d))
pm_out=$(ctx "$ROOT/Gamma/pm")
echo "$pm_out" | grep -q "Legacy bare entry" \
  && pass "legacy bare rows ride seat tail" || fail "legacy bare rows ride seat tail"

# (d) -N cap: chat allows 3 → oldest chat entries fall off
echo "$out" | grep -q "Chat entry one" && fail "N cap honored (entry one should be cut)" \
  || pass "N cap honored"
echo "$out" | grep -q "Chat entry two" && pass "N window correct (two..four)" \
  || fail "N window correct (two missing)"

# (e) verdict rides injection
echo "$pm_out" | grep -q "↳ verdict: blocked — waiting on a decision" \
  && pass "verdict rides injection" || fail "verdict rides injection"

# (f) review submode → nothing
[[ -z "$(ctx "$ROOT/Gamma/review")" ]] \
  && pass "review submode skipped" || fail "review submode skipped"

# (g) non-workspace cwd → nothing
[[ -z "$(ctx "$TMP")" ]] \
  && pass "non-workspace silent" || fail "non-workspace silent"

# (h) unlisted seat → nothing (gamma/social has entries? none — but also no config)
"$LOG_EVENT" gamma/social --at 14:00 --date "$DAY" "Social entry" >/dev/null
mkdir -p "$ROOT/Gamma/social"
[[ -z "$(ctx "$ROOT/Gamma/social")" ]] \
  && pass "unlisted seat gets nothing" || fail "unlisted seat gets nothing"

# (i) kill switch
out_killed=$(printf '{"cwd":"%s"}' "$ROOT/Gamma" \
  | JSTACK_REVIEW_CONFIG="$CFG" JSTACK_TIMELINE_INJECT_DISABLED=1 python3 "$HOOK")
[[ -z "$out_killed" ]] && pass "kill switch honored" || fail "kill switch honored"

echo
if [[ $fails -gt 0 ]]; then
  echo "timeline-injection: $fails FAILED" >&2
  exit 1
fi
echo "timeline-injection: all pass"
