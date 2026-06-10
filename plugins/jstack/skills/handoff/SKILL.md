---
name: handoff
description: Hand off the current session to a fresh Claude Code terminal with context preserved — same workspace, or a different agent via @name.
argument-hint: "[@agent] [focus]"
---

# /jstack:handoff — hand off this session to a fresh terminal with context preserved

User invoked handoff. Opens a new Claude Code session in a fresh terminal window, loaded with a concise handoff doc summarizing this session's actionable state. By default the new session boots in the same workspace; with `@agent` it boots in another agent's workspace — the CLAUDE.md walk-up there does the identity switch, the handoff doc carries the context across.

## Arguments

`$ARGUMENTS` = `[@agent] [focus]`, both optional.

- **`@agent`** (first token, `@`-prefixed): hand off to a different agent. Resolve the target workspace under `${user_config.agent_root}`: match `{Name}` against the agent subdirectories case-insensitively (`@ted` → `Ted/`). Target cwd = the agent's `chat/` subdirectory if it exists, else the agent root. If no matching directory exists, list the available agent directories and stop — do not guess.
- **`focus`** (everything after the optional `@agent`): scope "Current Work" and "Still To Do" to that focus. Drop unrelated tangents. The next session boots narrowed. Don't try to be balanced — the argument is an explicit narrowing instruction. If omitted: general handoff covering the active thread at session end.

With no `@agent`, the target cwd is the current cwd (same-workspace handoff, original behavior).

## Step 1 — Generate the handoff summary

Reflect on this entire conversation and write a concise handoff document. Focus on **actionable state**, not history. Scope per the focus argument.

**When targeting another agent (`@agent` given), write the doc FOR that agent:** address their role and what they own, name who is handing off and why, and mark decisions that are locked (made by the user — the receiving agent must not relitigate them). Drop anything that only matters to the current agent's duties. A cross-agent handoff is a briefing, not a diary.

Structure:

```markdown
# Session Handoff

## Current Work
What we're actively working on right now — the immediate task/goal.

## In Progress
Anything mid-flight: partial implementations, uncommitted changes, pending decisions.
Include file paths, branch names, specific details.

## Still To Do
Remaining work items from this session that haven't been started yet.

## Key Decisions
Important choices made this session that the next session needs to respect.

## Context
Anything else critical — blockers, gotchas, things to watch out for.
```

Rules:
- Be specific: file paths, function names, line numbers, exact state
- Skip what the next session can derive from CLAUDE.md or the code
- Keep it under 200 lines — goes into system prompt space

## Step 2 — Write the summary

Write to `{TARGET_CWD}/handoff-context.md` using the Write tool (target cwd from the Arguments section — current cwd unless `@agent` redirected it).

If a prior `handoff-context.md` exists there, remove it FIRST so the Write is a fresh-file create (avoids the Read-before-write guard burn):

```bash
trash "$TARGET_CWD/handoff-context.md" 2>/dev/null || rm -f "$TARGET_CWD/handoff-context.md"
```

Then Write the new content.

## Step 3 — Show the summary

Output the summary to the user.

## Step 4 — Open the new session

Call the bundled terminal-open adapter (on PATH while jstack is enabled). Contract:

```
open-terminal-here <cwd> [extra-claude-args...]
```

Invocation:

```bash
open-terminal-here "$TARGET_CWD" --append-system-prompt-file "$TARGET_CWD/handoff-context.md"
```

The adapter self-detects the terminal (iTerm → Terminal.app on macOS; gnome-terminal/konsole/xterm on Linux; Windows Terminal on Windows). Put your own `open-terminal-here` earlier in PATH to override.

**If the adapter exits nonzero** (no supported terminal found, or an unsupported platform), tell the user:

> Couldn't open a new terminal automatically. Handoff doc is at `<target cwd>/handoff-context.md`. Open a new Claude session there manually with `--append-system-prompt-file handoff-context.md`.

The handoff file lives in the target workspace so each agent keeps its own. The new session loads the CLAUDE.md walk-up from the target cwd — same agent for a plain handoff, the target agent's identity for an `@agent` handoff.
