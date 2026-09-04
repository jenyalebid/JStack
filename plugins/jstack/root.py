"""root — the one declaration a JStack install derives its tree from.

"Where is everything" used to be answered in six places: SCHEDULER_HOME, an
`agent_root` in scheduler.json, the same default restated independently in
three hooks, and absolute machine paths in review.json. Each was a separate
chance to disagree, and on a second machine they did — half the tools resolved
into a private tree that machine never had. This module is the single answer:
one root, everything below it by structure.

    $JSTACK_ROOT/
    ├── Agents/         agent workspaces; a seat is Agents/<id>/<seat>/
    ├── Systems/        Systems/<slug>/SYSTEM.md
    ├── Config/         scheduler.json, schedule.json, review.json
    ├── State/          runtime state, runs, locks
    ├── Logs/           timeline db, tool logs
    └── Credentials/    tokens (never in the checkout)

Callers hand in their own already-parsed config dict. This module never reads
a config file itself: reading one would make it a second opinion about which
file is authoritative, which is the exact disease being cured.

Import discipline: this file imports nothing from the package and nothing
beyond the stdlib. It is loaded two ways — as a sibling (`import root` with
the plugin dir on sys.path, which is how scheduler/* reaches it) and by
standalone bin/ scripts that insert the plugin dir themselves — and anything
it imported from the tree would close a cycle on the first module that
imports it back.

Every function resolves on every call. A daemon lives for weeks and the test
suite changes the environment between cases; a module constant captured at
import answers with the environment of a process start nobody remembers —
that is exactly how five tests once errored at setup instead of running.
Recomputing is a handful of dict lookups; correctness beats a saved syscall.

Results are `expanduser()`-ed but never `resolve()`-d: a symlinked workspace
is legitimate, and resolving it changes the path a session reports as its cwd.
"""

from __future__ import annotations

import os
from pathlib import Path


def _shipping_tree_roots() -> "tuple[Path, ...]":
    """The trees no JStack data dir may resolve into: the checkout shipping this file.

    Same rule as `scheduler/config.py::_shipping_tree_roots`, and deliberately
    a copy rather than an import. config.py must keep working on an older
    install where this module is absent, and importing config here would hand
    root.py the very cycle it exists to stay free of — so both files carry the
    rule, each self-contained. If the rule ever changes, change it in both.

    This package is distributed inside a PUBLIC git repository. A Config/,
    State/, Logs/ or Credentials/ dir rooted in that checkout puts a live
    token one `git add -A` from being published — so resolving there is an
    error, never a fallback. Forbidden: this file's own directory always (a
    plugin-cache install has no .git, but is still wiped on update), plus the
    nearest enclosing git checkout. The walk stops before $HOME so a user
    whose home directory is itself a repo (dotfiles) keeps ~ usable.
    """
    here = Path(__file__).resolve().parent
    roots = [here]
    home = Path.home()
    for candidate in here.parents:
        if candidate == home or candidate == candidate.parent:
            break
        if (candidate / ".git").exists():
            if candidate not in roots:
                roots.append(candidate)
            break
    return tuple(roots)


def _refuse_shipping_tree(path: Path, env_var: str) -> Path:
    """Refuse a data dir inside the shipping checkout, loudly.

    Failing beats silently picking somewhere else: a secret written to a
    wrong-but-safe place is recoverable; one written into a public working
    tree is not. The refusal is the same whether the value came from the
    environment, a config file, or the derivation — the repo is not a valid
    home even on purpose.
    """
    probe = Path(os.path.expanduser(str(path))).resolve()
    for tree in _shipping_tree_roots():
        if probe == tree or tree in probe.parents:
            raise RuntimeError(
                f"{env_var}={path} resolves inside the checkout that ships "
                f"this package ({tree}) — a public git tree. Config, state, "
                f"logs and credentials must live outside it: set JSTACK_ROOT "
                f"(or the {env_var} override) to a directory outside the "
                f"repository."
            )
    return path


