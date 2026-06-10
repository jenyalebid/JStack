# JStack

Cross-machine Claude Code skills for agent workflows. Built around the `{agent_root}/{Name}/` workspace convention, where `agent_root` is **configured per machine** (no hardcoded paths). Adapters ship inside the plugin and self-detect the environment, so the same plugin behaves richly everywhere with zero per-machine scripting.

## What this gives you

Six slash commands (all namespaced as `/jstack:*`):

| Command | What it does |
|---|---|
| `/jstack:active` | List active items for the current agent, or load one to resume |
| `/jstack:save` | File the current conversation as an active item under the agent's `active/` |
| `/jstack:handoff` | Hand off the session to a fresh terminal with context preserved |
| `/jstack:push` | Commit + push this session's edits (default), or `all` pending changes grouped by unit of work |
| `/jstack:install-rules` | Symlink the 19 bundled rules into `~/.claude/rules/` |
| `/jstack:post-session-review` | Review playbook the SessionEnd engine runs after every session (also manually invocable with a session id) |

Plus two **whole systems** that run themselves once installed:

- **Post-session review** — a SessionEnd hook spawns a validated review of every session that ends inside an agent workspace: reconciles `state.md` + `active/` with what actually happened, extracts dropped threads into follow-ups, logs timeline entries. Output is machine-validated (required sections, evidence floors, a timeline-grew gate); rejected output re-spawns once, persistent failure escalates. See **Post-session review + timeline** below.
- **Timeline log** — `bin/log_event` writes daily `{YYYY-MM-DD}.md` timeline files (the day's spine) with strict block format, chronological insertion, and pipeline-task consolidation.

And the supporting machinery: 19 path-scoped rule files (auto-load by glob after install), a **PreToolUse hook** that re-injects path-matched rules at edit time even when the file lives outside the session's launch tree, four bundled `bin/` adapters (`open-terminal-here`, `file-followup`, `log_event`, `session-review-spawn`), a `systems.json` registry where every bundled system declares a runnable test (`plugins/jstack/tests/*.sh` — run them any time), and per-system deep docs under `plugins/jstack/docs/systems/`.

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

Confirms and symlinks 19 rules into `~/.claude/rules/` (agent-state, canvas, claude-md-editing, claude-sessions, code-review, execution-gates, ios-charts, ios-design-ethos, ios-forms, ios-lists, ios-modifiers, ios-screens, ios-services, ios-sheets, ios-style, rules, timeline, visual-assets, x-compound-tools). Skips files that already exist; pass `--force` to overwrite. The source is `${CLAUDE_PLUGIN_ROOT}/rules-stage/` — resolved automatically.

### 6. Verify end-to-end

Restart Claude Code, then in a session inside an agent directory:

```bash
cd "$AGENT_ROOT"/{YourAgentName}
claude
```

In the session, run `/jstack:active`. It should list your active items (or report an empty list). If it says you're "not inside an agent tree," check that `agent_root` is set correctly and the agent's `CLAUDE.md` exists.

---

## Post-session review + timeline (the self-running systems)

Once the plugin is installed, the SessionEnd hook is live — but it only does anything when a session ends inside a reviewable agent workspace, so installing the plugin never spawns surprise reviews on a machine that isn't set up for it.

### What makes an agent reviewable

```
{agent_root}/{Name}/review/        ← this directory existing IS the opt-in
{agent_root}/{Name}/review/CLAUDE.md   (optional but recommended: agent-specific review glue,
                                        auto-loaded by walk-up when the review spawns there)
{agent_root}/{Name}/state.md       ← what the review reconciles (see the agent-state rule)
```

That's the whole setup for the default experience:

```bash
mkdir -p "$AGENT_ROOT"/{YourAgentName}/review
```

End a session inside that agent's tree → the engine resolves the owner, spawns `claude --print` from `review/` running `/jstack:post-session-review <session-id>`, validates the output, retries once on rejection. Reviews log to `~/.claude/jstack/review-state/session-review.log` by default.

### Timeline

The review (and anything else) writes the day's spine with the bundled CLI — it's on PATH for review spawns, or call it via the plugin cache:

```bash
log_event <agent> --at HH:MM "headline" [--detail "..."] [--pipeline-task repo#42]
```

Files land at `~/Logs/Timeline/{YYYY-MM-DD}.md` (`JSTACK_TIMELINE_DIR` overrides). Format spec + editorial bar: the `timeline` rule. The `agent-state` rule carries the state.md discipline (the review is the only writer; ≤50 lines, ≤10 per entry). Install both via `/jstack:install-rules`.

### Machine config (optional — defaults are fully portable)

`~/.claude/jstack/review.json` (env override: `JSTACK_REVIEW_CONFIG`). You only need it to change defaults — e.g. point `skill_invocation` at a richer host playbook, extend `required_sections` to that playbook's output contract, add host tool dirs to the spawned PATH, or wire `escalate_cmd` / `tg_classify_cmd` adapters. Full key reference: `plugins/jstack/docs/systems/post-session-review.md`. Model/budget defaults: opus, 50 turns, 1200s × 2 attempts, 2 concurrent reviews.

**Single entry point rule:** the plugin's SessionEnd hook is the only review spawner. Don't add a second hook in `settings.json` — and if a host ever has one anyway, the engine's per-session atomic claim still guarantees exactly one review.

### Verify it works

```bash
"$(ls ~/.claude/plugins/cache/JStack/jstack/*/tests/log-event.sh | sort -V | tail -1)"        # timeline CLI contract
"$(ls ~/.claude/plugins/cache/JStack/jstack/*/tests/session-review.sh | sort -V | tail -1)"   # engine validator/resolution/claims
```

Then the live test: `cd` into a reviewable agent dir, run `claude --print -p "test"`, and watch `SPAWN → DONE` appear in the review log within a few minutes.

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

## The PreToolUse hook: cross-tree rule injection

Native rules in `~/.claude/rules/*.md` auto-load by `paths:` glob, but only against files **inside the session's launch CWD**. If your editor is launched from one tree (`~/Agents/Mario/`) and the code you're editing lives in a sibling tree (`~/Wordy-Project/`), no rule fires — a real gap for agents that span multiple projects.

JStack ships a PreToolUse hook (`plugins/jstack/hooks/inject-path-rules.py`, auto-registered via `plugins/jstack/hooks/hooks.json`) that closes that gap. Whenever Claude Code is about to invoke `Edit`, `Write`, `MultiEdit`, or `NotebookEdit`, the hook:

1. Reads the tool's `tool_input.file_path` (an **absolute** path, so launch CWD doesn't matter).
2. Walks `~/.claude/rules/*.md`, parses each rule's `paths:` frontmatter, tests every glob against the file path.
3. For matched rules, returns the rule body as `additionalContext` via the hook's JSON envelope (`permissionDecision: "allow"`). Claude sees the rule before executing the edit.

