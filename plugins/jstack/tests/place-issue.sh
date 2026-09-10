#!/usr/bin/env bash
# Hermetic test for bin/place-issue — a stub `gh` on PATH, no network, no card
# ever moved. Asserts the behaviours whose failure would be silent.
#
# What must never regress, in order of what it would cost:
#   - a receipt that claims a column the card never got. The working session
#     quotes this line back on the issue; a status it did not set is a lie told
#     to the only person reading.
#   - a personal-account repo treated as an error. Only one of organization /
#     user can resolve and GitHub returns NOT_FOUND for the other, which makes
#     `gh` exit non-zero on a call that fully succeeded — the exit code is not
#     the signal here, the data is.
#   - a substring shadowing an exact board title. "Work" must not pick whichever
#     of "Auto-Work" and "Work" happened to sort first.
#   - a dry run answering 0 to a call that would land half-done. Its whole
#     purpose is to check the call before making it.
#   - the board resolved from the repo's owner. A work board belongs to the
#     operation, not the repo: derive it from the owner and every out-of-org
#     repo becomes unplaceable, because a personal account has no board to find.
set -uo pipefail

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$PLUGIN_ROOT/bin/place-issue"

TMP="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$TMP"' EXIT
STUB="$TMP/bin"; mkdir -p "$STUB"
export GH_CALLS="$TMP/calls.log"

# Hermetic against the machine running the suite: the real config would name a
# real board, and every assertion below about which owner was searched would be
# answering about this Mac rather than about the binary.
export JSTACK_ISSUE_WORK_CONFIG="$TMP/absent.json"
export JSTACK_CONFIG_DIR="$TMP/config"

fails=0
ok()  { echo "  ok   $1"; }
bad() { echo "  FAIL $1 — $2"; fails=$((fails+1)); }

# ── stub gh: canned GraphQL from $GH_BOARDS, mutations logged ───────────────
cat > "$STUB/gh" <<'STUBEOF'
#!/usr/bin/env bash
echo "gh $*" >> "$GH_CALLS"
case "$1 ${2:-}" in
  "auth status") exit 0 ;;
  "api graphql")
    q=""
    for a in "$@"; do case "$a" in query=*) q="${a#query=}" ;; esac; done
    if [[ "$q" == *addProjectV2ItemById* ]]; then
      [[ "${GH_ADD_FAIL:-0}" == "1" ]] && exit 1
      echo "PVTI_item9"; exit 0
    fi
    if [[ "$q" == *updateProjectV2ItemFieldValue* ]]; then
      [[ "${GH_SETCOL_FAIL:-0}" == "1" ]] && exit 1
      echo '{"data":{}}'; exit 0
    fi
    if [[ "$q" == *"node(id:"* ]]; then
      [[ -n "${GH_NODE:-}" && -r "${GH_NODE:-}" ]] || { echo '{"data":{"node":null}}'; exit 0; }
      cat "$GH_NODE"; exit 0
    fi
    [[ -n "${GH_BOARDS:-}" && -r "${GH_BOARDS:-}" ]] || { echo "boom" >&2; exit 1; }
    cat "$GH_BOARDS"; exit 0 ;;
  "issue view")
    [[ "${GH_NO_ISSUE:-0}" == "1" ]] && exit 1
    echo "I_nodeid5"; exit 0 ;;
esac
exit 1
STUBEOF
chmod +x "$STUB/gh"
export PATH="$STUB:$PATH"

boards() {  # $1=name  $2=json   — what the owner-scoped board query answers
  printf '%s' "$2" > "$TMP/$1.json"; export GH_BOARDS="$TMP/$1.json"
}

node() {  # $1=json — what node(id:) answers
  printf '%s' "$1" > "$TMP/node.json"; export GH_NODE="$TMP/node.json"
}

cfg() {  # $1=json, or empty for a machine with no board configured
  if [[ -z "$1" ]]; then export JSTACK_ISSUE_WORK_CONFIG="$TMP/absent.json"; return; fi
  printf '%s' "$1" > "$TMP/issue_work.json"
  export JSTACK_ISSUE_WORK_CONFIG="$TMP/issue_work.json"
}

AUTOWORK='{"data":{"organization":{"projectsV2":{"nodes":[
  {"id":"PVT_7","number":7,"title":"Auto-Work","closed":false,
   "field":{"id":"F_ST","options":[
     {"id":"o_todo","name":"Todo"},
     {"id":"o_prog","name":"In Progress"},
     {"id":"o_rev","name":"Review"},
     {"id":"o_blk","name":"Blocked"}]}}]}},"user":null}}'

