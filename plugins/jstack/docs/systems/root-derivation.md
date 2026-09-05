# Root Derivation

**One declaration says where the install lives. Everything else is derived.**

## The problem

"Where is everything" used to be answered in six places: a `SCHEDULER_HOME`
environment variable, an `agent_root` key in `scheduler.json`, the same default
restated independently inside three hooks, and absolute machine paths written
into `review.json`. Each was a separate chance to disagree.

On the machine they were written for they agreed, so nothing looked wrong. On a
second machine they did not: half the tools resolved into a private tree that
machine had never had, and the failure was not a crash. Each tool succeeded —
against a different directory. Mail landed in one place, sessions in another,
and the daemon watched a third for activity that was happening somewhere else.

Three literals that agree are not one location. They are three locations that
happen to collide, and the collision ends the moment anyone moves one.

## The answer

`root.py` is the single answer. A host declares one thing; the rest is structure:

```
$JSTACK_ROOT/
├── Agents/         agent workspaces; a seat is Agents/<id>/<seat>/
├── Systems/        Systems/<slug>/SYSTEM.md
├── Config/         scheduler.json, schedule.json, review.json
├── State/          runtime state, runs, locks
├── Logs/           timeline db, tool logs
│   └── Timeline/   timeline.db
└── Credentials/    tokens (never in the checkout)
```

Declaring nothing is a supported install. With no `JSTACK_ROOT`, `root()`
answers `$HOME` and every derived directory equals the literal the tools shipped
with — `~/Agents`, `~/Logs/Timeline`, and so on. Adding the derivation moved no
existing install; that was the requirement it was built under.

There is no walk-up marker search and no probing. A root is stated or defaulted,
never discovered — a search finds a different answer depending on where the
process happened to start.

## Precedence

Every directory resolves through the same three-step ladder, highest first:

| Rank | Source | Example |
|---|---|---|
| 1 | That directory's own env var | `JSTACK_LOGS_DIR=/var/jstack/logs` |
| 2 | That directory's key in the caller's config | `"logs_dir": "/var/jstack/logs"` |
| 3 | Derived from the root | `$JSTACK_ROOT/Logs` |

Per-directory overrides sit *above* the derivation on purpose: an install that
already names its directories explicitly is untouched by the derivation existing.
A live daemon keeps its state where it has always kept it.

| Accessor | Env override | Config key | Derives to |
|---|---|---|---|
| `agents_dir()` | `JSTACK_AGENTS_DIR` | `agent_root` | `{root}/Agents` |
| `systems_dir()` | `JSTACK_SYSTEMS_DIR` | `systems_root` | `{root}/Systems` |
| `config_dir()` | `JSTACK_CONFIG_DIR` | `config_dir` | `{root}/Config` |
| `state_dir()` | `JSTACK_STATE_DIR` | `state_dir` | `{root}/State` |
| `logs_dir()` | `JSTACK_LOGS_DIR` | `logs_dir` | `{root}/Logs` |
| `credentials_dir()` | `JSTACK_CREDENTIALS_DIR` | `credentials_dir` | `{root}/Credentials` |
| `timeline_dir()` | `JSTACK_TIMELINE_DIR` | `timeline_dir` | `{logs_dir}/Timeline` |

`agent_root` is deliberately the pre-existing key name rather than a symmetric
`agents_dir`. Installs already set it; renaming a key every install has set
breaks them for the sake of a tidier table.

`timeline_dir` derives from `logs_dir()`, not from the root. It is nested inside
another derived directory, so it follows that directory's override — point
`JSTACK_LOGS_DIR` somewhere else and the timeline goes with the logs instead of
being stranded in a `Logs/` nobody is writing to.

## The checkout is never a home

`Config/`, `State/`, `Logs/` and `Credentials/` are guarded: resolving one inside
the git checkout that ships this package raises, whether the value came from the
environment, a config file, or the derivation.

