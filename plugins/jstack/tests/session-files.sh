#!/usr/bin/env bash
# Hermetic test for bin/session-files — fixture HOME, fixture transcript, a real
# throwaway git repo. No real ~/.claude, no real repo touched.
#
# What must never regress, in order of what it would cost:
#   - a run that cannot read the transcript EXITS NONZERO. An empty list from a
#     blind tool reads as "nothing to commit" and the work it was asked about
#     never lands. That is the whole reason this binary exists.
#   - the list comes from the transcript, never the tree — so a file another
#     session left dirty can never enter it, and a file this session wrote can
#     never fall out of it for being hard to attribute.
#   - subagent (sidechain) writes count as the session's own work.
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$PLUGIN_ROOT/bin/session-files"

TMP="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT

FIX="$TMP/home"
REPO="$FIX/repo"
SID="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
PROJ="$FIX/.claude/projects/-fixture-repo"
mkdir -p "$PROJ" "$REPO"

fail() { echo "FAIL: $1"; echo "---- output ----"; echo "${OUT:-<none>}"; exit 1; }
run()  { HOME="$FIX" "$BIN" "$@"; }

# --- fixture repo: one commit, then a tree in every state that matters -------
git -C "$REPO" init -q -b main
git -C "$REPO" config user.email test@example.com
git -C "$REPO" config user.name  Test

printf 'log\n' > "$REPO/.gitignore"           # *.log ignored below
echo "*.log" > "$REPO/.gitignore"
echo "v1" > "$REPO/modified.py"
echo "v1" > "$REPO/clean.py"
echo "v1" > "$REPO/deleted.py"
git -C "$REPO" add .gitignore modified.py clean.py deleted.py
git -C "$REPO" commit -qm "base"

echo "v2"      > "$REPO/modified.py"    # tracked + changed  → committable
                                        # clean.py untouched → clean
rm "$REPO/deleted.py"                   # tracked + gone     → committable
echo "new"     > "$REPO/untracked.py"   # untracked          → committable
echo "noise"   > "$REPO/ignored.log"    # ignored            → NOT committable
echo "{}"      > "$REPO/nb.ipynb"       # untracked notebook → committable
echo "sub"     > "$REPO/sub_agent.py"   # written by subagent→ committable
echo "read"    > "$REPO/not_a_write.py" # only ever READ     → absent
echo "outside" > "$FIX/outside.txt"     # in no repo         → outside_repo

# a path another session left dirty, which this session never wrote: the tool
# must be structurally incapable of listing it
echo "theirs"  > "$REPO/someone_else.py"

# --- fixture transcript ------------------------------------------------------
# Deliberate order — the committable list is asserted in first-write order.
w() {   # w <tool> <key> <path> [sidechain]
  local sc=""; [ "${4:-}" = "sidechain" ] && sc='"isSidechain":true,'
  printf '{%s"type":"assistant","message":{"content":[{"type":"tool_use","name":"%s","input":{"%s":"%s"}}]}}\n' \
    "$sc" "$1" "$2" "$3"
}
{
  w Write        file_path     "$REPO/modified.py"
  w Edit         file_path     "$REPO/clean.py"
  w Write        file_path     "$REPO/untracked.py"
  w Write        file_path     "$REPO/ignored.log"
  w MultiEdit    file_path     "$REPO/deleted.py"
  w NotebookEdit notebook_path "$REPO/nb.ipynb"
  w Write        file_path     "$REPO/sub_agent.py" sidechain
  w Read         file_path     "$REPO/not_a_write.py"
  printf '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"mv a b"}}]}}\n'
  w Edit         file_path     "$REPO/modified.py"      # dup → deduped
  w Write        file_path     "$FIX/outside.txt"
  printf '{"type":"assistant","message":{"content":[{"type":"tool_u'   # torn tail line
} > "$PROJ/$SID.jsonl"

# =============================================================================
# 1. the stage list: exactly the written paths git still sees a change at,
#    in first-write order
# =============================================================================
OUT="$(run --session "$SID")"
EXPECTED="$REPO/modified.py
$REPO/untracked.py
$REPO/deleted.py
$REPO/nb.ipynb
$REPO/sub_agent.py"
[ "$OUT" = "$EXPECTED" ] || fail "stage list wrong — expected:
$EXPECTED"

