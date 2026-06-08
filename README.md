# JStack

Cross-machine Claude Code skills for agent workflows. Built around the `{agent_root}/{Name}/` workspace convention, where `agent_root` is **configured per machine** (no hardcoded paths). Adapters ship inside the plugin and self-detect the environment, so the same plugin behaves richly everywhere with zero per-machine scripting.

## What this gives you

Five slash commands (all namespaced as `/jstack:*`):

| Command | What it does |
|---|---|
| `/jstack:active` | List active items for the current agent, or load one to resume |
| `/jstack:save` | File the current conversation as an active item under the agent's `active/` |
| `/jstack:handoff` | Hand off the session to a fresh terminal with context preserved |
| `/jstack:push` | Commit + push this session's edits (default), or `all` pending changes grouped by unit of work |
| `/jstack:install-rules` | Symlink the 16 bundled rules into `~/.claude/rules/` |

Plus 16 path-scoped rule files (Claude Code auto-loads them by glob match after install), two bundled `bin/` adapters (terminal-open + follow-up filer), and two architecture docs in `docs/` for building larger systems (agents dashboard, post-session review).

---

## Setup

### 1. Verify prerequisites

```bash
claude --version          # need 2.x or later
which git
```

If `claude` is missing, install Claude Code first (`brew install --cask claude-code` on macOS).

### 2. Register the marketplace and install the plugin

```bash
claude plugin marketplace add jenyalebid/JStack
claude plugin install jstack@JStack
```

Verify:

```bash
claude plugin list   # should show jstack@JStack as enabled
```

### 3. Configure the agent root (and optional follow-up backend)

JStack reads its paths from **plugin config** — no path is hardcoded. Three options (declared in `plugin.json` `userConfig`):

| Key | Type | Default | Meaning |
|---|---|---|---|
| `agent_root` | directory | `~/Agents` | Directory that contains your per-agent workspaces (`{Name}/CLAUDE.md`, `{Name}/active/`). |
| `followup_backend` | string | `none` | How `/jstack:save` files a reminder: `none` \| `todo` \| `reminders` \| `slack`. |
| `followup_target` | string | _(empty)_ | For `todo`: a file path (default `<agent_root>/followups.md`). For `reminders`: the macOS Reminders list name (default `Follow-ups`). |

Set them in Claude Code's plugin config UI, or directly in `settings.json`:

```jsonc
// ~/.claude/settings.json  (or .claude/settings.json for a project)
{
  "pluginConfigs": {
    "jstack@JStack": {
      "options": {
        "agent_root": "/Users/you/Desktop/MyStuff/Agents",
        "followup_backend": "reminders",
        "followup_target": "Follow-ups"
      }
    }
  }
}
```

If you leave `agent_root` at the default, JStack uses `~/Agents/`.

### 4. Create at least one agent workspace

```bash
mkdir -p "$AGENT_ROOT"/{YourAgentName}/active     # $AGENT_ROOT = whatever you set above
cat > "$AGENT_ROOT"/{YourAgentName}/CLAUDE.md <<'EOF'
# {YourAgentName}

(your agent identity here — what this agent does, voice, durable rules)
EOF
```

The walk-up auto-loads this CLAUDE.md whenever a session runs inside that agent dir or any subdirectory.

### 5. (Optional) Install the bundled rules

After restarting Claude Code so the plugin loads:

```
/jstack:install-rules
```

Confirms and symlinks 16 rules into `~/.claude/rules/` (canvas, claude-md-editing, claude-sessions, code-review, execution-gates, ios-charts, ios-forms, ios-lists, ios-modifiers, ios-screens, ios-services, ios-sheets, ios-style, rules, visual-assets, x-compound-tools). Skips files that already exist; pass `--force` to overwrite. The source is `${CLAUDE_PLUGIN_ROOT}/rules-stage/` — resolved automatically.

### 6. Verify end-to-end

Restart Claude Code, then in a session inside an agent directory:

```bash
cd "$AGENT_ROOT"/{YourAgentName}
claude
```

In the session, run `/jstack:active`. It should list your active items (or report an empty list). If it says you're "not inside an agent tree," check that `agent_root` is set correctly and the agent's `CLAUDE.md` exists.

---

## Adapters (bundled — usually nothing to do)

JStack ships two adapter scripts in the plugin's `bin/`, which Claude Code auto-adds to the Bash `PATH` while the plugin is enabled. Skills call them as bare commands.

### `open-terminal-here` — used by `/jstack:handoff`

Opens a new Claude Code terminal at a directory. Self-detects the terminal:

- **macOS:** iTerm if installed, else Terminal.app
- **Linux:** gnome-terminal → konsole → x-terminal-emulator → xterm
- **Windows:** Windows Terminal (`wt.exe`)

**Contract:** `open-terminal-here <cwd> [extra-claude-args...]`. To override on a machine, put your own `open-terminal-here` earlier in `PATH`.

### `file-followup` — used by `/jstack:save`

Files a follow-up reminder, routed by the `followup_backend` config:

- `none` (default) — silent no-op
- `todo` — appends `- [ ] <title> — <body>` to `followup_target` (default `<agent_root>/followups.md`)
- `reminders` — adds to the macOS Reminders list named in `followup_target` (default `Follow-ups`)
- `slack` — POSTs to the webhook in env var `SLACK_FOLLOWUP_WEBHOOK`