def root(cfg: "dict|None" = None) -> Path:
    """The install root: $JSTACK_ROOT, else the caller's cfg["root"], else $HOME.

    No walk-up marker search, no probing — one declaration, stated or
    defaulted. `cfg` is the caller's own already-parsed config file, so there
    is exactly one opinion about which file is authoritative: the caller's.
    """
    val = os.environ.get("JSTACK_ROOT")
    if not val and cfg:
        val = cfg.get("root")
    if val:
        return Path(str(val)).expanduser()
    return Path.home()


def _derived(cfg: "dict|None", env_var: str, cfg_key: str, leaf: str,
             guarded: bool, base=None) -> Path:
    """One derived dir: its env override, else its cfg key, else base()/leaf.

    `base` defaults to root() — the top-level dirs hang straight off it. A dir
    nested inside another one passes that other one's accessor, so it follows
    its parent's override instead of re-deriving from the root: with
    JSTACK_LOGS_DIR pointed elsewhere, the timeline goes with the logs rather
    than staying behind in a Logs/ nobody is writing to.
    """
    val = os.environ.get(env_var)
    if not val and cfg:
        val = cfg.get(cfg_key)
    if val:
        path = Path(str(val)).expanduser()
    else:
        path = (root(cfg) if base is None else base(cfg)) / leaf
    if guarded:
        _refuse_shipping_tree(path, env_var)
    return path


def agents_dir(cfg: "dict|None" = None) -> Path:
    """Where agent workspaces live.

    The cfg key is the EXISTING `agent_root`: installs already declare it, and
    renaming a key every install has set breaks them for the sake of symmetry.
    Not guarded — a user may legitimately keep agent workspaces inside a repo.
    """
    return _derived(cfg, "JSTACK_AGENTS_DIR", "agent_root", "Agents", guarded=False)


def systems_dir(cfg: "dict|None" = None) -> Path:
    """Systems/<slug>/SYSTEM.md lives here. Not guarded — docs, not secrets."""
    return _derived(cfg, "JSTACK_SYSTEMS_DIR", "systems_root", "Systems", guarded=False)


def config_dir(cfg: "dict|None" = None) -> Path:
    return _derived(cfg, "JSTACK_CONFIG_DIR", "config_dir", "Config", guarded=True)


def state_dir(cfg: "dict|None" = None) -> Path:
    return _derived(cfg, "JSTACK_STATE_DIR", "state_dir", "State", guarded=True)


def logs_dir(cfg: "dict|None" = None) -> Path:
    return _derived(cfg, "JSTACK_LOGS_DIR", "logs_dir", "Logs", guarded=True)


def credentials_dir(cfg: "dict|None" = None) -> Path:
    return _derived(cfg, "JSTACK_CREDENTIALS_DIR", "credentials_dir",
                    "Credentials", guarded=True)


def timeline_dir(cfg: "dict|None" = None) -> Path:
    """Where timeline.db lives — one answer, because it is one database.

    Three tools wrote this default independently: bin/log_event (the writer),
    bin/msg (which files an exchange into both seats' timelines) and the
    session-end engine (which exports it to every spawn and reads the row count
    back to prove a write happened). Three literals agreeing is not one
    location; it is three locations that happen to collide. Move any one of
    them and the tools do not fail — they succeed against different files, and
    the timeline silently forks: mail written to one db, sessions to another,
    the engine watching a third for growth that is happening somewhere else.
    """
    return _derived(cfg, "JSTACK_TIMELINE_DIR", "timeline_dir", "Timeline",
                    guarded=True, base=logs_dir)


# ----------------------------------------------------------------- agents
#
# Six places in three repos used to disagree about what an agent is. This is
# the one definition: an agent is a directory directly under agents_dir() that
# either carries a CLAUDE.md itself, or has at least one immediate subdirectory
# that does — the second case being a seat, Agents/<id>/<seat>/CLAUDE.md.
# A directory with neither is not an agent; it is some other folder that
# happens to live there.


def _has_claude_md(d: Path) -> bool:
    return (d / "CLAUDE.md").is_file()


