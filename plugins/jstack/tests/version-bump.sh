#!/usr/bin/env bash
# JStack live test — can the change that just landed actually reach an install?
#
# A plugin is installed by version. The CLI caches the tree under
# ~/.claude/plugins/cache/<market>/<plugin>/<version>/ and `plugin update`
# compares numbers, not contents — so a runtime file changed on main without a
# version bump is invisible: every machine keeps running the cached copy and
# `update` answers "already at the latest version". The work is pushed, green,
# and reaches nobody, with no signal anywhere that anything is stale.
#
# That is not hypothetical. Five commits — a root fix, a doctor fix, a scrub
# fix, the app-install path — sat on main behind an unbumped 0.59.0 while every
# installed copy ran the old files.
#
# So: any commit that touches the shipped plugin outside tests/ must be
# accompanied by a version bump. tests/ is excluded because it does not ship
# behavior — nothing an installed copy runs comes from there.
#
# Exit 0 = the version on disk is newer than every shipped change under it.
# Exit 1 = shipped files moved since the bump; names the commits.

set -u

# Main is what installs consume — the cache-stranding failure this gate exists
# for can only happen there. The pre-push hook reads the refs being pushed and
# sets JSTACK_PUSH_TO_MAIN; a push that never touches refs/heads/main cannot
# strand anyone and passes free, which is what lets work land on branches
# without minting a release per commit. Standalone runs (variable unset) keep
# the full check: asking "is main consistent?" by hand should always answer.
if [ "${JSTACK_PUSH_TO_MAIN:-1}" = "0" ]; then
  echo "  ok   version-bump gate — not a push to main, bump not required"
  exit 0
fi

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$PLUGIN_ROOT/../.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "FAIL: python3 not on PATH" >&2
  exit 1
fi

python3 - "$PLUGIN_ROOT" "$REPO_ROOT" <<'PY'
import json, os, subprocess, sys

plugin_root, repo_root = sys.argv[1], sys.argv[2]

MANIFEST = "plugins/jstack/.claude-plugin/plugin.json"
SHIPPED = "plugins/jstack"
# Excluded from "shipped": nothing an installed copy runs comes out of these.
EXCLUDED = (":(exclude)plugins/jstack/tests", ":(exclude)plugins/jstack/__pycache__")


def git(*args):
    res = subprocess.run(["git", "-C", repo_root, *args],
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or f"git {' '.join(args)} failed")
    return res.stdout


def version_at(commit):
    """The manifest version as of one commit, or None if unparseable there."""
    try:
        return json.loads(git("show", f"{commit}:{MANIFEST}")).get("version")
    except Exception:
        return None


# ── can this check look at all? ──────────────────────────────────────────────
# This gate reads history. Where there is no history to read it says so and
# stands down, rather than reporting a green it cannot see: a shallow clone or
# an unpacked tarball genuinely cannot answer the question, and this is a
# maintainer-side push gate — it runs where the full clone is.
try:
    git("rev-parse", "--git-dir")
except Exception as exc:
    print(f"  SKIP version-bump gate — no git history here ({exc})")
    sys.exit(0)

if git("rev-parse", "--is-shallow-repository").strip() == "true":
    print("  SKIP version-bump gate — shallow clone, the bump commit is not in history")
    sys.exit(0)

try:
    with open(os.path.join(plugin_root, ".claude-plugin", "plugin.json")) as fh:
        current = json.load(fh).get("version")
except Exception as exc:
    print(f"  FAIL version-bump gate — cannot read {MANIFEST}: {exc}")
    sys.exit(1)

if not current:
    print(f"  FAIL version-bump gate — {MANIFEST} declares no version")
    sys.exit(1)

# ── find the commit that set the version now on disk ─────────────────────────
# Walk the manifest's own history newest-first; the OLDEST commit still
# carrying this version is the bump. Keyed on the version VALUE, not on the
# file being touched, so editing a description does not read as a release.
history = [c for c in git("log", "--format=%H", "--", MANIFEST).split() if c]
bump = None
for commit in history:
    if version_at(commit) == current:
        bump = commit
    else:
        break

if bump is None:
    # The version on disk is in no commit — the bump is staged or uncommitted,
    # which is exactly what this gate wants to see happen.
    print(f"  ok   version-bump gate — {current} is a pending bump, not yet committed")
    sys.exit(0)

# ── anything shipped move since? ─────────────────────────────────────────────
out = git("log", "--format=%h %s", f"{bump}..HEAD", "--", SHIPPED, *EXCLUDED)
offenders = [line for line in out.splitlines() if line.strip()]

if not offenders:
    print(f"  ok   version-bump gate — {current} covers every shipped change "
          f"(bump {bump[:7]})")
    sys.exit(0)

print(f"  FAIL version-bump gate — {len(offenders)} shipped commit(s) since {current} was cut:")
for line in offenders:
    print(f"         {line}")
print()
print("  Every one of these is cached-over on installed machines: the CLI keys the")
print(f"  cache by version, so `plugin update` answers \"already at {current}\" and the")
print("  old files keep running. Bump the version in BOTH manifests and push:")
print("    plugins/jstack/.claude-plugin/plugin.json")
print("    plugins/jstack/.codex-plugin/plugin.json")
sys.exit(1)
PY
