#!/bin/bash
# Does the suite report on the tree it is standing in?
#
# The pre-push gate runs jStack's own tests with JSTACK_PYTHON pointed at the
# host's Infrastructure venv, because the scheduler suite needs dateutil. That
# venv carries a .pth — `sys.path.insert(0, ~/jStack/plugins/jstack)`, how the
# host's daemon finds the plugin — and position 0 outranks PYTHONPATH. Every
# issue is worked in a worktree by mandate, so that was the normal path: the
# gate imported MAIN's root.py, repo_seat.py and scheduler/* while claiming to
# report on the branch being pushed.
#
# The red half announced itself (root.sh's shipping-tree guard comparing two
# different trees, #11). The green half did not, and is the one this file
# exists for: a change made in the worktree must be the change the gate sees,
# and a module the worktree does not have must not import from next door.
#
# Everything here is staged in a tmpdir: a decoy plugin copy, a throwaway venv
# carrying the same one-line .pth the host's does, and a stand-in "tree being
# pushed". No real venv, .pth or checkout is read or written.
#
# Exit 0 = the pin holds. Exit 1 = the suite can be made to answer about
# another checkout, which makes every other green in this directory a claim.

set -u
PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
PY="${JSTACK_PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { echo "FAIL: no python3 on PATH (set JSTACK_PYTHON)"; exit 1; }

# This file holds the suite to the pin, so it holds itself to it too — every
# check below that wants an UNPINNED interpreter says so by setting PYTHONPATH
# on that one command, which is the only way an unpinned run should ever be
# reachable in this directory.
. "$PLUGIN_ROOT/tests/lib/pin-plugin-root.sh"

