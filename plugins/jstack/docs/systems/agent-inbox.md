# Agent Messaging — Architecture & Usage

Seat-to-seat messaging in exactly two forms: an **update** that obliges
nobody, and a **task** that blocks its sender until it is answered. The store
is a `messages` table in the same sqlite file as the timeline; `bin/msg` is
its only sanctioned writer.

The timeline answers "what did this seat do?". This answers "what did another
seat need from it, and what came back?" — the half a per-seat history cannot
carry, because nobody else can write to your history.

## The design constraint

A mailbox that accumulates is worse than no mailbox. The failure it produces
is specific and bad: an agent opens a chat to do one thing, inherits a pile of
half-relevant requests someone left lying around, and goes off doing those
instead. So the system is built so accumulation is impossible rather than
discouraged:

- An **update** is delivered exactly once and then it is gone. Unread ones
  older than `UPDATE_TTL_DAYS` are never shown to anyone.
- A **task** binds to the single session it was delivered to. No other session
  can see it — not the seat's next session, not a cron worker in that seat,
  not the cockpit.
- A task that reaches nobody is **not filed at all**. The send fails and no
  row is written, because a task nobody is doing is not a message.

There is no state in which mail is waiting to be found.

## Components

| Piece | Path | Role |
|-------|------|------|
| Writer/query CLI | `bin/msg` | The only sanctioned writer; also serves reads |
| Update delivery | `hooks/session-start-inject.py` | Injects unseen updates once, then consumes them |
| Task enforcement | `hooks/stop-inbox-guard.py` | Blocks a session that holds an unanswered task |
| Task delivery | `scheduler/` `add-once` | Books a headless wake — the task's own session |
| Tests | `tests/msg.sh`, `tests/inbox-guard.sh` | Hermetic CLI- and hook-contract verification |

## Writer contract

```bash
msg send @agent[-seat] "<content>" [--wake] [--file PATH]... [--from SEAT]
msg reply <id> "<content>" [--wake] [--file PATH]...
```

- **Subject is the first line**, body is the rest. One content argument.
- **`--wake` is the whole distinction.** Without it, an update. With it, a
  task: reached now, answered now.
- **`--file`** copies into the receiving seat's pad. A file already inside the
  receiving agent's tree is recorded in place rather than copied beside itself
  (a share-sheet drop lands there first).
- **`--from`** overrides the sending seat (`JSTACK_MAIL_FROM` too). Hosts
  filing on a human's behalf pass `--from boss`. Otherwise the seat comes from
  cwd, and failing that from the session's own workspace — so a message sent
  after `cd`-ing into a repo still carries the seat that sent it.

## When a task is legitimate

The bar is that it genuinely needs *them*: their access, their device, context
the sender cannot get, or the operator asked for it. Two failures the wording
exists to prevent, because both look reasonable from inside:

- **Handing off by citation.** A doc names another agent as the owner of an
  area, so work touching that area gets mailed to them. Ownership says who
  carries a thing long-term, never who may touch it — work in front of you is
  yours to finish, in whatever repo it lands in.
- **Mailing a correction.** Something sent earlier turns out to be wrong or
  moot, and the reflex is to send a second message saying so. That doubles the
  traffic to fix the first message. An update will pass on its own; a task is
  answered, not amended.

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

A seat is a directory holding a `CLAUDE.md`. Anything else is refused **at
send time**, because a message filed where no session boots could never be
read. `@boss` is refused: the host's own human channel owns that.

Hyphen resolution tries the longest agent-name match first, then the whole
remaining string as one directory before splitting it — so an agent or seat
whose real name contains a hyphen wins over the same string read as nesting.

## Lifecycle

```
update  ──delivered──>  seen                    (or ages out unseen)
task    ──replied───>   answered
```

That is the entire state machine. There is no close verb, no defer, no
retraction: the reply is the close, and nothing else can be pending.

## Delivery

**An update** waits for the receiver's next session. That is its only rung.

**A task** gets a **scheduler one-shot** — a wake about a minute out — and
fails if one cannot be booked. The task rides inline as the run's prompt behind
an `[inbox:<id>]` marker, so the spawned session needs no injection to see what
it was woken for. Wakes are headless `claude --print`: one turn, then exit.

A task is never typed into a session that is already running. There was a rung
that did exactly that — find the seat's most recently active session and type
the task into its input box — and it is gone. Mail addresses a seat, and a seat
is a chat dir, so every session that rung could ever resolve was a
conversation, and "most recently active" is by construction the one a person is
typing in. It appended a task to a half-written question of the user's and
submitted both as one message. A minute of latency is cheaper than that.

## Enforcement

The Stop hook binds tasks handed to **this exact session** — matched by the
`[inbox:N]` in its own first prompt (the wake it was spawned for), or by
session id for a task bound to one directly. One block per (session, task);
`stop_hook_active` and a
marker written *before* the block make a loop impossible; an unwritable marker
means allow.

It cannot surface anything else. Updates never block. A task belonging to
another session is invisible to it. That is the anti-ambush guarantee, and it
is one SQL clause rather than a policy.

## Injection follows the timeline's gate exactly

Updates are built in the same hook as the timeline block, after the same
single `_is_interactive()` check, and placed *below* it — the seat's own
history is what it builds on; another seat's news is not. Headless work gets
neither.

## Configuration

| Knob | Default | Meaning |
|------|---------|---------|
| `agent_root` (review config) | `~/Agents` | Where seats live |
| `mail.scheduler_home` | package default | Where the scheduler's `schedule.json` lives |
| `mail.category` | `inbox` | Run-category for a spawn |
| `mail.python` | `sys.executable` | Interpreter for the scheduler call |
| `mail.wake` | `true` | `false` disables the spawn rung |
| `JSTACK_INBOX_INJECT_DISABLED` | unset | Kill switch for update injection |
| `JSTACK_INBOX_GUARD_DISABLED` | unset | Kill switch for the Stop block |
| `JSTACK_MAIL_FROM` | unset | Sending seat override |

With no `mail` block at all, updates still work end to end; tasks cannot be
delivered, so they fail at send rather than pretending.

## The store

Same sqlite file as the timeline (`{timeline_dir}/timeline.db`, WAL), own
table, own writer. One store, one backup, one lock discipline; `entries` and
`messages` never touch each other. Schema is created on connect, so the first
`msg` call on a timeline-only db is safe.

## Host delegation

A host may add entrances (a share-sheet drop, a dashboard form) and the live
delivery rung. Those **shell out to `bin/msg`** — a second writer would fork
the source of truth. Direct sqlite reads are fine.
