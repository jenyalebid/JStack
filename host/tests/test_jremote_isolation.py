"""The host package stands on its own, or it is not a host.

jRemote's trust story is that this package is source a user can read: the app
is closed, the host is open, and anyone who wants to know what happens to
their data can look. A reader who takes that seriously will ask the obvious
follow-up — does this actually run on *my* machine, or only on the one it was
written on? Every answer to that lives here and in `test_jremote_standalone`.

`test_jremote_standalone` proves the package *imports* with the embedding
tree removed. This file proves it never asks for that tree at call time
either, which an import probe cannot see.

Machine-specific behaviour goes through the profile seam (`hostenv.profile()`).
A feature that needs a fact about one deployment adds a profile answer — never
an import of a private module, never a literal.
"""

import re
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "jstack_host"


def test_the_package_never_reaches_for_an_embedding_hosts_own_modules():
    """A call-time preference (`try: from lib import x` / a "lib.x" string
    handed to an importer) passes the import probe on a machine that happens
    to have `lib`, and still ships a dependency no user's machine can satisfy.
    The router and server both carried exactly that shape once; this pins the
    retirement."""
    pat = re.compile(r"\bfrom lib[. ]|\bimport lib\b|[\"']lib\.")
    hits = []
    for f in sorted(PKG.glob("*.py")):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if pat.search(line):
                hits.append(f"{f.name}:{i}: {line.strip()[:80]}")
    assert not hits, (
        "the package references an embedding host's `lib` tree — route the "
        "fact through the profile seam instead:\n" + "\n".join(hits))


def test_no_module_resolves_a_path_by_counting_parents():
    """`parents[N]` is a constant that keeps working right up until the package
    moves, and then silently picks a directory that merely exists.

    This package was two levels inside a larger tree for its whole life, so
    five modules walked `parents[2]` to find the root. After the move each of
    those resolved somewhere real and wrong — a compose shim that wasn't
    there, an APNs key directory that would have been created empty. Those
    answers belong to `hostenv`, which is the one module allowed to know where
    anything is.
    """
    pat = re.compile(r"parents\[\d+\]")
    hits = []
    for f in sorted(PKG.glob("*.py")):
        if f.name == "hostenv.py":
            continue          # the seam itself; that is its job
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if pat.search(line):
                hits.append(f"{f.name}:{i}: {line.strip()[:80]}")
    assert not hits, (
        "a module counts directory levels to find something — ask `hostenv` "
        "for it instead, so the answer moves when the package does:\n"
        + "\n".join(hits))
