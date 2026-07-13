# Timeline — Architecture & Usage

The timeline is the single running memory: a sqlite store of seat-tagged entries at `{timeline_dir}/timeline.db`, rendered one-way to daily `{YYYY-MM-DD}.md` view files, written by `bin/log_event`. Downstream consumers split by need: humans and day-level readers (daily briefs, nightly reviews) read the rendered day files; per-seat readers (the SessionStart injector, meta reviews, validators) query the store via `log_event tail`.

## Components

| Piece | Path | Role |
|-------|------|------|
| Writer/query CLI | `bin/log_event` | The only sanctioned writer; also serves seat queries, verdicts, renders, migration |
| Read-half hook | `hooks/session-start-inject.py` | Injects a seat's last N entries on SessionStart (`timeline_inject` config) |
| Format rule | `rules-stage/timeline.md` | Auto-loads (via `/jstack:install-rules` + path-rule-injection) when the timeline is touched — carries the format spec and editorial bar |
| Tests | `tests/log-event.sh`, `tests/timeline-injection.sh` | Hermetic CLI-contract + injection-contract verification |

## Writer contract

```bash
log_event <agent[/submode]> "<headline>" [--at HH:MM] [--date YYYY-MM-DD]
          [--detail "..."]... [--pipeline-task <repo>#<issue>] [--session <sid>]
```

- **Source is the seat:** `agent/submode` (e.g. `alpha/chat`) — stored as split columns; always pass the submode when the seat is known, since seat injection filters on it. A bare `agent` source is legal but invisible to seat tails once seat-tagged entries fill the window.
- **Block format (rendered view):** `HH:MM [agent/submode]` header line, one-line headline, 0–3 `- ` detail bullets. Exactly one blank line between blocks.
- **Chronological rendering:** entries render sorted by `--at`, not insert order. Late-logged events slot into place.
- **`--date`** files under a previous local day.
- **`--pipeline-task <tag>`** consolidates: every existing entry carrying the tag (tagged column or legacy tag-in-text) is replaced by one current entry. The tag is auto-prepended to the headline; the earliest matched timestamp is kept unless `--at` is given. One live entry per task, always current.
- **`--session <sid>`** links the entry to the transcript that produced it.
- Headlines collapse internal newlines/whitespace; details are normalized to `- ` bullets.

## Query / admin contract

```bash
log_event tail <agent[/submode]> [-n N] [--json]     # seat history, oldest→newest; bare agent = all seats
log_event verdict <agent[/submode]> shipped|drift|blocked|empty --note "..."
log_event render [--date YYYY-MM-DD]                 # re-render a day view (repair; writes render automatically)
log_event migrate [--force]                          # import legacy day-md files (strictly non-destructive)
```

Seat tails also match the agent's submode-less rows (pre-seat-era migrations) so seats aren't blind right after migration; those age out of the last-N window naturally. `verdict` stamps an independent review's call on the seat's latest entry — it rides `tail` and injection (`↳ verdict:`), never the day md.

## The store and the view

- Sqlite, WAL — concurrent session-ends write safely.
- The day md is a **one-way render**, regenerated on every write to its date. Never hand-edit it: before rendering, the writer absorbs any md block the db doesn't know (a stray writer, a hand edit, a stale plugin cache mid-upgrade) as a new row instead of erasing it — self-healing against the two-writer clobber, not an editing channel.
- `migrate` imports pre-db history: a file whose re-render is not byte-identical is rolled back and left as md-only archive (`--force` imports its rows anyway, file still untouched).

## Configuration

| Knob | Default | Meaning |
|------|---------|---------|
| `JSTACK_TIMELINE_DIR` | `~/Logs/Timeline` | Directory holding `timeline.db` + the daily view files |
| `timeline_inject` (review config) | none | `{"agent/submode": N, "*/submode": N}` — seats injected on SessionStart |

Self-contained python3 stdlib — no venv, no host imports. Safe to call from hooks, crons, spawned reviews, or interactively.

## Host delegation

A host machine may have its own in-process caller (e.g. a daemon module that logs events). It must **delegate to `bin/log_event`** — a second writer implementation would fork the store from the view. A host that wraps the binary should pin the delegation with a test (same inputs through the wrapper and the binary → byte-identical day files, rows present in the store).

## Editorial bar (enforced by the rule, summarized)

Timeline-worthy: shipped code, live features, decisions, fixed problems, user directives that drove work, durable lessons. NOT timeline-worthy: process noise, counts, hashes, paths, session UUIDs, routine maintenance. One event = one entry; check `log_event tail` before logging; detail bullets earn their place by serving the seat's next run.
