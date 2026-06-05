# JStack

A Claude Code marketplace + plugin for cross-machine agent workflows. Skills work on any machine that adopts the conventions; per-machine adapters at `~/Agents/bin/` plug in environment-specific behavior (terminal launch, follow-up filing, etc.) without forking the skill.

## Install

```bash
# Add the marketplace (one of these)
claude plugin marketplace add github:Jarvis-and-J/JStack    # from GitHub
claude plugin marketplace add ~/JStack                       # from a local clone

# Install the plugin
claude plugin install jstack@JStack

# Optional: install bundled rules into ~/.claude/rules/
# (Rules aren't auto-installed by the plugin system; this skill does it.)
/jstack:install-rules
```

## Update

```bash
claude plugin marketplace update JStack && claude plugin update jstack
```

## What's in the plugin

Skills (slash commands, namespaced as `/jstack:<name>`):

- `/jstack:active` — list or load in-progress items from `~/Agents/{Name}/active/`
- `/jstack:save` — file the current conversation as a new active item
- `/jstack:handoff` — hand off this session to a fresh terminal with context preserved
- `/jstack:install-rules` — symlink bundled rules into `~/.claude/rules/`

Bundled rules (staged at `plugins/jstack/rules-stage/`, installed via the skill above):

- `canvas`, `claude-md-editing`, `claude-sessions`, `code-review`, `execution-gates`, `ios-screens`, `ios-sheets`, `ios-style`, `rules`, `visual-assets`, `x-compound-tools`

Architecture docs (reference reading, not installed anywhere):

- `docs/agents-dashboard.md` — spec for a local agents dashboard
- `docs/post-session-review.md` — spec for an automatic post-session review pass

## Conventions

The skills assume:

1. **Agent root** — `~/Agents/{Name}/`
2. **Identity** — `~/Agents/{Name}/CLAUDE.md` (Claude Code walk-up auto-loads it)
3. **Cross-mode state** — `~/Agents/{Name}/state.md` (optional)
4. **In-progress items** — `~/Agents/{Name}/active/{slug}.md` (format defined in `save` skill)
5. **Sub-modes** — subdirectories of the agent root, same identity in a different context

If your machine has these, skills work out of the box.

## Per-machine adapters

OS-specific or org-specific behavior lives at `~/Agents/bin/`, NOT in the plugin. Each machine implements its own. Skills check for existence and degrade cleanly when an adapter isn't there.

### Required (for full functionality)

| Adapter | Used by | Signature |
|---|---|---|
| `~/Agents/bin/open-terminal-here` | `/jstack:handoff` | `<cwd> [extra-claude-args...]` — open a new terminal at cwd, run `claude` with extra args appended |

### Optional

| Adapter | Used by | Signature |
|---|---|---|
| `~/Agents/bin/file-followup` | `/jstack:save` | `<title> <body>` — file a follow-up reminder (Apple Reminders, todo file, Slack, whatever you wire up). Exit 0 = success. |

### Reference: macOS iTerm `open-terminal-here`

```bash
#!/usr/bin/env bash
CWD="$1"; shift
ARGS="$*"
osascript <<EOF
tell application "iTerm"
    activate
    create window with default profile
    tell current session of current window
        write text "cd \"$CWD\" && claude $ARGS"
    end tell
end tell
EOF
```

## What this plugin doesn't ship

Intentional exclusions to keep the plugin cross-domain:

- Daemons, dashboards, backend code (these are machine-specific; patterns go in `docs/`)
- Project-specific rules (anything that names a particular product, app, repo)
- Personal identity (owner name, agent personas, voice prose — those live on each machine)
- Credentials, secrets
- OS-tool integrations beyond the adapter contract
- Anything that only works on one OS without a documented adapter fallback

If a piece of knowledge depends on infra that doesn't exist on every adopting machine, it goes in `docs/` as an architecture spec — not in the skills.

## Repository layout

```
JStack/
├── .claude-plugin/
│   └── marketplace.json          # marketplace manifest (Claude Code reads this)
├── plugins/
│   └── jstack/
│       ├── .claude-plugin/
│       │   └── plugin.json       # plugin manifest
│       ├── skills/
│       │   ├── active/SKILL.md
│       │   ├── save/SKILL.md
│       │   ├── handoff/SKILL.md
│       │   └── install-rules/SKILL.md
│       └── rules-stage/          # rules waiting to be installed via /jstack:install-rules
│           ├── canvas.md
│           ├── claude-md-editing.md
│           └── ...
├── docs/                         # architecture docs (reference, not installed)
│   ├── agents-dashboard.md
│   └── post-session-review.md
└── README.md                     # this file
```

## Dogfood (verified)

This plugin was installed locally from `~/JStack` via:
```bash
claude plugin marketplace add ~/JStack
claude plugin install jstack@JStack
```
Both `claude plugin validate` calls returned `✔ Validation passed`. The install registered under user scope; commands available as `/jstack:*` after session restart.
