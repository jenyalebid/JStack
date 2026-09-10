# shellcheck shell=bash
# Point every interpreter this test starts at the tree the test lives in.
#
#     PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
#     PY="${JSTACK_PYTHON:-python3}"
#     . "$PLUGIN_ROOT/tests/lib/pin-plugin-root.sh"
#
# Sourced, never run. Expects PLUGIN_ROOT and PY to be set already, and exits
# the calling test if the pin does not take — a suite that cannot say which
# checkout it is answering about must not answer at all.
#
# PYTHONPATH alone is not enough: the pre-push gate hands these tests the
# host's venv, whose .pth does `sys.path.insert(0, ~/JStack/plugins/jstack)`,
# and position 0 outranks PYTHONPATH. lib/sitecustomize.py is imported after
# every .pth and does the real work; see lib/jstack_pin.py.

: "${PLUGIN_ROOT:?pin-plugin-root.sh: set PLUGIN_ROOT before sourcing}"
: "${PY:?pin-plugin-root.sh: set PY before sourcing}"

export PYTHONPATH="$PLUGIN_ROOT/tests/lib:$PLUGIN_ROOT${PYTHONPATH:+:$PYTHONPATH}"
# The pin dir is imported by every interpreter below; without this its
# __pycache__ lands inside the public checkout being tested.
export PYTHONDONTWRITEBYTECODE=1

# Call again after any later change to PYTHONPATH — a test that installs its
# own sitecustomize shadows lib/sitecustomize.py and has to carry the import
# itself, and this is what proves it did.
jstack_assert_pinned() {
    local py="${1:-$PY}" want got
    want="$(cd "$PLUGIN_ROOT" && pwd -P)/root.py"
    if ! got="$("$py" -c 'import os, root; print(os.path.realpath(root.__file__))' 2>&1)"; then
        echo "FAIL: $py cannot import root at all — $got" >&2
        return 1
    fi
    if [ "$got" != "$want" ]; then
        echo "FAIL: this suite is testing a different checkout." >&2
        echo "      import root  -> $got" >&2
        echo "      under test   -> $want" >&2
        echo "      Something ahead of tests/lib/sitecustomize.py is fronting" >&2
        echo "      another copy of the plugin (a .pth, or a shadowing" >&2
        echo "      sitecustomize of this test's own). Nothing below this line" >&2
        echo "      would be reporting on the tree you are pushing." >&2
        return 1
    fi
    return 0
}

jstack_assert_pinned || exit 1
