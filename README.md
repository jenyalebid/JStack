# JStack

A small, intentional collection of Claude Code skills, rules, and system architecture docs that work across machines and domains.

The promise: edit a skill or rule here, push, pull on another machine, both updated. No render layer, no token substitution — files drop in as-is.

## What's in here

- `skills/` — actual skill files (`.md`). Install: symlink or copy into `~/.claude/commands/` on each machine.
- `rules/` — actual rule files (`.md`). Install: symlink or copy into `~/.claude/rules/` on each machine.
- `systems/` — architecture docs for systems too coupled to a specific machine's infra to ship as code. Reader builds against the pattern.

## Conventions

JStack assumes these on every adopting machine. Skills depend on them.

1. **Agent root** — `~/Agents/{Name}/`
2. **Identity** — `~/Agents/{Name}/CLAUDE.md` (Claude Code walk-up auto-loads on any session inside the tree)
3. **Cross-mode state** — `~/Agents/{Name}/state.md` (optional)
4. **In-progress items** — `~/Agents/{Name}/active/{slug}.md` (one .md per item, frontmatter format defined in `skills/active.md`)
5. **Sub-modes** — subdirectories of the agent root. Same identity, different operational context. Walk-up handles inheritance.

## Per-machine helper scripts

Anything OS-specific (terminal launch, editor open, OS notification) is NOT shipped in JStack. JStack defines the contract; each machine implements.

Conventional location: `~/Agents/bin/`. Each machine ships its own implementations. NOT in this repo.

### Required helpers

| Script | Signature | What it does |
|---|---|---|
| `open-terminal-here` | `<cwd> [extra-claude-args...]` | Opens a new terminal window at `cwd`, runs `claude` with the extra args appended. macOS example uses iTerm + AppleScript; Linux gnome-terminal; Windows wt.exe. |

### Optional helpers (skills check for existence)

| Script | Signature | Used by |
|---|---|---|
| `open-file` | `<path>` | Editor-open skills (none yet — placeholder) |
| `notify` | `<title> <body>` | Skills that want OS notifications (none yet — placeholder) |

If an optional helper doesn't exist on a given machine, the skill that wants it skips that step cleanly — no error.

## Per-machine config (parameters)

Non-OS parameters that vary per machine live in `~/Agents/config.local.json`, NOT in this repo. Skills read it where they need it. Empty keys = skill skips that behavior.

```json
{
  "owner": "<your name or label used in skill prose>",
  "default_editor": "code",
  "reminders_backend": null
}
```

Keep this file out of the repo. Each machine sets its own.

## Install

On any machine that adopts JStack:

```bash
git clone <jstack-remote> ~/JStack
ln -s ~/JStack/skills ~/.claude/commands/jstack
ln -s ~/JStack/rules  ~/.claude/rules/jstack
# write your ~/Agents/bin/open-terminal-here
# write your ~/Agents/config.local.json
```

The directory-name approach (`~/.claude/commands/jstack/`) keeps JStack-shipped skills separate from machine-local ones — easy to see what's vendored vs custom. Claude Code picks them up either way.

Update: `cd ~/JStack && git pull`. Done.

## What's NOT in here

JStack is intentionally light. Things that DON'T belong:

- Daemons, dashboards, backend code (these are machine-specific implementations — patterns go in `systems/`)
- Project-specific rules (anything that names a particular product, app, repo)
- Personal identity (owner name, agent personas, voice prose — those live on each machine)
- Credentials, configs with secrets
- Reminder-list names, OS-tool tool integrations, daemon-tool integrations
- Things that only work on one OS without falling back gracefully

If a piece of knowledge depends on infra that doesn't exist on every adopting machine, it goes in `systems/` as an architecture doc — not in `skills/` or `rules/`.

## v1 contents

- `skills/active.md` — list/load in-progress items
- `skills/save.md` — file the current conversation as an active item
- `skills/handoff.md` — hand off this session to a fresh terminal with context preserved
- `rules/` — 12 generic rules covering Claude Code editing patterns, code review, execution gates, iOS UI patterns
- `systems/agents-dashboard.md` — architecture for a local agents dashboard
- `systems/post-session-review.md` — architecture for an automatic post-session review pass
