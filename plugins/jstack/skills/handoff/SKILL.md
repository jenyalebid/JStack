---
name: handoff
description: Hand off the current session to a fresh Claude Code terminal with context preserved.
argument-hint: "[focus]"
---

# /jstack:handoff — hand off this session to a fresh terminal with context preserved

User invoked handoff. Opens a new Claude Code session in a fresh terminal window, loaded with a concise handoff doc summarizing this session's actionable state.

## Arguments

Optional `$ARGUMENTS` = focus of the handoff (e.g. `/jstack:handoff mission refactor`).

- **If provided:** scope "Current Work" and "Still To Do" to that focus. Drop unrelated tangents. The next session boots narrowed. Don't try to be balanced — the argument is an explicit narrowing instruction.
- **If omitted:** general handoff covering the active thread at session end.

## Step 1 — Generate the handoff summary

Reflect on this entire conversation and write a concise handoff document. Focus on **actionable state**, not history. Scope per the argument.

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

Write to `{CWD}/handoff-context.md` using the Write tool.

If a prior `handoff-context.md` exists in cwd, remove it FIRST so the Write is a fresh-file create (avoids the Read-before-write guard burn):

```bash
trash "$CWD/handoff-context.md" 2>/dev/null || rm -f "$CWD/handoff-context.md"
```

Then Write the new content.

## Step 3 — Show the summary

Output the summary to the user.

## Step 4 — Open the new session

Call the per-machine terminal-open adapter. Contract:

```
~/Agents/bin/open-terminal-here <cwd> [extra-claude-args...]
```

Invocation:

```bash
bash ~/Agents/bin/open-terminal-here "$(pwd)" --append-system-prompt-file "$(pwd)/handoff-context.md"
```

The adapter is per-machine. macOS example: iTerm + AppleScript. Linux: gnome-terminal. Windows: wt.exe. JStack's README documents the contract.

**If the adapter doesn't exist** on this machine, tell the user:

> Terminal-open adapter not found at `~/Agents/bin/open-terminal-here`. Handoff doc is at `<cwd>/handoff-context.md`. Open a new Claude session there manually with `--append-system-prompt-file handoff-context.md`.

The handoff file lives in the workspace so each agent keeps its own. New session loads the same CLAUDE.md walk-up from the same cwd.
