---
name: splitoff
description: Use only when the user asks to fork or copy this session into a new terminal and the JStack hook did not answer it.
argument-hint: "[name for the copy]"
---

# /jstack:splitoff — fork this session, verbatim, into a new terminal

Copy this session's full transcript under a fresh session id and open it in a new
Claude Code terminal in the **same workspace**. The new window continues this exact
conversation — every message, tool result, and decision intact — and diverges forward
as its own session. The original is untouched and keeps running independently.

A **lossless** fork. Contrast `/jstack:handoff`, which distills the session to a
<200-line brief and boots a *fresh* session with no history. Split to branch an
exploration while keeping all the context; hand off when context is bloated and a
clean slate is the point.

**When the user types `/splitoff`, this skill is not what runs.**
`hooks/splitoff-command.py` intercepts it at UserPromptSubmit and does both calls
in-process without starting a turn. That is not only cheaper — it cuts at the last
completed turn, so the branch does not carry a paragraph about being branched, which
is what running the fork through the model put in the copy.

You are reading this because the hook did not fire: not wired, not executable, or a
Claude Code version that does not run `UserPromptSubmit` for slash commands. Say so
in one line, then do it by hand.

## Arguments

Words are the copy's **name** — appended to the source's title so the resume picker
tells two forks apart. There is **no focus argument**: splitoff never narrows, it dubs
the whole transcript. If the user clearly meant a scope, say so and point at
`/jstack:handoff <focus>`.

## Step 1 — Dub the transcript

`dub-session` (on PATH while jstack is enabled) copies the live `.jsonl` to a new UUID
in the same project dir, rewrites the internal `sessionId` so the copy is
self-consistent, retitles it, and prints the new id:

```bash
NEW_ID="$(dub-session '' '' ' - copy')"      # third arg: ' - <the words typed>' if any
echo "$NEW_ID"
```

With no source it defaults to `$CLAUDE_CODE_SESSION_ID`, and the project dir to `$PWD`
with `/` → `-`. A first argument ending in `.jsonl` is taken as the transcript itself,
which is the exact form to use when you have a real path in hand.

**Nonzero exit** (no `CLAUDE_CODE_SESSION_ID`, transcript not found) → report the
stderr and stop. Never fabricate an id.

## Step 2 — Open the new terminal on the copy

Use `--resume` (loads the copied history); never `--session-id`, which forces a fresh
empty session and errors when the file exists:

```bash
open-terminal-here "$PWD" --resume "$NEW_ID"
```

**If the adapter exits nonzero** (no supported terminal), the fork still exists — hand
back the id and `claude --resume <NEW_ID>` from this directory.

## Step 3 — Report

One or two lines: the new id, that it's a verbatim copy in a new window, and that this
session is unchanged and independent.

## Notes

- **Never resume the *same* id in two windows** — concurrent appends corrupt the file.
  The dub copies first precisely to avoid this.
- The copy appears under the same workspace in any session lister / dashboard
  automatically (they key by workspace path) — no registry edit needed.
- The title is the copy's name at fork time. It's AI-generated, so once the copy
  diverges it may regenerate to match the new direction — expected, not a bug.