run() { OUT="$("$BIN" "$@" 2>&1)"; RC=$?; }

echo "usage gates"
boards a "$AUTOWORK"
run --issue 5 --status Todo
[[ $RC -eq 64 && "$OUT" == *"--repo"* ]] && ok "repo required" || bad "repo required" "rc=$RC $OUT"
run --repo notslashed --issue 5 --status Todo
[[ $RC -eq 64 ]] && ok "repo must be owner/name" || bad "repo must be owner/name" "rc=$RC"
run --repo O/R --status Todo
[[ $RC -eq 64 && "$OUT" == *"--issue"* ]] && ok "issue number required" || bad "issue number required" "rc=$RC $OUT"
run --repo O/R --issue 5
[[ $RC -eq 64 && "$OUT" == *"undefined state"* ]] \
  && ok "status required — a card with no column is not placed" || bad "status required" "rc=$RC $OUT"
run --repo O/R --issue 5 --status Todo --bogus
[[ $RC -eq 64 ]] && ok "unknown flag refused" || bad "unknown flag refused" "rc=$RC"

echo "blind states exit nonzero and place nothing"
( export PATH="/usr/bin:/bin"; "$BIN" --repo O/R --issue 5 --status Todo >/dev/null 2>&1 ); RC=$?
[[ $RC -eq 3 ]] && ok "no gh on PATH exits 3" || bad "no gh on PATH exits 3" "rc=$RC"
export GH_BOARDS="$TMP/nope.json"
run --repo O/R --issue 5 --status Todo
[[ $RC -eq 4 && "$OUT" == *"cannot read projects"* ]] && ok "graphql failure exits 4" || bad "graphql failure exits 4" "rc=$RC $OUT"
boards nullboth '{"data":{"organization":null,"user":null}}'
run --repo O/R --issue 5 --status Todo
[[ $RC -eq 4 ]] && ok "owner resolves to neither org nor user exits 4" || bad "owner resolves to neither org nor user exits 4" "rc=$RC $OUT"

echo "the owner may be a user, and gh's exit code is not the signal"
boards useracct '{"data":{"organization":null,"user":{"projectsV2":{"nodes":[
  {"id":"PVT_U","number":2,"title":"Auto-Work","closed":false,
   "field":{"id":"F_U","options":[{"id":"u_todo","name":"Todo"}]}}]}}}}'
run --repo someone/repo --issue 5 --status Todo --dry-run
[[ $RC -eq 0 && "$OUT" == *"PLACED board=Auto-Work status=Todo"* ]] \
  && ok "user-owned project resolves like an org one" || bad "user-owned project resolves like an org one" "rc=$RC $OUT"

echo "board resolution by title"
boards a "$AUTOWORK"
run --repo O/R --issue 5 --status Todo --board Nonesuch --dry-run
[[ $RC -eq 4 && "$OUT" == *"matched 0 boards"* && "$OUT" == *"Auto-Work"* ]] \
  && ok "unknown board exits 4 and lists what exists" || bad "unknown board exits 4 and lists what exists" "rc=$RC $OUT"

boards amb '{"data":{"organization":{"projectsV2":{"nodes":[
  {"id":"PVT_1","number":1,"title":"Auto-Work","closed":false,"field":{"id":"F1","options":[{"id":"a","name":"Todo"}]}},
  {"id":"PVT_2","number":2,"title":"Manual Work","closed":false,"field":{"id":"F2","options":[{"id":"b","name":"Todo"}]}}]}},"user":null}}'
run --repo O/R --issue 5 --status Todo --board Work --dry-run
[[ $RC -eq 4 && "$OUT" == *"matched 2 boards"* ]] \
  && ok "ambiguous substring exits 4 rather than guessing" || bad "ambiguous substring exits 4 rather than guessing" "rc=$RC $OUT"

boards shadow '{"data":{"organization":{"projectsV2":{"nodes":[
  {"id":"PVT_A","number":1,"title":"Auto-Work","closed":false,"field":{"id":"FA","options":[{"id":"a","name":"Todo"}]}},
  {"id":"PVT_W","number":2,"title":"Work","closed":false,"field":{"id":"FW","options":[{"id":"w","name":"Todo"}]}}]}},"user":null}}'
