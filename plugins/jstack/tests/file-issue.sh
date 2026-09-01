#!/usr/bin/env bash
# Hermetic test for bin/file-issue — a stub `gh` on PATH, no network, no real
# issue ever created. Asserts the behaviours whose failure would be silent.
#
# What must never regress, in order of what it would cost:
#   - a filed issue that never reaches the board. `gh issue create` alone leaves
#     projectItems[] empty: the issue exists, is numbered, and is invisible to
#     the person who has to act on it. Filing and placing are one act.
#   - a bad exit read as success. Every failure path (no gh, no repo, issues
#     off, create refused) must exit nonzero so the caller reports "not filed"
#     instead of claiming a number it never got.
#   - a body-less issue. The context IS the deliverable; a title alone is a note
#     to yourself, filed where only strangers will read it.
#   - an unknown label taking the whole issue down with it.
set -uo pipefail

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$PLUGIN_ROOT/bin/file-issue"

TMP="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT
STUB="$TMP/bin"; mkdir -p "$STUB"
export GH_CALLS="$TMP/calls.log"

fails=0
ok()  { echo "  ok   $1"; }
bad() { echo "  FAIL $1 — $2"; fails=$((fails+1)); }

# ── stub gh: canned GraphQL from $GH_META, mutations logged ─────────────────
cat > "$STUB/gh" <<'STUBEOF'
#!/usr/bin/env bash
echo "gh $*" >> "$GH_CALLS"
case "$1 ${2:-}" in
  "auth status") exit 0 ;;
  "api graphql")
    q=""
    for a in "$@"; do case "$a" in query=*) q="${a#query=}" ;; esac; done
    if [[ "$q" == *addProjectV2ItemById* ]];        then echo "PVTI_item123"; exit 0; fi
    if [[ "$q" == *updateProjectV2ItemFieldValue* ]]; then echo '{"data":{}}'; exit 0; fi
    [[ -n "${GH_META:-}" && -r "${GH_META:-}" ]] || { echo "boom" >&2; exit 1; }
    cat "$GH_META"; exit 0 ;;
  "issue create") echo "https://github.com/O/R/issues/77"; exit 0 ;;
  "issue view")   echo "I_nodeid77"; exit 0 ;;
esac
exit 1
STUBEOF
chmod +x "$STUB/gh"
export PATH="$STUB:$PATH"

meta() {  # $1=file  $2=json
  printf '%s' "$2" > "$TMP/$1.json"; export GH_META="$TMP/$1.json"
}

BOARD_TODO='{"data":{"repository":{"hasIssuesEnabled":true,
  "labels":{"nodes":[{"name":"bug"},{"name":"enhancement"}]},
  "projectsV2":{"nodes":[{"id":"PVT_1","number":1,"title":"Pipeline",
    "field":{"id":"F_1","options":[{"id":"o_todo","name":"TODO"},{"id":"o_q","name":"Queue"}]}}]}}}}'

run() { OUT="$("$BIN" "$@" 2>&1)"; RC=$?; }

echo "usage gates"
meta m "$BOARD_TODO"
run --repo O/R --title t                        # no body
[[ $RC -eq 64 && "$OUT" == *"body is required"* ]] && ok "body-less issue refused" || bad "body-less issue refused" "rc=$RC"
run --repo O/R --body b                         # no title
[[ $RC -eq 64 ]] && ok "title required" || bad "title required" "rc=$RC"
run --repo notslashed --title t --body b
[[ $RC -eq 64 ]] && ok "repo must be owner/name" || bad "repo must be owner/name" "rc=$RC"
run --repo O/R --title t --body b --bogus
[[ $RC -eq 64 ]] && ok "unknown flag refused" || bad "unknown flag refused" "rc=$RC"

echo "blind and refusing states exit nonzero"
run --repo O/R --title t --body b --dry-run     # gh present, meta readable
[[ $RC -eq 0 ]] && ok "happy dry-run exits 0" || bad "happy dry-run exits 0" "rc=$RC out=$OUT"
( export PATH="/usr/bin:/bin"; "$BIN" --repo O/R --title t --body b >/dev/null 2>&1 )
[[ $? -eq 3 ]] && ok "no gh on PATH exits 3" || bad "no gh on PATH exits 3" "got $?"
export GH_META="$TMP/nope.json"                 # graphql call itself fails
run --repo O/R --title t --body b
[[ $RC -eq 4 && "$OUT" == *"cannot read"* ]] && ok "graphql failure exits 4" || bad "graphql failure exits 4" "rc=$RC $OUT"
meta null '{"data":{"repository":null}}'        # call succeeds, repo invisible
run --repo O/R --title t --body b
[[ $RC -eq 4 && "$OUT" == *"not found or not visible"* ]] && ok "null repo exits 4" || bad "null repo exits 4" "rc=$RC $OUT"
meta off '{"data":{"repository":{"hasIssuesEnabled":false,"labels":{"nodes":[]},"projectsV2":{"nodes":[]}}}}'
run --repo O/R --title t --body b
[[ $RC -eq 4 && "$OUT" == *"issues are disabled"* ]] && ok "issues disabled exits 4" || bad "issues disabled exits 4" "rc=$RC"

