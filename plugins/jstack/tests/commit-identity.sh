#!/usr/bin/env bash
# JStack live test — the pre-commit identity gate.
#
# This repo is public; githooks/pre-commit is what keeps a wrong local git
# identity (the way a private employer address once entered history) from
# ever producing a commit. This test proves the gate actually gates:
#   - an off-list author email is BLOCKED, with the fix in the message
#   - an off-list committer email is BLOCKED even under a good author
#   - both identities on-list → the commit lands
# Runs against a throwaway fixture repo; never touches JStack's own index.
#
# Exit 0 = all pass, exit 1 = any fail.

set -u

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$PLUGIN_ROOT/githooks/pre-commit"

# A hook inherits git's own env when run under a real commit; this fixture
# must not inherit JStack's (same reasoning as the pre-push gate's tests).
unset GIT_DIR GIT_INDEX_FILE GIT_WORK_TREE GIT_OBJECT_DIRECTORY \
      GIT_ALTERNATE_OBJECT_DIRECTORIES GIT_PREFIX GIT_CONFIG_PARAMETERS

TMP=$(mktemp -d /tmp/jstack-commit-identity.XXXXXX)
trap 'rm -rf "$TMP"' EXIT

fails=0
fail() { echo "FAIL: $1" >&2; fails=$((fails+1)); }
pass() { echo "ok: $1"; }

[ -x "$HOOK" ] || { fail "githooks/pre-commit missing or not executable"; echo "1 check(s) failed"; exit 1; }

git init -q "$TMP/repo"
cd "$TMP/repo" || exit 1
git config user.name "Fixture"
git config user.email "271424658+jandj-agent@users.noreply.github.com"
cp "$HOOK" .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
echo x > file && git add file

GOOD="271424658+jandj-agent@users.noreply.github.com"
BAD="somebody@employer-corp.example"

# ── off-list author is blocked ──
out=$(GIT_AUTHOR_EMAIL="$BAD" git commit -m "bad author" 2>&1)
if [ $? -ne 0 ] && [ "$(git rev-list --count HEAD 2>/dev/null || echo 0)" = "0" ]; then
    pass "off-list author email blocked, no commit created"
else
    fail "off-list author email was NOT blocked ($out)"
fi
if echo "$out" | grep -q "git config user.email"; then
    pass "refusal message says how to fix it"
else
    fail "refusal message lacks the git config fix ($out)"
fi

# ── off-list committer is blocked even under a good author ──
if GIT_AUTHOR_EMAIL="$GOOD" GIT_COMMITTER_EMAIL="$BAD" git commit -m "bad committer" >/dev/null 2>&1; then
    fail "off-list committer email was NOT blocked"
else
    pass "off-list committer email blocked"
fi

# ── on-list identity commits normally ──
if git commit -m "good identity" >/dev/null 2>&1 \
   && [ "$(git rev-list --count HEAD)" = "1" ]; then
    pass "on-list identity commits normally"
else
    fail "on-list identity could not commit"
fi

echo
if [ "$fails" -eq 0 ]; then
    echo "PASS — commit identity gate verified"
    exit 0
fi
echo "$fails check(s) failed"
exit 1