run --repo O/R --issue 5 --status Todo --board Work --dry-run
[[ $RC -eq 0 && "$OUT" == *"board=Work"* ]] \
  && ok "exact title wins over a substring that also matches" || bad "exact title wins over a substring that also matches" "rc=$RC $OUT"

boards closed '{"data":{"organization":{"projectsV2":{"nodes":[
  {"id":"PVT_OLD","number":1,"title":"Auto-Work","closed":true,"field":{"id":"FO","options":[{"id":"o","name":"Todo"}]}},
  {"id":"PVT_NEW","number":9,"title":"Auto-Work 2026","closed":false,"field":{"id":"FN","options":[{"id":"n","name":"Todo"}]}}]}},"user":null}}'
run --repo O/R --issue 5 --status Todo --dry-run
[[ $RC -eq 0 && "$OUT" == *"board=Auto-Work 2026"* ]] \
  && ok "a closed board is not a placement target" || bad "a closed board is not a placement target" "rc=$RC $OUT"

echo "--list-boards shows every open board and its columns"
boards a "$AUTOWORK"
run --repo O/R --list-boards
[[ $RC -eq 0 && "$OUT" == *"#7"* && "$OUT" == *"Auto-Work"* && "$OUT" == *"In Progress"* ]] \
  && ok "lists number, title and columns" || bad "lists number, title and columns" "rc=$RC $OUT"
boards closed '{"data":{"organization":{"projectsV2":{"nodes":[
  {"id":"PVT_OLD","number":1,"title":"Retired","closed":true,"field":{"id":"FO","options":[{"id":"o","name":"Todo"}]}}]}},"user":null}}'
run --repo O/R --list-boards
[[ $RC -eq 0 && "$OUT" != *"Retired"* ]] && ok "closed boards omitted" || bad "closed boards omitted" "rc=$RC $OUT"

echo "the dry run refuses what the real call could not finish"
boards a "$AUTOWORK"
run --repo O/R --issue 5 --status "In Progress" --dry-run
[[ $RC -eq 0 && "$OUT" == *"PLACED board=Auto-Work status=In Progress"* ]] \
  && ok "happy dry-run exits 0" || bad "happy dry-run exits 0" "rc=$RC $OUT"
run --repo O/R --issue 5 --status Shipped --dry-run
[[ $RC -eq 5 && "$OUT" == *"Todo, In Progress"* ]] \
  && ok "unknown column exits 5 in dry run and names the real columns" || bad "unknown column exits 5 in dry run" "rc=$RC $OUT"
: > "$GH_CALLS"
run --repo O/R --issue 5 --status Todo --dry-run
! grep -qE "addProjectV2ItemById|updateProjectV2ItemFieldValue" "$GH_CALLS" \
  && ok "dry run mutates nothing" || bad "dry run mutates nothing" "$(cat "$GH_CALLS")"

echo "the real call adds the card AND sets the column"
: > "$GH_CALLS"
run --repo O/R --issue 5 --status "In Progress"
[[ $RC -eq 0 && "$OUT" == *"PLACED board=Auto-Work status=In Progress item=PVTI_item9"* ]] \
  && ok "prints parseable receipt" || bad "prints parseable receipt" "rc=$RC $OUT"
grep -q "addProjectV2ItemById" "$GH_CALLS" && ok "card added to the board" || bad "card added to the board" "no add mutation"
grep -q "o_prog" "$GH_CALLS" && ok "column set to the resolved option id" || bad "column set to the resolved option id" "no option id"

echo "a column it could not set is never claimed"
run --repo O/R --issue 5 --status Shipped
[[ $RC -eq 5 && "$OUT" == *"status=unset"* && "$OUT" == *"card added, column unset"* ]] \
  && ok "unknown column: card lands, receipt says unset, exit 5" || bad "unknown column: card lands, receipt says unset, exit 5" "rc=$RC $OUT"
export GH_SETCOL_FAIL=1
run --repo O/R --issue 5 --status Todo
[[ $RC -eq 5 && "$OUT" == *"status=unset"* ]] \
  && ok "column mutation refused: receipt says unset, exit 5" || bad "column mutation refused: receipt says unset, exit 5" "rc=$RC $OUT"
