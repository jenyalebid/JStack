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
#   (j) live-session-only: headless spawns never inject, any seat, any config
#       form; liveness is read off the process ancestry (hooks run detached
#       from the controlling terminal, /dev/tty never opens inside one)
#   (k) per-dir seats: each dir is its own seat — own lineage + ancestor dirs,
#       never a sibling dir's
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
# Injection is live-session-only, so emulate the live shape explicitly —
# these legs test resolution/content, the (j) legs test the liveness gate.
ctx() { printf '{"hook_event_name":"SessionStart","cwd":"%s","source":"startup"}' "$1" \
          | JSTACK_REVIEW_CONFIG="${2:-$CFG}" JSTACK_ASSUME_INTERACTIVE=1 python3 "$HOOK" \
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

# (j) live-session-only — the injection law: only a human-driven session ever
#     injects, for every seat, regardless of config value form (plain int
#     here). The CLI spawns hooks detached from the controlling terminal —
#     /dev/tty NEVER opens inside a hook, even in a human-driven session —
#     so the hook must read liveness off its ancestry (the CLI process holds
#     the tty). The legs model production process shapes:
#       (j1) truly headless — orphaned to PID 1, no terminal anywhere → nothing
#       (j2) detached hook under a tty-holding ancestor (the real interactive
#            shape: script(1) grants a pty to sh, sh spawns the hook setsid'd
#            so /dev/tty fails inside it) → injects via the ancestor's tty
#       (j3) hook attached to a pty directly (/dev/tty fast path) → injects
mkdir -p "$ROOT/Gamma/social/chat"
CFG2="$TMP/review2.json"
printf '{ "agent_root": "%s", "timeline_inject": {"*/social": 5} }' "$ROOT" > "$CFG2"
"$LOG_EVENT" gamma/social --at 15:00 --date "$DAY" "Social seat entry" >/dev/null
PAYLOAD=$(printf '{"cwd":"%s"}' "$ROOT/Gamma/social/chat")

# (j1) orphan double-fork: grandchild waits for reparent to PID 1 (ancestor
# chain = launchd only, no tty) before running the hook; output via temp file.
HEADLESS_OUT="$TMP/headless.out"
JSTACK_REVIEW_CONFIG="$CFG2" python3 - "$HOOK" "$PAYLOAD" "$HEADLESS_OUT" <<'PYEOF'
import os, subprocess, sys, time
hook, payload, outfile = sys.argv[1], sys.argv[2], sys.argv[3]
if os.fork() == 0:
    os.setsid()
    if os.fork() == 0:
        deadline = time.time() + 5
        while os.getppid() != 1 and time.time() < deadline:
            time.sleep(0.05)
        r = subprocess.run(["python3", hook], input=payload,
                           capture_output=True, text=True)
        with open(outfile, "w") as f:
            f.write(r.stdout)
        os._exit(0)
    os._exit(0)
else:
    os.wait()
PYEOF
for _ in $(seq 1 60); do [[ -f "$HEADLESS_OUT" ]] && break; sleep 0.1; done
[[ -f "$HEADLESS_OUT" && ! -s "$HEADLESS_OUT" ]] \
  && pass "live-only: orphaned headless spawn gets nothing" \
  || fail "live-only: orphaned headless spawn gets nothing"

# (j2) the production interactive shape — detached hook, tty on the ancestor
SPAWNER="$TMP/detached_spawn.py"
cat > "$SPAWNER" <<'PYEOF'
import os, subprocess, sys
hook, payload_file = sys.argv[1], sys.argv[2]
payload = open(payload_file).read()
r = subprocess.run(["python3", hook], input=payload,
                   capture_output=True, text=True, preexec_fn=os.setsid)
sys.stdout.write(r.stdout)
PYEOF
printf '%s' "$PAYLOAD" > "$TMP/payload.json"
detached=$(JSTACK_REVIEW_CONFIG="$CFG2" script -q /dev/null \
  python3 "$SPAWNER" "$HOOK" "$TMP/payload.json" | tr -d '\r')
echo "$detached" | grep -q "Social seat entry" \
  && pass "live-only: detached hook under tty ancestor injected" \
  || fail "live-only: detached hook under tty ancestor injected"

# (j3) /dev/tty fast path still holds
tty_out=$(JSTACK_REVIEW_CONFIG="$CFG2" script -q /dev/null sh -c "echo '$PAYLOAD' | python3 '$HOOK'")
echo "$tty_out" | grep -q "Social seat entry" && pass "live-only: pty-attached hook injected" \
  || fail "live-only: pty-attached hook injected"

# (k) per-dir seats: each dir is its own seat — a session in social/chat boots
#     on its own dir's lineage plus ancestor dirs, never a sibling dir's
mkdir -p "$ROOT/Gamma/social/threads"
"$LOG_EVENT" gamma/social/chat    --at 16:00 --date "$DAY" "Chat seat lineage entry" >/dev/null
"$LOG_EVENT" gamma/social/threads --at 16:10 --date "$DAY" "Threads sibling entry" >/dev/null
k_chat=$(ctx "$ROOT/Gamma/social/chat" "$CFG2")
echo "$k_chat" | grep -q "gamma/social/chat (your seat)" \
  && echo "$k_chat" | grep -q "Chat seat lineage entry" \
  && echo "$k_chat" | grep -q "Social seat entry" \
  && pass "per-dir: social/chat = own seat + ancestor lineage" \
  || fail "per-dir: social/chat = own seat + ancestor lineage"
echo "$k_chat" | grep -q "Threads sibling entry" \
  && fail "per-dir: sibling dir excluded from chat seat" \
  || pass "per-dir: sibling dir excluded from chat seat"
k_threads=$(ctx "$ROOT/Gamma/social/threads" "$CFG2")
if echo "$k_threads" | grep -q "Threads sibling entry" && ! echo "$k_threads" | grep -q "Chat seat lineage entry"; then
  pass "per-dir: sibling seat boots its own lineage only"
else
  fail "per-dir: sibling seat boots its own lineage only"
fi

# (l) auto-session entries never ride an injection: origin=indirect rows
# (crons, publish wakes) are excluded from the injected content — the
# injection is the seat's human-driven narrative only.
"$LOG_EVENT" gamma/chat --at 12:30 --date "$DAY" --origin indirect "Published by a cron" >/dev/null
l_out=$(ctx "$ROOT/Gamma")
if echo "$l_out" | grep -q "Published by a cron"; then
  fail "indirect entries excluded from injection"
else
  echo "$l_out" | grep -q "Chat entry four" \
    && pass "indirect entries excluded from injection" \
    || fail "indirect entries excluded from injection (direct content missing)"
fi

# (m) --explain: the injector answers "what would this seat be injected" as
# data (ids + N). Anything that DISPLAYS or checks an injection asks this —
# a consumer that re-derives the window from the db grows its own second
# truth and drifts (a UI that marks the cron flood as injected). The answer
# obeys the same two laws as the injection itself: the config walk sets N,
# origin=indirect never rides.
id_of() { "$LOG_EVENT" tail "$1" -n 50 --json | python3 -c '
import json,sys
want=sys.argv[1]
print(next((str(r["id"]) for r in json.load(sys.stdin) if r["headline"]==want), ""))
' "$2"; }
explain() { JSTACK_REVIEW_CONFIG="${2:-$CFG}" python3 "$HOOK" --explain "$1"; }
field() { python3 -c 'import json,sys;print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }

m_out=$(explain gamma/chat)
cron_id=$(id_of gamma/chat "Published by a cron")
live_id=$(id_of gamma/chat "Chat entry four")
[[ "$(echo "$m_out" | field ok)" == "True" && "$(echo "$m_out" | field n)" == "3" ]] \
  && pass "--explain answers ok with the seat's configured N" \
  || fail "--explain answers ok with the seat's configured N ($m_out)"
m_ids=$(echo "$m_out" | field ids)
# Both ids must exist, or the two legs below would pass on nothing.
if [[ -z "$cron_id" || -z "$live_id" ]]; then
  fail "--explain fixture: seeded rows not found (cron='$cron_id' live='$live_id')"
elif echo "$m_ids" | grep -qE "(^|[^0-9])$cron_id([^0-9]|$)"; then
  fail "--explain excludes indirect rows (cron id $cron_id marked: $m_ids)"
else
  pass "--explain excludes indirect rows"
fi
if echo "$m_ids" | grep -qE "(^|[^0-9])$live_id([^0-9]|$)"; then
  pass "--explain names the rows the injection carries"
else
  fail "--explain names the rows the injection carries ($m_ids)"
fi

# unconfigured seat and the review seat both answer n=0 — never a guess
[[ "$(explain gamma/social | field n)" == "0" ]] \
  && pass "--explain: unconfigured seat answers n=0" \
  || fail "--explain: unconfigured seat answers n=0"
[[ "$(explain gamma/review "$CFG2" | field n)" == "0" ]] \
  && pass "--explain: review seat answers n=0" \
  || fail "--explain: review seat answers n=0"

echo
if [[ $fails -gt 0 ]]; then
  echo "timeline-injection: $fails FAILED" >&2
  exit 1
fi
echo "timeline-injection: all pass"
