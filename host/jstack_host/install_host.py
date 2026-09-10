"""Turn this Mac into a jRemote host — one user LaunchAgent, no admin.

    python3 -m jstack_host.install_host status
    python3 -m jstack_host.install_host install
    python3 -m jstack_host.install_host uninstall

`server.py` is the host; this is what makes it survive a logout, a crash and a
reboot without anyone typing a command again. A **user** LaunchAgent in
`~/Library/LaunchAgents`, bootstrapped into `gui/$UID` — no root, no
`sudo`, nothing written outside the user's own tree. That is not a convenience:
an install that needs a password is an install that can be refused, and a host
is a thing someone should be able to add and remove on their own machine
without asking anyone.

The agent runs the interpreter that ran this installer, against the package
this module is in. Nothing is copied, nothing is unpacked, no path is guessed —
a host installed from a JStack checkout runs that checkout, and one installed
from an unpacked payload runs the payload. It is the one arrangement that
cannot come up pointing at a Python that no longer exists.

Binds `0.0.0.0` by default. A host is reached over the mesh, and mesh traffic
arrives on a tunnel interface, not on loopback — a host bound to `127.0.0.1` is
a host only the machine it runs on can see. Every route already requires the
bearer token; `/api/health` is the deliberate exception and says nothing about
what is on the machine.

Refuses to install over a port *something else* answers on. On this Mac that
something is the dashboard, which serves the same API on 9090 — a second host
against the same state dir is two reapers closing each other's sessions, and
`server.acquire_lock` would refuse it a moment later anyway. Catching it here
means the refusal comes before a LaunchAgent exists to clean up. A host this
installer put there itself is not somebody else: re-running upgrades it in
place, which is the only way a payload Mac ever gets new code.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import hostenv

LABEL = "com.jremote.host"

# The package's parent — the directory `jstack_host.server` is importable
# from, which is what the agent needs as its working directory. Derived, never
# configured: an installer that took this as a flag could be pointed at a tree
# it is not the one running out of.
PACKAGE_ROOT = hostenv.package_root()

DEFAULT_PORT = 9090
DEFAULT_BIND = "0.0.0.0"


# ── paths ──

def plist_path(label: str = LABEL) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def log_dir() -> Path:
    """Where the agent's stdout and stderr land.

    Under the host's own state dir rather than a repo `Logs/`: the standalone
    profile has no repo, and a log path that only exists on this Mac is a host
    that will not start on any other.
    """
    return hostenv.state_dir() / "logs"


# ── the agent ──

def carried_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """The `JREMOTE_*` overrides the agent must run under.

    Whatever the installer resolved the token and the state dir against, the
    agent has to resolve the same way — and a launchd job inherits none of the
    shell that installed it. Carrying them makes the plist say out loud what
    was only implied by an exported variable, which is also the difference
    between an install that survives the terminal it was typed in and one that
    comes up on the wrong profile after a reboot.
    """
    env = source if source is not None else dict(os.environ)
    return {k: v for k, v in env.items() if k.startswith("JREMOTE_")}


def installed_environment(path: Path | None = None) -> dict[str, str]:
    """The `JREMOTE_*` overrides the installed agent actually runs under.

    `status` and `doctor` are typed into a shell, and a shell has none of the
    plist's environment: read from there they would resolve the profile, the
    agents root and the state dir on their own and report a host that does
    not exist — a registry looked for under $HOME, a state dir with no token.
    The plist is the one record of what the host was installed to be, so
    those commands adopt it before they look at anything.
    """
    path = path or plist_path()
    try:
        with path.open("rb") as fh:
            job = plistlib.load(fh)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return {}
    env = job.get("EnvironmentVariables") if isinstance(job, dict) else None
    if not isinstance(env, dict):
        return {}
    return {str(k): str(v) for k, v in env.items() if str(k).startswith("JREMOTE_")}


def installed_port(path: Path | None = None) -> int | None:
    """The port the installed agent is actually serving on, or None.

    Read off `ProgramArguments`, which is the only record of it — the port is
    an argv flag, not an environment variable, so `installed_environment()`
    cannot see it. Anything that builds an address for this host has to ask
    here rather than assume `DEFAULT_PORT`: a machine installed with `--port`
    would otherwise be handed a URL for a port nothing is listening on, and
    the failure arrives later, somewhere else, as "the app cannot reach it".
    """
    path = path or plist_path()
    try:
        with path.open("rb") as fh:
            job = plistlib.load(fh)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return None
    argv = job.get("ProgramArguments") if isinstance(job, dict) else None
    if not isinstance(argv, list):
        return None
    argv = [str(a) for a in argv]
    try:
        value = int(argv[argv.index("--port") + 1])
    except (ValueError, IndexError):
        return None
    return value if 1 <= value <= 65535 else None


def adopt_installed_environment(path: Path | None = None) -> None:
    """Apply `installed_environment()` beneath whatever the shell already
    set — an explicit export or `--state-dir` still wins — and re-resolve."""
    adopted = False
    for k, v in installed_environment(path).items():
        if k not in os.environ:
            os.environ[k] = v
            adopted = True
    if adopted:
        hostenv.reset_profile()


def render_plist(*, label: str = LABEL, port: int = DEFAULT_PORT,
                 bind: str = DEFAULT_BIND, interpreter: str | None = None,
                 working_dir: Path | None = None,
                 state_dir: Path | None = None,
                 logs: Path | None = None,
                 environment: dict[str, str] | None = None) -> bytes:
    """The LaunchAgent, as it will be written.

    Separate from writing it so the shape is a thing tests can assert. What it
    must never grow is a shell: `ProgramArguments` is exec'd directly, so an
    address or a state dir with a space in it is an argument and not two.
    """
    logs = logs or log_dir()
    # PATH from the one seam, never a list written here. launchd hands a job
    # almost nothing, and a host that cannot resolve `claude` or `tmux` serves
    # a board it can never act on — which is exactly the 2026-07-09 outage,
    # six hand-copied PATHs that all missed the binary moving to ~/.local/bin.
    env = {"PATH": hostenv.spawn_path()}
    env.update(carried_environment() if environment is None else environment)
    # Always pinned, not only when `--state-dir` asked for one. launchd builds
    # the job's HOME from the user record rather than from the shell that
    # installed it, so leaving this out means the installer and the host each
    # derive the state dir on their own and merely happen to agree. When they
    # don't, the host comes up, serves `/api/health`, and 401s every route with
    # `provisioned: false` — while the token it is looking for sits on disk
    # where the installer put it and printed it. Nothing about that failure
    # points at the state dir.
    env["JREMOTE_STATE_DIR"] = str(state_dir if state_dir is not None
                                   else hostenv.state_dir())

    # Pinned for the same reason the state dir is: launchd builds the job from
    # the user record, not the shell that installed it, so a daemon that read
    # the agents root on its own would fall through `$HOME/Agents` to nothing
    # on any install whose agents live under `$JSTACK_ROOT`. Left unpinned,
    # `active_agents()` came up reading the whole home directory as agents and
    # `welcome` opened its first session in a CI checkout — the blank thread.
    # Resolved now, while the installing shell still has `$JSTACK_ROOT`, and
    # only when it does not already carry an explicit override.
    env.setdefault("JREMOTE_INSTANCE_ROOT", str(hostenv.instance_root()))

    job = {
        "Label": label,
        "ProgramArguments": [
            interpreter or sys.executable,
            "-m", "jstack_host.server",
            "--host", bind,
            "--port", str(port),
        ],
        "WorkingDirectory": str(working_dir or PACKAGE_ROOT),
        "RunAtLoad": True,
        "KeepAlive": True,
        # This job carries live keystrokes and terminal frames, so its latency
        # *is* the product — a host that answers a second late is a terminal
        # that types a second late. Omitting the key leaves launchd's default
        # of `Standard`, whose whole definition is a job that may be throttled
        # to keep the foreground responsive; on a Mac building in Xcode that
        # is exactly when the phone is holding a terminal open, and exactly
        # the job launchd would pick to slow down. `Interactive` is the one
        # class launchd exempts from those limits. It is also the only lever
        # available here: negative `Nice` needs root, and a user LaunchAgent —
        # which this is precisely so it installs without admin — cannot ask.
        "ProcessType": "Interactive",
        "StandardOutPath": str(logs / "host.out"),
        "StandardErrorPath": str(logs / "host.err"),
        "EnvironmentVariables": env,
    }
    return plistlib.dumps(job)


# ── the token ──

def mint_token(path: Path) -> tuple[str, bool]:
    """The bearer token this host will expect. Returns (token, minted).

    Never overwrites. A token already on disk is one the app on the user's phone is
    already carrying, and replacing it during an install would lock out every
    device that was working a second earlier — the failure would look like the
    install broke the host.
    """
    try:
        existing = path.read_text().strip()
        if existing:
            return existing, False
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token)
    path.chmod(0o600)
    return token, True


# ── launchctl ──

def _domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def is_loaded(label: str = LABEL) -> bool:
    return _launchctl("print", f"{_domain()}/{label}").returncode == 0


def wait_unloaded(label: str, seconds: float = 30.0) -> bool:
    """Block until `label` has left the domain, or give up.

    `bootout` returns when the request is queued, not when the job is gone: a
    live host on this Mac was measured leaving between five and sixteen seconds
    after the call returned, because it shuts its server down first. Waiting on
    the fact is what makes the budget generous without costing anything — an
    install onto a free port asks once, is told no job, and goes on.

    Bounded, and the caller does not check: a job that will not leave is not a
    reason to hang the installer. `bootstrap` retries after this and reports
    the real error if the domain still refuses.
    """
    deadline = time.monotonic() + seconds
    while is_loaded(label):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.25)
    return True


def bootstrap(label: str, path: Path, attempts: int = 8,
              delay: float = 0.75) -> subprocess.CompletedProcess:
    """Load the agent, retried in case the job it replaces is still going away.

    The wait above is what normally closes the gap; this is the safety net for
    a domain that reports the label gone a moment before it will accept a new
    one, which still fails with `Bootstrap failed: 5: Input/output error`.
    """
    boot = _launchctl("bootstrap", _domain(), str(path))
    for _ in range(attempts - 1):
        if boot.returncode == 0:
            break
        time.sleep(delay)
        boot = _launchctl("bootstrap", _domain(), str(path))
    return boot


def port_answers(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    """Is anything listening there right now."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def health(port: int, timeout: float = 1.0) -> dict | None:
    """What the host on this port says it is, or None.

    `/api/health` and not a token-bearing route on purpose: this runs during
    provisioning, when the caller's whole question is whether anything came up.
    """
    url = f"http://127.0.0.1:{port}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_for_health(port: int, seconds: float = 20.0) -> dict | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        got = health(port)
        if got:
            return got
        time.sleep(0.5)
    return None


