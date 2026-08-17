---
name: handoff
description: Hand off the current session to a fresh Claude Code terminal with context preserved — same workspace, or a different agent via @name.
argument-hint: "[@agent] [focus]"
---

# /jstack:handoff — hand off this session to a fresh terminal with context preserved

User invoked handoff. Opens a new Claude Code session in a fresh terminal window, loaded with a concise handoff doc summarizing this session's actionable state. By default the new session boots in the same workspace; with `@agent` it boots in another agent's workspace — the CLAUDE.md walk-up there does the identity switch, the handoff doc carries the context across.

## Arguments

`$ARGUMENTS` = `[@agent] [focus]`, both optional.

- **`@agent`** (first token, `@`-prefixed): hand off to a different agent. Resolve the target workspace under `${user_config.agent_root}`: match `{Name}` against the agent subdirectories case-insensitively (`@atlas` → `Atlas/`). **Target cwd is focus-aware:** if the focus clearly belongs to one of the agent's sub-mode directories (a subdirectory with its own CLAUDE.md whose name/domain matches the focus — e.g. a social focus → `social/`), boot THERE — path-scoped rules and the sub-mode's CLAUDE.md only load from inside that tree, and a session booted in the wrong subdirectory silently misses them. Otherwise: the agent's `chat/` subdirectory if it exists, else the agent root. If no matching agent directory exists, list the available agent directories and stop — do not guess.
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

## Step 2 — Write the summary to a throwaway temp file

The summary is a one-shot payload: it loads into the new session's system prompt and is never needed again. So it must NOT land in any workspace — no `handoff-context.md` to delete later. Write it to a temp path outside the tree:

```bash
# mktemp reserves a unique name, then we delete the file it created: an
# existing-but-unread file trips the Write tool's "read it before you write it"
# guard, forcing a pointless Read of an empty file. Deleting it lets the Write
# tool create it fresh while keeping mktemp's collision-safe name.
HANDOFF_TMP="$(mktemp -t jstack-handoff)" && rm -f "$HANDOFF_TMP"
```

Write the summary to `$HANDOFF_TMP` with the Write tool — it creates the file, no prior Read needed. The adapter (Step 4) reads it into the new session inline and deletes it before Claude starts — nothing lingers anywhere.

## Step 3 — Show the summary

Output the summary to the user.

## Step 4 — Open the new session

Call the bundled terminal-open adapter (on PATH while jstack is enabled). Contract:

```
open-terminal-here <cwd> [--prompt-file <path>] [--name <title>] [extra-claude-args...]
```

**Session title — required on every invocation.** `--name` is never omitted: a handoff terminal without an `HF.` title is a failed handoff. Format:
- plain handoff → `HF.<topic>`
- `@agent` handoff → `HF→<Agent>.<topic>`

`<topic>` is **derived, never literal**: name what the handoff is actually about in 1–3 words, the way a fresh session's default title would — read the handoff doc you just wrote and title that (e.g. a session mid-refactor of the auth retry queue → `HF.retry queue`). Never paste the focus argument or the user's phrasing verbatim, and never skip the topic; the argument scopes the doc, the title names the work.

Invocation — **always emit it through the guard below**, never the bare `--prompt-file` form:

```bash
# --prompt-file / --name are adapter-only options added in 0.15.0. A stale PATH can
# resolve an older open-terminal-here that forwards them straight to `claude`, which
# then dies on `unknown option '--prompt-file'` and an unquoted name. Detect the
# adapter's contract and pick a form it actually understands.
if open-terminal-here 2>&1 | grep -q -- '--prompt-file'; then
  # 0.15.0+ adapter: inline briefing, auto-deletes the temp file, re-quotes the name.
  open-terminal-here "$TARGET_CWD" --prompt-file "$HANDOFF_TMP" --name "$TITLE"
else
  # Pre-0.15.0 adapter (pass-through): use a real claude flag every version forwards
  # verbatim. The temp file lingers in /tmp (OS-cleaned, never in the workspace). The
  # name must be a single shell token here — pass-through adapters don't re-quote it.
  SAFE_TITLE="${TITLE// /-}"  # "HF.retry queue" → "HF.retry-queue"
  open-terminal-here "$TARGET_CWD" --append-system-prompt-file "$HANDOFF_TMP" --name "$SAFE_TITLE"
fi
```

- `--prompt-file` — the new shell reads the briefing into `--append-system-prompt` and `rm`s the temp file before Claude starts. The handoff content is never written into a workspace and never has to be cleaned up.
- `--name` — sets the new session's display name AND its terminal title (native `claude --name`, applied externally at launch, so Claude doesn't overwrite it with its own summary).
- The fallback branch keeps handoff working when the adapter on PATH is older than the skill (the classic long-running-shell version skew) — it degrades the niceties, not the launch.

The adapter self-detects the terminal (iTerm → Terminal.app on macOS; gnome-terminal/konsole/xterm on Linux; Windows Terminal on Windows). Put your own `open-terminal-here` earlier in PATH to override.

**If the adapter exits nonzero** (no supported terminal found, or an unsupported platform), tell the user:

> Couldn't open a new terminal automatically. Handoff doc is at `$HANDOFF_TMP`. Open a new Claude session in the target workspace manually with `--append-system-prompt-file "$HANDOFF_TMP"`.

The new session loads the CLAUDE.md walk-up from the target cwd — same agent for a plain handoff, the target agent's identity for an `@agent` handoff.
