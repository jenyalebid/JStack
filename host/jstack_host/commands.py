"""Enumerate the slash commands available to an agent, for jRemote autocomplete.

**This has to answer for the seat, not the agent.** The harness resolves a
slash command by walking UP from the session's own directory — nearest
`.claude/commands/<name>.md` wins, then the user-level dir (`bin/pict`,
`resolve_command`). So the palette on the phone is the seat's chain or it is
wrong, and it was wrong: a `ops/chat` thread listed `/create-agent`,
`/meta_review`, `/morning_brief`, `/ops_hygiene` — the four at the agent root —
and offered none of `/device`, `/distribute`, `/testflight`, `/sim`, `/gallery`,
`/asc-strip`, which are the six that seat actually has. A palette that lists
commands the session will refuse and hides the ones it would run is worse than
no palette; it is why this walks now.

Sources, in override order (later wins, so nearest wins):
  1. The user level, `~/.claude/`
  2. The agent root's `.claude/`, then every directory down to the seat itself

Both `commands/*.md` and `skills/<name>/SKILL.md` count at every level, the
user level included: a skill is invoked as `/{name}` exactly like a command,
and leaving them out hid all three of `ops/chat`'s. The user level counted
only its commands until 2026-09-02, which hid the ten Apple SDK skills in
`~/.claude/skills/` from every seat on the machine — they are invocable in any
session and appeared in no palette. Installed-plugin entries stay namespaced
(`/jstack:push`) and never override a local file of the same stem.

A plugin from a `directory` marketplace is read from that directory, not from
the versioned copy under `plugins/cache/` — see `plugin_paths.py`.

A command's name is `/{stem}`; its description is the frontmatter `description:`
if present, else the first meaningful line of the file.
"""

import json
from pathlib import Path

from . import plugin_paths
from .hostenv import split_id, workspace

_USER = Path.home() / ".claude"
_INSTALLED_PLUGINS = Path.home() / ".claude" / "plugins" / "installed_plugins.json"

# jStack caps a skill description at 140 chars, so a conformant one arrives whole
# rather than cut mid-word — the old 120 truncated /jstack:recall and /jstack:task.
_DESC_MAX = 140


def _describe(path: Path) -> str:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return ""
    # YAML frontmatter description
    if lines and lines[0].strip() == "---":
        for ln in lines[1:]:
            if ln.strip() == "---":
                break
            if ln.lower().startswith("description:"):
                return ln.split(":", 1)[1].strip().strip('"').strip("'")
    # else first meaningful line (skip headings, html, tables, fences)
    for ln in lines:
        s = ln.strip()
        if s and not s.startswith(("#", "---", "<", "|", "```")):
            return s
    return ""


def _plugin_name(root: Path) -> str:
    for p in (root / ".claude-plugin" / "plugin.json", root / "plugin.json"):
        try:
            return json.loads(p.read_text()).get("name", "")
        except (OSError, json.JSONDecodeError):
            continue
    return ""


def _plugin_commands() -> list[dict]:
    """Installed-plugin skills + commands, namespaced `/{plugin}:{name}` — the
    form Claude Code actually invokes (e.g. `/jstack:push`, `/superpowers:...`).

    Each plugin is read wherever `plugin_paths` says it lives, which for a
    `directory` marketplace is the working tree and not the frozen install."""
    out: list[dict] = []
    try:
        data = json.loads(_INSTALLED_PLUGINS.read_text())
    except (OSError, json.JSONDecodeError):
        return out
    live_roots = plugin_paths.live_marketplace_roots()
    for key, entries in data.get("plugins", {}).items():
        for entry in entries:
            ip = entry.get("installPath")
            root = plugin_paths.plugin_root(
                key, Path(ip) if ip else None, live_roots)
            if root is None:
                continue
            name = _plugin_name(root)
            if not name:
                continue
            skills = root / "skills"
            if skills.exists():
                for sk in sorted(skills.iterdir()):
                    md = sk / "SKILL.md"
                    if md.exists():
                        out.append({"name": f"/{name}:{sk.name}",
                                    "description": _describe(md)[:_DESC_MAX]})
            cmds = root / "commands"
            if cmds.exists():
                for f in sorted(cmds.glob("*.md")):
                    out.append({"name": f"/{name}:{f.stem}",
                                "description": _describe(f)[:_DESC_MAX]})
    return out


def _seat_chain(agent_id: str) -> list[Path]:
    """Agent root → … → the seat itself, the order the harness walks in
    reverse. An agent whose workspace can't be resolved contributes nothing,
    which leaves the global commands standing rather than erroring the palette.
    """
    base, _ = split_id(agent_id)
    try:
        root, seat = workspace(base).resolve(), workspace(agent_id).resolve()
    except KeyError:
        return []
    if root != seat and root not in seat.parents:
        return [root]
    chain = [root]
    for part in seat.relative_to(root).parts:
        chain.append(chain[-1] / part)
    return chain


def _local_entries(claude_dir: Path) -> list[tuple[str, Path]]:
    """`(name, file)` for one `.claude/` — its commands and its skills, both
    invoked as `/{stem}`."""
    out: list[tuple[str, Path]] = []
    cmds = claude_dir / "commands"
    if cmds.is_dir():
        out += [("/" + f.stem, f) for f in sorted(cmds.glob("*.md"))]
    skills = claude_dir / "skills"
    if skills.is_dir():
        for sk in sorted(p for p in skills.iterdir() if p.is_dir()):
            md = sk / "SKILL.md"
            if md.is_file():
                out.append(("/" + sk.name, md))
    return out


def list_commands(agent_id: str) -> list[dict]:
    entries: list[tuple[str, Path]] = []
    entries += _local_entries(_USER)     # the user level is a level like any other
    for d in _seat_chain(agent_id):
        entries += _local_entries(d / ".claude")

    seen: dict[str, dict] = {}
    for name, f in entries:                 # later wins — nearest the seat
        seen[name] = {"name": name, "description": _describe(f)[:_DESC_MAX]}
    for cmd in _plugin_commands():          # plugin skills/commands (namespaced)
        seen.setdefault(cmd["name"], cmd)
    return sorted(seen.values(), key=lambda c: c["name"])
