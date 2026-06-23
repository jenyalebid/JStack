---
name: splitoff
description: Dub the current session into a new terminal — a verbatim copy of this conversation under a fresh id, opened in a new window, diverging forward. Use to branch an exploration without losing the full transcript (unlike handoff, which distills to a brief).
argument-hint: ""
---

# /jstack:splitoff — fork this session, verbatim, into a new terminal

User invoked splitoff. Copy this session's full transcript under a fresh session id and open it in a new Claude Code terminal in the **same workspace**. The new window continues this exact conversation — every message, tool result, and decision intact — and diverges forward as its own session. The original session is untouched and keeps running independently.

This is a **lossless** fork. Contrast with `/jstack:handoff`, which distills the session to a <200-line brief and boots a *fresh* session with no history. Use splitoff when you want to branch (e.g. try a different approach) while keeping all the context; use handoff when context is bloated and you want a clean slate.

There is **no focus argument** — splitoff is always a verbatim dub of the whole session. (If the user typed a focus, ignore it and tell them so: splitoff doesn't narrow; suggest `/jstack:handoff <focus>` if they want a scoped restart.)

## Step 1 — Dub the transcript

Call the bundled adapter (on PATH while jstack is enabled). It copies the live session's `.jsonl` to a new UUID in the same project dir, rewrites the internal `sessionId` so the copy is self-consistent, renames the copy to **"&lt;original title&gt; - copy"** so it's distinguishable in the resume picker, and prints the new id:

```bash
NEW_ID="$(dub-session)"
echo "$NEW_ID"
```

`dub-session` defaults the source to `$CLAUDE_CODE_SESSION_ID` and the project dir to `$PWD` transformed (`/` → `-`) — both correct when run inside this session. Do not pass arguments.

**If it exits nonzero** (no `CLAUDE_CODE_SESSION_ID`, or the transcript isn't found), report the stderr message and stop — do not fabricate an id.

## Step 2 — Open the new terminal on the copy

Resume the dubbed id in a fresh window with the same terminal adapter handoff uses. Use `--resume` (loads the copied history); never `--session-id` (forces a fresh empty session and errors when the file exists):

```bash
open-terminal-here "$PWD" --resume "$NEW_ID"
```

**If the adapter exits nonzero** (no supported terminal), tell the user:

> Couldn't open a new terminal automatically. The session was dubbed to `<NEW_ID>`. Open it yourself with `claude --resume <NEW_ID>` from `<PWD>`.

## Step 3 — Report

Tell the user the split is live: the new id, that it's a verbatim copy opened in a new window, and that this session is unchanged and independent. Keep it to a line or two — both windows now share history up to this point and diverge from here.

## Notes

- **Never resume the *same* id in two windows** — concurrent appends corrupt the file. The dub copies first precisely to avoid this: the new window gets its own file, this session keeps its own.
- The new session appears under the same workspace in any session lister / dashboard automatically (they key by workspace path) — no registry edit needed.
- The in-flight invocation turn may not be flushed to the transcript yet; the copy captures everything up to roughly now, which is the intent.
- The "- copy" title is the copy's name at fork time. It's an AI-generated title, so once the copy diverges it may regenerate to reflect the new direction — that's expected, not a bug.
