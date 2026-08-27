# Repo Seats

**A session whose cwd is a repo an agent owns runs as that agent.**

## The problem

A seat is a directory. `Agents/WBIS/chat/` is a seat; the session's cwd names it,
and everything keyed to a seat follows — the timeline injected on entry, the
entry written on exit, the auto-memory the agent accumulates.

A session started by an IDE never gets that choice. Xcode (and every editor that
embeds a coding agent) fixes cwd to the checked-out repo, so a WBIS session
launched from the IDE lands in `WBIS-iOS/`, which is outside `{agent_root}`,
which resolves to no seat at all. That session:

- starts cold — no timeline, no idea what the agent did yesterday
- ends silent — no entry written, so the work never joins the running memory
- remembers separately — auto-memory files under the repo's own project key,
  invisible to the cockpit and vice versa

The same hole swallows disposable worktrees (`WBIS-iOS-issue-288/`).

## The answer

The ownership map already exists. The agent registry records the repos each agent
owns — the same map `/jstack:day-audit` dispatches on — so a repo resolves back
to a seat instead of being treated as nobody's.

```
{agent_root}/agents.json
  "wbis": { "workspace": ".../Agents/WBIS/chat", "repos": ["WBIS_iOS", ...] }

/Users/.../WBIS-iOS  →  wbis/chat
```

The seat is the agent's own registered `workspace`, read back as a seat under
`{agent_root}`. IDE work joins the agent's one running memory rather than forking
a second history nobody thinks to read.

## Resolution

`repo_seat.py`, first hit wins:

| # | Rule | Carries |
|---|---|---|
| 1 | git toplevel of cwd, else cwd | a subdirectory of a checkout |
| 2 | basename vs each entry's `repos`, normalized | the ordinary case |
| 3 | `remote.origin.url` basename, normalized | a worktree or a differently-named clone |
| 4 | longest normalized prefix on a `-` boundary | `<Repo>-issue-42` with no origin |

Normalized = case folded, `_` and `-` equivalent, any leading `owner/` and a
trailing `.git` dropped — so `WBIS_iOS`, `WBIS-iOS` and
`git@github.com:org/WBIS_iOS.git` are one name.

Two rules hold the edges: **a real seat directory always wins** — the registry is
consulted only after the normal `{agent_root}`-relative resolution comes up
empty, so no registry line can rename an agent out of its own cockpit. And
entries marked `"active": false` never claim a repo.

```
repo-seat                    # seat of the working directory, or exit 3
repo-seat <dir> --json       # {agent, submode, seat, repo, via, dir}
```

`via` names the rule that matched — the fastest way to see why a directory did
or didn't resolve where you expected.

## Wiring an IDE

`bin/ide-bridge` handles the second half: an IDE that embeds Claude Code
downloads a private copy of the CLI and runs a sign-in of its own, so the
session gets none of the host's login, version, plugins, hooks, skills or
history — a capable stranger every time, no matter how well its seat resolves.

The way in is **ACP**. Xcode and Zed both run any Agent Client Protocol agent as
a plain subprocess with the open project as its working directory — which is
both halves at once: our own CLI, and the cwd the seat resolves from.
`bin/acp-agent` is that subprocess.

```
ide-bridge status      what is wired, which repos resolve, what owns nothing
ide-bridge install     link repo memory to seats; print the ACP fields
ide-bridge uninstall   drop the legacy home-directory override
```

Registration is one manual step, because the IDE stores it in its own
preferences with no documented key. In **Xcode**: Settings ▸ Intelligence ▸
*Add an Agent…* ▸ *Add an ACP Agent*, with `bin/acp-agent` as the Executable and
every other field empty — not the *Get* buttons above it, which are the IDE's
own download-and-sign-in path. `install` prints the exact values and `status` reports
whether it has been done. **One registration covers every repo** — the seat is
resolved per launch from the project the IDE opened.

### What acp-agent has to fix

`@zed-industries/claude-code-acp` translates the protocol, and nothing more; the
session is whatever CLI it spawns. Two things decide whether that session is
yours:

**The adapter bundles its own CLI** inside the Agent SDK, and that copy loads no
plugins — no hooks, so no seat, no timeline, no identity, and the SDK's model
defaults rather than your settings. `CLAUDE_CODE_EXECUTABLE` points it at the
CLI you actually installed. This is the difference between a session that
answers *"I'm on the main conversation seat"* and one that answers *"seat
`wbis/chat`"*.

