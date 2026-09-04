#!/bin/bash
# The scheduler on a machine that has installed nothing.
#
# python-dateutil is this package's only third-party dependency, and it is
# needed by exactly one job kind: recurring. One-shot jobs are the delivery
# mechanism for a message wake and a self-scheduled follow-up — the first two
# things a fresh install does — so a one-shot must book on a stock interpreter.
#
# It did not. `scheduler/occurrences.py` imported rrulestr at module top and
# `scheduler/cli.py` imports occurrences, so on any python without dateutil the
# CLI died at import and `add-once` never reached argparse. On a second machine
# that read as "the tools just do not work here", with a ModuleNotFoundError
# naming a line nobody had heard of.
#
# This file blocks dateutil regardless of what the host interpreter actually
# has, so the guarantee is proved on the machine that HAS the package too —
# otherwise it only ever gets tested where it was already fine.

set -u
PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${JSTACK_PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { echo "FAIL: no python3 on PATH (set JSTACK_PYTHON)"; exit 1; }

TMP=$(mktemp -d /tmp/jstack-scheduler-bare.XXXXXX)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/config" "$TMP/agents/demo"

# Block dateutil for every interpreter started under this PYTHONPATH.
mkdir -p "$TMP/shim"
cat > "$TMP/shim/sitecustomize.py" <<'EOF'
import sys


class _NoDateutil:
    """Refuse dateutil the way a machine without it does."""

    def find_module(self, name, path=None):
        return self if name == "dateutil" or name.startswith("dateutil.") else None

    def find_spec(self, name, path=None, target=None):
        if name == "dateutil" or name.startswith("dateutil."):
            raise ImportError(f"No module named {name!r}")
        return None


sys.meta_path.insert(0, _NoDateutil())
for mod in [m for m in sys.modules if m == "dateutil" or m.startswith("dateutil.")]:
    del sys.modules[mod]
EOF

export SCHEDULER_HOME="$TMP"
export PYTHONPATH="$TMP/shim:$PLUGIN_ROOT${PYTHONPATH:+:$PYTHONPATH}"

cat > "$TMP/config/scheduler.json" <<EOF
{ "timezone": "America/Los_Angeles", "agent_root": "$TMP/agents" }
EOF

fails=0
fail() { echo "FAIL: $1" >&2; fails=$((fails+1)); }
pass() { echo "ok: $1"; }

# The shim has to actually work, or every check below passes for the wrong
# reason on a machine that never had dateutil in the first place.
if "$PY" -c "import dateutil" 2>/dev/null; then
    fail "the dateutil blocker did not take — the rest of this file proves nothing"
    echo "$fails check(s) failed"; exit 1
fi
pass "dateutil is blocked for this run"

if "$PY" -c "from scheduler import cli" 2>"$TMP/err"; then
    pass "scheduler.cli imports without dateutil"
else
    fail "scheduler.cli still needs dateutil at import: $(tail -2 "$TMP/err")"
fi

out=$("$PY" -m scheduler.cli add-once --at "2099-01-01 09:00" --agent demo \
      --workspace "$TMP/agents/demo" --category inbox --name "bare install" \
      --message "hello" 2>&1)
if [ $? -eq 0 ] && printf '%s' "$out" | grep -q "added once job"; then
    pass "add-once books on a stock interpreter"
else
    fail "add-once failed without dateutil: $out"
fi

if "$PY" -m scheduler.cli list 2>/dev/null | grep -q "bare install"; then
    pass "the booked one-shot is really in the registry"
else
    fail "add-once reported success but the job is not listed"
fi

# Recurrence genuinely cannot work here. What matters is that it says so in
# terms of the job kind, not as an ImportError against a line number.
out=$("$PY" -m scheduler.cli add-recurring --cron "0 9 * * *" --agent demo \
      --workspace "$TMP/agents/demo" --category inbox --name "recurs" \
      --message "hi" 2>&1)
if printf '%s' "$out" | grep -q "python-dateutil"; then
    pass "a recurring job names the missing package, not an import line"
else
    fail "recurring failure message does not name the dependency: $(printf '%s' "$out" | tail -2)"
fi

echo
if [ "$fails" -eq 0 ]; then
    echo "PASS — one-shot scheduling works with nothing installed"
    exit 0
fi
echo "$fails check(s) failed"
exit 1
