#!/usr/bin/env bash
# JStack live test — is the tree free of the org it grew up in?
#
# This plugin was built inside one private operation before it shipped as a
# public product, and its history is squashed: whatever identity is in the
# tree when a release cuts is permanent. This gate is what keeps the names of
# that operation — its people, its principal, its closed-source siblings, its
# machine paths — from riding back in through a docstring, a fixture, or a
# pasted example.
#
# One obvious term list below; extend it there. Lowercase `boss` / `@boss` is
# NOT on it: that is a shipped wire literal (the refused address, the
# `--from boss` convention) — only the capitalized persona is banned. The
# allowlist is per (file, term), each entry carrying its reason; a new hit in
# a new file never passes silently.
#
# Exit 0 = no org identity in any tracked file (names checked too).
# Exit 1 = at least one hit, named file:line: term with the offending line.

set -u

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$PLUGIN_ROOT/../.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "FAIL: python3 not on PATH" >&2
  exit 1
fi

python3 - "$REPO_ROOT" <<'PY'
import re, subprocess, sys

repo_root = sys.argv[1]

# ── the term list ────────────────────────────────────────────────────────────
# label → (pattern, flags). Word-bounded so the public owner username (which
# merely CONTAINS two of these) never matches. Extend here, nowhere else.
TERMS = [
    ("jremote",   r"\bjremote\b",   re.I),  # closed-source sibling product
    ("jarvis",    r"\bjarvis\b",    re.I),  # org agent / machine account (covers its /Users path)
    ("lynda",     r"\blynda\b",     re.I),  # org agent
    ("mario",     r"\bmario\b",     re.I),  # org agent
    ("maggie",    r"\bmaggie\b",    re.I),  # org agent
    ("brian",     r"\bbrian\b",     re.I),  # org agent
    ("ted",       r"\bted\b",       re.I),  # org agent
    ("tim",       r"\btim\b",       re.I),  # org agent
    ("junior",    r"\bjunior\b",    re.I),  # org agent
    ("jenya",     r"\bjenya\b",     re.I),  # the principal's given name
    ("lebid",     r"\blebid\b",     re.I),  # the principal's family name
    ("Boss",      r"\bBoss\b",      0),     # the org's persona for its principal — capitalized form only
    ("jandj",     r"\bjandj\b",     re.I),  # the org's GitHub account prefix
    ("J&J",       r"J&J",           0),     # the org's short name
    ("auto-work", r"\bauto-work\b", re.I),  # the org's project-board name
    ("org-infra-path", r"Operations/Infrastructure", 0),  # the org's private repo path
]
COMPILED = [(label, re.compile(pat, flags)) for label, pat, flags in TERMS]

# ── the allowlist ────────────────────────────────────────────────────────────
# (repo-relative path, term label) → why this file may hold this term.
# Narrow on purpose: the same term in any OTHER file still fails.
ALLOW = {
    ("plugins/jstack/githooks/pre-commit", "jandj"):
        "the commit-identity allowlist must name the accounts it allows; "
        "this is the public noreply address stamped on every commit anyway",
    ("plugins/jstack/tests/commit-identity.sh", "jandj"):
        "fixture proving the real allowlisted account passes the identity gate",
    ("plugins/jstack/bin/place-issue", "auto-work"):
        "shipped default board name — renaming the default reroutes every "
        "existing install; load-bearing, reported not scrubbed",
    ("plugins/jstack/tests/place-issue.sh", "auto-work"):
        "fixtures proving routing and tie-breaks against the shipped default board",
    ("plugins/jstack/tests/file-issue.sh", "auto-work"):
        "fixture board title matching the shipped default place-issue routes to",
}

SELF = "plugins/jstack/tests/scrub.sh"  # holds the term list; cannot scan itself

res = subprocess.run(["git", "-C", repo_root, "ls-files", "-z"],
                     capture_output=True, text=True)
if res.returncode != 0:
    # A check that cannot look must raise: a raw directory walk would scan
    # other sessions' untracked work-in-progress, which never ships.
    print(f"FAIL — cannot list tracked files: {res.stderr.strip()}")
    sys.exit(1)
paths = [p for p in res.stdout.split("\0") if p and p != SELF]

hits, allowed_used, scanned = [], set(), 0
for rel in paths:
    # File NAMES carry identity too (a term list can't reach a path otherwise).
    for label, rx in COMPILED:
        if rx.search(rel) and (rel, label) not in ALLOW:
            hits.append((rel, 0, label, "(in the file's path)"))
    try:
        with open(f"{repo_root}/{rel}", "rb") as fh:
            raw = fh.read()
    except OSError:
        continue  # tracked but deleted in this worktree — nothing ships from it
    if b"\0" in raw:
        continue  # binary — not a carrier of prose identity
    scanned += 1
    for lineno, line in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
        for label, rx in COMPILED:
            if not rx.search(line):
                continue
            if (rel, label) in ALLOW:
                allowed_used.add((rel, label))
                continue
            hits.append((rel, lineno, label, line.strip()[:120]))

# An allowlist entry nothing matches is rot — it would mask a future hit in a
# file that no longer holds one for a reason anyone remembers.
stale = sorted(set(ALLOW) - allowed_used)
for rel, label in stale:
    hits.append((rel, 0, label, "(stale allowlist entry — term no longer present; delete it)"))

if hits:
    print(f"FAIL — {len(hits)} org-identity hit(s) in {scanned} tracked files:")
    for rel, lineno, label, excerpt in hits:
        where = f"{rel}:{lineno}" if lineno else rel
        print(f"  {where}: term '{label}' — {excerpt}")
    sys.exit(1)

print(f"PASS — {scanned} tracked files scanned, no org identity "
      f"({len(allowed_used)} allowlisted carriers, each with its reason)")
PY
