# JStack

Cross-machine Claude Code skills for agent workflows. Install on any machine that uses the `~/Agents/{Name}/` convention. Skills are environment-aware via per-machine adapter scripts — same plugin behaves richly where adapters are wired, minimally where they aren't.

## What this gives you

Four slash commands (all namespaced as `/jstack:*`):

| Command | What it does |
|---|---|
| `/jstack:active` | List active items for the current agent, or load one to resume |
| `/jstack:save` | File the current conversation as an active item under the agent's `active/` |
| `/jstack:handoff` | Hand off the session to a fresh terminal with context preserved |
| `/jstack:install-rules` | Symlink the 11 bundled rules into `~/.claude/rules/` |

Plus 11 path-scoped rule files (Claude Code auto-loads them by glob match after install). And two architecture docs in `docs/` for building larger systems (agents dashboard, post-session review).

---

## Setup (run these exactly)

### 1. Verify prerequisites

```bash
claude --version          # need 2.x or later
which git
```

If `claude` is missing, install Claude Code first (`brew install --cask claude-code` on macOS).

### 2. Register the marketplace and install the plugin

```bash
claude plugin marketplace add github:jenyalebid/JStack
claude plugin install jstack@JStack
```

Verify:

```bash
claude plugin list   # should show jstack@JStack as enabled
```

### 3. Set up the agent root convention

JStack skills assume agents live under `~/Agents/{Name}/`. Create at least one agent dir before using the skills:

```bash
mkdir -p ~/Agents/{YourAgentName}/active
cat > ~/Agents/{YourAgentName}/CLAUDE.md <<'EOF'
# {YourAgentName}

(your agent identity here — what this agent does, voice, durable rules)
EOF
```

The walk-up will auto-load this CLAUDE.md whenever a session runs inside `~/Agents/{YourAgentName}/` or any of its subdirectories.

### 4. (Optional) Install the bundled rules

After restarting Claude Code so the plugin loads:

```
/jstack:install-rules
```

Confirms and symlinks 11 rules into `~/.claude/rules/` (canvas, claude-md-editing, claude-sessions, code-review, execution-gates, ios-screens, ios-sheets, ios-style, rules, visual-assets, x-compound-tools). Skips files that already exist; pass `--force` to overwrite.

### 5. (Optional but recommended) Write the per-machine adapters

JStack skills check for two adapter scripts at `~/Agents/bin/`. If they exist, skills use them for richer behavior. If they don't, skills degrade cleanly to base behavior.

```bash
mkdir -p ~/Agents/bin
```

#### Adapter A — `~/Agents/bin/open-terminal-here`

Used by `/jstack:handoff` to open a new Claude Code terminal at a given directory.

**Contract:** `~/Agents/bin/open-terminal-here <cwd> [extra-claude-args...]` — open a new terminal window at `<cwd>` and run `claude` with the extra args appended.

**Reference implementation (macOS + iTerm):**

```bash
#!/usr/bin/env bash
# ~/Agents/bin/open-terminal-here
# JStack adapter — open a new iTerm window at $1, run claude with $2..N appended.
set -euo pipefail
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

**Reference implementation (Linux + gnome-terminal):**

```bash
#!/usr/bin/env bash
set -euo pipefail
CWD="$1"; shift
gnome-terminal --working-directory="$CWD" -- claude "$@"
```

**Reference implementation (macOS + Terminal.app, no iTerm needed):**

```bash
#!/usr/bin/env bash
set -euo pipefail
CWD="$1"; shift
ARGS="$*"
osascript <<EOF
tell application "Terminal"
    activate
    do script "cd \"$CWD\" && claude $ARGS"
end tell
EOF
```

After writing, make executable:

```bash
chmod +x ~/Agents/bin/open-terminal-here
```

#### Adapter B — `~/Agents/bin/file-followup`

Used by `/jstack:save` to pair each new active item with a follow-up notification (so you don't lose track of it). Optional — if absent, `/jstack:save` just files the active doc.

**Contract:** `~/Agents/bin/file-followup <title> <body>` — file a follow-up reminder. Exit 0 = success.

**Reference implementation (Apple Reminders via macOS):**

```bash
#!/usr/bin/env bash
# ~/Agents/bin/file-followup
# JStack adapter — file follow-ups into the "Follow-ups" Apple Reminders list.
set -euo pipefail
TITLE="$1"
BODY="$2"
osascript <<EOF
tell application "Reminders"
    set targetList to list "Follow-ups"
    make new reminder at end of targetList with properties {name:"$TITLE", body:"$BODY"}
