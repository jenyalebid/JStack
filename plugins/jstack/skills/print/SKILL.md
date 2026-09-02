---
name: print
description: Print the absolute path of this session's local JSONL transcript file. Answered by a UserPromptSubmit hook without a model turn; this is the fallback when the hook does not fire.
argument-hint: ""
---

# /jstack:print — this session's transcript path

**When the user types `/print`, this skill is not what runs.** `hooks/print-command.py`
intercepts it at UserPromptSubmit and answers from the hook payload's
`transcript_path` — the file the harness is itself writing to — without starting a
turn. Where is a conversation stored has one right answer and no judgement in it;
paying a model call to reach a foregone conclusion is the cost the hook removes.

You are reading this because the hook did not fire: not wired, not executable, or a
Claude Code version that does not run `UserPromptSubmit` for slash commands. Say so
in one line, then do it by hand.

## By hand

```bash
ls ~/.claude/projects/*/"$CLAUDE_CODE_SESSION_ID".jsonl
```

`$CLAUDE_CODE_SESSION_ID` is authoritative for the running session, and the glob
sidesteps project-dir path encoding — a symlinked cwd like `/tmp` encodes as
`-private-tmp`, and computing that by hand gets it wrong.

Report the path back as a single inline-code line. Nothing else is required.

## Failure handling

- `$CLAUDE_CODE_SESSION_ID` empty, or the glob matches nothing → say the transcript
  can't be located from inside this session and stop. **Never fall back to "newest
  `.jsonl` in the project dir"** — concurrent sessions share a project dir, and
  mtime-guessing returns another session's file with no sign that it did.
- More than one match (same id under two project dirs — shouldn't happen) → print
  every match and flag the anomaly.

## Notes

- The transcript is append-only and live; the invocation turn itself may not be
  flushed to it yet.
- Subagent transcripts sit alongside as `agent-*.jsonl` in the same project dir —
  those are not this session's file.
