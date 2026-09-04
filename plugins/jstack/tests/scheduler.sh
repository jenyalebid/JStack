#!/usr/bin/env bash
# JStack live test — the scheduler package and its install seam.
#
# Runs the real shipped package against a hermetic temp SCHEDULER_HOME (never
# touches a real registry, state dir, or running daemon). Verifies the contract
# that makes one package serve every machine:
#   - config/scheduler.json drives timezone, spawn env, and spawn PATH
#   - workspace resolution: job override > resolver hook > registry > agents dir,
#     with seat_rules applied only when the seat is real
#   - data dirs: SCHEDULER_*_DIR > SCHEDULER_HOME > JSTACK_ROOT derivation >
#     ~/.scheduler, and the derivation layer never moves an install that
#     predates it
#   - a broken resolver spec raises instead of silently running elsewhere
#   - permission_mode defaults to bypassPermissions and resolves job>category>default
#   - VTIMEZONE is derived from the zone (DST, last-Sunday, and no-DST cases)
#   - registry round-trip: add a job, read it back, remove it
#   - the daemon actually boots and serves /health
#
# Exit 0 = all pass, exit 1 = any fail.

set -u

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

PY="${JSTACK_PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { echo "FAIL: no python3 on PATH (set JSTACK_PYTHON)"; exit 1; }

# python-dateutil is needed for RRULE expansion and for NOTHING ELSE. Recurring
# jobs require it; one-shot jobs must not, because a one-shot is how a message
# wake and a self-scheduled follow-up are delivered — the paths a fresh install
# needs on day one, before anyone has installed anything. The rest of this file
# exercises recurrence and so needs the package; the portability check below
# runs first and deliberately runs WITHOUT it.
if ! "$PY" -c "import dateutil.rrule" >/dev/null 2>&1; then
    echo "SKIP: python-dateutil not installed for $PY — the recurrence checks need it."
    echo "      Install it (pip install python-dateutil) or point JSTACK_PYTHON at the venv that runs the daemon."
    echo "      NOTE: the one-shot path does not need it; see tests/scheduler-bare.sh."
    exit 0
fi

TMP=$(mktemp -d /tmp/jstack-scheduler-test.XXXXXX)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/config" "$TMP/agents/demo-social/chat" "$TMP/agents/plain"
# `plain` and `demo-social` stay bare on purpose: a workspace is not required
# to be a declared agent. The fallback's bar is "a directory that exists", and
# these two check it stays that low.

export SCHEDULER_HOME="$TMP"
export PYTHONPATH="$PLUGIN_ROOT${PYTHONPATH:+:$PYTHONPATH}"

cat > "$TMP/config/scheduler.json" <<EOF
{
  "timezone": "America/Los_Angeles",
  "spawn_env": {"JSTACK_TIMELINE_ORIGIN": "indirect", "MARKER": "set"},
  "spawn_path_prepend": ["$TMP/tools"],
  "spawn_dirs": ["/usr/bin"],
  "agent_root": "$TMP/agents",
  "seat_rules": [{"agent_id_suffix": "-social", "seat": "chat"}]
}
EOF

fails=0
fail() { echo "FAIL: $1" >&2; fails=$((fails+1)); }
pass() { echo "ok: $1"; }

check() {  # check <name> <python expression asserting truth>
    local name="$1"; shift
    if out=$("$PY" -c "$1" 2>&1); then
        pass "$name"
    else
        fail "$name — $out"
    fi
}

# ── install config drives the machine-specific bits ──

check "timezone comes from scheduler.json" '
from scheduler import config
assert config.default_tz() == "America/Los_Angeles", config.default_tz()
'

check "spawn env + PATH prepend come from scheduler.json" '
from scheduler import spawn
env = spawn.run_env({"PATH": "/inherited"})
assert env["MARKER"] == "set", env.get("MARKER")
assert env["JSTACK_TIMELINE_ORIGIN"] == "indirect"
assert env["PATH"].endswith("/usr/bin:/inherited"), env["PATH"]
'

# ── workspace resolution ──

check "job workspace override wins" '
from scheduler import spawn
from pathlib import Path
assert spawn.resolve_workspace({"agent_id": "x", "workspace": "/tmp/override"}) == Path("/tmp/override")
'

