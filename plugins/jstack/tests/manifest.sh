#!/usr/bin/env bash
# JStack live test — does JStack describe itself correctly?
#
# Every fact below is stated in two places: once on disk, once in a file a
# human maintains (systems.json, README.md, the two plugin manifests). The
# hand-written copy is the one that rots, silently, and the rot only surfaces
# when somebody asks — which is the failure this test exists to end.
#
# What it counts, it counts FROM DISK, then compares the restatement to it.
# A restatement that cannot be parsed is a FAILURE, never a pass: a check that
# cannot look must raise, because returning "nothing found" reports "no drift"
# when it means "could not see".
#
# Exit 0 = every restatement matches the tree. Exit 1 = at least one is stale.

set -u

PLUGIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REPO_ROOT="$(cd "$PLUGIN_ROOT/../.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "FAIL: python3 not on PATH" >&2
  exit 1
fi

python3 - "$PLUGIN_ROOT" "$REPO_ROOT" <<'PY'
import json, os, re, subprocess, sys

plugin_root, repo_root = sys.argv[1], sys.argv[2]
fails, passes = [], []

def ok(label, detail=""):
    passes.append(label)
    print(f"  ok   {label}" + (f" — {detail}" if detail else ""))

def bad(label, detail):
    fails.append(label)
    print(f"  FAIL {label} — {detail}")

def read_json(path):
    with open(path) as fh:
        return json.load(fh)

# ── 0. what "on disk" means here ─────────────────────────────────────────────
# The tree this gate audits is the one a clone gets, so it counts what git
# tracks, not what the filesystem holds. The checkout is shared: several
# sessions are mid-edit at any moment, and a raw directory listing sees their
# untracked work-in-progress. That work is invisible to every consumer of the
# repo, so it cannot be a stale restatement — counting it only blocks the push
# of whoever pushes next, for files that are not theirs to register.
#
# A staged deletion still lists, and that is correct: the index is what is
# about to be pushed.
def tracked(subdir):
    res = subprocess.run(["git", "-C", plugin_root, "ls-files", "-z", "--", subdir],
                         capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or f"git ls-files failed on {subdir}")
    return [p for p in res.stdout.split("\0") if p]

# A check that cannot look must raise: falling back to a raw listing here would
# report "no drift" when it means "could not see git".
try:
    for _probe in ("skills", "tests", "bin", "rules-stage"):
        tracked(_probe)
except Exception as exc:
    print(f"  FAIL git tracking — cannot list tracked files: {exc}")
    print("\nFAIL — the tree could not be read; nothing was checked.")
    sys.exit(1)

# ── 1. version parity across the two plugin manifests ────────────────────────
# Each engine reads its own manifest. Two files, one fact: whichever is not
# bumped reports a stale version to its CLI (`codex plugin list` showed 0.46.0
# against a 0.48.0 tree for two days).
print("version parity")
claude_manifest = os.path.join(plugin_root, ".claude-plugin", "plugin.json")
codex_manifest = os.path.join(plugin_root, ".codex-plugin", "plugin.json")
versions = {}
for label, path in (("claude", claude_manifest), ("codex", codex_manifest)):
    try:
        versions[label] = read_json(path)["version"]
    except Exception as exc:
        bad(f"{label} manifest", f"unreadable: {exc}")
if len(versions) == 2:
    if versions["claude"] == versions["codex"]:
        ok("manifests agree", versions["claude"])
    else:
        bad("manifests disagree",
            f"claude={versions['claude']} codex={versions['codex']} — bump both")

# ── 2. systems.json vs the tree ──────────────────────────────────────────────
print("systems.json registry")
systems_path = os.path.join(plugin_root, "systems.json")
try:
    systems = read_json(systems_path)["systems"]
except Exception as exc:
    bad("systems.json", f"unreadable: {exc}")
    systems = None

