#!/bin/bash
# Does the doctor tell the truth, and does it change nothing while doing it?
#
# A validator is the one tool nobody double-checks: its whole job is to be the
# thing you believe about a machine you cannot see. So two properties matter
# more than any individual check.
#
# READ-ONLY. The first run of this tool created three empty directories at the
# root — its writability probe did `mkdir -p` on its own subject — and then
# reported them healthy. That is a doctor describing a machine it just changed,
# and it is the failure mode that makes a green result worthless. Proven here
# against a sandbox root: run it, then assert not one path came into existence.
#
# WORST-GRADE EXIT. A script gating on this tool branches on its exit status,
# so 0/1/2 must track ok/warn/fail exactly — including the case where a check
# raises, which must land as FAIL rather than quietly dropping out of the list.
#
# Everything runs against a redirected HOME and a JSTACK_ROOT inside the
# tmpdir, so nothing here can read or write the real install.

set -u
PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
PY="${JSTACK_PYTHON:-python3}"
TOOL="$PLUGIN_ROOT/bin/jstack-doctor"
command -v "$PY" >/dev/null 2>&1 || { echo "FAIL: no python3 on PATH (set JSTACK_PYTHON)"; exit 1; }

TMP=$(mktemp -d /tmp/jstack-doctor.XXXXXX)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/root" "$TMP/home"

fails=0
fail() { echo "FAIL: $1" >&2; fails=$((fails+1)); }
pass() { echo "ok: $1"; }

# SCHEDULER_API_PORT points at a port nothing serves, so the scheduler probe
# resolves fast and can only report what this test controls.
run_doctor() {
    HOME="$TMP/home" JSTACK_ROOT="$TMP/root" \
    SCHEDULER_INSTALL_FILE="${INSTALL_FILE:-$TMP/root/absent-scheduler.json}" \
    SCHEDULER_API_PORT=59992 \
    "$PY" "$TOOL" "$@"
}

# Grade for one check name, out of the JSON. Absent name is an error, not an
# empty string: a check that vanished must not read as a check that passed.
grade_of() {
    "$PY" - "$1" "$2" <<'PY'
import json, sys
path, name = sys.argv[1], sys.argv[2]
data = json.load(open(path))
for c in data["checks"]:
    if c["name"] == name:
        print(c["grade"]); sys.exit(0)
print(f"MISSING:{name}")
PY
}

# ── read-only: the tool creates nothing ─────────────────────────────────────
# Snapshot the sandbox, run, compare. The root is deliberately EMPTY — every
# derived dir (Agents, Systems, Config, State, Logs, Credentials) is absent, so
# a probe that creates its subject has six chances to be caught.

before=$(find "$TMP" | sort)
run_doctor >/dev/null 2>&1
after=$(find "$TMP" | sort)
if [ "$before" = "$after" ]; then
    pass "read-only: an empty root is unchanged by a full run"
else
    fail "the doctor created or removed paths:"
    diff <(echo "$before") <(echo "$after") >&2
fi

# ── an empty root fails, and says which part ────────────────────────────────

run_doctor --json > "$TMP/empty.json" 2>/dev/null
rc=$?
[ "$rc" = "2" ] || fail "empty root should exit 2 (fail), got $rc"
[ "$rc" = "2" ] && pass "empty root exits 2"

g=$(grade_of "$TMP/empty.json" agents)
[ "$g" = "fail" ] || fail "no agents should grade fail, got '$g'"
[ "$g" = "fail" ] && pass "an agents dir with nothing in it is a failure"

# The root check itself must still pass: absent-but-creatable is a normal fresh
# install, and grading it fail would make every first run unfixable.
g=$(grade_of "$TMP/empty.json" root)
[ "$g" = "ok" ] || fail "absent-but-creatable dirs should grade ok, got '$g'"
[ "$g" = "ok" ] && pass "absent derived dirs are ok, not a failure"

# ── one agent flips it, and gets named ──────────────────────────────────────