# ── commands ──

def install(*, port: int = DEFAULT_PORT, bind: str = DEFAULT_BIND,
            label: str = LABEL, state_dir: Path | None = None,
            force: bool = False, out=None) -> int:
    # Resolved at call time, never bound as a default: a default would capture
    # whatever `sys.stdout` was at import, which is not the stream a caller
    # redirecting output is watching.
    out = out or sys.stdout
    if state_dir is not None:
        os.environ["JREMOTE_STATE_DIR"] = str(state_dir)
        hostenv.reset_profile()

    # A port that answers is only a conflict when what answers is somebody
    # else's. Our own LaunchAgent serving `jremote-host` there is the machine
    # this installer already set up, and re-running is how it takes new code —
    # the upgrade `jremote_host_install.command` promises in its own header.
    # Refusing it made that promise impossible to keep on any Mac that had ever
    # been installed, which is every Mac it is for. The dashboard the refusal
    # exists for is not this: it answers on 9090 under its own label, so
    # `is_loaded` is what tells the two apart.
    upgrading = False
    if port_answers(port):
        served = health(port)
        upgrading = (served or {}).get("service") == "jremote-host" and is_loaded(label)
        if not (upgrading or force):
            who = (served or {}).get("service") or "something"
            print(f"refusing: {who} is already answering on {port}.", file=sys.stderr)
            print("  A Mac already serving the host API there does not need a "
                  "second one — pick another --port, or --force if you mean it.",
                  file=sys.stderr)
            return 1
        if upgrading:
            print(f"upgrading the host already answering on {port}.", file=out)

    state = hostenv.ensure_state_dir()
    logs = log_dir()
    logs.mkdir(parents=True, exist_ok=True)
    token, minted = mint_token(hostenv.token_path())
    if minted:
        # A token file written *now* has no history to grandfather. Say so
        # while the fact is still known — see devices.adopt_master_token.
        # Never fatal: a registry that could not be opened is a device list
        # that reads oddly, not an install that failed.
        try:
            from . import devices
            devices.adopt_master_token(token)
        except Exception as exc:  # noqa: BLE001
            print(f"  note: could not register this Mac's own token ({exc})",
                  file=out)

    path = plist_path(label)
    path.parent.mkdir(parents=True, exist_ok=True)
    # What was there before, so a failed upgrade can put it back. Booting out a
    # working host and then failing to bootstrap the new plist used to leave
    # the Mac with no agent at all — down now, and still down after the next
    # login, on the machine whose whole point is being reachable from away.
    previous = path.read_bytes() if path.exists() else None
    path.write_bytes(render_plist(label=label, port=port, bind=bind,
                                  state_dir=state_dir, logs=logs))

    # Bootout first, and ignore the result: a label that was never loaded is
    # an error to launchctl and a no-op to us. Without it, re-running the
    # installer after an edit bootstraps onto the job already there and the
    # new plist is never read.
    _launchctl("bootout", f"{_domain()}/{label}")
    wait_unloaded(label)
    boot = bootstrap(label, path)
    if boot.returncode != 0:
        if previous is None:
            # Nothing was here before. Take the plist back out: left behind it
            # is loaded at the next login anyway — an install that reported
            # failure and then quietly started the thing hours later is the
            # worst of both.
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(previous)
            _launchctl("bootout", f"{_domain()}/{label}")
            wait_unloaded(label)
            back = bootstrap(label, path)
            if back.returncode == 0:
                _launchctl("kickstart", "-k", f"{_domain()}/{label}")
                print("the host that was already here has been put back.",
                      file=sys.stderr)
            else:
                print(f"WARNING: the previous host could not be restarted "
                      f"either — {path} is in place and will load at the next "
                      f"login.", file=sys.stderr)
        print(f"launchctl bootstrap failed: {boot.stderr.strip()}", file=sys.stderr)
        return 1
    _launchctl("kickstart", "-k", f"{_domain()}/{label}")

    served = wait_for_health(port)
    if not served:
        print(f"the agent is installed but nothing answered on {port} "
              f"within 20s — see {logs / 'host.err'}", file=sys.stderr)
        return 1

    print(f"host up on {bind}:{port} — profile {served.get('profile')}", file=out)
    print(f"  name      {hostenv.host_name()}", file=out)
    print(f"  host id   {hostenv.host_id()}", file=out)
    print(f"  state     {state}", file=out)
    print(f"  agent     {path}", file=out)
    print(f"  token     {token}"
          + ("" if minted else "   (already provisioned — unchanged)"), file=out)
    # Not "type the token into the app". Adding a machine is something the hub
    # does: it mints a one-time code and hands it to the app over the app's own
    # URL scheme (`cli.pair_link`), which is also the only path that works
    # before this machine has a name anything else can resolve. The token above
    # is this host's own credential, printed for the cases that genuinely need
    # it — no app should ever be asked to carry it, and this line used to ask.
    print("\nThe app pairs itself: `jstack-host pair --open` on this Mac, or "
          "`jstack-host pair \"<device name>\"` for a code to type into "
          "another one.", file=out)
    # The setup check, last: what the app will find when it connects, graded,
    # with the fix beside each thing that is not there yet. Never the exit
    # status — the host is up, and a warning is a screen waiting on a store.
    from . import doctor
    print("\nSetup check:", file=out)
    doctor.report(out)
    return 0


