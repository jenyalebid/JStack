"""repo_seat — the seat of the agent that owns a directory of code.

A seat is normally a directory under {agent_root}: the session's cwd names it,
and everything keyed to a seat (the timeline injected on entry, the entry
written on exit, auto-memory) follows from that. A session started by an IDE
never gets that choice — the editor fixes cwd to the checked-out repo, so an
agent's own work done from Xcode lands in Acme-iOS/ and resolves to no seat at
all: it starts cold and leaves no record. Disposable worktrees fall in the same
hole.

The ownership answer already exists. The agent registry maps each agent to the
repos it owns — the same map /jstack:day-audit dispatches on — so a repo can be
resolved back to a seat instead of being treated as nobody's.

Resolution, first hit wins:
  1. git toplevel of the directory (a subdirectory of a checkout resolves as
     the checkout), else the directory itself
  2. basename against every registry entry's `repos`, normalized
  3. `remote.origin.url` basename, normalized — this is what carries a
     worktree, which shares its checkout's origin but not its name
  4. longest normalized prefix of the basename on a `-` boundary, which carries
     a `<Repo>-issue-42` worktree that has no origin of its own

Normalized = case folded, `_` and `-` equivalent, any leading `owner/` and a
trailing `.git` dropped — so `Acme_iOS`, `Acme-iOS` and
`git@github.com:org/Acme_iOS.git` are one name.

The seat an IDE session joins is the agent's own registered `workspace`, read
back as a seat under {agent_root} — so the work joins the agent's one running
memory instead of forking a second history nobody thinks to read. A registry
entry with no usable `workspace` falls back to the default cockpit seat "chat".
Entries marked `"active": false` are skipped: an archived agent should not
start claiming sessions.
"""

# Both hooks import this module and macOS ships /usr/bin/python3 at 3.9, where
# a bare `str | None` annotation is a TypeError at import — the whole hook dies
# before its own never-block guard exists. Deferring annotation evaluation is
# what lets the file state its types and still load everywhere the hooks run.
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

try:
    import root as _root
except ImportError:
    # An older install ships this module without root.py — a supported state,
    # not an error. Everything this module answers ends up inside a session
    # hook, so degrading to the literal pre-root default beats raising.
    _root = None

DEFAULT_SEAT = "chat"


def agents_root(cfg: "dict|None" = None) -> Path:
    """The agent-workspace root — root.py's one derivation when it is present.

    Kept here so every consumer of this module resolves the root the same way
    instead of each spelling its own default; on an older install without
    root.py the literal pre-root behaviour holds: cfg["agent_root"], else
    ~/Agents."""
    if _root is not None:
        return _root.agents_dir(cfg)
    return Path(str((cfg or {}).get("agent_root") or "~/Agents")).expanduser()


def _norm(name: str) -> str:
    """A repo name reduced to its comparable form. Registries spell the same
    repo `Acme_iOS`, `Acme-iOS`, or as a full clone URL; all three are one."""
    n = str(name).strip().rstrip("/")
    for sep in ("/", ":"):
        n = n.rsplit(sep, 1)[-1]
    if n.endswith(".git"):
        n = n[:-4]
    return n.lower().replace("_", "-")


def _git(directory: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(directory), *args],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None if out.returncode == 0 else None


def load_registry(path: Path) -> dict:
    """{agent: entry} for every active agent in the registry. Keys starting
    with "_" are the registry's own metadata, not agents."""
    try:
        data = json.loads(Path(path).expanduser().read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(k).lower(): v for k, v in data.items()
        if not str(k).startswith("_") and isinstance(v, dict)
        and v.get("active", True)
    }


def _seat_of(entry: dict, agent: str, root: Path) -> tuple[str, str]:
    """(agent-dir-name lowered, submode) for a registry entry — its `workspace`
    read back as a seat under {agent_root}, which is where that agent's own
    cockpit sessions already file. No usable workspace → the default seat."""
    ws = entry.get("workspace")
    if ws:
        try:
            rel = Path(str(ws)).expanduser().resolve().relative_to(root.resolve())
        except (ValueError, OSError):
            rel = None
        if rel is not None and rel.parts:
            submode = "/".join(p.lower() for p in rel.parts[1:]) or DEFAULT_SEAT
            return rel.parts[0].lower(), submode
    return agent, DEFAULT_SEAT


def owner_of(directory, registry: dict) -> tuple[str | None, str | None, str | None]:
    """(agent, repo-basename, how) for the registry entry owning `directory`,
    or (None, None, None). `how` names the rule that matched, for --json
    callers and for saying why a directory did or didn't resolve."""
    d = Path(directory).expanduser()
    try:
        d = d.resolve()
    except OSError:
        return None, None, None
    if not d.is_dir():
        return None, None, None

    top = _git(d, "rev-parse", "--show-toplevel")
    repo_dir = Path(top) if top else d
    base = _norm(repo_dir.name)

    owned: list[tuple[str, str]] = [
        (_norm(r), agent)
        for agent, entry in registry.items()
        for r in (entry.get("repos") or [])
    ]
    if not owned:
        return None, None, None

    for norm, agent in owned:
        if norm == base:
            return agent, repo_dir.name, "name"

    origin = _git(repo_dir, "config", "--get", "remote.origin.url")
    if origin:
        norm_origin = _norm(origin)
        for norm, agent in owned:
            if norm == norm_origin:
                return agent, repo_dir.name, "origin"

    # `<Repo>-issue-42` worktrees: same code, different directory, no origin of
    # their own when detached from the clone. Longest match wins so a repo whose
    # name prefixes another can't steal it.
    best: tuple[int, str] | None = None
    for norm, agent in owned:
        if base.startswith(norm) and len(base) > len(norm) and base[len(norm)] == "-":
            if best is None or len(norm) > best[0]:
                best = (len(norm), agent)
    if best:
        return best[1], repo_dir.name, "prefix"

    return None, None, None


def seat_for(directory, root: "Path|None" = None,
             registry_path=None) -> tuple[str | None, str | None]:
    """(agent, submode) for a session whose cwd is an owned repo, else
    (None, None). Callers use this only after the normal {agent_root}-relative
    resolution has come up empty — a real seat directory always wins.

    `root` (and the registry path derived from it) defaults through
    agents_root(), so a caller with no opinion of its own inherits the one
    derivation instead of restating a default."""
    if root is None:
        root = agents_root()
    if registry_path is None:
        registry_path = registry_path_for({}, root)
    registry = load_registry(registry_path)
    if not registry:
        return None, None
    agent, _repo, _how = owner_of(directory, registry)
    if agent is None:
        return None, None
    return _seat_of(registry[agent], agent, Path(root).expanduser())


def registry_path_for(cfg: dict, root: "Path|None" = None) -> Path:
    """Where the registry lives: `agent_registry` if the host set one, else the
    documented default of {agent_root}/agents.json."""
    p = cfg.get("agent_registry") or os.environ.get("JSTACK_AGENT_REGISTRY")
    if p:
        return Path(p).expanduser()
    return Path(root) / "agents.json" if root is not None else \
        agents_root(cfg) / "agents.json"
