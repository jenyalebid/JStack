# jstack-host

The API a phone, an iPad or another Mac reaches this machine through.

It serves your terminal sessions: what is running, what each one said, and a
live PTY you can type into from somewhere else. The jRemote app is the client;
this is the half that runs on the Mac.

```bash
curl -fsSL https://raw.githubusercontent.com/jenyalebid/JStack/main/host/install.sh | bash
```

That clones this repository to `~/JStack`, builds a virtualenv beside the
package, installs a **user** LaunchAgent, and prints a pairing code to type
into the app. No `sudo`, no root, nothing written outside your home directory.

If you would rather read it first — and you should, see below — clone and run
it from the checkout:

```bash
git clone https://github.com/jenyalebid/JStack.git ~/JStack
~/JStack/host/install.sh --dry-run     # prints the plan, changes nothing
~/JStack/host/install.sh
```

---

## What this can do to your machine

Read this part. It is the reason the source is public.

A host is not a status page. It **starts, watches and types into terminal
sessions** on the Mac it runs on. Anything holding a valid token can:

- list and read your agent sessions, including full transcripts
- open a new session in a tmux pane and send keystrokes to it
- read markdown files under the fenced roots (`~/.claude`, your agent root,
  `~/Systems`, and any installed plugin checkout) — markdown only, nothing else,
  and the fence is checked after symlinks are resolved
- read commit activity and token spend that the machine already records
- open documents and URLs on the desktop

That is a large amount of trust, so the security model is small enough to
check in an afternoon:

| | |
|---|---|
| **Auth** | One bearer token, required on every route. The only exception is `/api/health`, which answers `{"ok": true}` and says nothing about the machine. |
| **The token** | Generated on this Mac at install, `0600`, in your state dir. It is never sent anywhere. `jstack-host token` prints it; `jstack-host pair` mints a short-lived code instead, which is the better way to add a device. |
| **Brute force** | Failed auth is rate-limited and locked out per client address. |
| **Privileges** | A user LaunchAgent. It runs as you, it cannot escalate, and `launchctl` never sees a root domain. |
| **Network** | Binds `0.0.0.0` by default because a host is reached over a tunnel or across your LAN. Nothing is exposed to the internet unless *you* put it there. |
| **Phoning home** | None. No analytics, no crash reporting, no update ping. The host talks to the devices you paired and nothing else. |
| **Updates** | `git pull` in a checkout you own. There is no auto-updater, and nothing downloads code at runtime. |

The one dependency worth naming: pairing a device over a mesh needs WireGuard
tooling that does not ship in this repository. Without it `jstack-host` reports
`tunnel_pairing: false` and everything else works — you pair over your LAN.

---

## Commands

```
jstack-host install          install the host as a user LaunchAgent
jstack-host pair "iPhone"    a code to type into the app
jstack-host status           installed? loaded? answering?
jstack-host doctor           grade every dependency, with the fix beside each gap
jstack-host serve            run in this terminal instead, in the foreground
jstack-host where            every path this host resolves
jstack-host token            print the bearer token
jstack-host uninstall        remove the LaunchAgent (state and token stay)
```

`doctor` is the one to run when something is missing. Every check names what it
looked for and what to do about it, and a host with gaps still starts — a screen
waiting on a store is not a reason to refuse to come up.

---

## Where things live

| | |
|---|---|
| the code | `~/JStack/host` — the LaunchAgent runs this checkout directly, so `git pull` is the update |
| the virtualenv | `~/JStack/host/.venv` |
| state | `~/.local/state/jremote` — board index, devices, session registry, the token |
| credentials | `~/.local/share/jremote/credentials` — kept apart from state, because state is rebuildable and these are not |
| the LaunchAgent | `~/Library/LaunchAgents/com.jremote.host.plist` |
| logs | alongside state; `jstack-host status` prints the path |

`jstack-host where` prints all of it for the host you actually have, which is
the thing to paste into a bug report.

Every one of these can be moved: `--state-dir` on install, or the
`JREMOTE_STATE_DIR` / `JREMOTE_CREDENTIALS_DIR` environment variables.

---

## Profiles — teaching the host about a machine

Almost everything here is generic: it reads transcripts, scans processes,
drives tmux. What it cannot work out alone is *whose* session it is looking at
— which agents exist, where each one's workspace is, how this machine starts an
engine.

Those questions go through one module, `hostenv.py`, and nowhere else. Out of
the box the **default profile** answers them from the filesystem: every
directory under your agent root is an agent, every directory inside one is a
sub-mode, and Claude Code's own project-dir encoding is reversed against that
root. A machine with nothing configured still names its sessions correctly.

A machine with its own plumbing supplies a module called
`jremote_host_profile` on the import path with a `make_profile()` function.
The host takes its *answers*, never its modules — which is what keeps a
particular machine a profile rather than a fork.

---

## Requirements

- macOS (the installer registers a LaunchAgent)
- Python 3.11+ — Homebrew's is preferred over Apple's `/usr/bin/python3`
- `tmux` and an agent CLI on `PATH` for the session features; `jstack-host
  doctor` grades both and the host runs without them

---

## Development

```bash
cd ~/JStack/host
.venv/bin/python3 -m pip install -e '.[dev]'
.venv/bin/python3 -m pytest tests/
```

The package must never import from whatever tree it happens to sit inside.
`tests/test_jremote_isolation.py` pins that — it walks every module for an
import that escapes the package and for any path resolved by counting parent
directories, which is the constant that keeps working right up until the
package moves and then silently picks a directory that merely exists.

---

## Licence

MIT. See the repository root.