echo "board routing is read from the repo's live linkage"
meta m "$BOARD_TODO"
run --repo O/R --title t --body b --dry-run
[[ "$OUT" == *"board:  TODO"* ]] && ok "single linked project -> intake column" || bad "single linked project -> intake column" "$OUT"

meta none '{"data":{"repository":{"hasIssuesEnabled":true,"labels":{"nodes":[]},"projectsV2":{"nodes":[]}}}}'
run --repo O/R --title t --body b --dry-run
[[ $RC -eq 0 && "$OUT" == *"board=none"* ]] && ok "no linked project still files" || bad "no linked project still files" "rc=$RC $OUT"

meta two '{"data":{"repository":{"hasIssuesEnabled":true,"labels":{"nodes":[]},"projectsV2":{"nodes":[
  {"id":"PVT_1","number":1,"title":"A","field":{"id":"F","options":[{"id":"x","name":"TODO"}]}},
  {"id":"PVT_2","number":2,"title":"B","field":{"id":"G","options":[{"id":"y","name":"TODO"}]}}]}}}}'
run --repo O/R --title t --body b --dry-run
[[ "$OUT" == *"2 projects linked"* ]] && ok "ambiguous board skipped, not guessed" || bad "ambiguous board skipped, not guessed" "$OUT"
run --repo O/R --title t --body b --project 2 --dry-run
[[ "$OUT" == *"board:  TODO"* ]] && ok "--project disambiguates" || bad "--project disambiguates" "$OUT"

meta backlog '{"data":{"repository":{"hasIssuesEnabled":true,"labels":{"nodes":[]},"projectsV2":{"nodes":[
  {"id":"PVT_1","number":1,"title":"A","field":{"id":"F","options":[{"id":"d","name":"Done"},{"id":"b","name":"Backlog"}]}}]}}}}'
run --repo O/R --title t --body b --dry-run
[[ "$OUT" == *"board:  Backlog"* ]] && ok "intake column found by synonym, not position" || bad "intake column found by synonym, not position" "$OUT"

meta nocol '{"data":{"repository":{"hasIssuesEnabled":true,"labels":{"nodes":[]},"projectsV2":{"nodes":[
  {"id":"PVT_1","number":1,"title":"A","field":{"id":"F","options":[{"id":"z","name":"Shipped"}]}}]}}}}'
run --repo O/R --title t --body b --dry-run
[[ $RC -eq 0 && "$OUT" == *"project default"* ]] && ok "no intake column still boards it" || bad "no intake column still boards it" "rc=$RC $OUT"

echo "labels never take the issue down with them"
meta m "$BOARD_TODO"
run --repo O/R --title t --body b --label bug --label ghost --dry-run
[[ $RC -eq 0 && "$OUT" == *"labels: bug"* && "$OUT" == *"'ghost' does not exist"* ]] \
  && ok "unknown label dropped, known label kept" || bad "unknown label dropped, known label kept" "$OUT"

echo "the filing path places the issue, not just creates it"
: > "$GH_CALLS"
run --repo O/R --title t --body b --label bug
[[ $RC -eq 0 && "$OUT" == *"ISSUE https://github.com/O/R/issues/77 board=TODO"* ]] \
  && ok "prints parseable receipt" || bad "prints parseable receipt" "rc=$RC $OUT"
grep -q "addProjectV2ItemById" "$GH_CALLS" \
  && ok "issue added to the board" || bad "issue added to the board" "no add mutation in call log"
grep -q "o_todo" "$GH_CALLS" \
  && ok "column set to the resolved intake option" || bad "column set to the resolved intake option" "no option id in call log"

: > "$GH_CALLS"
run --repo O/R --title t --body b --no-board
[[ $RC -eq 0 && "$OUT" == *"board=none"* ]] && ! grep -q "addProjectV2ItemById" "$GH_CALLS" \
  && ok "--no-board files without touching the board" || bad "--no-board files without touching the board" "$OUT"

BF="$TMP/body.md"; printf 'line one\nline two\n' > "$BF"
run --repo O/R --title t --body-file "$BF" --dry-run
[[ $RC -eq 0 ]] && ok "--body-file accepted" || bad "--body-file accepted" "rc=$RC $OUT"
run --repo O/R --title t --body-file "$TMP/absent.md" --dry-run
[[ $RC -eq 64 ]] && ok "missing --body-file refused" || bad "missing --body-file refused" "rc=$RC"

echo ""
if [[ $fails -gt 0 ]]; then echo "$fails check(s) failed" >&2; exit 1; fi
echo "ALL PASS — file-issue verified"