# 2. a torn final line (transcript flushed mid-write) must not crash the run
#    — assertion 1 passing at all is that proof; make the intent explicit
[ -n "$OUT" ] || fail "torn tail line killed the run"

# 3. the tree cannot leak in: another session's dirty file is not listable
echo "$OUT" | grep -q "someone_else.py" && fail "a file this session never wrote entered the list"

# 4. reads are not writes
echo "$OUT" | grep -q "not_a_write.py" && fail "a Read was counted as a write"

# 5. subagent writes are the session's work
echo "$OUT" | grep -q "sub_agent.py" || fail "sidechain (subagent) write dropped"

# 6. clean and ignored paths stay out of the stage list
echo "$OUT" | grep -q "clean.py"   && fail "unchanged file offered for staging"
echo "$OUT" | grep -q "ignored.log" && fail "gitignored file offered for staging"

# 7. dedup — a file written twice is staged once
[ "$(echo "$OUT" | grep -c "modified.py")" -eq 1 ] || fail "duplicate write not deduped"

# 8. a tracked file deleted on disk is still committable (the deletion)
echo "$OUT" | grep -q "deleted.py" || fail "deletion dropped from stage list"

# =============================================================================
# 9. --json splits the buckets and keeps the full written list
# =============================================================================
OUT="$(run --session "$SID" --json)"
j() { echo "$OUT" | python3 -c "import json,sys;d=json.load(sys.stdin);print('\n'.join(d['$1']))"; }
[ "$(j committable | wc -l | tr -d ' ')" -eq 5 ] || fail "json committable count"
j clean        | grep -q "clean.py"    || fail "json: unchanged file not in clean"
j clean        | grep -q "ignored.log" || fail "json: ignored file not in clean"
j outside_repo | grep -q "outside.txt" || fail "json: non-repo path not in outside_repo"
j written      | grep -q "outside.txt" || fail "json: written list is not the full set"
[ "$(j written | wc -l | tr -d ' ')" -eq 8 ] || fail "json written count (dedup or capture drift)"

# =============================================================================
# 10. --all ignores git state entirely
# =============================================================================
OUT="$(run --session "$SID" --all)"
echo "$OUT" | grep -q "clean.py"    || fail "--all dropped an unchanged file"
echo "$OUT" | grep -q "ignored.log" || fail "--all dropped an ignored file"
echo "$OUT" | grep -q "outside.txt" || fail "--all dropped a non-repo file"

# =============================================================================
# 11. THE LOAD-BEARING ONES — cannot-look must never render as nothing-to-commit
# =============================================================================
set +e
OUT="$(HOME="$FIX" env -u CLAUDE_CODE_SESSION_ID "$BIN" 2>&1)"; RC=$?
set -e
[ "$RC" -ne 0 ] || fail "no session id exited 0 — a blind run must raise, not return empty"

set +e
OUT="$(run --session "ffffffff-0000-0000-0000-000000000000" 2>&1)"; RC=$?
set -e
[ "$RC" -ne 0 ] || fail "unknown session exited 0 — a missing transcript must raise"

# same id under two project dirs → ambiguous, must refuse rather than pick one
mkdir -p "$FIX/.claude/projects/-fixture-other"
cp "$PROJ/$SID.jsonl" "$FIX/.claude/projects/-fixture-other/$SID.jsonl"
set +e
OUT="$(run --session "$SID" 2>&1)"; RC=$?
set -e
[ "$RC" -ne 0 ] || fail "ambiguous session id resolved silently instead of refusing"
rm -rf "$FIX/.claude/projects/-fixture-other"

# =============================================================================
# 12. the default path: resolve THIS session from the environment
# =============================================================================
OUT="$(HOME="$FIX" TMPDIR="$TMP" CLAUDE_CODE_SESSION_ID="$SID" "$BIN")"
[ "$OUT" = "$EXPECTED" ] || fail "env-resolved session differs from --session"

echo "PASS: session-files"