This package is distributed in a **public** repository. A credentials directory
rooted in that checkout puts a live token one `git add -A` from being published.
Failing loudly beats silently choosing somewhere safer — a secret written to a
wrong-but-recoverable place can be moved; one written into a public working tree
cannot be unpublished.

Forbidden trees: this file's own directory (a plugin-cache install has no `.git`
but is still wiped on update), plus the nearest enclosing git checkout. The walk
stops before `$HOME`, so a user whose home directory is itself a dotfiles repo
keeps `~` usable.

`Agents/` and `Systems/` are **not** guarded — workspaces and docs may legitimately
live inside a repo.

## What an agent is

The same module carries the one definition, because six places in three repos
used to disagree about it:

> An agent is a directory directly under `agents_dir()` that either carries a
> `CLAUDE.md` itself, or has at least one immediate subdirectory that does.

```
{agent_root}/{Name}/CLAUDE.md            ← identity at the top
{agent_root}/{Name}/{seat}/CLAUDE.md     ← or one seat down, no top-level identity
```

The second case is what every private copy of the gate missed. On a machine laid
out as `Agents/<id>/<seat>/CLAUDE.md` with nothing at the agent's top level, each
copy refused to name the seat the session was sitting in — mail could not say who
sent it, the session-end engine found no agents at all, and the tools read as
simply not working there.

| Function | Answers |
|---|---|
| `is_agent(dir)` | Is this specific directory an agent? |
| `agents(cfg)` | Sorted ids of every agent under `agents_dir()` |
| `resolve_agent(id, cfg)` | That agent's workspace, or `None` — never a path that does not exist |
| `seat_of(path, cfg)` | `(agent, submode)` for a directory inside an agent |
| `seats(id, cfg)` | An agent's seat names |

`resolve_agent` matches exact name, then case-insensitively, then with `-`/`_`
folded away, so `work-ops`, `work_ops` and `workops` are one agent to anyone
typing an id from memory. It returns `None` rather than joining blind: a
nonexistent directory handed to a spawn fails later and further away than the
typo that caused it.

`seat_of` returns the path below the agent, `/`-joined and lowered — seats are
per-directory, so `social/chat` is its own seat, distinct from `chat`.

## Contracts that hold

- **Reads no config file.** Callers hand in their own already-parsed dict, so
  there is exactly one opinion about which file is authoritative: the caller's.
- **Imports nothing from the package.** Stdlib only. It is loaded both as a
  sibling module and by standalone `bin/` scripts, and anything it imported from
  the tree would close a cycle on the first module that imports it back.
- **Never cached at import.** Every function resolves on every call. A daemon
  lives for weeks and the suite changes the environment between cases; a constant
  captured at import answers with the environment of a process start nobody
  remembers.
- **`expanduser()` but never `resolve()`.** A symlinked workspace is legitimate,
  and resolving it changes the path a session reports as its cwd.
- **Consumers degrade.** Every `bin/` script wraps `import root` in a try/except
  and keeps its shipped literal on `ImportError` — an older install is a
  supported state, and a hook that raises wedges the session.
- **`scheduler/config.py` keeps its own copy of the shipping-tree guard**
  deliberately: it must work where `root.py` is absent, and importing the other
  way would be the cycle. If the rule changes, change it in both.

## Test

```bash
plugins/jstack/tests/root.sh
```

Hermetic tmpdir roots with `HOME` redirected: the six-directory derivation, the
env > config > derivation ladder per directory (resolved per call, so a mid-process
env change takes effect), the legacy `agent_root` key, an explicit
`JSTACK_STATE_DIR` outranking the derivation, the guard raising for a data dir
inside the checkout while `agents_dir` inside a repo stays legal, the full agent
taxonomy through `is_agent`/`agents`/`resolve_agent`/`seats`, and a bare-root
proof that every answer comes from a tmpdir holding only `Agents/alice/CLAUDE.md`
— never the machine's own tree.