**Contract:** `file-followup <title> <body>`, exit 0 = filed or intentionally skipped.

---

## How the skills work (so you can predict behavior)

`{root}` below = the configured `agent_root`.

### `/jstack:active [n|last|oldest]`

- No arg: lists every `*.md` under `{root}/{Name}/active/`, sorted by `filed:` date ascending. Up to 3 items.
- Numeric arg: loads that item (1 = oldest) and briefs on its Goal / Where I am now / Next moves / Reference.
- `last` / `oldest`: aliases.

### `/jstack:save [slug] [--title "..."] [--paused] [--resume "..."]`

Reads the current conversation, distills it into an active doc, writes to `{root}/{Name}/active/{slug}.md` with this frontmatter:

```yaml
---
title: <title>
slug: <slug>
status: in-progress | paused
filed: YYYY-MM-DD
last_touched: YYYY-MM-DD HH:MM
lead: <agent name>
resume_trigger: <only if paused>
---
```

Then:
1. If `{root}/{Name}/state.md` exists with a `## Active items` section, appends a one-liner pointer there.
2. Calls `file-followup` with `<title>` and `<body>` (body includes a one-line "why" + path to the active doc). With `followup_backend: none` this is a silent no-op.
3. Confirms with a one-line receipt.

### `/jstack:handoff [focus]`

1. Walks this conversation, writes a `handoff-context.md` to the current working directory with Current Work / In Progress / Still To Do / Key Decisions / Context sections.
2. Shows the summary.
3. Calls `open-terminal-here "$(pwd)" --append-system-prompt-file handoff-context.md`. If no terminal can be opened, prints instructions for opening the new session manually.

### `/jstack:install-rules [--copy] [--force]`

Symlinks every `.md` in `${CLAUDE_PLUGIN_ROOT}/rules-stage/` into `~/.claude/rules/`. Default mode is symlink (edits to the source affect the live rule, and updates track automatically). `--copy` makes update-independent local copies. `--force` overwrites existing files.

---

## Update

```bash
claude plugin marketplace update JStack
claude plugin update jstack
```

Symlinked rules track new content automatically. The plugin install path changes on version bumps (old version cleaned up ~7 days later), so if symlinks ever go stale, re-run `/jstack:install-rules --force`.

---

## Uninstall

```bash
claude plugin uninstall jstack
claude plugin marketplace remove JStack
```

Remove any rule symlinks still pointing into a jstack install:

```bash
for f in ~/.claude/rules/*.md; do
    [ -L "$f" ] && readlink "$f" | grep -q "jstack/rules-stage" && rm "$f"
done
```

---

## Convention summary

1. **Agent root** — `{agent_root}/{Name}/` (configured, not hardcoded)
2. **Identity** — `{agent_root}/{Name}/CLAUDE.md` (auto-loaded by walk-up)
3. **Cross-mode state** — `{agent_root}/{Name}/state.md` (optional; if present, `save` mirrors to its `## Active items` section)
4. **In-progress items** — `{agent_root}/{Name}/active/{slug}.md` (format defined above)
5. **Sub-modes** — subdirectories of the agent root, same identity in a different context (walk-up handles inheritance)
6. **Adapters** — bundled in the plugin's `bin/`, configured via `followup_backend` / `followup_target`

Set `agent_root` to wherever your workspaces live and JStack works out of the box on any machine.

---

## Architecture docs (reference reading, not installed)

For building larger systems beyond the four shipped skills:

- `docs/agents-dashboard.md` — full spec for building a local FastAPI dashboard that surfaces every agent + sub-agent + session with categorization, tagging, history. Pattern-only — you implement against your environment.
- `docs/post-session-review.md` — architecture spec for automatic post-session review pass that reconciles state files with what just happened and surfaces dropped threads.

Both are docs (not skills) because the implementations are environment-specific. Read them when building those systems.

---

## Repository layout

```
JStack/
├── .claude-plugin/marketplace.json        # marketplace manifest
├── plugins/jstack/
│   ├── .claude-plugin/plugin.json         # plugin manifest (declares userConfig)
│   ├── skills/                            # the four slash commands
│   │   ├── active/SKILL.md
│   │   ├── save/SKILL.md
│   │   ├── handoff/SKILL.md
│   │   └── install-rules/SKILL.md
│   ├── bin/                               # bundled adapters (auto-added to PATH)
│   │   ├── open-terminal-here
│   │   └── file-followup
│   └── rules-stage/                       # rules installed via /jstack:install-rules
│       └── *.md
├── docs/                                  # architecture specs (not installed)
└── README.md                              # this file
```

---

## For a model setting this up

If you're a Claude session setting this up on a fresh machine, execute steps 1–6 in order. All steps are mechanical now: there are no adapters to hand-write (they're bundled and self-detecting). The only choices are the `agent_root` path and, optionally, the `followup_backend`. After step 6 returns a successful `/jstack:active` listing, JStack is installed and verified.

If `/jstack:install-rules` would overwrite anything important on the target machine, ask the user first (default behavior skips existing files, so this only matters with `--force`).
