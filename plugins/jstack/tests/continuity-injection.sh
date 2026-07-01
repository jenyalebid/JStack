#!/usr/bin/env bash
# JStack live test — SessionStart continuity/state injection hook.
#
# Calls the real hook (hooks/session-start-inject.py) with the real SessionStart
# JSON stdin contract against a hermetic fixture (a temp agents tree pointed at
# via JSTACK_REVIEW_CONFIG). Verifies the behaviors that define the hook:
#   (a) agent-root cwd   → submode "chat"; injects state.md + chat/continuity.md
#   (b) submode cwd      → injects that submode's continuity.md
#   (c) review submode   → no output (reviewer reconciles state.md itself)
#   (d) non-workspace    → no output (silent no-op)
#   (e) no review/ dir   → not a reviewable agent → no output
#
# Exit 0 = all pass, 1 = any fail. Hermetic — never touches real workspaces.

set -u

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$PLUGIN_ROOT/hooks/session-start-inject.py"

[[ -f "$HOOK" ]] || { echo "FAIL: hook not found at $HOOK" >&2; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "FAIL: python3 not on PATH" >&2; exit 1; }

TMP="$(mktemp -d "${TMPDIR:-/tmp}/jstack-injecttest.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

ROOT="$TMP/Agents"
mkdir -p "$ROOT/Mario/review" "$ROOT/Mario/chat" "$ROOT/Mario/pm" "$ROOT/Loner" "$ROOT/Solo/review"
printf '# Mario — state\n\n## Active items\n- **thing** — doing it. → active/thing.md\n' > "$ROOT/Mario/state.md"
# Solo is reviewable but has NO continuity yet (only state) → nothing to inject
printf '# Solo — state\n\n## Active items\n- **x** — y. → active/x.md\n' > "$ROOT/Solo/state.md"
printf '# Continuity — Mario · chat\n\n## Today\n- Shipped the freeze fix.\n' > "$ROOT/Mario/chat/continuity.md"
printf '# Continuity — Mario · pm\n\n## Today\n- Reviewed the roadmap.\n' > "$ROOT/Mario/pm/continuity.md"
# Loner has NO review/ dir → not a reviewable agent
printf '# Loner — state\n\n_None._\n' > "$ROOT/Loner/state.md"

CFG="$TMP/review.json"
printf '{ "agent_root": "%s" }' "$ROOT" > "$CFG"

# Fire the hook with a given cwd; echo its raw stdout.
fire() { printf '{"hook_event_name":"SessionStart","cwd":"%s","source":"startup"}' "$1" \
           | JSTACK_REVIEW_CONFIG="$CFG" python3 "$HOOK"; }

# Fire and print the DECODED additionalContext (empty string if no output) — the
# JSON escapes non-ASCII (·→·, —→—), so assert on the decoded text.
ctx() { fire "$1" | python3 -c 'import json,sys
raw=sys.stdin.read().strip()
print(json.loads(raw)["hookSpecificOutput"]["additionalContext"] if raw else "")'; }

pass=0; fail=0
ok()   { echo "  ok: $1"; pass=$((pass+1)); }
bad()  { echo "FAIL: $1" >&2; fail=$((fail+1)); }

# (a) agent root → chat: chat continuity present; state.md NOT injected
OUT="$(ctx "$ROOT/Mario")"
echo "$OUT" | grep -q "Shipped the freeze fix" && echo "$OUT" | grep -q "chat" \
  && ! echo "$OUT" | grep -q "active-items" \
  && ok "agent-root injects chat continuity (and not state.md)" \
  || bad "agent-root injection wrong :: $OUT"

# (b) explicit submode cwd → that submode's continuity, not chat's
OUT="$(ctx "$ROOT/Mario/pm")"
echo "$OUT" | grep -q "Reviewed the roadmap" && echo "$OUT" | grep -q " pm " \
  && ! echo "$OUT" | grep -q "Shipped the freeze fix" \
  && ok "submode cwd injects that submode's continuity" \
  || bad "submode cwd resolution wrong :: $OUT"

# (c) review submode → no output
OUT="$(fire "$ROOT/Mario/review")"
[[ -z "$OUT" ]] && ok "review submode is skipped" || bad "review submode emitted output :: $OUT"

# (d) non-workspace cwd → no output
OUT="$(fire "$TMP/somewhere/else")"
[[ -z "$OUT" ]] && ok "non-workspace cwd is a no-op" || bad "non-workspace emitted output :: $OUT"

# (e) agent without review/ dir → not recognized → no output
OUT="$(fire "$ROOT/Loner")"
[[ -z "$OUT" ]] && ok "agent without review/ is not recognized" || bad "unreviewable agent emitted output :: $OUT"

# (f) reviewable agent with state but NO continuity → no output (state is not injected)
OUT="$(fire "$ROOT/Solo")"
[[ -z "$OUT" ]] && ok "no continuity → no output (state.md alone is not injected)" || bad "injected with no continuity :: $OUT"

# valid-JSON check on the one that emits
OUT="$(fire "$ROOT/Mario")"
echo "$OUT" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["hookSpecificOutput"]["hookEventName"]=="SessionStart"' 2>/dev/null \
  && ok "output is valid SessionStart hook JSON" || bad "output not valid hook JSON :: $OUT"

echo "---- continuity-injection: $pass passed, $fail failed ----"
[[ $fail -eq 0 ]] || exit 1
