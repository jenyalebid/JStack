#!/usr/bin/env python3
"""Print one line per repo under the code root: agent<TAB>workspace<TAB>repo_path.

Ownership comes from the agent registry's per-agent `repos` list, matched on the
directory name or the origin URL. An unowned repo prints "-" for its agent.

Usage: resolve-repos.py <agent_root> <repo_root> <registry_path>
"""
import glob, json, os, subprocess, sys

agent_root, repo_root, registry = sys.argv[1:4]


def norm(s):
    # Acme_iOS and Acme-iOS are the same repo
    return os.path.basename(s.rstrip("/")).lower().replace("_", "-")


repos = sorted({os.path.dirname(g) for g in glob.glob(os.path.join(repo_root, "*", ".git"))})

owners = {}
try:
    for key, a in json.load(open(registry)).items():
        if isinstance(a, dict):
            for r in (a.get("repos") or []):
                owners[norm(r)] = (key, a.get("workspace", ""))
except (FileNotFoundError, ValueError):
    pass


def origin(r):
    try:
        u = subprocess.run(["git", "-C", r, "remote", "get-url", "origin"],
                           capture_output=True, text=True).stdout.strip()
        return norm(u[:-4] if u.endswith(".git") else u)
    except Exception:
        return ""


for repo in repos:
    hit = next((owners[k] for k in (norm(repo), origin(repo)) if k in owners), ("-", ""))
    print(f"{hit[0]}\t{hit[1]}\t{repo}")