check "agent_root fallback resolves" '
import os
from scheduler import spawn
from pathlib import Path
want = Path(os.environ["SCHEDULER_HOME"]) / "agents" / "plain"
assert spawn.resolve_workspace({"agent_id": "plain"}) == want
'

check "seat rule redirects into a real seat" '
import os
from scheduler import spawn
from pathlib import Path
root = Path(os.environ["SCHEDULER_HOME"]) / "agents" / "demo-social"
(root / "chat" / "CLAUDE.md").write_text("## Machine\n")
assert spawn.resolve_workspace({"agent_id": "demo-social"}) == root / "chat"
'

check "seat rule ignored when the seat has no CLAUDE.md" '
import os
from scheduler import spawn
from pathlib import Path
root = Path(os.environ["SCHEDULER_HOME"]) / "agents" / "demo-social"
(root / "chat" / "CLAUDE.md").unlink()
assert spawn.resolve_workspace({"agent_id": "demo-social"}) == root
'

check "broken resolver spec raises rather than falling back" '
from scheduler import config, spawn
config.reset_install_cache()
inst = config.install()
inst["workspace_resolver"] = "not-a-spec"
try:
    spawn.resolve_workspace({"agent_id": "plain"})
except ValueError:
    pass
else:
    raise AssertionError("silently fell back instead of raising")
finally:
    config.reset_install_cache()
'

# ── workspace fallback: real directories, not fabricated joins ──
# These need the parent env minus any ambient JSTACK_* declarations — the
# resolution under test must come from scheduler.json's agent_root, not from
# whatever the machine running this file happens to export.

mkdir -p "$TMP/agents/CasedAgent" "$TMP/agents/snake_agent"
touch "$TMP/agents/CasedAgent/CLAUDE.md" "$TMP/agents/snake_agent/CLAUDE.md"

