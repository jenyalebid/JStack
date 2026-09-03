# Agent Messaging — Architecture & Usage

Messaging in exactly two forms, and the difference between them is what they
are addressed to:

- an **update** is addressed to a **seat** — news for whoever next sits down
  there, obliging nobody;
- a **task** is addressed to a **session** — it spawns one, ties it to the
  session that sent it, and opens a two-way **channel** between them.

The store is a `messages` table in the same sqlite file as the timeline;
`bin/msg` is its only sanctioned writer.

The timeline answers "what did this seat do?". This answers "what did another
seat need from it, and what came back?" — the half a per-seat history cannot
carry, because nobody else can write to your history. A finished exchange is
written back into both seats' timelines, so the two halves meet.

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
- A **reply** binds to the single session that asked for it, and is consumed by
  being shown. Nobody else in that seat is handed someone else's answer.
- A task that reaches nobody is **not filed at all**. The send fails and no
  row is written, because a task nobody is doing is not a message.

There is no state in which mail is waiting to be found.

## Components

| Piece | Path | Role |
|-------|------|------|
| Writer/query CLI | `bin/msg` | The only sanctioned writer; also serves reads |
| Update delivery | `hooks/session-start-inject.py` | Injects unseen updates once, then consumes them |
| Channel enforcement | `hooks/stop-inbox-guard.py` | Blocks a session holding an unanswered task; hands a sender the answer it asked for |
| Session delivery | `scheduler/` `add-once` | Books a headless wake — the task's own session, or a fork-resume of the one that asked |
| Exchange record | `bin/log_event` | One timeline entry per seat when a task is answered |
| Tests | `tests/msg.sh`, `tests/inbox-guard.sh` | Hermetic CLI- and hook-contract verification |

## Writer contract

```bash
msg send @agent[-seat] "<content>" [--wake] [--file PATH]... [--from SEAT]
msg reply <id> "<content>" [--file PATH]...
msg check <id>
```

- **Subject is the first line**, body is the rest. One content argument.
- **`--wake` is the whole distinction.** Without it, an update to a seat. With
  it, a task: a session is spawned for it, tied to yours, and answered.
- **`reply` takes no `--wake`.** Every reply reaches the other end's session —
  that is what a channel is, and a flag would imply it could be opted out of.
- **`check`** is the sender's end: which session took the task, whether it is
  still running, and whether the answer is back.
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
@alice-service-call   -> alice/service-call     (hyphen inside a real dir name)
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
addressed to a SEAT      update ──delivered──> seen        (or ages out unseen)
addressed to a SESSION   task   ──replied───>  answered    (the reply is the close)
                         reply  ──shown─────>  seen        (nothing is owed back)