if systems is not None:
    # Entries nest: a system's subsystems carry their own code paths and their
    # own tests (push → session-files, agent-inbox → inbox-guard). Flatten first,
    # or every subsystem test reads as an orphan and every nested path as absent.
    def flatten(entries):
        for entry in entries:
            yield entry
            yield from flatten(entry.get("subsystems") or [])

    systems = list(flatten(systems))

    # 2a. every skill dir on disk is registered, and every registered skill exists
    on_disk = {p.split("/")[1] for p in tracked("skills") if p.endswith("/SKILL.md")}
    registered = set()
    for entry in systems:
        for path in entry.get("code", []):
            m = re.match(r"skills/([^/]+)/", path)
            if m:
                registered.add(m.group(1))
    missing = sorted(on_disk - registered)
    phantom = sorted(registered - on_disk)
    if missing:
        bad("unregistered skills",
            f"on disk, absent from systems.json: {', '.join(missing)}")
    if phantom:
        bad("phantom skills",
            f"named in systems.json, no SKILL.md on disk: {', '.join(phantom)}")
    if not missing and not phantom:
        ok("skills registered", f"{len(on_disk)} skills, all accounted for")

    # 2b. every declared test resolves and runs; every test script is declared
    declared, broken = set(), []
    for entry in systems:
        test = entry.get("test") or {}
        if test.get("type") != "script":
            continue
        rel = test.get("path", "")
        abs_path = os.path.join(plugin_root, rel)
        if not os.path.exists(abs_path):
            broken.append(f"{entry.get('id')} → {rel} (missing)")
        elif not os.access(abs_path, os.X_OK):
            broken.append(f"{entry.get('id')} → {rel} (not executable)")
        else:
            declared.add(os.path.basename(rel))
    if broken:
        bad("declared tests", "; ".join(broken))
    else:
        ok("declared tests resolve", f"{len(declared)} distinct scripts")

    scripts = {os.path.basename(p) for p in tracked("tests") if p.endswith(".sh")}
    # this script proves the registry; it needs no registry entry of its own
    orphans = sorted(scripts - declared - {"manifest.sh"})
    if orphans:
        bad("orphan test scripts",
            f"on disk, no systems.json entry runs them: {', '.join(orphans)}")
    else:
        ok("no orphan tests", f"{len(scripts)} scripts, all declared")

    # 2c. every code/config path an entry names still exists
    dangling = []
    for entry in systems:
        for field in ("code", "config", "docs"):
            for path in entry.get(field, []):
                # ~ = host path outside the plugin, {install} = documented
                # placeholder resolved per host. Neither is ours to resolve.
                if path.startswith(("~", "http")) or "{" in path:
                    continue
                if not os.path.exists(os.path.join(plugin_root, path.rstrip("/"))):
                    dangling.append(f"{entry.get('id')}.{field}: {path}")
    if dangling:
        bad("dangling paths", "; ".join(dangling[:8])
            + (f" (+{len(dangling) - 8} more)" if len(dangling) > 8 else ""))
    else:
        ok("registry paths resolve")

# ── 3. README counts vs the tree ─────────────────────────────────────────────
# The README states counts in prose. A count is a derived fact, so it is
# checkable — and an unparseable claim fails rather than passing quietly.
print("README claims")
readme_path = os.path.join(repo_root, "README.md")
try:
    readme = open(readme_path).read()
except Exception as exc:
    bad("README", f"unreadable: {exc}")
    readme = None

if readme is not None:
    adapters = {os.path.basename(p) for p in tracked("bin")
                if not os.path.basename(p).startswith(("__", "."))}

    m = re.search(r"(\d+) bundled `bin/` adapters \(([^)]*)\)", readme)
    if not m:
        bad("bin/ adapter claim",
            "no parseable '<N> bundled `bin/` adapters (…)' sentence in README "
            "— reword to that shape or this check is blind")
    else:
        claimed_n = int(m.group(1))
        claimed = set(re.findall(r"`([^`]+)`", m.group(2)))
        if claimed_n != len(adapters):
            bad("bin/ adapter count",
                f"README says {claimed_n}, disk has {len(adapters)}")
        elif claimed != adapters:
            bad("bin/ adapter names",
                f"README omits {sorted(adapters - claimed)}, "
                f"invents {sorted(claimed - adapters)}")
        else:
            ok("bin/ adapters", f"{len(adapters)}, names match")

    rules = {os.path.basename(p) for p in tracked("rules-stage") if p.endswith(".md")}
    rule_claims = set(int(n) for n in re.findall(r"(\d+) (?:bundled rules|path-scoped rule files)", readme))
    if not rule_claims:
        bad("rule count claim",
            "no parseable '<N> path-scoped rule files' / '<N> bundled rules' "
            "in README — reword to that shape or this check is blind")
    elif rule_claims != {len(rules)}:
        bad("rule count",
            f"README says {sorted(rule_claims)}, disk has {len(rules)}")
    else:
        ok("rule count", str(len(rules)))

print()
if fails:
    print(f"FAIL — {len(fails)} stale restatement(s), {len(passes)} ok")
    for f in fails:
        print(f"  · {f}")
    sys.exit(1)
print(f"PASS — {len(passes)} checks, JStack matches its own description")
PY