if out=$(env -u JSTACK_ROOT -u JSTACK_AGENTS_DIR "$PY" -c '
import os
from pathlib import Path
from scheduler import spawn
base = Path(os.environ["SCHEDULER_HOME"]) / "agents"
assert spawn.resolve_workspace({"agent_id": "casedagent"}) == base / "CasedAgent"
assert spawn.resolve_workspace({"agent_id": "snake-agent"}) == base / "snake_agent"
' 2>&1); then
    pass "fallback tolerates case and -/_ spelling of a real agent dir"
else
    fail "agent id folding — $out"
fi

if out=$(env -u JSTACK_ROOT -u JSTACK_AGENTS_DIR "$PY" -c '
import os
from pathlib import Path
from scheduler import spawn
base = Path(os.environ["SCHEDULER_HOME"]) / "agents"
# `plain` has no CLAUDE.md, so it is not an agent — and still resolves. A
# workspace only has to exist; requiring a declaration would refuse to run a
# job in a directory that is sitting right there.
assert spawn.resolve_workspace({"agent_id": "plain"}) == base / "plain"
' 2>&1); then
    pass "a real directory resolves even when nothing declared it an agent"
else
    fail "undeclared-but-real workspace — $out"
fi

if out=$(env -u JSTACK_ROOT -u JSTACK_AGENTS_DIR "$PY" -c '
from scheduler import spawn
try:
    spawn.resolve_workspace({"agent_id": "gh0st"})
except ValueError as e:
    msg = str(e)
    assert "gh0st" in msg, msg            # the id that missed
    assert "/agents" in msg, msg          # the dir that was searched
    assert "CasedAgent" in msg, msg       # a real neighbouring agent id
else:
    raise AssertionError("a nonexistent agent resolved to a fabricated path")
' 2>&1); then
    pass "a miss raises at the mistake, naming the searched dir and the real ids"
else
    fail "workspace miss error — $out"
fi

if out=$(env -u JSTACK_ROOT -u JSTACK_AGENTS_DIR "$PY" -c '
from pathlib import Path
from scheduler import spawn
got = spawn.resolve_workspace({"agent_id": "gh0st", "workspace": "/tmp/pinned"})
assert got == Path("/tmp/pinned"), got
' 2>&1); then
    pass "an explicit job workspace wins even when the agent does not exist"
else
    fail "workspace override for a missing agent — $out"
fi

# ── data dirs: the JSTACK_ROOT derivation layer ──
# A NEW layer between SCHEDULER_HOME and the ~/.scheduler default. Each check
# states its own environment outright: the layer's whole contract is
# precedence, and precedence only shows under a controlled one.

JROOT="$TMP/jstack-root"; LEGACY_HOME="$TMP/legacy-home"
mkdir -p "$JROOT" "$LEGACY_HOME"

# No JSTACK_ROOT: byte-identical to the pre-derivation chain. This is the
# regression that protects the running daemon.
if out=$(env -u JSTACK_ROOT -u SCHEDULER_CONFIG_DIR -u SCHEDULER_STATE_DIR \
        -u SCHEDULER_CREDENTIALS_DIR SCHEDULER_HOME="$TMP" "$PY" -c '
import os
from pathlib import Path
from scheduler import config
home = Path(os.environ["SCHEDULER_HOME"])
assert config.CONFIG_DIR == home / "config", config.CONFIG_DIR
assert config.STATE_DIR == home / "state" / "scheduler", config.STATE_DIR
assert config.CREDENTIALS_DIR == home / "Credentials", config.CREDENTIALS_DIR
' 2>&1); then
    pass "no JSTACK_ROOT: SCHEDULER_HOME keeps the exact legacy shapes"
else
    fail "SCHEDULER_HOME legacy regression — $out"
fi

# The interpreter that runs a live daemon may declare SCHEDULER_HOME itself
# through a site hook (a .pth setdefault), so `env -u` alone cannot produce
# the unset state these checks are about. -S keeps site processing out of a
# subprocess whose whole premise is that the variable is absent.
if out=$(env -u JSTACK_ROOT -u SCHEDULER_HOME -u SCHEDULER_CONFIG_DIR \
        -u SCHEDULER_STATE_DIR -u SCHEDULER_CREDENTIALS_DIR \
        HOME="$LEGACY_HOME" "$PY" -S -c '
import os
from pathlib import Path
from scheduler import config
home = Path(os.environ["HOME"]) / ".scheduler"
assert config.CONFIG_DIR == home / "config", config.CONFIG_DIR
assert config.STATE_DIR == home / "state" / "scheduler", config.STATE_DIR
assert config.CREDENTIALS_DIR == home / "Credentials", config.CREDENTIALS_DIR
' 2>&1); then
    pass "no JSTACK_ROOT, no SCHEDULER_HOME: the ~/.scheduler default is untouched"
else
    fail "bare-default legacy regression — $out"
fi

if out=$(env -u SCHEDULER_HOME -u SCHEDULER_CONFIG_DIR -u SCHEDULER_STATE_DIR \
        -u SCHEDULER_CREDENTIALS_DIR -u JSTACK_CONFIG_DIR -u JSTACK_STATE_DIR \
        -u JSTACK_CREDENTIALS_DIR JSTACK_ROOT="$JROOT" "$PY" -S -c '
import os
from pathlib import Path
from scheduler import config
r = Path(os.environ["JSTACK_ROOT"])
assert config.CONFIG_DIR == r / "Config", config.CONFIG_DIR
assert config.STATE_DIR == r / "State" / "scheduler", config.STATE_DIR
assert config.CREDENTIALS_DIR == r / "Credentials", config.CREDENTIALS_DIR
' 2>&1); then
    pass "JSTACK_ROOT alone: dirs derive as Config / State/scheduler / Credentials"
else
    fail "JSTACK_ROOT derivation — $out"
fi

if out=$(env -u SCHEDULER_HOME -u SCHEDULER_CONFIG_DIR -u SCHEDULER_CREDENTIALS_DIR \
        -u JSTACK_CONFIG_DIR -u JSTACK_STATE_DIR -u JSTACK_CREDENTIALS_DIR \
        JSTACK_ROOT="$JROOT" SCHEDULER_STATE_DIR="$TMP/live-state" "$PY" -S -c '
import os
from pathlib import Path
from scheduler import config
assert config.STATE_DIR == Path(os.environ["SCHEDULER_STATE_DIR"]), config.STATE_DIR
assert config.CONFIG_DIR == Path(os.environ["JSTACK_ROOT"]) / "Config", config.CONFIG_DIR
' 2>&1); then
    pass "SCHEDULER_STATE_DIR outranks JSTACK_ROOT; its siblings still derive"
else
    fail "explicit-dir precedence over JSTACK_ROOT — $out"
fi

# ── permission_mode ──

check "permission_mode defaults to bypassPermissions" '
from scheduler import config, runner
argv = runner.build_argv("claude", "opus", "sid", "msg")
assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
assert config.BUILTIN_DEFAULTS["permission_mode"] == "bypassPermissions"
'

check "permission_mode resolves job > category > default" '
from scheduler import resolve
d = {"permission_mode": "bypassPermissions"}
c = {"tight": {"permission_mode": "acceptEdits"}}
assert "permission_mode" in resolve.INHERITED_KEYS
assert resolve.resolve_setting({"category": "tight"}, "permission_mode", d, c) == "acceptEdits"
assert resolve.resolve_setting({"category": "tight", "permission_mode": "plan"}, "permission_mode", d, c) == "plan"
'

# ── ics VTIMEZONE derivation ──

check "VTIMEZONE derives a US DST rule" '
from scheduler import ics
lines = ics.vtimezone("America/Los_Angeles")
assert "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU" in lines, lines
assert "DTSTART:19700308T020000" in lines, lines
assert "TZNAME:PDT" in lines and "TZNAME:PST" in lines
'

check "VTIMEZONE derives a last-Sunday rule" '
from scheduler import ics
lines = ics.vtimezone("Europe/Berlin")
assert "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU" in lines, lines
'

check "VTIMEZONE for a zone without DST has no recurrence" '
from scheduler import ics
lines = ics.vtimezone("Asia/Tokyo")
assert not [l for l in lines if l.startswith("RRULE")], lines
assert "BEGIN:DAYLIGHT" not in lines
'

# ── registry round-trip through the real CLI ──

if "$PY" -m scheduler.cli add-once --agent plain --at "2030-01-01 09:00" \
        --message "test wake" --name "jstack selftest" >"$TMP/add.out" 2>&1; then
    JOB_ID=$(sed -n 's/.*added once job \([0-9a-f-]*\).*/\1/p' "$TMP/add.out")
    if [ -n "$JOB_ID" ] && "$PY" -m scheduler.cli list --all 2>/dev/null | grep -q "jstack selftest"; then
        pass "registry round-trip: job added and listed"
        if "$PY" -m scheduler.cli rm "$JOB_ID" --force >/dev/null 2>&1 \
           && ! "$PY" -m scheduler.cli list --all 2>/dev/null | grep -q "jstack selftest"; then
            pass "registry round-trip: job removed"
        else
            fail "registry round-trip: job not removed"
        fi
    else
        fail "registry round-trip: job not listed after add ($(cat "$TMP/add.out"))"
    fi
else
    fail "registry round-trip: add-once failed ($(cat "$TMP/add.out"))"
fi

# ── the daemon boots and serves /health ──

PORT=$(( 19000 + RANDOM % 2000 ))
SCHEDULER_API_PORT="$PORT" SCHEDULER_TICK_SECONDS=0.5 \
    "$PY" -m scheduler >"$TMP/daemon.out" 2>&1 &
DAEMON_PID=$!
health=""
for _ in $(seq 1 40); do
    health=$(curl -s --max-time 1 "http://127.0.0.1:$PORT/health" 2>/dev/null) && [ -n "$health" ] && break
    health=""
done
if echo "$health" | grep -q '"ok": *true'; then
    pass "daemon boots and serves /health"
else
    fail "daemon never became healthy ($(tail -5 "$TMP/daemon.out" 2>/dev/null))"
fi
kill "$DAEMON_PID" 2>/dev/null
wait "$DAEMON_PID" 2>/dev/null

echo
if [ "$fails" -eq 0 ]; then
    echo "PASS — scheduler package + install seam verified"
    exit 0
fi
echo "$fails check(s) failed"
exit 1
