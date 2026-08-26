# Agent Inbox — Architecture & Usage

Addressed seat-to-seat messaging with a tracked outcome: one seat sends another
a message, it lands in a mailbox that seat cannot walk past, and closing it
records what was done. The store is a `messages` table in the same sqlite file
as the timeline; `bin/msg` is its only sanctioned writer.

The timeline answers "what did this seat do?". The inbox answers "what is this
seat being asked to do, by whom, and what came of it?" — the half a per-seat
history cannot carry, because nobody else can write to your history.

## Components

| Piece | Path | Role |
|-------|------|------|
| Writer/query CLI | `bin/msg` | The only sanctioned writer; also serves inbox reads and closure |
| Read half | `hooks/session-start-inject.py` | Injects a seat's open items on SessionStart, above the timeline block |
| Enforcement | `hooks/stop-inbox-guard.py` | Blocks the first stop that leaves an item open |
| Live delivery | host command (`mail.deliver_live`) | Optional — types into a running session |
| Wake | `scheduler/` `add-once` | Optional — spawns the receiver when nobody is home |
| Tests | `tests/msg.sh`, `tests/inbox-guard.sh` | Hermetic CLI- and hook-contract verification |

## Writer contract

```bash
msg send @agent[-seat] "<content>" [--wake] [--file PATH]... [--reply-to ID]
                                   [--from SEAT]
msg reply <id> "<content>" [--wake] [--file PATH]...
```

- **Subject is the first line**, body is the rest. One content argument; no
  separate subject to compose.
- **`--wake`** means the receiver acts now. Without it the message waits for
  their next session. This is the sender's call and the only knob they get.
- **`--file`** copies into the receiving seat's pad, so the attachment outlives
  the sender's scratch. A file already inside that pad is recorded in place
  rather than copied beside itself (a share-sheet drop lands there first).
- **`--from`** overrides the sending seat (`JSTACK_MAIL_FROM` env does the
  same). Hosts filing on a human's behalf pass `--from boss`.
- Sender identity otherwise comes from cwd — the same seat resolution the
  injector uses.

## Addressing

`@agent` is the agent's cockpit; hyphens walk down the seat tree; a seat that
holds its own `chat/` resolves to that operator seat.

```
@mario                -> mario/chat
@lynda-social         -> lynda/social/chat      (descends into chat/)
@lynda-pm             -> lynda/pm               (no pm/chat exists)
@jarvis-service-call  -> jarvis/service-call    (hyphen inside a real dir name)
@self                 -> the sending seat
```

A seat is a directory holding a `CLAUDE.md`. Anything else — a pad, a scratch
dir, an unknown agent — is refused **at send time**, because a message filed
where no session boots could never be read. `@boss` is refused too: the host's
own human channel owns that and has its own reply path.

Hyphen resolution tries the longest agent-name match first, then the whole
remaining string as one directory before splitting it — so an agent or a seat
whose real name contains a hyphen wins over the same string read as a nesting.

## Why messages are addressed to a seat

An agent has many seats and most are workers whose whole job is one task. If
mail to `mario` surfaced in every mario seat, a worker would boot, inherit "you
have unread mail, handle it first", and be hijacked by something meant for the
cockpit. So the law binds one seat; the agent-wide view is just a query
(`msg inbox --agent mario`).

## Lifecycle

`unread` → `done` | `deferred`. A deferred item re-opens on its own at
`deferred_until` and is indistinguishable from unread from then on.

**Closing requires `--note`.** That note is the point of the whole system: the
record of what a message actually caused, readable by the sender via
`msg sent`. A close with no note is refused; a double close is a no-op that
reports who closed it and how.

## Delivery — four rungs

Tried in order. Each is allowed to fail; a message is never lost to a broken
rung, it only arrives by a slower one.

1. **SessionStart injection** — the seat's next session.
2. **Stop hook** — any live session, any transport, one turn later. This is the
   universal floor: it needs no knowledge of how the session is running, so a
   raw terminal, a GUI client and a headless run are all reachable.
3. **`mail.deliver_live`** — a host command that types into a running session.
   Fast path, seconds, mid-turn. Absent config → skipped silently.
4. **Scheduler one-shot** — `--wake` with nobody home. The message rides inline
   as the run's prompt with an `[inbox:<id>]` routing marker, so the woken
   session needs no injection to see what it was woken for.

## Enforcement

Injection states the law; the Stop hook is what makes it hold.

- One block per **(session, message)** — a long session gets one block per
  message, not one per turn, and mail arriving mid-session still gets its own.
- `stop_hook_active` and a marker file written *before* the block is emitted
  make a loop impossible; an unwritable marker means allow, never risk it.
- **User-driven sessions** are bound to every open item in the seat.
  **Headless sessions** are bound only to the item they were woken for. A cron
  worker with unrelated mail in its seat stops untouched.

## Injection follows the timeline's gate exactly

The inbox block is built in the same hook as the timeline block, after the same
single `_is_interactive()` check. It is structurally impossible for the inbox
to inject where the timeline would not — they cannot drift. Headless work gets
neither: it was given its task, and the seat's mail is not it.

## Configuration

| Knob | Default | Meaning |
|------|---------|---------|
| `agent_root` (review config) | `~/Agents` | Where seats live |
| `mail.deliver_live` | unset | argv list; `{seat}`/`{text}` substituted. Exit 0 + sid on stdout = delivered |
| `mail.scheduler_home` | package default | Where the scheduler's `schedule.json` lives |
| `mail.category` | `inbox` | Run-category for a wake |
| `mail.python` | `sys.executable` | Interpreter for the scheduler call |
| `mail.wake` | `true` | `false` never books a wake |
| `JSTACK_INBOX_INJECT_DISABLED` | unset | Kill switch for injection |
| `JSTACK_INBOX_GUARD_DISABLED` | unset | Kill switch for the Stop block |
| `JSTACK_MAIL_FROM` | unset | Sending seat override |

With no `mail` block at all the inbox still works end to end — messages file,
inject, and enforce. Only the two delivery rungs that need host knowledge go
quiet.

## The store

Same sqlite file as the timeline (`{timeline_dir}/timeline.db`, WAL), own
table, own writer. One store, one backup, one lock discipline; `entries` and
`messages` never touch each other. Schema is created on connect, so the first
`msg` call on a timeline-only db is safe.

## Host delegation

A host may add entrances (a share-sheet drop, a dashboard form) and the live
delivery rung. Those **shell out to `bin/msg`** — a second writer would fork
the source of truth. Direct sqlite reads are fine.
