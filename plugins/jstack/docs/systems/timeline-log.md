# Timeline Log — Architecture & Usage

Daily timeline files — the day's spine. One file per day at `{timeline_dir}/{YYYY-MM-DD}.md`, written by `bin/log_event`. Downstream consumers (daily briefs, nightly reviews, post-session reviews) read these files to answer "what happened today?".

## Components

| Piece | Path | Role |
|-------|------|------|
| Writer CLI | `bin/log_event` | The only sanctioned way to append timeline entries |
| Format rule | `rules-stage/timeline.md` | Auto-loads (via `/jstack:install-rules` + path-rule-injection) when timeline files are touched — carries the format spec and editorial bar |
| Test | `tests/log-event.sh` | Hermetic CLI-contract verification |

## Writer contract

```bash
log_event <source> "<headline>" [--at HH:MM] [--date YYYY-MM-DD]
                                [--detail "..."]... [--pipeline-task <repo>#<issue>]
```

- **Block format:** `HH:MM [source]` header line, one-line headline, 0–3 `- ` detail bullets. Exactly one blank line between blocks.
- **Chronological insertion:** entries land sorted by `--at`, not append order. Late-logged events slot into place.
- **`--date`** writes a previous day's file (late-logged events from a prior local day).
- **`--pipeline-task <tag>`** consolidates: every existing block containing the tag is removed and replaced by one current block. The tag is auto-prepended to the headline; the earliest matched timestamp is kept unless `--at` is given. One live block per task, always current.
- Headlines collapse internal newlines/whitespace; details are normalized to `- ` bullets.

## Configuration

| Knob | Default | Meaning |
|------|---------|---------|
| `JSTACK_TIMELINE_DIR` | `~/Logs/Timeline` | Directory holding the daily files |

Self-contained python3 stdlib — no venv, no host imports. Safe to call from hooks, crons, spawned reviews, or interactively.

## Host parity

A host machine may have its own in-process timeline writer (e.g. a daemon module that logs events without shelling out). That is allowed **only with a parity test**: run both writers on the same inputs and assert byte-identical output, so the format can never drift between implementations. The Jarvis host pins this with `tests/test_jstack_timeline_parity.py` in its infrastructure repo.

## Editorial bar (enforced by the rule, summarized)

Timeline-worthy: shipped code, live features, decisions, fixed problems, user directives that drove work. NOT timeline-worthy: process noise, counts, hashes, paths, session UUIDs, routine maintenance. One event = one entry; read the day's file before logging; curate at end of day.
