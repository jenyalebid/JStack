#!/usr/bin/env bash
# Hermetic test for bin/pict — fixture home tree, fixture rules, fixture
# review config, stub log_event. No real ~/.claude or timeline touched.
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PICT="$PLUGIN_ROOT/bin/pict"

# pwd -P: pict resolves symlinks (macOS /var → /private/var), the fixture
# key must be computed from the same physical path
TMP="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT

FIX="$TMP/home"
CLAUDE="$FIX/.claude"
mkdir -p "$FIX/Agents/Alpha/chat" "$CLAUDE/rules" "$CLAUDE/jstack"

# --- fixture walk-up chain -------------------------------------------------
echo "# Org root law" > "$FIX/CLAUDE.md"
echo "# Alpha identity" > "$FIX/Agents/Alpha/CLAUDE.md"
echo "# Alpha chat seat" > "$FIX/Agents/Alpha/chat/CLAUDE.md"

# --- fixture rules: one unconditional, one anchored, one elsewhere ---------
printf '# Always-on gates\nGate body.\n' > "$CLAUDE/rules/gates.md"
printf -- '---\npaths:\n  - "Agents/*/chat/**"\n---\n\n# Chat law\nChat rule body.\n' \
  > "$CLAUDE/rules/chat-law.md"
printf -- '---\npaths:\n  - "Other/place/**"\n---\n\n# Elsewhere law\nBody.\n' \
  > "$CLAUDE/rules/elsewhere.md"
# filename-pattern rule with NO matching file under the spawn dir — must NOT
# list as anchored (the possibility-based trap: "a .xyz could exist here")
printf -- '---\npaths:\n  - "**/*.xyz"\n---\n\n# Pattern law\nPattern body.\n' \
  > "$CLAUDE/rules/pattern.md"

# --- fixture auto-memory keyed by the dir (no git repo in fixture) ---------
KEY="$(printf '%s' "$FIX/Agents/Alpha/chat" | sed 's/[^A-Za-z0-9]/-/g')"
mkdir -p "$CLAUDE/projects/$KEY/memory"
echo "- memory index line" > "$CLAUDE/projects/$KEY/memory/MEMORY.md"

# --- fixture timeline config + stub log_event -------------------------------
cat > "$CLAUDE/jstack/review.json" <<EOF
{"agent_root": "$FIX/Agents", "timeline_inject": {"*/chat": 2}}
EOF
cat > "$TMP/log_event" <<'EOF'
#!/usr/bin/env bash
[ "$1" = "tail" ] || exit 1
echo "2026-01-01 — did a thing"
echo "2026-01-02 — did another thing"
EOF
chmod +x "$TMP/log_event"

# --- fixture settings hook ---------------------------------------------------
cat > "$CLAUDE/settings.json" <<'EOF'
{"hooks": {"PreToolUse": [{"matcher": "Bash",
  "hooks": [{"type": "command", "command": "/some/nudge.sh"}]}]}}
EOF

OUT="$(PICT_CLAUDE_DIR="$CLAUDE" PICT_WALK_ROOT="$FIX" PICT_LOG_EVENT="$TMP/log_event" \
      JSTACK_REVIEW_CONFIG="$CLAUDE/jstack/review.json" JSTACK_RULES_DIR="$CLAUDE/rules" \
      "$PICT" "$FIX/Agents/Alpha/chat")"

fail() { echo "FAIL: $1"; echo "---- output ----"; echo "$OUT"; exit 1; }

# 1. all three walk-up mds present, parent-most first
echo "$OUT" | grep -q "Org root law"    || fail "org root md missing"
echo "$OUT" | grep -q "Alpha identity"  || fail "agent root md missing"
echo "$OUT" | grep -q "Alpha chat seat" || fail "seat md missing"
ROOT_LINE=$(echo "$OUT" | grep -n "Org root law" | head -1 | cut -d: -f1)
SEAT_LINE=$(echo "$OUT" | grep -n "Alpha chat seat" | head -1 | cut -d: -f1)
[ "$ROOT_LINE" -lt "$SEAT_LINE" ] || fail "walk-up order wrong (root after seat)"

