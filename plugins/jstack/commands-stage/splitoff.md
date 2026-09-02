---
name: splitoff
description: Fork this session verbatim into a new terminal under a fresh id. Runs in the JStack UserPromptSubmit hook — no model turn.
argument-hint: "[name for the copy]"
---

JSTACK_SPLITOFF_CMD $ARGUMENTS

---

**If you are reading this, the hook did not fire.** `hooks/splitoff-command.py` normally
intercepts this prompt and answers it without starting a turn; reaching the model
means it is not wired, not executable, or this Claude Code version does not run
`UserPromptSubmit` for slash commands. Say so in one line, then do the work by hand:

```bash
NEW_ID="$(dub-session '' '' ' - copy')"      # third arg: ' - <words typed>' if any
open-terminal-here "$PWD" --resume "$NEW_ID"
```

`dub-session` with no source defaults to `$CLAUDE_CODE_SESSION_ID` and the project dir
to `$PWD` with the slashes swapped. Nonzero exit → report its stderr and stop; never
fabricate an id. The terminal adapter failing is not fatal: the fork exists, so hand
back `claude --resume <id>` from this directory.

Any words are the copy's **name**, never a scope — splitoff dubs the whole transcript
and never narrows. `/jstack:handoff <focus>` is the scoped restart. Use `--resume`, never
`--session-id`, which forces a fresh empty session and errors when the file exists. And
never resume the same id in two windows: concurrent appends corrupt the transcript,
which is why the dub copies first.
