# jstack-host

The API a phone, an iPad or another Mac reaches this machine through. It serves
your terminal sessions — what is running, what each one said, and a live PTY you
can type into from somewhere else.

## Install

```bash
./install.sh                # from a clone of this repo
./install.sh --dry-run      # print the plan, change nothing
```

Clones nothing you have not already cloned, builds a virtualenv beside the
package, installs a **user** LaunchAgent, and prints a pairing code for the app.
No `sudo`, nothing written outside your home directory.

## Commands

```
jstack-host install          install as a user LaunchAgent
jstack-host pair "iPhone"    a code to type into the app
jstack-host status           installed? loaded? answering?
jstack-host doctor           grade every dependency, with the fix beside each gap
jstack-host serve            run in this terminal instead
jstack-host where            every path this host resolves
jstack-host uninstall        remove the LaunchAgent (state and token stay)
```

## Security

One bearer token, required on every route. `/api/health` is the only exception
and reports nothing about the machine. The token is generated locally at
install, `0600`, and never leaves it. Failed auth is rate-limited per client
address.

Binds `0.0.0.0` by default, because a host is reached over a tunnel or across a
LAN and one bound to `127.0.0.1` is a host only this Mac can see. Nothing is
exposed to the internet unless you put it there.

No analytics, no crash reporting, no update ping. Updates are `git pull` in a
checkout you own; nothing downloads code at runtime.

Markdown reads are fenced to `~/.claude`, the agent root and `~/Systems`, and
the fence is checked after symlinks resolve.

## Paths

| | |
|---|---|
| state | `~/.local/state/jremote` |
| credentials | `~/.local/share/jremote/credentials` |
| LaunchAgent | `~/Library/LaunchAgents/com.jremote.host.plist` |

`jstack-host where` prints them for the host you actually have. All of them move
with `--state-dir`, `JREMOTE_STATE_DIR` or `JREMOTE_CREDENTIALS_DIR`.

## Profiles

Almost everything here is generic: it reads transcripts, scans processes, drives
tmux. What it cannot work out alone is *whose* session it is looking at — which
agents exist, where their workspaces are, how this machine starts an engine.

Those questions go through `hostenv.py` and nowhere else. By default they are
answered from the filesystem: every directory under the agent root is an agent,
every directory inside one is a sub-mode. A machine with its own plumbing
supplies a `jremote_host_profile` module with a `make_profile()` function; the
host takes its answers, never its modules.

## Requirements

macOS, Python 3.11+. `tmux` and an agent CLI on `PATH` for the session features —
`jstack-host doctor` grades both, and the host runs without them.

## Development

```bash
.venv/bin/python3 -m pip install -e '.[dev]'
.venv/bin/python3 -m pytest tests/
```

`tests/test_jremote_isolation.py` pins that the package never imports from
whatever tree it sits inside, and never resolves a path by counting parent
directories.

MIT.