# 2. unconditional rule injected as global, BEFORE the walk-up chain
echo "$OUT" | grep -q "Gate body." || fail "unconditional rule missing"
GATE_LINE=$(echo "$OUT" | grep -n "Gate body." | head -1 | cut -d: -f1)
[ "$GATE_LINE" -lt "$ROOT_LINE" ] || fail "globals must precede walk-up"

# 3. anchored path rule body included; elsewhere rule excluded but listed
echo "$OUT" | grep -q "Chat rule body." || fail "anchored rule body missing"
echo "$OUT" | grep -q "elsewhere" || fail "non-anchored rule not listed"
echo "$OUT" | grep -A8 "no matching files here" | grep -q "elsewhere" \
  || fail "elsewhere rule not in no-matching-files section"
BODY_HITS=$(echo "$OUT" | grep -c "Elsewhere law" || true)
[ "$BODY_HITS" -eq 0 ] || fail "non-anchored rule body leaked into output"

# 3b. filename-pattern rule with no matching files: listed, body NOT included
echo "$OUT" | grep -A9 "no matching files here" | grep -q "pattern" \
  || fail "pattern rule not in no-matching-files section"
PAT_HITS=$(echo "$OUT" | grep -c "Pattern body." || true)
[ "$PAT_HITS" -eq 0 ] || fail "pattern rule anchored despite no matching files"

# 3c. ...and once a matching file exists, it anchors
touch "$FIX/Agents/Alpha/chat/thing.xyz"
OUT3="$(PICT_CLAUDE_DIR="$CLAUDE" PICT_WALK_ROOT="$FIX" PICT_LOG_EVENT="$TMP/log_event" \
       JSTACK_REVIEW_CONFIG="$CLAUDE/jstack/review.json" JSTACK_RULES_DIR="$CLAUDE/rules" \
       "$PICT" "$FIX/Agents/Alpha/chat")"
echo "$OUT3" | grep -q "Pattern body." || fail "pattern rule not anchored after file created"
rm "$FIX/Agents/Alpha/chat/thing.xyz"

# 4. auto-memory content present
echo "$OUT" | grep -q "memory index line" || fail "memory index missing"

# 5. timeline entries present via stub log_event
echo "$OUT" | grep -q "did another thing" || fail "timeline entries missing"
echo "$OUT" | grep -q 'seat `alpha/chat`' || fail "seat resolution wrong"

# 6. headless preview: interactive_only seat goes quiet
cat > "$CLAUDE/jstack/review.json" <<EOF
{"agent_root": "$FIX/Agents",
 "timeline_inject": {"*/chat": {"n": 2, "interactive_only": true}}}
EOF
OUT2="$(PICT_CLAUDE_DIR="$CLAUDE" PICT_WALK_ROOT="$FIX" PICT_LOG_EVENT="$TMP/log_event" \
       JSTACK_REVIEW_CONFIG="$CLAUDE/jstack/review.json" JSTACK_RULES_DIR="$CLAUDE/rules" \
       PICT_INTERACTIVE=0 "$PICT" "$FIX/Agents/Alpha/chat")"
echo "$OUT2" | grep -q "did another thing" && fail "headless preview injected timeline"

# 7. settings hook enumerated
echo "$OUT" | grep -q "nudge.sh" || fail "settings hook not listed"

# 8. summary separates spawn-time total from on-demand pool
echo "$OUT" | grep -q "loads at spawn" || fail "spawn total missing"
echo "$OUT" | grep -q "on-demand pool" || fail "on-demand pool total missing"

# --- spawn-descriptor flags fixtures ----------------------------------------
# a project command reachable by walk-up from the seat (agent-root .claude)
mkdir -p "$FIX/Agents/Alpha/.claude/commands"
printf '# Reply procedure\nCommand body law.\n' \
  > "$FIX/Agents/Alpha/.claude/commands/do-thing.md"
