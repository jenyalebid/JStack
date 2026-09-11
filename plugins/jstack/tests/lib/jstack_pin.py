"""Make `import root` mean the tree THIS file ships in, whatever the interpreter prefers.

The pre-push gate runs jStack's own suite with JSTACK_PYTHON pointed at the
host's Infrastructure venv, and that venv carries a .pth:

    import os, sys; _p = os.path.expanduser("~/jStack/plugins/jstack")
    (_p in sys.path) or sys.path.insert(0, _p)

which is how the host's scheduler finds the plugin, and is not wrong. But
position 0 outranks PYTHONPATH, and /jstack:issue mandates a worktree for
every issue — so `import root` inside a test running from a worktree resolved
to the MAIN checkout instead. The false red was the harmless half: root.sh's
shipping-tree guard compares $PLUGIN_ROOT against a root.py living in another
tree, so the guard never fires and the assertion that it must fails. The false
GREEN is the half that matters — a change to root.py, repo_seat.py or
scheduler/* pushed from a worktree was gated against main's copy of those
files, and the gate said PASS about code nobody was pushing.

Two layers, because each one alone loses to something:

  · sys.path is reordered here — this tree first, every rival checkout of the
    same plugin dropped. .pth files execute while `site` is initialising and
    `sitecustomize` is imported after the last of them, so this gets the final
    word over the .pth. PYTHONPATH cannot: it is read before site runs.

  · a meta_path finder, because sys.path order is not final either. CPython
    prepends the script dir (or the cwd, for `-c`) to sys.path[0] AFTER site
    has run, so a test invoked from inside another checkout gets that checkout
    handed back at position 0 — the same bug wearing a different hat. A
    meta_path entry is consulted before any path entry at all, so nothing that
    arrives later can outrank it.

Self-locating on purpose: the tree it pins is the tree it ships in, so there
is no env var to lose across an `env -i` and nothing to keep in sync with the
test that reads it.
"""

import os
import sys
from importlib import machinery

#: This file is <PLUGIN_ROOT>/tests/lib/jstack_pin.py — three levels up.
PLUGIN_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _same_dir(a, b):
    try:
        return os.path.realpath(a) == os.path.realpath(b)
    except (OSError, ValueError):
        return False


def _is_rival_copy(entry):
    """A DIFFERENT checkout of this same plugin, by its top-level signature.

    Fronting PLUGIN_ROOT is enough to win `import root`. Dropping the rival is
    what closes the other half: a module deleted or renamed in the tree being
    pushed but still present in the other one would keep importing from over
    there, and the suite would report green on a file the push does not have.
    """
    if not entry or _same_dir(entry, PLUGIN_ROOT):
        return False
    return (os.path.isfile(os.path.join(entry, "root.py"))
            and os.path.isfile(os.path.join(entry, "repo_seat.py"))
            and os.path.isdir(os.path.join(entry, "scheduler")))


class _PinnedTreeFinder:
    """Answer for this tree's own top-level modules, ahead of every path entry.

    Deliberately narrow. It sits directly in front of PathFinder and never in
    front of the builtin and frozen importers, it declines submodules (a
    package already carries the tree it was loaded from in its __path__), and
    it declines a directory with no loader — `tests/`, `bin/` and `docs/` are
    folders, not this package's modules, and claiming them as namespace
    packages would shadow whatever else a test legitimately imports by those
    names. Everything it does not answer falls straight through.
    """

    __jstack_pin__ = True

    @classmethod
    def find_spec(cls, fullname, path=None, target=None):
        if path is not None:
            return None
        spec = machinery.PathFinder.find_spec(fullname, [PLUGIN_ROOT], target)
        if spec is None or spec.loader is None:
            return None
        return spec


def pin():
    """PLUGIN_ROOT first on sys.path and first in front of PathFinder.

    Idempotent: every interpreter started under this PYTHONPATH runs it,
    including the ones the code under test spawns.
    """
    kept = [p for p in sys.path
            if not _same_dir(p, PLUGIN_ROOT) and not _is_rival_copy(p)]
    sys.path[:] = [PLUGIN_ROOT] + kept

    if any(getattr(f, "__jstack_pin__", False) for f in sys.meta_path):
        return
    at = len(sys.meta_path)
    for i, finder in enumerate(sys.meta_path):
        if finder is machinery.PathFinder:
            at = i
            break
    sys.meta_path.insert(at, _PinnedTreeFinder)


pin()
