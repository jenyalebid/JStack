# JStack

Cross-machine Claude Code skills for agent workflows. Built around the `{agent_root}/{Name}/` workspace convention, where `agent_root` is **configured per machine** (no hardcoded paths). Adapters ship inside the plugin and self-detect the environment, so the same plugin behaves richly everywhere with zero per-machine scripting.

## What this gives you

Slash commands (all namespaced as `/jstack:*`):

| Command | What it does |
|---|---|
| `/work` | Get battle-ready on a topic — orient, load every relevant skill, survey recent changes, read the core files, report a grounded lay of the land. `[@project] <topic>` |
| `/handoff` | Hand off the session to a fresh terminal with context preserved |
| `/splitoff` | Dub the session into a new terminal — a verbatim copy under a fresh id, diverging forward |
| `/audit` | Spawn a trust-nothing auditor in a fresh terminal to verify this session's work from source |
| `/push` | Commit + push this session's edits (default), or `all` pending changes grouped by unit of work |
| `/report` | Close out a task: settle every finding as its own commit or a filed GitHub issue, then report |
| `/day-audit` | Reverify a day's shipped work across every repo against the timeline — did the commits (esp. fixes) improve each app without regressing something? |
| `/recall` | Replay what was done on a day or period, scoped to an agent or the whole op |
| `/showme` | Surface the result of the current topic in its real viewer instead of describing it |
| `/print` | Print the absolute path of this session's JSONL transcript |
| `/install-rules` | Symlink the 17 bundled rules into `~/.claude/rules/` |
| `/post-session-review` | Review playbook the SessionEnd engine runs after every session (also manually invocable with a session id) |

Plus four **whole systems** that run themselves once installed:

- **Session-end self-write** — a SessionEnd hook resumes every session that ends inside an agent workspace for one turn so it writes its own seat-tagged timeline entry (the cheapest, best-informed writer); a full validated multi-phase review remains available as the `review` action. See **Session-end engine + timeline** below.
- **Timeline** — the single running memory: `bin/log_event` writes a sqlite store (`timeline.db`; daily `{YYYY-MM-DD}.md` files are a one-way rendered view) with seat-tagged sources (`agent/submode`), session-id linkage, chronological rendering, pipeline-task consolidation, seat queries (`log_event tail`), and review verdict stamps (`log_event verdict`). A SessionStart hook injects each seat's last N entries into its next session (`timeline_inject` config), so sessions start sighted.
- **Agent inbox** — addressed seat-to-seat messaging with a tracked outcome: `bin/msg` sends `@agent` / `@agent-seat` a message that lands in a `messages` table beside the timeline, injects at the top of that seat's next session, and cannot be walked past — a Stop hook blocks the first stop that would leave it open, and closing it requires recording what was done. Optional rungs type into a live session or wake the receiver outright. Where the timeline answers *what did this seat do*, the inbox answers *what is it being asked to do, by whom, and what came of it*. Full contract: **[docs/systems/agent-inbox.md](plugins/jstack/docs/systems/agent-inbox.md)**.
- **Scheduler** — the piece that *starts* a session rather than reviewing or remembering one: a daemon firing one-time and recurring agent runs on RRULE schedules, with the timeout counted from spawn, TTFT/stall watchdogs on hung turns, authoritative process-group kills, catch-up after downtime, per-job concurrency policy, and rate-limit deferral. One package, every machine — a host declares its timezone, spawn environment, and workspace resolution in `config/scheduler.json` and nothing host-specific lives in the code. Needs `python-dateutil`. Setup and the full contract: **[docs/systems/scheduler.md](plugins/jstack/docs/systems/scheduler.md)**.

