---
name: print
description: Print the absolute path of this session's local JSONL transcript file. Use when the user asks where the current conversation is stored on disk.
argument-hint: ""
---

# /jstack:print — this session's transcript path

Print the absolute path of the live session's `.jsonl` transcript. One command, no guessing:

```bash
ls ~/.claude/projects/*/"$CLAUDE_CODE_SESSION_ID".jsonl
```

`$CLAUDE_CODE_SESSION_ID` is authoritative for the running session, and the glob sidesteps project-dir path encoding (symlinked cwds like `/tmp` encode as `-private-tmp`; computing the encoding by hand gets this wrong).

Report the path back as a single inline-code line. Nothing else is required.

## Failure handling

- `$CLAUDE_CODE_SESSION_ID` empty, or the glob matches nothing → say the transcript can't be located from inside this session and stop. **Never fall back to "newest `.jsonl` in the project dir"** — concurrent sessions share a project dir, and mtime-guessing returns another session's file.
- Glob matches more than one file (same id under two project dirs — shouldn't happen) → print all matches and flag the anomaly.

## Notes

- The transcript is append-only and live; the invocation turn itself may not be flushed to it yet.
- Subagent transcripts sit alongside as `agent-*.jsonl` in the same project dir — those are not this session's file.
