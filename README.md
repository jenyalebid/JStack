# jStack

jStack is two things that install together:

- **A Claude Code plugin** — slash commands, rules and self-running systems for
  agent workflows, built around a simple convention: an agent is a directory
  with a `CLAUDE.md`, and everything else (timeline, scheduler, inbox) hangs off
  that. No paths are hardcoded; it works on any machine once you say where your
  workspaces live.
- **A way to reach that Mac from your phone, iPad, or another Mac** — a small
  token-authed host that serves your terminal sessions (what's running, what
  each one said, a live PTY you can type into), and a Mac app that connects to
  it from anywhere.

Neither half needs the other. You can run the plugin and never install the host,
or install the host on a headless Mac with no agent workspaces at all.

## Install

One command on a fresh Mac. It installs the plugin, the host, the menu bar item
and the Mac app, then runs `jstack-doctor` so it ends on a verdict, not an
assumption:

```bash
curl -fsSL https://raw.githubusercontent.com/jenyalebid/jStack/main/install.sh | bash
```

It asks two things — where your stack lives and what to name your first agent —
and runs to the end. Everything else has one sensible answer and is a flag:

```bash
./install.sh --dry-run            # print the plan, change nothing
./install.sh --yes --agent Ada    # unattended, everything
./install.sh --no-app             # skip a piece: --no-app --no-host --no-menubar --no-scheduler
```

It refuses to run as root, never overwrites a file it didn't write, and touches
nothing outside the checkout, `~/.claude`, your agent root, `~/Applications` and
one appended shell-profile line. Every step is idempotent, so re-running it is
how you update.

**Dependencies are installed only if missing and never removed** — Claude Code,
git, Python, `python-dateutil`. An install that finds them present leaves them
exactly as they were.

The Mac app is closed source; its installer is not. Before anything lands in
`/Applications` it verifies the download's SHA-256 against the signed manifest,
checks the code signature, asks Gatekeeper the same question macOS asks on first
launch, and pins the signing team. There is no skip-verify.

### Just one piece

- **Plugin only** — `claude plugin marketplace add jenyalebid/jStack` then
  `claude plugin install jstack@jStack`.
- **Host only** (a headless Mac) — `host/install.sh`.
- **App only** (against a host that already exists) — `app/install.sh`.

## What you get

### Slash commands, namespaced `/jstack:*`

| Command | What it does |
|---|---|
| `/work` | Get battle-ready on a topic — load the relevant skills, read the core files, report a grounded lay of the land |
| `/handoff` | Hand this session to a fresh terminal with context preserved |
| `/splitoff` | Copy this session into a new terminal under a fresh id, diverging forward |
| `/audit` | Spawn a trust-nothing auditor that re-verifies this session's work from source |
| `/push` | Commit and push this session's edits, grouped by unit of work |
| `/report` | Close out a task — settle every finding as a commit or a filed issue, then report |
| `/issue` | Work a GitHub issue end to end — read it, build the fix in a worktree, open the PR |
| `/task` | Hand a unit of work to an agent — files the task issue, spawns the executor |
| `/recall` | Replay what was done on a day or period, by agent or across the whole op |
| `/day-audit` | Re-verify a day's shipped work across every repo against the timeline |
| `/tag` · `/pict` · `/print` · `/showme` | Timeline tagging, injected-context render, transcript path, result viewer |
| `/install-rules` | Symlink the bundled path-scoped rules into `~/.claude/rules/` |

### Systems that run themselves once installed

- **Timeline** — the running memory. Each session logs a seat-tagged entry
  (`log_event`); the last few are injected into that seat's next session, so
  sessions start sighted instead of cold.
- **Session-end self-write** — when a session ends inside an agent workspace, a
  hook resumes it for one turn to write its own timeline entry.
- **Agent inbox** — addressed seat-to-seat messages (`msg send @agent`) that
  land at the top of the receiver's next session and can't be walked past until
  answered.
- **Scheduler** — a daemon that fires one-time and recurring agent sessions on a
  schedule, with watchdogs on hung turns and catch-up after downtime.

