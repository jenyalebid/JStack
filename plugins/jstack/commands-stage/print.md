---
name: print
description: Use only if /print was typed and the JStack hook did not answer it.
argument-hint: ""
---

JSTACK_PRINT_CMD $ARGUMENTS

---

**If you are reading this, the hook did not fire.** `hooks/print-command.py` normally
intercepts this prompt and answers it without starting a turn; reaching the model
means it is not wired, not executable, or this Claude Code version does not run
`UserPromptSubmit` for slash commands. Say so in one line, then do the work by hand:

```bash
ls ~/.claude/projects/*/"$CLAUDE_CODE_SESSION_ID".jsonl
```

The glob sidesteps project-dir path encoding — a symlinked cwd like `/tmp` encodes as
`-private-tmp`, and computing that by hand gets it wrong. Report the one match as an
inline-code line and nothing else. No match, or no `$CLAUDE_CODE_SESSION_ID` → say the
transcript can't be located from inside this session and stop. **Never fall back to the
newest `.jsonl` in the project dir** — concurrent sessions share that directory, and
mtime-guessing hands back another session's conversation with no sign that it did.