end tell
EOF
```

(Adjust `"Follow-ups"` to whichever Apple Reminders list you use.)

**Reference implementation (plain text todo file):**

```bash
#!/usr/bin/env bash
set -euo pipefail
echo "- [ ] $1 — $2" >> ~/todo.md
```

**Reference implementation (Slack via webhook):**

```bash
#!/usr/bin/env bash
set -euo pipefail
curl -s -X POST -H 'Content-Type: application/json' \
    --data "{\"text\":\"*$1*\n$2\"}" \
    "$SLACK_FOLLOWUP_WEBHOOK"
```

After writing, make executable:

```bash
chmod +x ~/Agents/bin/file-followup
```

### 6. Verify end-to-end

Restart Claude Code (so plugin + adapters are picked up), then in a session inside an agent directory:

```bash
cd ~/Agents/{YourAgentName}
claude
```

In the session, run:

```
/jstack:active
```

Should respond with either an empty active list or your existing items. If it errors with "not inside an agent tree," check that `~/Agents/{YourAgentName}/CLAUDE.md` exists.

---

## How the skills work (so you can predict behavior)

### `/jstack:active [n|last|oldest]`

- No arg: lists every `*.md` under `~/Agents/{Name}/active/`, sorted by `filed:` date ascending. Up to 3 items.
- Numeric arg: loads that item (1 = oldest) and briefs on its Goal / Where I am now / Next moves / Reference.
- `last` / `oldest`: aliases.

### `/jstack:save [slug] [--title "..."] [--paused] [--resume "..."]`

Reads the current conversation, distills it into an active doc, writes to `~/Agents/{Name}/active/{slug}.md` with this frontmatter:

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
1. If `~/Agents/{Name}/state.md` exists with a `## Active items` section, appends a one-liner pointer there.
2. If `~/Agents/bin/file-followup` exists, calls it with `<title>` and `<body>` (the body includes a one-line "why" + path to the active doc).
3. Confirms with a one-line receipt.

### `/jstack:handoff [focus]`

1. Walks this conversation, writes a `handoff-context.md` to the current working directory with Current Work / In Progress / Still To Do / Key Decisions / Context sections.
2. Shows the summary.
3. Calls `~/Agents/bin/open-terminal-here "$(pwd)" --append-system-prompt-file handoff-context.md`. If the adapter doesn't exist, prints instructions for opening the new session manually.

### `/jstack:install-rules [--copy] [--force]`

Symlinks every `.md` in the plugin's `rules-stage/` directory into `~/.claude/rules/`. Default mode is symlink (edits to the source file affect the live rule). `--copy` makes independent local copies. `--force` overwrites existing files.

---

## Update

```bash
claude plugin marketplace update JStack
claude plugin update jstack
```

After updating, if new rules were added you may want to re-run `/jstack:install-rules`. Existing symlinks already track the new content automatically.

---

## Uninstall

```bash
claude plugin uninstall jstack
claude plugin marketplace remove JStack
```

Remove any rule symlinks manually (only those still pointing into the plugin cache):

```bash
for f in ~/.claude/rules/*.md; do
    if [ -L "$f" ] && readlink "$f" | grep -q "JStack/jstack"; then rm "$f"; fi
done
```

Adapters at `~/Agents/bin/` are your files — leave or delete as you wish.

---

## Convention summary

JStack skills assume:

1. **Agent root** — `~/Agents/{Name}/`
2. **Identity** — `~/Agents/{Name}/CLAUDE.md` (auto-loaded by walk-up)
3. **Cross-mode state** — `~/Agents/{Name}/state.md` (optional; if present, `save` mirrors to its `## Active items` section)
4. **In-progress items** — `~/Agents/{Name}/active/{slug}.md` (format defined above)
5. **Sub-modes** — subdirectories of the agent root, same identity in a different context (walk-up handles inheritance)
6. **Per-machine adapters** — `~/Agents/bin/{open-terminal-here, file-followup}` (optional, enable richer behavior)

If these match your machine, JStack works out of the box. If not, adjust the agent root path in your own CLAUDE.md walk-up — skills follow the walk-up's agent directory.

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
│   ├── .claude-plugin/plugin.json         # plugin manifest
│   ├── skills/                            # the four slash commands
│   │   ├── active/SKILL.md
│   │   ├── save/SKILL.md
│   │   ├── handoff/SKILL.md
│   │   └── install-rules/SKILL.md
│   └── rules-stage/                       # rules waiting to be installed via /jstack:install-rules
│       └── *.md
├── docs/                                  # architecture specs (not installed)
└── README.md                              # this file
```

---

## For a model setting this up

If you're a Claude session being told to set this up on a fresh machine, execute steps 1-6 above in order. Steps 1-4 are mechanical; step 5 (writing adapters) requires choosing which reference implementation matches the machine's OS and preferred reminder backend. After step 6 returns a successful `/jstack:active` listing, JStack is fully installed and verified.

If `/jstack:install-rules` would overwrite anything important on the target machine, ask the user first (default behavior is to skip existing files, so this is only relevant with `--force`).