Under the hood, skills call 18 bundled `bin/` adapters (`acp-agent`,
`dub-session`, `file-followup`, `file-issue`, `ide-bridge`, `jstack-doctor`,
`jstack-scheduler`, `log_event`, `msg`, `open-artifact`, `open-terminal-here`,
`pict`, `place-issue`, `repo-seat`, `schedule-self`, `session-files`,
`session-review-spawn`, `task-create`) as bare commands. 17 path-scoped rule files
auto-load by glob once installed with `/install-rules`.

### The host and the app

The host is a token-authed HTTP/SSE API bound so it's reachable over the tunnel,
installed as a per-user LaunchAgent (no sudo, nothing outside your home). Its CLI
is `jstack-host` — `pair`, `status`, `mode`, `open`, `attach`, `doctor`,
`uninstall`. The menu bar item shows whether it's running and owns the device
list. The Mac app is the client that connects to it.

## Reaching your Mac from anywhere

A host is one of three shapes, and the only difference between them is how a
device that is **not on your network** reaches it. Off-network access always
rides an encrypted WireGuard tunnel — the modes differ only in which end stands
that tunnel up.

- **local** — the default a fresh install lands in. Reachable only on your own
  network; nothing off it can get in. Honest: a Mac that's done nothing to be
  reachable isn't.
- **open** — this Mac holds its own way in. It publishes a WireGuard endpoint the
  outside dials.
- **managed** — this Mac dials *out* to another Mac that's already a hub, and
  rides its mesh. Every device paired to that hub reaches this one with no setup
  of its own.

### Making one Mac reachable (open mode)

For a single Mac, run **`jstack-host open`**. It walks the whole thing:

1. It finds your Mac's LAN address and your router's public IP (by asking the
   router directly — nothing phones out to a third party).
2. It forwards **one UDP port** on the router — automatically where the router
   supports it, otherwise printing the exact one-line rule to enter by hand. Only
   that silent tunnel port is ever exposed; the HTTP API is never forwarded, so
   off-network traffic rides the encrypted tunnel or it doesn't arrive.
3. It prints the endpoint and the single line to stand up the tunnel:
   `sudo bash install_hub.sh --endpoint <your-public-ip>:51820`
   (one sudo, once; prereq `brew install wireguard-go wireguard-tools`).
4. Pair your phone while both are on the same wifi (the app's *Add a Device*).

Then **prove it**: a WireGuard port is silent, so reachability can't be shown by
scanning from outside. Instead you produce the proof — take the phone off wifi
onto cellular and open the app. The moment its handshake lands from the internet,
`jstack-host open --verify` flips to *verified*. Until then it says "declared,
not verified" — it won't claim a router in between forwards packets when it can't
see that.

### Joining an existing hub (managed mode)

If you already have a Mac acting as a hub, skip all of the above: run
**`jstack-host attach <code>`** on the new Mac, where `<code>` comes from the
hub. It dials out, joins the mesh, and every device already paired to that hub
reaches the new Mac — no router touched.

`jstack-host mode` reports which shape a Mac is in at any time.

## Update

```bash
claude plugin marketplace update jStack
claude plugin update jstack
```

Or just re-run `install.sh` — it's idempotent and upgrades what has drifted.
Symlinked rules track new content automatically; if one ever goes stale after a
version bump, `/install-rules --force`.

## Uninstall

Only jStack's own artifacts come off; dependencies are left alone.

```bash
app/install.sh --uninstall          # remove the Mac app (paired hosts stay)
host/install.sh --uninstall         # remove the host LaunchAgent (state + token stay)
host/install.sh --purge             # ...and delete state, token and credentials
jstack-scheduler uninstall          # remove the scheduler daemon
claude plugin uninstall jstack
claude plugin marketplace remove jStack
```

Then drop any rule symlinks still pointing into a jStack checkout:

```bash
for f in ~/.claude/rules/*.md; do
  [ -L "$f" ] && readlink "$f" | grep -q jstack/rules-stage && rm "$f"
done
```

## Working on jStack itself

This repo is public, and `.git/hooks/` doesn't travel with a clone. Restore the
commit-identity gate first, so a commit under an off-list author email is refused
before it exists:

```bash
ln -s ../../plugins/jstack/githooks/pre-commit .git/hooks/pre-commit
```