def uninstall(*, label: str = LABEL, out=None) -> int:
    out = out or sys.stdout
    _launchctl("bootout", f"{_domain()}/{label}")
    path = plist_path(label)
    existed = path.exists()
    path.unlink(missing_ok=True)
    # The token and the state dir stay. A machine being taken off the mesh for
    # an afternoon should come back as the same instance, and deleting the
    # token would silently re-key every device that has it.
    print("host agent removed." if existed else "no host agent was installed.",
          file=out)
    print(f"  token and state left in place ({hostenv.state_dir()})", file=out)
    return 0


def status(*, port: int = DEFAULT_PORT, label: str = LABEL, out=None) -> int:
    out = out or sys.stdout
    path = plist_path(label)
    served = health(port)
    print(f"agent      {'installed' if path.exists() else 'not installed'} "
          f"({path})", file=out)
    print(f"loaded     {'yes' if is_loaded(label) else 'no'}", file=out)
    if served:
        print(f"serving    {port} — profile {served.get('profile')}, "
              f"{'provisioned' if served.get('provisioned') else 'NO TOKEN'}",
              file=out)
    else:
        print(f"serving    nothing answered on {port}", file=out)
    print(f"state      {hostenv.state_dir()}", file=out)
    print(f"token      {hostenv.token_path()} "
          f"({'present' if hostenv.token_path().exists() else 'missing'})",
          file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python3 -m jstack_host.install_host",
        description="Install this machine as a jRemote host (user LaunchAgent, "
                    "no admin).")
    ap.add_argument("action", choices=["install", "uninstall", "status", "doctor"])
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--bind", default=DEFAULT_BIND,
                    help="bind address (default 0.0.0.0 — the mesh arrives on "
                         "a tunnel interface, not loopback)")
    ap.add_argument("--label", default=LABEL)
    ap.add_argument("--state-dir", default=None,
                    help="override where this host keeps its state")
    ap.add_argument("--force", action="store_true",
                    help="install even if the port is already answering")
    args = ap.parse_args(argv)

    state = Path(args.state_dir).expanduser() if args.state_dir else None
    if args.action == "install":
        return install(port=args.port, bind=args.bind, label=args.label,
                       state_dir=state, force=args.force)
    if args.action == "uninstall":
        return uninstall(label=args.label)
    adopt_installed_environment(plist_path(args.label))
    if state is not None:
        os.environ["JREMOTE_STATE_DIR"] = str(state)
        hostenv.reset_profile()
    if args.action == "doctor":
        from . import doctor
        return doctor.report()
    return status(port=args.port, label=args.label)


if __name__ == "__main__":
    raise SystemExit(main())
