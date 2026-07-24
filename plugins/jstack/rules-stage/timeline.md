---
paths:
  - "Logs/Timeline/**"
  - "**/bin/log_event"
---

# Timeline — the running memory

The timeline is the single running record of what happened, when — and each
seat's memory: a session's entries under its `agent/submode` source are
injected into that seat's next LIVE session on start (a human sitting down
mid-history). Auto sessions and injections never mix, in either direction:
headless spawns never receive an injection, and `origin=indirect` entries
(crons, publish wakes, spawned work) never ride in one — the injected view
is `tail --origin direct`, the seat's human-driven narrative. Feeds daily
briefs, nightly reviews, and every seat's cold start. **Not a session log.
Not a commit log. Not a build report.**

Store: sqlite at `{timeline_dir}/timeline.db` (default `~/Logs/Timeline/`) —
the ONLY artifact; there are no rendered files. Everything goes through the
jstack `log_event` tool (in the plugin's `bin/`, on PATH for review spawns):
writes AND reads. Never write the db from other code — a second writer forks
the source of truth. Timeline dir override: `JSTACK_TIMELINE_DIR`.

## Format — strict

Every entry is one block (this is also how `recall`/`tail` print it):

```
HH:MM [agent/submode]
Headline — present-tense, one line, ≤120 chars.
- optional detail
- max 3 bullets, each ≤80 chars
```

- 24h `HH:MM`. Never relative, never seconds.
- `[agent/submode]` is the lowercase seat that did the work — seats are
  directories: the session dir's full path under the agent root (e.g.
  `alpha/chat`, `delta/social/chat` — each dir its own seat). Always pass the
  submode when the seat is known — seat-tagged entries are what the next
  session of that seat boots on; a seat's tail also serves its ancestor dirs'
  rows (`social/chat` pulls `social`), never a sibling dir's; a bare
  `[agent]` entry is invisible to seat injection once the seat's own entries
  fill the window.
- Headline is one line. 0-3 detail bullets follow, each starting with `- `.

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

## Depth on demand — `--context`

The block stays lean — it is what every next session boots on. When an event
carries state worth more than three bullets (a design's why, an incident's
trace, the exact state of a half-done thread), put it in `--context`: stored
on the entry, never injected. It surfaces only via `log_event show <id>` or
`tail --json`. The `--session` link is advisory — transcripts get cleaned
over time; the entry plus its context must stand alone.

## Origin — who drove the session

Every entry carries an origin: `direct` (a human was at the wheel of the
session that produced it) or `indirect` (cron / gateway / spawned work, no
human driving). Resolution, first match wins:

1. `--origin direct|indirect` on the write
2. `JSTACK_TIMELINE_ORIGIN` env (spawn plumbing sets it on unattended
   sessions; the session-end engine sets it on self-write resumes)
3. `direct`

Interactive sessions never need the flag. Pass it only when writing on
behalf of the other kind (e.g. a human logging an event a cron performed).
Dashboards and queries filter on it — a mislabeled origin miscounts the
day's autonomous vs driven work.

## Headline grade

The headline reads like a news ticker. Short, declarative, present-tense.

✅ `Search v3 shipped — 8 pipeline tasks merged to v3.`
❌ `Pipeline #87 (custom boards + share flow) MERGED to v3 via manual PR after orchestrator failure. Built clean 04:25 (commits 174ff33 + 45b4640 on task/87-custom-boards: generator + profanity list + ...).`

Bullets are punchy too:
✅ `- 14 themes, daily seed rotation`
❌ `- ThemesService greedy 6×7 placer, longest-first retry shuffles, SplitMix64 seed in .../Services/...`

## Order is chronological

Stamps are machine-local wall clock, and `--at`/`--date` default to now and
today — **omit both when logging as you go** (a session-end self-write passes
neither). Pass them only for an event that happened earlier: a review writing
for an already-ended session stamps the transcript file's **mtime**; a
late-logged event from a previous local day adds `--date YYYY-MM-DD`. Never
copy a timestamp from inside a session JSONL — those are UTC and land hours
ahead (`log_event` clamps impossible future stamps to now as a backstop).

## One event, one entry

Before logging, check what's already recorded — `log_event tail <agent> -n 15`.
If the event is already covered by another block, skip; don't restate it from
your angle.

Pipeline tasks (multi-session work tracked by an issue) **must** use
`--pipeline-task {repo}#{issue}` so the new block replaces prior ones. One
live block per task, always current.

## How to write

```bash
log_event {agent}/{submode} "headline"                    # stamps now — the normal self-write
log_event {agent}/{submode} "headline" --detail "bullet" --detail "bullet"
log_event {agent}/{submode} "headline" --context "freeform depth, loaded on demand"
log_event {agent}/{submode} --pipeline-task appx#89 "headline" --detail "bullet"
log_event {agent}/{submode} --at 14:05 "event from earlier today"
log_event {agent}/{submode} --at 23:10 --date 2026-04-28 "late-logged event"
log_event {agent}/{submode} --session {session_id} "headline"   # link the transcript
log_event {agent}/{submode} --origin indirect "headline"  # writing for unattended work
```

Agents write their own seat as source. Reserved sources (e.g. `assistant`)
belong to the system that owns them.

## Reading back — the default recall surface

"What did we do?" questions resolve here first, not by digging transcripts:
a **date** question ("what happened Monday?") → `log_event recall`; a
**keyword** question ("when did we ship X?") → `log_event grep`. Injection
and recall are the same mechanism — one store, different read shapes.

```bash
log_event tail alpha/chat -n 10     # a seat's recent history, all origins
log_event tail alpha/chat -n 10 --origin direct  # human-driven only (what injection shows)
log_event tail alpha -n 20          # all of an agent's seats
log_event tail alpha/chat --json    # structured: ids, session ids, origins, verdicts, context
log_event recall 2026-04-28                    # a day replayed, all seats
log_event recall 2026-04-28 alpha              # one agent's day (alpha/chat = one seat)
log_event recall 2026-04-21..2026-04-27 --full # a week, context blobs included
log_event grep "publish endpoint" --seat alpha/chat --since 2026-04-01
log_event show 1234                 # everything one entry holds (id from grep/recall/tail --json)
```

## Verdicts — the independent check

A reviewing process (e.g. a nightly meta review) stamps its call on a seat's
latest entry:

```bash
log_event verdict beta/pm blocked --note "do not repeat: bare re-ping; escalate format past 5 cycles"
```

Verdicts ride `tail`, `recall`, and seat injection (`↳ verdict: ...`) so the
next run sees the call.