unset GH_SETCOL_FAIL
export GH_ADD_FAIL=1
run --repo O/R --issue 5 --status Todo
[[ $RC -eq 5 && "$OUT" == *"could not add"* ]] \
  && ok "add refused exits 5 with no receipt" || bad "add refused exits 5 with no receipt" "rc=$RC $OUT"
unset GH_ADD_FAIL
export GH_NO_ISSUE=1
run --repo O/R --issue 5 --status Todo
[[ $RC -eq 4 && "$OUT" == *"not found"* ]] \
  && ok "missing issue exits 4 before touching the board" || bad "missing issue exits 4" "rc=$RC $OUT"
unset GH_NO_ISSUE

# ── the board is configured, not derived from the repo ──────────────────────
#
# Everything above ran with no board configured, which is the pre-config
# behaviour and must stay exactly that. From here the config exists, and what
# is asserted is WHICH ACCOUNT WAS SEARCHED and WHICH BOARD ID WAS USED — the
# stub answers the same boards to every owner on purpose, so a test that only
# checked the receipt would pass even with the bug still in.

CFG_ORG='{"board":{"org":"Acme-Org","number":7,"title":"Auto-Work"}}'
CFG_ID='{"board":{"org":"Acme-Org","number":7,"title":"Auto-Work","project_id":"PVT_cfg"}}'
NODE_OK='{"data":{"node":{"id":"PVT_cfg","number":7,"title":"Auto-Work","closed":false,
  "field":{"id":"F_CFG","options":[{"id":"c_todo","name":"Todo"},{"id":"c_rev","name":"Review"}]}}}}'

echo "an out-of-org repo places on the configured board"
boards a "$AUTOWORK"; cfg "$CFG_ORG"; : > "$GH_CALLS"
run --repo jenyalebid/JStack --issue 6 --status Review --dry-run
[[ $RC -eq 0 && "$OUT" == *"PLACED board=Auto-Work status=Review"* ]] && grep -q "owner=Acme-Org" "$GH_CALLS" \
  && ok "board.org is searched, not the repo's owner" || bad "board.org is searched, not the repo's owner" "rc=$RC $OUT"
! grep -q "owner=jenyalebid" "$GH_CALLS" \
  && ok "the repo owner is never searched once a board is configured" || bad "repo owner not searched" "$(cat "$GH_CALLS")"

node "$NODE_OK"; cfg "$CFG_ID"; : > "$GH_CALLS"
run --repo jenyalebid/JStack --issue 6 --status Review --dry-run
[[ $RC -eq 0 && "$OUT" == *"PLACED board=Auto-Work status=Review"* ]] && grep -q "id=PVT_cfg" "$GH_CALLS" \
  && ok "board.project_id names the board outright" || bad "board.project_id names the board outright" "rc=$RC $OUT"
! grep -q "owner=" "$GH_CALLS" \
  && ok "a configured board id skips the owner search entirely" || bad "configured id skips owner search" "$(cat "$GH_CALLS")"

node '{"data":{"node":{"id":"PVT_cfg","number":7,"title":"Auto-Work 2027","closed":false,
  "field":{"id":"F_CFG","options":[{"id":"c_rev","name":"Review"}]}}}}'
run --repo jenyalebid/JStack --issue 6 --status Review --dry-run
[[ $RC -eq 0 && "$OUT" == *"board=Auto-Work 2027"* ]] \
  && ok "a renamed board still takes the card — the id is the identity" || bad "renamed board still takes the card" "rc=$RC $OUT"

echo "in-org placement is unchanged by the config"
boards a "$AUTOWORK"; cfg "$CFG_ORG"; : > "$GH_CALLS"
run --repo Acme-Org/thing --issue 5 --status "In Progress" --dry-run
[[ $RC -eq 0 && "$OUT" == *"PLACED board=Auto-Work status=In Progress"* ]] && grep -q "owner=Acme-Org" "$GH_CALLS" \
  && ok "a repo inside the configured org resolves as it always did" || bad "in-org unchanged" "rc=$RC $OUT"

echo "the caller can still ask for somewhere else"
cfg "$CFG_ID"; boards a "$AUTOWORK"; : > "$GH_CALLS"
run --repo jenyalebid/JStack --issue 6 --status Todo --owner Other-Org --dry-run
[[ $RC -eq 0 ]] && grep -q "owner=Other-Org" "$GH_CALLS" && ! grep -q "id=PVT_cfg" "$GH_CALLS" \
  && ok "--owner outranks the config and drops its board id" || bad "--owner outranks the config" "rc=$RC $OUT"