TMP=$(mktemp -d /tmp/jstack-plugin-pin.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

fails=0
fail() { echo "FAIL: $1" >&2; fails=$((fails+1)); }
pass() { echo "ok: $1"; }

# ── the decoy: another checkout of this plugin, by signature ─────────────────
# root.py answers WHICH_TREE, so any import that lands here says so out loud
# rather than passing for the wrong tree. only_in_decoy.py is the deletion
# case: a module that exists over there and not in the tree under test.
DECOY="$TMP/decoy"
mkdir -p "$DECOY/scheduler"
echo 'WHICH_TREE = "decoy"' > "$DECOY/root.py"
: > "$DECOY/repo_seat.py"
: > "$DECOY/scheduler/__init__.py"
: > "$DECOY/only_in_decoy.py"

# ── the hijacking interpreter ────────────────────────────────────────────────
# A venv of the interpreter under test with the host venv's .pth line copied
# verbatim, aimed at the decoy. Building it from "$PY" is the point: this is
# the same interpreter the gate would hand the suite.
if ! "$PY" -m venv --without-pip "$TMP/venv" >"$TMP/venv.log" 2>&1; then
    echo "FAIL: could not build a venv from $PY — the hijack cannot be staged," >&2
    echo "      so nothing below would be proving anything." >&2
    sed -n '1,10p' "$TMP/venv.log" >&2
    exit 1
fi
HIJACK="$TMP/venv/bin/python3"
SITE=$("$HIJACK" -c 'import site; print(site.getsitepackages()[0])')
PTH="$SITE/decoy-plugin.pth"
cat > "$PTH" <<EOF
import os, sys; _p = os.path.expanduser("$DECOY"); (_p in sys.path) or sys.path.insert(0, _p)
EOF
PTH_BEFORE=$(cksum < "$PTH")

# ── the tree being pushed ────────────────────────────────────────────────────
# The real root.py plus one line that exists nowhere else — a stand-in for any
# change made in a worktree. It carries lib/ so it can pin itself, exactly as
# the checkout it stands in does.
UNDER="$TMP/under-test"
mkdir -p "$UNDER/tests/lib" "$UNDER/scheduler"
cp "$PLUGIN_ROOT/root.py" "$UNDER/root.py"
cp "$PLUGIN_ROOT/tests/lib/jstack_pin.py" \
   "$PLUGIN_ROOT/tests/lib/sitecustomize.py" \
   "$PLUGIN_ROOT/tests/lib/pin-plugin-root.sh" "$UNDER/tests/lib/"
: > "$UNDER/repo_seat.py"
: > "$UNDER/scheduler/__init__.py"
echo 'WHICH_TREE = "under-test"' >> "$UNDER/root.py"

# Run a python snippet the way a pinned test does: source the helper for the
# named tree, then start the hijacking interpreter under it.
pinned() {  # $1 = plugin root to pin, rest = python source
    local root="$1"; shift
    PLUGIN_ROOT="$root" PY="$HIJACK" bash -c \
        '. "$PLUGIN_ROOT/tests/lib/pin-plugin-root.sh"; "$PY" -c "$1"' _ "$*" 2>&1
}

# ── 1. the control: the bug reproduces ───────────────────────────────────────
# Without this, a green run below could mean the fix works or could mean the
# fixture never staged the hijack at all.
out=$(cd "$TMP" && PYTHONPATH="$UNDER" "$HIJACK" -c 'import root; print(root.WHICH_TREE)' 2>&1)
if [ "$out" = "decoy" ]; then
    pass "control: a .pth at sys.path[0] beats PYTHONPATH — the defect reproduces"
else
    echo "FAIL: the hijack did not stage (import root -> '$out'). Nothing below" >&2
    echo "      this line would prove anything, so this run reports nothing." >&2
    exit 1
fi

# ── 2. the pin wins the import ───────────────────────────────────────────────
out=$(pinned "$UNDER" 'import root; print(root.WHICH_TREE)')
if [ "$out" = "under-test" ]; then
    pass "the pinned tree wins over the interpreter's own .pth"
else
    fail "pinned import still resolved elsewhere: $out"
fi

# ── 3. the change in the worktree IS the change the gate sees ────────────────
# The false green, stated as behaviour: root.py's shipping-tree guard must
# name the tree under test, not the one the interpreter prefers. This is the
# check that was passing against main's copy on 2026-09-06.
out=$(pinned "$UNDER" "
import root
try:
    root.state_dir({'state_dir': '$UNDER/state'})
except RuntimeError as e:
    print('refused' if '$UNDER' in str(e) else 'named the wrong tree: %s' % e)
else:
    print('accepted a state dir inside the tree under test')
")
if [ "$out" = "refused" ]; then
    pass "the shipping-tree guard fires on the tree under test, naming it"
else
    fail "guard answered about another checkout: $out"
fi

# ── 4. a module the tree under test does not have must not import ────────────
out=$(pinned "$UNDER" 'import only_in_decoy; print("imported")')
if printf '%s' "$out" | grep -q "ModuleNotFoundError"; then
    pass "a module absent from the tree under test does not import from next door"
else
    fail "the rival checkout is still reachable: $out"
fi

# ── 5. a pin that cannot take fails loudly, and stops the test ───────────────
# Silence here is the whole defect: a suite that quietly answers about another
# checkout reports PASS on code nobody pushed.
BROKEN="$TMP/broken"
mkdir -p "$BROKEN/tests/lib"
cp "$PLUGIN_ROOT/root.py" "$BROKEN/root.py"
cp "$PLUGIN_ROOT/tests/lib/pin-plugin-root.sh" "$BROKEN/tests/lib/"   # no sitecustomize
out=$(PLUGIN_ROOT="$BROKEN" PY="$HIJACK" bash -c \
      '. "$PLUGIN_ROOT/tests/lib/pin-plugin-root.sh"; echo REACHED-THE-CHECKS' 2>&1); rc=$?
if [ $rc -ne 0 ] && printf '%s' "$out" | grep -q "testing a different checkout" \
   && ! printf '%s' "$out" | grep -q "REACHED-THE-CHECKS"; then
    pass "a pin that does not take exits the test, naming both trees"
else
    fail "a broken pin ran the checks anyway (rc=$rc): $out"
fi

# ── 6. end to end: the suite's own file, under the hijacking interpreter ─────
# The case that failed on 2026-09-06, run against a venv this test built.
#
# From two cwds, because cwd is the second attack vector and the one that
# makes this check lie if it is left to chance: the interpreter prepends it to
# sys.path[0] after site has run. $TMP is the gate's own situation (git runs a
# hook from the repo root, which is not a plugin root); $DECOY is the harder
# one, a cwd that IS another checkout of this plugin.
for from in "$TMP" "$DECOY"; do
    if out=$(cd "$from" && JSTACK_PYTHON="$HIJACK" "$PLUGIN_ROOT/tests/root.sh" 2>&1); then
        pass "root.sh passes under a .pth-carrying venv, run from $(basename "$from")"
    else
        fail "root.sh from $(basename "$from"): $(printf '%s' "$out" | grep FAIL | head -3)"
    fi
done

# ── 7. the .pth is left exactly as it was ────────────────────────────────────
# The constraint on the fix: the .pth is how a host's scheduler finds the
# plugin. Nothing here may remove or weaken it — the pin lives inside the test
# interpreters, and an interpreter nobody pinned still reads its .pth first.
out=$(cd "$TMP" && PYTHONPATH="$UNDER" "$HIJACK" -c 'import root; print(root.WHICH_TREE)' 2>&1)
if [ "$(cksum < "$PTH")" = "$PTH_BEFORE" ] && [ "$out" = "decoy" ]; then
    pass "the .pth is untouched and still wins for any interpreter outside the suite"
else
    fail "the .pth was disturbed (file changed, or unpinned import gave '$out')"
fi

echo
if [ "$fails" -eq 0 ]; then
    echo "PASS — the suite answers about the tree it ships in"
    exit 0
fi
echo "$fails check(s) failed"
exit 1
