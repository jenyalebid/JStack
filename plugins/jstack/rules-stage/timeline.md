---
paths:
  - "Logs/Timeline/**"
  - "**/bin/log_event"
---

# Timeline Format

`{timeline_dir}/{YYYY-MM-DD}.md` (default `~/Logs/Timeline/`) is the day's spine — what happened, when. Feeds daily briefs and nightly reviews. **Not a session log. Not a commit log. Not a build report.**

Write entries with the jstack `log_event` tool (in the plugin's `bin/`, on PATH for review spawns). Timeline dir override: `JSTACK_TIMELINE_DIR`.

## Format — strict

Every entry is a block, separated by one blank line:

```
HH:MM [agent]
Headline — present-tense, one line, ≤120 chars.
- optional detail
- max 3 bullets, each ≤80 chars
```

- 24h `HH:MM`. Never relative, never seconds.
- `[agent]` is the lowercase agent name.
- Headline is one line. 0-3 detail bullets follow, each starting with `- `.
- Exactly one blank line between blocks.

## What belongs

- Code shipped, feature live, decision made, problem fixed.
- User directive, user question that drove work, user call.
- Pipeline task state change (consolidated to one block per task).
- Significant autonomous work.

## What does NOT belong

- File paths, commit hashes, branch names, session UUIDs, PIDs, exit codes.
- Test counts, line counts, build configs, device/simulator models, OS versions.
- Process noise — "pushed", "build clean", "5/5 tests pass".
- Routine maintenance — "reviewed session", "updated state.md".
- Multiple entries for the same event from different angles.

A reader asks "what happened today?" — not "which simulator on which iOS?".

## Headline grade

The headline reads like a news ticker. Short, declarative, present-tense.

✅ `Word Search v3 shipped — 8 pipeline tasks merged to v3.`
❌ `Pipeline #87 (custom WS boards + Game Send) MERGED to v3 via manual PR after orchestrator failure. Built clean 04:25 (commits 174ff33 + 45b4640 on task/87-ws-custom-boards: generator + profanity list + ...).`

Bullets are punchy too:
✅ `- 14 themes, daily seed rotation`
❌ `- WordSearchThemesService greedy 6×7 placer, longest-first retry shuffles, SplitMix64 seed in .../Services/...`

## Order is chronological

**Always pass `--at HH:MM`** — for post-session-review entries, this is the **timestamp of the LAST message in the reviewed conversation** (machine-local time, not UTC). For in-session direct `log_event` calls, use the actual event time. Late-logged events from a previous local day: also pass `--date YYYY-MM-DD`.

## One event, one entry

Before logging, **read today's timeline.** If the event is already covered by another agent's block, don't duplicate — edit the file to extend the existing block, or skip.

Pipeline tasks (multi-session work tracked by an issue) **must** use `--pipeline-task {repo}#{issue}` so the new block replaces prior ones. One live block per task, always current.

## How to write

```bash
log_event {agent} --at HH:MM "headline"
log_event {agent} --at HH:MM "headline" --detail "bullet" --detail "bullet"
log_event {agent} --at HH:MM --pipeline-task wordy#89 "headline" --detail "bullet"
log_event {agent} --at HH:MM --date 2026-04-28 "late-logged event"
```

Agents write their own name as source. Reserved sources (e.g. `assistant`) belong to the system that owns them.

## Curate, don't just append

If today's timeline is messy at end of day, edit it: collapse duplicates, tighten headlines, prune detail bullets. Downstream briefs read this file — quality matters.