def is_agent(d: Path) -> bool:
    """CLAUDE.md at the top, or at least one non-dot seat subdir carrying one.

    Public because a caller that has already resolved its own agents dir needs
    to ask the question about a directory it names itself, without handing over
    a cfg that JSTACK_AGENTS_DIR could then outrank.
    """
    if _has_claude_md(d):
        return True
    try:
        return any(
            child.is_dir() and not child.name.startswith(".")
            and _has_claude_md(child)
            for child in d.iterdir()
        )
    except OSError:
        return False


def agents(cfg: "dict|None" = None) -> "list[str]":
    """Sorted ids of every agent under agents_dir(). Dot-entries are skipped.

    A missing agents_dir() answers [] — a machine mid-install is a normal
    state, not an error.
    """
    try:
        children = list(agents_dir(cfg).iterdir())
    except OSError:
        return []
    return sorted(
        d.name for d in children
        if d.is_dir() and not d.name.startswith(".") and is_agent(d)
    )


def _fold(name: str) -> str:
    """`work-ops`, `work_ops` and `workops` are one agent to anyone typing an
    id from memory; only the directory on disk knows which spelling it chose."""
    return name.lower().replace("-", "").replace("_", "")


def resolve_agent(agent_id: str, cfg: "dict|None" = None) -> "Path|None":
    """The workspace dir for `agent_id`, or None when no such agent exists.

    Matching, first hit wins: exact directory name, then case-insensitive,
    then with `-`/`_` folded away. When two on-disk names fold together the
    answer is deterministic — the exact-case hit wins outright, otherwise the
    first candidate in sort order.

    Never returns a path that does not exist. Joining {agent_root}/{agent_id}
    blind hands a nonexistent directory to a spawn, which fails later and
    further away than the typo that caused it; None lets the caller say so at
    the point of the mistake, naming the id that missed.
    """
    if not agent_id:
        return None
    ids = agents(cfg)
    if not ids:
        return None
    base = agents_dir(cfg)
    if agent_id in ids:
        return base / agent_id
    for candidates in (
        [i for i in ids if i.lower() == agent_id.lower()],
        [i for i in ids if _fold(i) == _fold(agent_id)],
    ):
        if candidates:
            return base / sorted(candidates)[0]
    return None


def seat_of(path, cfg: "dict|None" = None, base=None) -> "tuple[str|None, str|None]":
    """(agent, submode) for a directory inside an agent, else (None, None).

    submode is the rest of the path below the agent, "/"-joined and lowered —
    per-dir seats, so `social/chat` is its own seat, distinct from `chat` — or
    "chat" at the agent root itself.

    The gate is `agents()`'s definition of an agent, and that is the point.
    Three callers each carried their own copy of it, all gating on a CLAUDE.md
    at the agent's top level. On a machine whose agents each keep one that is
    invisible; on a machine laid out as Agents/<id>/<seat>/CLAUDE.md with
    nothing at the top, every one of them refused to name the seat the session
    was sitting in — mail could not say who sent it, and the tools read as
    simply not working there. One definition, asked once, cannot drift apart
    into three answers again.
    """
    if path is None:
        return None, None
    # `base` lets a caller that already resolved the agents dir pass it
    # straight in, so its answer cannot differ from the one it just computed.
    base = agents_dir(cfg) if base is None else Path(base)
    try:
        rel = Path(path).resolve().relative_to(base.resolve())
    except (ValueError, OSError):
        return None, None
    # `is_agent` directly, not `resolve_agent`: the name here was read off the
    # path, so it needs no fuzzy matching, and routing through a lookup would
    # re-resolve the agents dir and could answer about a different one.
    if not rel.parts or not is_agent(base / rel.parts[0]):
        return None, None
    submode = "/".join(p.lower() for p in rel.parts[1:]) or "chat"
    return rel.parts[0].lower(), submode


def seats(agent_id: str, cfg: "dict|None" = None) -> "list[str]":
    """Sorted seat names for an agent that resolves — its immediate non-dot
    subdirectories carrying their own CLAUDE.md — else []."""
    ws = resolve_agent(agent_id, cfg)
    if ws is None:
        return []
    try:
        children = list(ws.iterdir())
    except OSError:
        return []
    return sorted(
        c.name for c in children
        if c.is_dir() and not c.name.startswith(".") and _has_claude_md(c)
    )