And the supporting machinery: 17 path-scoped rule files (auto-load by glob after install), a **PreToolUse hook** that re-injects path-matched rules at edit time even when the file lives outside the session's launch tree, 11 bundled `bin/` adapters (`open-terminal-here`, `file-followup`, `file-issue`, `place-issue`, `log_event`, `msg`, `session-review-spawn`, `session-files`, `dub-session`, `open-artifact`, `pict`), a `systems.json` registry where every bundled system declares a runnable test (`plugins/jstack/tests/*.sh` — run them any time), and per-system deep docs under `plugins/jstack/docs/systems/`.

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
| `followup_backend` | string | `none` | How the review skill files a follow-up reminder: `none` \| `todo` \| `reminders` \| `slack`. |
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
mkdir -p "$AGENT_ROOT"/{YourAgentName}     # $AGENT_ROOT = whatever you set above
cat > "$AGENT_ROOT"/{YourAgentName}/CLAUDE.md <<'EOF'
# {YourAgentName}

(your agent identity here — what this agent does, voice, durable rules)
EOF
```

The walk-up auto-loads this CLAUDE.md whenever a session runs inside that agent dir or any subdirectory.

### 5. (Optional) Install the bundled rules

After restarting Claude Code so the plugin loads:

```
/install-rules
```

Confirms and symlinks 17 rules into `~/.claude/rules/` (canvas, claude-md-editing, claude-sessions, code-review, execution-gates, ios-charts, ios-design-ethos, ios-forms, ios-lists, ios-modifiers, ios-screens, ios-services, ios-sheets, ios-style, rules, timeline, visual-assets). Skips files that already exist; pass `--force` to overwrite. The source is `${CLAUDE_PLUGIN_ROOT}/rules-stage/` — resolved automatically.

### 6. Verify end-to-end

Restart Claude Code, then in a session inside an agent directory:

```bash
cd "$AGENT_ROOT"/{YourAgentName}
claude
```

In the session, run `/jstack:work <any topic>`. If it reports you're not inside an agent tree, check that `agent_root` is set correctly and the agent's `CLAUDE.md` exists.

---

## Session-end engine + timeline (the self-running systems)

Once the plugin is installed, the SessionEnd hook is live — but it only does anything when a session ends inside a reviewable agent workspace, so installing the plugin never spawns surprise reviews on a machine that isn't set up for it.

### What makes an agent reviewable

```
{agent_root}/{Name}/CLAUDE.md      ← this file existing IS the opt-in (the agent identity)
```

End a session inside that agent's tree → the engine resolves the owner and (default `session_end_action: "selfwrite"`) resumes the ended session for one turn so it logs its own seat-tagged timeline entry. Set `session_end_action: "review"` for the legacy fresh multi-phase review (`/jstack:post-session-review`, output machine-validated, retried once on rejection). Engine activity logs to `~/.claude/jstack/review-state/session-review.log` by default.

### Timeline

The self-write (and anything else) writes the running memory with the bundled CLI — it's on PATH for engine spawns, or call it via the plugin cache:

```bash
log_event <agent>/<submode> --at HH:MM "headline" [--detail "..."] [--pipeline-task repo#42] [--session <sid>]
log_event tail <agent>/<submode> -n 10        # a seat's recent history (what injection shows)
log_event verdict <agent>/<submode> blocked --note "do not repeat: ..."
```

Store: `~/Logs/Timeline/timeline.db` (`JSTACK_TIMELINE_DIR` overrides); daily `{YYYY-MM-DD}.md` files are a one-way rendered view — never hand-edit them. Which seats get their history injected on session start, and how many entries, is the `timeline_inject` map in the review config. Format spec + editorial bar: the `timeline` rule (install via `/install-rules`).

### Machine config (optional — defaults are fully portable)

`~/.claude/jstack/review.json` (env override: `JSTACK_REVIEW_CONFIG`). You only need it to change defaults — e.g. point `skill_invocation` at a richer host playbook, extend `required_sections` to that playbook's output contract, add host tool dirs to the spawned PATH, or wire `escalate_cmd` / `tg_classify_cmd` adapters. Full key reference: `plugins/jstack/docs/systems/session-end-engine.md`. Model/budget defaults: opus, 50 turns, 1200s × 2 attempts, 2 concurrent reviews.

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

### `open-terminal-here` — used by `/handoff`

Opens a new Claude Code terminal at a directory. Self-detects the terminal:

- **macOS:** iTerm if installed, else Terminal.app
- **Linux:** gnome-terminal → konsole → x-terminal-emulator → xterm
- **Windows:** Windows Terminal (`wt.exe`)

**Contract:** `open-terminal-here <cwd> [extra-claude-args...]`. To override on a machine, put your own `open-terminal-here` earlier in `PATH`.

### `file-followup` — used by the review skill

Files a follow-up reminder, routed by the `followup_backend` config:

- `none` (default) — silent no-op
- `todo` — appends `- [ ] <title> — <body>` to `followup_target` (default `<agent_root>/followups.md`)
- `reminders` — adds to the macOS Reminders list named in `followup_target` (default `Follow-ups`)
- `slack` — POSTs to the webhook in env var `SLACK_FOLLOWUP_WEBHOOK`

**Contract:** `file-followup <title> <body>`, exit 0 = filed or intentionally skipped.

### `file-issue` — used by `/report`

Files a GitHub issue for a finding the session did not fix, **and places it on the board its owner actually reads**. A bare `gh issue create` leaves `projectItems[]` empty — the issue exists, is numbered, and is invisible. Filing and placing are one act, or the tracker is a no-op with a receipt.

Board routing is read **live from GitHub** (`repository.projectsV2` → the project's `Status` field → the intake column, matched by name: TODO / Todo / Backlog / Triage / Inbox / New). There is no repo→board map to configure, and none to go stale.

**Contract:** `file-issue --repo <owner/name> --title <t> (--body <text> | --body-file <p>) [--label L]... [--project N] [--no-board] [--dry-run]`. Last stdout line is `ISSUE <url> board=<column|none>`.

Degrades rather than blocking: no `gh` → exit 3; repo unreadable or issues disabled → exit 4; repo linked to no project (or to several, without `--project`) → issue filed, board skipped, exit 0. Every non-zero exit means **nothing was filed**, so a caller can never report an issue number it didn't get.

---

## How the skills work (so you can predict behavior)

`{root}` below = the configured `agent_root`.

### `/handoff [focus]`

1. Walks this conversation, writes a `handoff-context.md` to the current working directory with Current Work / In Progress / Still To Do / Key Decisions / Context sections.
2. Shows the summary.
3. Calls `open-terminal-here "$(pwd)" --append-system-prompt-file handoff-context.md`. If no terminal can be opened, prints instructions for opening the new session manually.

### `/audit [focus] [@agent]`

The inverse of handoff: instead of a continuation briefing, the session writes a **claims document** (`audit-brief.md` — Original Issue / What Was Done / Claimed Verifications / Caution Flags / Blast Radius / Potential Pitfalls) prefixed with a fixed Audit Protocol, then opens a fresh terminal preloaded with it plus a kickoff prompt so the auditor starts immediately. The auditor's cornerstone rule: believe nothing in the brief — verify every claim from source (real diff, real builds, real test runs), verify user-stated "don't break X" constraints first, derive its own blast radius, and report CONFIRMED / REFUTED / UNVERIFIABLE per claim. Report-only: the auditor changes nothing. `@agent` runs the audit under another agent's identity, same workspace resolution as handoff.

### `/install-rules [--copy] [--force]`

Symlinks every `.md` in `${CLAUDE_PLUGIN_ROOT}/rules-stage/` into `~/.claude/rules/`. Default mode is symlink (edits to the source affect the live rule, and updates track automatically). `--copy` makes update-independent local copies. `--force` overwrites existing files.

---

## The PreToolUse hook: cross-tree rule injection

Native rules in `~/.claude/rules/*.md` auto-load by `paths:` glob, but only against files **inside the session's launch CWD**. If your editor is launched from one tree (`~/Agents/AgentA/`) and the code you're editing lives in a sibling tree (`~/Some-Project/`), no rule fires — a real gap for agents that span multiple projects.

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

Symlinked rules track new content automatically. The plugin install path changes on version bumps (old version cleaned up ~7 days later), so if symlinks ever go stale, re-run `/install-rules --force`.

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
3. **Running memory** — the timeline: each seat's `log_event` entries, injected back on session start (`timeline_inject`)
4. **Sub-modes** — subdirectories of the agent root, same identity in a different context (walk-up handles inheritance)
5. **Adapters** — bundled in the plugin's `bin/`, configured via `followup_backend` / `followup_target`

Set `agent_root` to wherever your workspaces live and JStack works out of the box on any machine.

---

## Deep docs

- `plugins/jstack/docs/systems/session-end-engine.md` — the review engine: gating table, full config key reference, log-line contract, safety switches.
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
│   ├── skills/                            # the 12 slash commands
│   │   ├── work/SKILL.md
│   │   ├── handoff/SKILL.md
│   │   ├── splitoff/SKILL.md
│   │   ├── audit/SKILL.md
│   │   ├── day-audit/SKILL.md
│   │   ├── recall/SKILL.md
│   │   ├── showme/SKILL.md
│   │   ├── print/SKILL.md
│   │   ├── push/SKILL.md
│   │   ├── report/SKILL.md
│   │   ├── install-rules/SKILL.md
│   │   └── post-session-review/SKILL.md
│   ├── hooks/
│   │   ├── hooks.json                     # PreToolUse + SessionStart + SessionEnd + Stop
│   │   ├── inject-path-rules.py           # cross-tree rule injection
│   │   ├── session-start-inject.py        # seat timeline injection
│   │   ├── stop-inbox-guard.py            # an open inbox message cannot be walked past
│   │   ├── stop-timeline-remind.py        # timeline write reminder
│   │   └── session-end-review.sh          # spawns the review engine, detached
│   ├── bin/                               # bundled adapters (auto-added to PATH)
│   │   ├── open-terminal-here             # /handoff, /audit, /splitoff
│   │   ├── dub-session                    # /splitoff
│   │   ├── open-artifact                  # /showme
│   │   ├── pict                           # image capture/convert
│   │   ├── session-files                  # /push stage list
│   │   ├── file-issue                     # /report issue filing + board placement
│   │   ├── file-followup                  # review follow-ups
│   │   ├── log_event                      # timeline writer
│   │   ├── msg                            # agent inbox
│   │   └── session-review-spawn           # review engine
│   ├── scheduler/                         # RRULE daemon (one-time + recurring runs)
│   ├── rules-stage/                       # rules installed via /install-rules
│   ├── systems.json                       # registry: every bundled system + its test
│   ├── tests/                             # runnable system tests (*.sh, exit 0 = pass)
│   └── docs/systems/                      # per-system deep docs
├── docs/                                  # architecture specs (not installed)
└── README.md                              # this file
```

---

## For a model setting this up

If you're a Claude session setting this up on a fresh machine, execute steps 1–6 in order. All steps are mechanical now: there are no adapters to hand-write (they're bundled and self-detecting). The only choices are the `agent_root` path and, optionally, the `followup_backend`. After step 6 returns a successful `/active` listing, JStack is installed and verified.

To activate the self-running systems, add the **Post-session review + timeline** section's one `mkdir` (the `review/` dir per agent), run `/install-rules` (the `timeline` + `agent-state` rules carry the format discipline), and run the two test scripts under **Verify it works**. No config file is required unless you're overriding defaults — read `plugins/jstack/docs/systems/session-end-engine.md` before writing one.

If `/install-rules` would overwrite anything important on the target machine, ask the user first (default behavior skips existing files, so this only matters with `--force`).