boards shadow2 '{"data":{"organization":{"projectsV2":{"nodes":[
  {"id":"PVT_A","number":1,"title":"Auto-Work","closed":false,"field":{"id":"FA","options":[{"id":"a","name":"Todo"}]}},
  {"id":"PVT_D","number":3,"title":"Design","closed":false,"field":{"id":"FD","options":[{"id":"d","name":"Todo"}]}}]}},"user":null}}'
: > "$GH_CALLS"
run --repo jenyalebid/JStack --issue 6 --status Todo --board Design --dry-run
[[ $RC -eq 0 && "$OUT" == *"board=Design"* ]] && grep -q "owner=Acme-Org" "$GH_CALLS" && ! grep -q "id=PVT_cfg" "$GH_CALLS" \
  && ok "--board naming another board searches the configured org by title" || bad "--board bypasses the configured id" "rc=$RC $OUT"

cfg ""; node "$NODE_OK"; : > "$GH_CALLS"
run --repo O/R --issue 5 --status Review --project-id PVT_cfg --dry-run
[[ $RC -eq 0 && "$OUT" == *"status=Review"* ]] && grep -q "id=PVT_cfg" "$GH_CALLS" \
  && ok "--project-id places with no config at all" || bad "--project-id places with no config" "rc=$RC $OUT"

run --repo O/R --issue 5 --status Todo --project-id PVT_cfg --board Other
[[ $RC -eq 64 ]] && ok "--project-id with --board is refused, not silently won" || bad "--project-id with --board refused" "rc=$RC"
run --repo O/R --issue 5 --status Todo --project-id PVT_cfg --owner Someone
[[ $RC -eq 64 ]] && ok "--project-id with --owner is refused" || bad "--project-id with --owner refused" "rc=$RC"

echo "the loud failures stay loud"
cfg "$CFG_ID"; node '{"data":{"node":null}}'
run --repo jenyalebid/JStack --issue 6 --status Review
[[ $RC -eq 4 && "$OUT" == *"PVT_cfg"* && "$OUT" == *"issue_work.json"* ]] \
  && ok "a configured id that no longer resolves exits 4 and names its source" || bad "stale configured id exits 4" "rc=$RC $OUT"
node '{"data":{"node":{"id":"PVT_cfg","number":7,"title":"Retired","closed":true,"field":null}}}'
run --repo jenyalebid/JStack --issue 6 --status Review
[[ $RC -eq 4 && "$OUT" == *"closed"* ]] \
  && ok "a configured board that was closed exits 4" || bad "closed configured board exits 4" "rc=$RC $OUT"

# The failure as the night auditor met it: no board configured, so the search
# fell back to a personal account that has none. Still exit 4 and still nothing
# placed — but it now names what to set instead of only what it could not find.
cfg ""; boards empty '{"data":{"organization":null,"user":{"projectsV2":{"nodes":[]}}}}'
run --repo jenyalebid/JStack --issue 6 --status Review
[[ $RC -eq 4 && "$OUT" == *"matched 0 boards on jenyalebid"* && "$OUT" == *"no board config at"* ]] \
  && ok "an unconfigured out-of-org repo exits 4 and names its fix" || bad "unconfigured out-of-org names its fix" "rc=$RC $OUT"

echo "a configured board is placed on for real, and its columns are still live"
cfg "$CFG_ID"; node "$NODE_OK"; : > "$GH_CALLS"
run --repo jenyalebid/JStack --issue 6 --status Review
[[ $RC -eq 0 && "$OUT" == *"PLACED board=Auto-Work status=Review item=PVTI_item9"* ]] \
  && grep -q "p=PVT_cfg" "$GH_CALLS" && grep -q "o=c_rev" "$GH_CALLS" \
  && ok "card added to the configured board and its column set" || bad "real placement on configured board" "rc=$RC $OUT"
run --repo jenyalebid/JStack --issue 6 --status Shipped
[[ $RC -eq 5 && "$OUT" == *"status=unset"* && "$OUT" == *"Todo, Review"* ]] \
  && ok "unknown column on a configured board: card lands, exit 5, real columns named" || bad "unknown column on configured board" "rc=$RC $OUT"

echo ""
if [[ $fails -gt 0 ]]; then echo "$fails check(s) failed" >&2; exit 1; fi
echo "ALL PASS — place-issue verified"
