"""The shipped host is a product, and a product carries nothing of ours.

jRemote's trust story is that the host package is source a user can read: the
app is closed, the host is open, and anyone who wants to know what happens to
their data can look. That story dies the moment the source reads like somebody
else's machine — an org name in a docstring, a home directory in a path, an
example id that is obviously a real deployment. So the rule is absolute and
enforced here rather than remembered: no org token, anywhere in anything the
payload ships.

The product rule behind it: every jRemote feature is designed as a public
JStack feature. Machine-specific behaviour goes through the profile seam
(`hostenv.profile()`), and the org's own profile lives outside the package
(`lib/jremote_profile.py`), supplied at runtime by the convention module.
A new feature that needs an org fact adds a profile answer, never an import,
never a literal.
"""

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[1]
PKG = INFRA / "dashboard" / "jremote"

# What ships: the package (build_jremote_payload.sh copies dashboard/jremote/*.py)
# and the installer artifacts beside it.
SHIPPED = sorted(PKG.glob("*.py")) + [
    INFRA / "scripts" / "jremote_host_README.txt",
    INFRA / "scripts" / "jremote_host_install.command",
]

# Word-bounded so `jj` cannot hide in an identifier, case-insensitive so prose
# cannot smuggle it. `boss` stays off this list deliberately: the lowercase
# wire token (`"boss"` in the pad-owner protocol) is app API surface, and
# capital-B prose is already gone — adding it would ban the protocol constant.
FORBIDDEN = re.compile(r"jarvis|j&j|jandj|jenya|\bjj\b", re.IGNORECASE)


def test_nothing_the_payload_ships_names_the_org():
    hits = []
    for f in SHIPPED:
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if FORBIDDEN.search(line):
                hits.append(f"{f.relative_to(INFRA)}:{i}: {line.strip()[:80]}")
    assert not hits, (
        "org tokens in shipped source — move the fact behind the profile seam "
        "or reword the prose:\n" + "\n".join(hits))


def test_the_package_never_reaches_for_the_embedding_hosts_own_modules():
    """`test_jremote_standalone` proves the package imports with `lib` blocked
    — but a call-time preference (`try: from lib import x` / a "lib.x" string
    handed to an importer) passes that probe on this machine and still ships a
    dependency on a tree no user has. The router and server both carried
    exactly that shape once; this pins the retirement."""
    pat = re.compile(r"\bfrom lib[. ]|\bimport lib\b|[\"']lib\.")
    hits = []
    for f in sorted(PKG.glob("*.py")):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if pat.search(line):
                hits.append(f"{f.relative_to(INFRA)}:{i}: {line.strip()[:80]}")
    assert not hits, (
        "the shipped package references the embedding host's `lib` tree — "
        "route the fact through the profile seam instead:\n" + "\n".join(hits))


def test_the_shipped_file_list_is_what_the_build_script_ships():
    """If the payload build ever ships more than `dashboard/jremote/*.py` plus
    the two installer files, this suite must widen with it — a new artifact
    that never entered SHIPPED is a hole in the whole check."""
    script = (INFRA / "scripts" / "build_jremote_payload.sh").read_text()
    assert 'dashboard/jremote/*.py' in script, (
        "build_jremote_payload.sh no longer copies dashboard/jremote/*.py — "
        "update SHIPPED here to match what it ships now")
