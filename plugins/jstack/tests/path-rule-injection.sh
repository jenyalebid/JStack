#!/usr/bin/env bash
# JStack live test — path-rule-injection hook.
#
# Calls the real hook script with the real PreToolUse JSON stdin contract
# against a hermetic fixture (JSTACK_RULES_DIR + JSTACK_CACHE_ROOT overrides).
# Verifies three behaviors that define the hook:
#   (a) cold-fire        — first call matches rule + emits additionalContext
#   (b) consecutive-dedup — same session, no transcript growth → empty stdout
#   (c) threshold re-fire — transcript grew past threshold → re-injection
#
# Exit 0 = all pass. Exit 1 = any fail. Safe to run any time, anywhere —
# never touches real markers or shipped rules.

set -u

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$PLUGIN_ROOT/hooks/inject-path-rules.py"

if [[ ! -f "$HOOK" ]]; then
  echo "FAIL: hook not found at $HOOK" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "FAIL: python3 not on PATH" >&2
  exit 1
fi

TMP="$(mktemp -d "${TMPDIR:-/tmp}/jstack-hooktest.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

RULES="$TMP/rules"
CACHE="$TMP/cache"
TRANSCRIPT="$TMP/transcript.jsonl"
mkdir -p "$RULES" "$CACHE"

cat > "$RULES/test-rule.md" <<'EOF'
---
name: test-rule
description: synthetic rule for path-rule-injection live test
paths:
  - "**/views/**.swift"
---

# Test Rule Body

Marker string — if you see this in additionalContext, injection worked.
EOF

FILE_PATH="/fake/repo/views/SomeView.swift"
echo '{"role":"user","content":"seed"}' > "$TRANSCRIPT"

call_hook() {
  local sid="$1"
  local payload
  payload=$(printf '{"session_id":"%s","tool_name":"Edit","tool_input":{"file_path":"%s"},"transcript_path":"%s"}' \
    "$sid" "$FILE_PATH" "$TRANSCRIPT")
  printf '%s' "$payload" \
    | JSTACK_RULES_DIR="$RULES" \
      JSTACK_CACHE_ROOT="$CACHE" \
      JSTACK_RULE_REINJECT_BYTES=100 \
      python3 "$HOOK"
}

assert_contains_rule_body() {
  local label="$1" out="$2"
  if ! printf '%s' "$out" | python3 -c '
import json, sys
d = json.load(sys.stdin)
ctx = d["hookSpecificOutput"]["additionalContext"]
assert "Marker string" in ctx, "rule body missing"
assert "test-rule" in ctx, "rule name missing"
' >/dev/null 2>&1; then
    echo "FAIL [$label]: output missing expected rule content" >&2
    echo "  raw: $out" >&2
    exit 1
  fi
}

fail() { echo "FAIL [$1]: $2" >&2; exit 1; }
pass() { echo "PASS [$1]"; }

SID="test-$$-$(date +%s)"

# (a) Cold-fire
out1="$(call_hook "$SID")"
[[ -n "$out1" ]] || fail "cold-fire" "expected JSON output, got empty"
assert_contains_rule_body "cold-fire" "$out1"
[[ -f "$CACHE/$SID/test-rule.marker" ]] || fail "cold-fire" "marker file not created"
pass "cold-fire"

# (b) Consecutive-dedup
out2="$(call_hook "$SID")"
[[ -z "$out2" ]] || fail "consecutive-dedup" "expected empty output, got: $out2"
pass "consecutive-dedup"

# (c) Threshold re-fire
head -c 300 /dev/zero >> "$TRANSCRIPT"
out3="$(call_hook "$SID")"
[[ -n "$out3" ]] || fail "threshold-refire" "expected JSON output after transcript growth"
assert_contains_rule_body "threshold-refire" "$out3"
pass "threshold-refire"

echo ""
echo "ALL PASS — path-rule-injection hook verified live"
