# /handoff — hand off this session to a fresh terminal with context preserved

User invoked `/handoff`. Opens a new Claude Code session in a fresh terminal window, loaded with a concise handoff doc summarizing this session's actionable state.

## Arguments

Optional `$ARGUMENTS` = focus of the handoff (e.g. `/handoff mission refactor`, `/handoff dashboard wiring`, `/handoff bug investigation`).

- **If provided:** scope "Current Work" and "Still To Do" to that focus specifically. Drop unrelated tangents. The next session boots narrowed. The argument is an explicit narrowing instruction — don't try to be balanced.
- **If omitted:** general handoff covering the active thread of work at session end.

## What to do

### Step 1 — Generate the handoff summary

Reflect on this entire conversation and write a concise handoff document. Focus on **actionable state**, not history. Scope per the argument above.

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

**Rules:**
- Be specific: file paths, function names, line numbers, exact state
- Skip anything the next session can derive from reading CLAUDE.md or the code
- If nothing is in progress, just say what was accomplished and what's next
- Keep it under 200 lines — this goes into system prompt space

### Step 2 — Write the summary

Write to `{CWD}/handoff-context.md` using the Write tool.

If a prior `handoff-context.md` already exists in the cwd, remove it FIRST (via Bash) so the Write is a fresh-file create — no need to Read it just to satisfy the Write tool's read-before-write guard.

```bash
trash "$CWD/handoff-context.md" 2>/dev/null || rm -f "$CWD/handoff-context.md"
```

Then Write the new content.

### Step 3 — Show the summary

Output the summary to the user so they can review what's being carried over.

### Step 4 — Open the new session

Call the per-machine terminal-open helper. Contract:

```
~/Agents/bin/open-terminal-here <cwd> [extra-claude-args...]
```

Invocation:

```bash
bash ~/Agents/bin/open-terminal-here "$(pwd)" --append-system-prompt-file "$(pwd)/handoff-context.md"
```

The helper is platform-specific — each machine ships its own. Contract is in JStack's README.

If the helper doesn't exist on this machine, tell the user: "Terminal-open helper not found at `~/Agents/bin/open-terminal-here`. Handoff doc is at `$(pwd)/handoff-context.md` — open a new Claude session there manually with `--append-system-prompt-file handoff-context.md`."

The handoff file lives in the workspace so each agent keeps its own. New session loads the same CLAUDE.md walk-up from the same cwd.