mkdir -p "$TMP/root/Agents/Testbed"
printf '# Testbed\n' > "$TMP/root/Agents/Testbed/CLAUDE.md"
run_doctor --json > "$TMP/one.json" 2>/dev/null
g=$(grade_of "$TMP/one.json" agents)
[ "$g" = "ok" ] || fail "one agent should grade ok, got '$g'"
[ "$g" = "ok" ] && pass "a directory with a CLAUDE.md is an agent"

if grep -q "Testbed" "$TMP/one.json"; then
    pass "the agent is named in the detail, not just counted"
else
    fail "found agents but did not name them — '0 agents' and 'agents I cannot name' read identically"
fi

# ── a dead rules symlink is a failure, not a passing file ───────────────────
# The version-cache rot: links into a versioned plugin path survive until that
# version is reaped. The name still appears in `ls`; only following it fails.

mkdir -p "$TMP/home/.claude/rules"
ln -s "$TMP/nonexistent-plugin-version/canvas.md" "$TMP/home/.claude/rules/canvas.md"
run_doctor --json > "$TMP/broken.json" 2>/dev/null
g=$(grade_of "$TMP/broken.json" rules)
[ "$g" = "fail" ] || fail "a dead rules symlink should grade fail, got '$g'"
[ "$g" = "fail" ] && pass "a dead symlink is a failure, not an installed rule"
rm -f "$TMP/home/.claude/rules/canvas.md"

# ── unparseable config is a failure, because both readers swallow it ────────
# install() and load_defaults() catch JSONDecodeError and fall back to
# built-ins, silently. Nothing else on the machine will ever mention it.

printf '{ this is not json\n' > "$TMP/bad-scheduler.json"
INSTALL_FILE="$TMP/bad-scheduler.json" run_doctor --json > "$TMP/badcfg.json" 2>/dev/null
g=$(grade_of "$TMP/badcfg.json" config)
[ "$g" = "fail" ] || fail "unparseable scheduler.json should grade fail, got '$g'"
[ "$g" = "fail" ] && pass "a config file that silently falls back to defaults is a failure"

# ── the exit status is the worst grade, and JSON agrees with it ─────────────

run_doctor --json > "$TMP/agree.json" 2>/dev/null
rc=$?
declared=$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["exit"])' "$TMP/agree.json")
if [ "$rc" = "$declared" ]; then
    pass "process exit ($rc) matches the exit the JSON declares"
else
    fail "exit status $rc but JSON declares $declared — a gate would branch wrong"
fi

worst=$("$PY" - "$TMP/agree.json" <<'PY'
import json, sys
rank = {"ok": 0, "warn": 1, "fail": 2}
d = json.load(open(sys.argv[1]))
print(max(rank[c["grade"]] for c in d["checks"]))
PY
)
if [ "$rc" = "$worst" ]; then
    pass "exit status is the worst individual grade"
else
    fail "exit $rc is not the worst grade among the checks ($worst)"
fi

# ── a check that raises FAILS; it does not disappear ───────────────────────
# Proven by breaking a seam the doctor reads rather than by patching the tool:
# a root that resolves inside the shipping checkout makes root.py raise, and
# the only acceptable outcome is a fail-graded check that names the crash.

crash=$(cd "$PLUGIN_ROOT" && HOME="$TMP/home" JSTACK_ROOT="$PLUGIN_ROOT/state-in-checkout" \
        SCHEDULER_INSTALL_FILE="$TMP/root/absent-scheduler.json" SCHEDULER_API_PORT=59992 \
        "$PY" "$TOOL" --json 2>&1)
crash_rc=$?
if [ "$crash_rc" = "2" ] && printf '%s' "$crash" | grep -q '"grade": "fail"'; then
    pass "a root inside the shipping checkout fails loudly instead of vanishing"
else
    fail "a raising check did not surface as a failure (exit $crash_rc)"
fi

# ── report ─────────────────────────────────────────────────────────────────

echo
if [ "$fails" -eq 0 ]; then
    echo "doctor: all checks passed"
    exit 0
fi
echo "doctor: $fails failure(s)"
exit 1