```

That is the entire state machine. There is no close verb, no defer, no
retraction.

## The channel

`--wake` does not just deliver a message, it opens a channel — and a channel
has two ends that stay tied to each other:

| Column | Holds |
|--------|-------|
| `origin_session` | the session that wrote this message — the far end |
| `bound_session` | the session this message is FOR |
| `wake_job` | the scheduler one-shot booked to carry it there |

On a task, `bound_session` is **NULL until the spawned session claims it**. The
wake is booked, the session does not exist, and naming one before it boots
would be a guess — in the column the whole anti-ambush rule reads. The
receiving session stamps itself when its Stop hook first asks what it owes
(`pending-for --woken`), and from then on `msg check` can say which session
took the work, whether it is still running, and — the state worth having — that
it **finished without answering**, which is a gap rather than a slow reply.

The reply goes back to `origin_session`, not to its seat. A seat's next session
is a different conversation; handing it an answer to a question it never asked
is how a channel turns into a stranger's note. Two paths race for it, both
correct, and neither needs a guess about which sessions are alive:

- the asking session is still running and takes it at its **next stop** (the
  Stop hook), which also cancels the wake below;
- it has already exited, and a **fork-resume wake** brings that conversation
  back to receive the answer — `--resume-session`, booked against the workspace
  that session *started* in, since that is what names its transcript.

The fork is told it is a fork. The conversation it came from may still be open
in front of a person, and a fork that assumes it is the only copy redoes work
or reports to someone who never asked it anything.

Either end can reply again — to clarify, to push back, to ask the one thing
that was missing — and each turn reaches the other end the same way. Past
`MAX_CHANNEL_TURNS` (8) the messages still file and still read, but nobody is
woken for them: two agents can always find one more thing to say, and each turn
is a spawned session on a machine that runs unattended.

If the asking session left no transcript, the reply says so and degrades to an
update for the seat. It never pretends at a channel it cannot reach.

## Delivery

**An update** waits for the receiver's next session. That is its only rung.

**A task** gets a **scheduler one-shot** — a wake about a minute out — and
fails if one cannot be booked. The task rides inline as the run's prompt behind
an `[inbox:<id>]` marker, so the spawned session needs no injection to see what
it was woken for. Wakes are headless `claude --print`: one turn, then exit, and
booked `--delete-after-run` because a spent one-shot is scheduler litter. The
record of the exchange is the `messages` row, which nothing deletes, and the
timeline entries written at close.

A task is never typed into a session that is already running. There was a rung
that did exactly that — find the seat's most recently active session and type
the task into its input box — and it is gone. Mail addresses a seat, and a seat
is a chat dir, so every session that rung could ever resolve was a
conversation, and "most recently active" is by construction the one a person is
typing in. It appended a task to a half-written question of the user's and
submitted both as one message. A minute of latency is cheaper than that.

Note what survives that: a **stop** is still a safe moment to hand a running
session something, because it is the harness's own continuation channel and
touches nothing a person is part-way through typing. What was fatal was
choosing the session by heuristic and typing into its input box. The channel
delivers to a session named on the row, through the hook.

## Enforcement

The Stop hook serves both ends. It binds messages addressed to **this exact
session** — matched by the `[inbox:N]` in its own first prompt (the wake it was
spawned for), or by session id for a row bound to it, which is how an answer
finds the session that asked. One block per (session, message);
`stop_hook_active` and a marker written *before* the block make a loop
impossible; an unwritable marker means allow.

A **task** blocks until answered. A **reply** blocks once to be read and is
consumed by being shown — nothing is owed back, and acknowledging it would be
traffic rather than work.

It cannot surface anything else. Updates never block. A message belonging to
another session is invisible to it. That is the anti-ambush guarantee, and it
is one SQL clause rather than a policy.

## The exchange is on record

When a task is answered, one timeline entry is written into each seat — the
asker's ("Asked X — …", carrying what came back) and the doer's ("Answered Y —
…"). Guarded by `logged_at` so it happens once however many turns follow, and
stamped only after the write lands, so a failure leaves it retriable rather
than silently swallowed.

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
| `mail.wake` | `true` | `false` disables every spawn — tasks then fail at send |
| `JSTACK_INBOX_INJECT_DISABLED` | unset | Kill switch for update injection |
| `JSTACK_INBOX_GUARD_DISABLED` | unset | Kill switch for the Stop block |
| `JSTACK_MAIL_FROM` | unset | Sending seat override |

Two constants in `bin/msg` rather than config, because they are judgements
about how a channel behaves and not facts about a machine: `MAX_CHANNEL_TURNS`
(8) and `REPLY_WAKE_MINUTES` (3, how long a reply waits for the asking session
to come and take it before a fork is woken for it).

With no `mail` block at all, updates still work end to end; tasks cannot be
delivered, so they fail at send rather than pretending.

## The store

Same sqlite file as the timeline (`{timeline_dir}/timeline.db`, WAL), own
table, own writer. One store, one backup, one lock discipline. Schema is
created on connect, so the first `msg` call on a timeline-only db is safe.

`messages` and `entries` are written by their own binaries and nothing reaches
across: the one crossing is at close, where `msg` shells out to `log_event` to
put the finished exchange in both seats' history. Every other read and write
stays on its own table.

## Host delegation

A host may add entrances — a share-sheet drop, a dashboard form. Those **shell
out to `bin/msg`**: a second writer would fork the source of truth. Direct
sqlite reads are fine.