# an --append payload (what a spawner passes via --append-system-prompt)
printf 'Append body law.\n' > "$TMP/append-law.md"
# a captured tool-served blob
printf 'Served blob data.\n' > "$TMP/blob.txt"
# a fixture plugin with a SessionStart hook that injects a marker
PLUG="$TMP/plugins/fake/1.0.0"
mkdir -p "$PLUG/hooks" "$CLAUDE/plugins"
cat > "$PLUG/hooks/hooks.json" <<'EOF'
{"hooks": {"SessionStart": [{"matcher": "startup|clear",
  "hooks": [{"type": "command",
             "command": "\"${CLAUDE_PLUGIN_ROOT}/hooks/inject.sh\""}]}]}}
EOF
cat > "$PLUG/hooks/inject.sh" <<'EOF'
#!/usr/bin/env bash
cat > /dev/null
echo "PLUGIN-CTX-MARKER content."
EOF
chmod +x "$PLUG/hooks/inject.sh"
cat > "$CLAUDE/plugins/installed_plugins.json" <<EOF
{"version": 2, "plugins": {"fake@test": [
  {"scope": "user", "installPath": "$PLUG", "version": "1.0.0"}]}}
EOF

OUT4="$(PICT_CLAUDE_DIR="$CLAUDE" PICT_WALK_ROOT="$FIX" PICT_LOG_EVENT="$TMP/log_event" \
       JSTACK_REVIEW_CONFIG="$CLAUDE/jstack/review.json" JSTACK_RULES_DIR="$CLAUDE/rules" \
       "$PICT" "$FIX/Agents/Alpha/chat" --headless --no-memory --exec-hooks \
       --append "$TMP/append-law.md" --prompt "/do-thing post=123" \
       --serve "$TMP/blob.txt")"
fail4() { echo "FAIL: $1"; echo "---- output ----"; echo "$OUT4"; exit 1; }

# 9. --no-memory: index body absent, DISABLED note present
echo "$OUT4" | grep -q "memory index line" && fail4 "--no-memory still loaded index"
echo "$OUT4" | grep -q "auto-memory DISABLED" || fail4 "DISABLED note missing"

# 10. --append body present, positioned in the system-prompt stage
echo "$OUT4" | grep -q "Append body law." || fail4 "append body missing"

# 11. --prompt /command resolved by walk-up, body inlined, args in wrapper
echo "$OUT4" | grep -q "Command body law." || fail4 "command body missing"
echo "$OUT4" | grep -q "command-args>post=123" || fail4 "command args missing"

# 12. --serve blob present and LAST in injection order
echo "$OUT4" | grep -q "Served blob data." || fail4 "served blob missing"
APPEND_LINE=$(echo "$OUT4" | grep -n "Append body law." | head -1 | cut -d: -f1)
CMD_LINE=$(echo "$OUT4" | grep -n "Command body law." | head -1 | cut -d: -f1)
BLOB_LINE=$(echo "$OUT4" | grep -n "Served blob data." | head -1 | cut -d: -f1)
[ "$APPEND_LINE" -lt "$CMD_LINE" ] || fail4 "append must precede command body"
[ "$CMD_LINE" -lt "$BLOB_LINE" ] || fail4 "command body must precede served blob"

# 13. --exec-hooks ran the plugin SessionStart hook, before the prompt
echo "$OUT4" | grep -q "PLUGIN-CTX-MARKER" || fail4 "plugin hook output missing"
HOOK_LINE=$(echo "$OUT4" | grep -n "PLUGIN-CTX-MARKER" | head -1 | cut -d: -f1)
[ "$HOOK_LINE" -lt "$CMD_LINE" ] || fail4 "hook output must precede command body"

# 14. plugin hook enumerated in the hooks table with plugin origin
echo "$OUT4" | grep -q "plugin fake@test" || fail4 "plugin hook not enumerated"

# 15. banner integrity: every BEGIN with a body has an END
B=$(echo "$OUT4" | grep -c "] BEGIN  " || true)
E=$(echo "$OUT4" | grep -c "END \[" || true)
[ "$E" -gt 0 ] || fail4 "no END banners"
[ "$E" -le "$B" ] || fail4 "more ENDs than BEGINs"

# 16. grand total row present
echo "$OUT4" | grep -q "TOTAL the model receives" || fail4 "grand total missing"

echo "PASS: pict"