### Dedup so the same rule doesn't flood context every edit

For each `(session, rule)` pair, the hook writes a marker file containing the transcript's byte offset at injection time. On subsequent matches, it re-injects only if the transcript has grown by **at least `JSTACK_RULE_REINJECT_BYTES` bytes** since the marker (default `400000` ≈ ~100K tokens at ~4 bytes/token). Override per-session by exporting `JSTACK_RULE_REINJECT_BYTES=N`.

### Kill switch

Set `JSTACK_PATH_RULES_DISABLED=1` to make the hook a no-op for a session.

### Defensive guarantees

- Any exception → silent `exit 0`, no output. The hook **never blocks** a tool call.
- Stdin is JSON via the documented PreToolUse contract; malformed or empty input → silent exit.
- Default hook timeout: 10s (configured in `hooks.json`). Typical runtime: <100ms.

### Cache location

Per-session marker files live at `/tmp/jstack-rule-cache/<sanitized-session-id>/<rule>.marker`. Reboot-clean; no persistence needed.

### Tuning

The hook is content-agnostic — whatever rules' `paths:` globs are, that's what fires. If you find too many rules matching a single edit (5–7 is possible if your rule globs are broad), tighten the rules' globs rather than the hook. The hook is doing exactly what you tell it via frontmatter.

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

## Deep docs

- `plugins/jstack/docs/systems/post-session-review.md` — the review engine: gating table, full config key reference, log-line contract, safety switches.
- `plugins/jstack/docs/systems/timeline-log.md` — the timeline writer: CLI contract, consolidation semantics, host-parity rule.
- `plugins/jstack/docs/systems/path-rule-injection.md` — the PreToolUse hook internals.
- `docs/agents-dashboard.md` — pattern spec for building a local dashboard that surfaces every agent + session (pattern-only — implement against your environment). A host dashboard can federate `plugins/jstack/systems.json` to surface and test the bundled systems alongside its own.

---

## Repository layout

```
JStack/
├── .claude-plugin/marketplace.json        # marketplace manifest
├── plugins/jstack/
│   ├── .claude-plugin/plugin.json         # plugin manifest (declares userConfig)
│   ├── skills/                            # the six slash commands
│   │   ├── active/SKILL.md
│   │   ├── save/SKILL.md
│   │   ├── handoff/SKILL.md
│   │   ├── push/SKILL.md
│   │   ├── install-rules/SKILL.md
│   │   └── post-session-review/SKILL.md
│   ├── hooks/
│   │   ├── hooks.json                     # PreToolUse + SessionEnd registration
│   │   ├── inject-path-rules.py           # cross-tree rule injection
│   │   └── session-end-review.sh          # spawns the review engine, detached
│   ├── bin/                               # bundled adapters (auto-added to PATH)
│   │   ├── open-terminal-here
│   │   ├── file-followup
│   │   ├── log_event                      # timeline writer
│   │   └── session-review-spawn           # review engine
│   ├── rules-stage/                       # rules installed via /jstack:install-rules
│   ├── systems.json                       # registry: every bundled system + its test
│   ├── tests/                             # runnable system tests (*.sh, exit 0 = pass)
│   └── docs/systems/                      # per-system deep docs
├── docs/                                  # architecture specs (not installed)
└── README.md                              # this file
```

---

## For a model setting this up

If you're a Claude session setting this up on a fresh machine, execute steps 1–6 in order. All steps are mechanical now: there are no adapters to hand-write (they're bundled and self-detecting). The only choices are the `agent_root` path and, optionally, the `followup_backend`. After step 6 returns a successful `/jstack:active` listing, JStack is installed and verified.

To activate the self-running systems, add the **Post-session review + timeline** section's one `mkdir` (the `review/` dir per agent), run `/jstack:install-rules` (the `timeline` + `agent-state` rules carry the format discipline), and run the two test scripts under **Verify it works**. No config file is required unless you're overriding defaults — read `plugins/jstack/docs/systems/post-session-review.md` before writing one.

If `/jstack:install-rules` would overwrite anything important on the target machine, ask the user first (default behavior skips existing files, so this only matters with `--force`).