**An IDE launches subprocesses with a login-less environment** — PATH is usually
just `/usr/bin:/bin:/usr/sbin:/sbin`, so node, `claude` and the adapter are all
invisible, and `USER` may be unset, which alone is enough to make the keychain
read fail and the session start signed out with nothing on screen to say why.
`acp-agent` rebuilds both before resolving anything. For the same reason it
carries `from __future__ import annotations`: that PATH resolves `python3` to
the system 3.9, which cannot evaluate `X | None` at import time.

Auth then needs no work at all. With `CLAUDE_CONFIG_DIR` left alone the CLI
reads the login keychain, so the IDE session is signed in because your terminal
is. There is no second sign-in and no download.

### The override that doesn't work

An earlier approach pointed Xcode's **built-in** agent at the host config
directory with `IDEChatOverrideAgenticHomeDirectory`. It cannot work, for two
reasons worth recording so they are not re-derived:

- **Setting `CLAUDE_CONFIG_DIR` at all moves Claude Code off the login
  keychain**, onto a credentials file in that directory. To any path, the host's
  own included. The override signs the session out rather than in.
- **The built-in agent authenticates through a sign-in of the IDE's own**, held
  under its own keychain services and handed to the CLI as
  `CLAUDE_CODE_OAUTH_REFRESH_TOKEN`. No config directory satisfies it, so the
  setup screen stays up no matter how the bridge is wired.

`status` flags the key if it is still set; `uninstall` removes it.

### Memory

`install` links each owned repo's auto-memory directory to its agent's, so the
agent remembers in the IDE what it learned in the terminal. Memory is never
overwritten: a repo already holding memories of its own is reported as a
`SPLIT BRAIN` and the merge is left to a human, because two directories of
remembered facts are not something a tool should silently pick a winner for.

`status` closes with the repos **no** entry owns. Those open in the IDE as no
agent — the fix is a line in a registry entry's `repos`, not a code change.

## Identity

A cockpit session loads its role by standing in it — CLAUDE.md walk-up climbs
from cwd to the workspace and picks up the shared protocol, the agent's role
file, and the seat's. A session in a repo can't: the workspace is a *sibling* of
the checkout, not an ancestor, so walk-up passes it by and the session arrives
with the repo's docs and none of its own identity.

So a session that reached its seat through a repo is handed those three files as
a `<jstack-identity>` block — the same answer walk-up would have given, applied
to the layout the IDE forces. A session already standing in the workspace gets
nothing extra; paying for the role twice is the only thing that would achieve.

`inject_identity: false` in the config turns it off and leaves the timeline
alone.

## Liveness

Timeline injection fires only into live human sessions — a headless spawn must
never be handed a history it didn't ask for. Liveness is read off the process
ancestry, and an IDE breaks that test: an editor drives its embedded agent from
a window, so nothing in the chain (`claude` → `Xcode` → `launchd`) ever holds a
tty, and a human sitting in Xcode reads as a daemon.

So an IDE ancestor counts as live, the same way a controlling terminal does.
The set is `JSTACK_IDE_ANCESTORS` (default `Xcode`), matched on the ancestor's
command name. Without this the whole feature resolves correctly and then
injects nothing, which is the failure mode worth knowing about.

## Verifying

`pict` renders everything a session started in a directory would receive, and
resolves repo seats the same way — so it answers "what will my IDE session
actually see" without opening the IDE:

```
pict /path/to/repo | grep -i timeline
repo-seat /path/to/repo --json
ide-bridge status
```

## Config

Read from the session-end engine's config (`JSTACK_REVIEW_CONFIG`, default
`~/.claude/jstack/review.json`):

| Key | Default | Use |
|---|---|---|
| `agent_root` | `~/Agents` | where seats live |
| `agent_registry` | `{agent_root}/agents.json` | the ownership map |
| `repo_root` | parent of `agent_root` | where `ide-bridge` scans for repos |

No registry, or no entry owning the directory → nothing resolves and every
caller behaves exactly as it did before. The feature is additive by
construction.

## Test

`tests/repo-seat.sh` — hermetic: a temp agents tree, a temp registry, real git
checkouts, a temp timeline. Covers each resolution rule, inactive entries,
workspace-derived seats, seat-beats-registry precedence, the end-to-end
SessionStart injection in an owned repo, and the no-registry no-op.
