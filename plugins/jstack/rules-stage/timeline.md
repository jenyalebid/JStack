---
paths:
  - "Logs/Timeline/**"
  - "**/bin/log_event"
---

# Timeline — the running memory

The timeline is the single running record of what happened, when — and each
seat's memory: a session's entries under its `agent/submode` source are
injected into that seat's next session on start. Feeds daily briefs, nightly
reviews, and every seat's cold start. **Not a session log. Not a commit log.
Not a build report.**

Store: sqlite at `{timeline_dir}/timeline.db` (default `~/Logs/Timeline/`).
The day file `{YYYY-MM-DD}.md` is a **one-way rendered view** — regenerated
from the db on every write. Never edit a day md by hand: the db doesn't know
your edit, and hand-writes are absorbed as `unknown`-quality strays at best.
Everything goes through the jstack `log_event` tool (in the plugin's `bin/`,
on PATH for review spawns). Timeline dir override: `JSTACK_TIMELINE_DIR`.

## Format — strict (the rendered day view)

Every entry is a block, separated by one blank line:

```
HH:MM [agent/submode]
Headline — present-tense, one line, ≤120 chars.
- optional detail
- max 3 bullets, each ≤80 chars
```

- 24h `HH:MM`. Never relative, never seconds.
- `[agent/submode]` is the lowercase seat that did the work (e.g.
  `alpha/chat`, `delta/social`). Always pass the submode when the seat is
  known — seat-tagged entries are what the next session of that seat boots
  on; a bare `[agent]` entry is invisible to seat injection once the seat's
  own entries fill the window.
- Headline is one line. 0-3 detail bullets follow, each starting with `- `.
- Exactly one blank line between blocks.

## What belongs

- Code shipped, feature live, decision made, problem fixed.
- User directive, user question that drove work, user call.
- Pipeline task state change (consolidated to one block per task).
- Significant autonomous work.
- A detail bullet earns its place when the NEXT session of the seat needs it:
  an open thread, a decision and its why, a do-not-repeat.

## What does NOT belong

- File paths, commit hashes, branch names, session UUIDs, PIDs, exit codes.
- Test counts, line counts, build configs, device/simulator models, OS versions.
- Process noise — "pushed", "build clean", "5/5 tests pass".
- Routine maintenance — "reviewed session".
- Multiple entries for the same event from different angles.

A reader asks "what happened today?" — not "which simulator on which iOS?".

## Headline grade

The headline reads like a news ticker. Short, declarative, present-tense.

✅ `Search v3 shipped — 8 pipeline tasks merged to v3.`
❌ `Pipeline #87 (custom boards + share flow) MERGED to v3 via manual PR after orchestrator failure. Built clean 04:25 (commits 174ff33 + 45b4640 on task/87-custom-boards: generator + profanity list + ...).`

Bullets are punchy too:
✅ `- 14 themes, daily seed rotation`
❌ `- ThemesService greedy 6×7 placer, longest-first retry shuffles, SplitMix64 seed in .../Services/...`

## Order is chronological

**Always pass `--at HH:MM`** — for a session's own end-of-session self-write,
this is the **timestamp of the LAST message in the reviewed conversation**
(machine-local time, not UTC). For in-session direct `log_event` calls, use
the actual event time. Late-logged events from a previous local day: also
pass `--date YYYY-MM-DD`.

## One event, one entry

Before logging, check what's already recorded — `log_event tail <agent> -n 15`
(or read today's rendered md). If the event is already covered by another
block, skip; don't restate it from your angle.

Pipeline tasks (multi-session work tracked by an issue) **must** use
`--pipeline-task {repo}#{issue}` so the new block replaces prior ones. One
live block per task, always current.

## How to write

```bash
log_event {agent}/{submode} --at HH:MM "headline"
log_event {agent}/{submode} --at HH:MM "headline" --detail "bullet" --detail "bullet"
log_event {agent}/{submode} --at HH:MM --pipeline-task appx#89 "headline" --detail "bullet"
log_event {agent}/{submode} --at HH:MM --date 2026-04-28 "late-logged event"
log_event {agent}/{submode} --at HH:MM --session {session_id} "headline"   # link the transcript
```

Agents write their own seat as source. Reserved sources (e.g. `assistant`)
belong to the system that owns them.

## Reading back

```bash
log_event tail alpha/chat -n 10     # a seat's recent history (what injection shows)
log_event tail alpha -n 20          # all of an agent's seats
log_event tail alpha/chat --json    # structured, with session ids + verdicts
```

## Verdicts — the independent check

A reviewing process (e.g. a nightly meta review) stamps its call on a seat's
latest entry:

```bash
log_event verdict beta/pm blocked --note "do not repeat: bare re-ping; escalate format past 5 cycles"
```

Verdicts ride `tail` and seat injection (`↳ verdict: ...`) so the next run
sees the call — they are NOT rendered into the day md, which stays strictly
the day's spine.
