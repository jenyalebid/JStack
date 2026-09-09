"""`jstack-host` — the one command a person types on their own Mac.

    jstack-host install          turn this Mac into a host, and keep it one
    jstack-host pair "iPhone"    a code to type into the app
    jstack-host pair --open      pair the app on this Mac, no code typed
    jstack-host status           is it up, and what does it know
    jstack-host doctor           what is missing, and how to fix each thing
    jstack-host uninstall        take it back off

Nothing here implements anything. `install_host` owns the LaunchAgent,
`server` owns serving, `enrolment` owns codes; this is the front door that
makes them one command with one `--help`, because "run `python3 -m` against a
module inside a package you have to know the name of" is not an install
instruction anyone should be given.

`pyproject.toml` has pointed `jstack-host` here since the package was split
out, so every `pip install` up to now produced a console script that raised
ImportError on its first line — the first thing a new host would ever have run.

**Every read command adopts the installed host's environment first.** A host
installed with `--state-dir` keeps its board, its devices and its token
somewhere this shell knows nothing about; asking about it from a plain
terminal would otherwise report on a *different*, empty host — "not
provisioned" for a machine with a token, and a pairing code minted into a
store nothing is serving. `adopt_installed_environment` reads that back off the
LaunchAgent, beneath anything the shell set explicitly.
"""

from __future__ import annotations

import argparse
import sys

from . import hostenv, install_host, server


def _adopt(args) -> None:
    """Point this process at the host that is actually installed."""
    install_host.adopt_installed_environment(install_host.plist_path(args.label))
    if getattr(args, "state_dir", None):
        import os
        os.environ["JREMOTE_STATE_DIR"] = args.state_dir
        hostenv.reset_profile()


def _cmd_pair(args) -> int:
    """Mint an enrolment code, the way the app expects to be introduced.

    A code rather than the raw token: it expires, it names the device before
    the device ever connects, and it can be revoked without re-keying every
    other device on the host. `jstack-host token` still prints the token for
    the case where someone is adding a host by hand.

    `--open` is the same code, delivered rather than displayed. On the machine
    that has just installed both halves there is nobody to read a code to —
    the app is right here — so it goes over the `jremote://pair` URL and the
    app spends it without anybody typing anything. See `pair_link`.
    """
    _adopt(args)
    from . import enrolment
    if not hostenv.token_path().exists():
        print("this host has no token yet — run `jstack-host install` first.",
              file=sys.stderr)
        return 1
    row = enrolment.mint_code(args.name, created_by="", ttl=args.ttl)
    if getattr(args, "open", False):
        return _hand_to_app(row)
    mins = row["expires_in"] // 60
    print(f"\n    {row['code']}\n")
    print(f"for {row['name']} — good for {mins} minute{'' if mins == 1 else 's'}.")
    print("In the app on that device: Instances › Add a Mac — this Mac's "
          "address, and this code.")
    return 0


def pair_link(code: str, port: int, name: str = "") -> str:
    """The `jremote://pair` URL that hands `code` to the app on this Mac.

    Loopback, always. This link is only ever fired at the app running on the
    host's own machine, and 127.0.0.1 is the one address that is true before
    the machine has a name anything else can resolve — a fresh install has no
    DNS entry, no Bonjour name it has published, and possibly no LAN. The app
    re-settles its own route on every launch anyway (it prefers loopback when
    the host it reaches IS the machine it is on), so this is the starting
    address and not a decision the app is stuck with.
    """
    from urllib.parse import urlencode
    query = {"code": code, "url": f"http://127.0.0.1:{port}"}
    if name:
        query["name"] = name
    return "jremote://pair?" + urlencode(query)


def _hand_to_app(row: dict) -> int:
    """Fire the pair link at the local app, or say what to do instead.

    Never fatal, and never silent about which of the two happened: a machine
    with no app installed is a normal outcome of `--open` (the app step is
    declinable), and the code is already minted and still good — so the
    fallback is to print it exactly as the plain form would.
    """
    import shutil
    import subprocess
    from . import install_host

    port = install_host.installed_port() or install_host.DEFAULT_PORT
    link = pair_link(row["code"], port, hostenv.host_name())
    opener = shutil.which("open")
    if opener:
        try:
            subprocess.run([opener, link], check=True, capture_output=True,
                           timeout=20)
            print(f"paired the app on this Mac as {row['name']} — it should be "
                  "opening now")
            return 0
        except (OSError, subprocess.SubprocessError):
            pass
    mins = row["expires_in"] // 60
    print("no app on this Mac answered that link — install it, then type this "
          "code into it:")
    print(f"\n    {row['code']}\n")
    print(f"good for {mins} minute{'' if mins == 1 else 's'}.")
    return 0


def _cmd_token(args) -> int:
    _adopt(args)
    path = hostenv.token_path()
    try:
        print(path.read_text().strip())
    except OSError:
        print(f"no token at {path} — run `jstack-host install` first.",
              file=sys.stderr)
        return 1
    return 0


def _cmd_where(args) -> int:
    """Every path this host resolves, so a support question is one paste.

    The seam answers these; printing them is how someone finds out that
    `--state-dir` took effect, or which credentials directory a missing APNs
    key is missing from.
    """
    _adopt(args)
    print(f"name         {hostenv.host_name()}")
    print(f"host id      {hostenv.host_id()}")
    print(f"profile      {hostenv.profile().name}")
    print(f"package      {hostenv.package_root()}")
    print(f"state        {hostenv.state_dir()}")
    print(f"token        {hostenv.token_path()}")
    print(f"credentials  {hostenv.credentials_dir()}")
    print(f"agents       {hostenv.instance_root()}")
    print(f"scheduler    {hostenv.scheduler_dir()}")
    return 0


def _cmd_version(args) -> int:
    from importlib.metadata import PackageNotFoundError, version
    try:
        print(version("jstack-host"))
    except PackageNotFoundError:
        # Running from a checkout that was never pip-installed. Not an error —
        # `python3 -m jstack_host.cli` is a legitimate way to drive this.
        print("unknown (not installed as a package)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="jstack-host",
        description="The JStack host: the API a phone, an iPad or another Mac "
                    "reaches this machine through.")
    ap.add_argument("--label", default=install_host.LABEL,
                    help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def _serving_args(p, *, bind_default, bind_help):
        p.add_argument("--port", type=int, default=install_host.DEFAULT_PORT)
        p.add_argument("--bind", default=bind_default, help=bind_help)
        p.add_argument("--state-dir", default=None,
                       help="where this host keeps its state "
                            "(default: ~/.local/state/jremote)")

    p = sub.add_parser("install", help="install the host as a user LaunchAgent")
    _serving_args(p, bind_default=install_host.DEFAULT_BIND,
                  bind_help="bind address (default 0.0.0.0 — a host is reached "
                            "over a tunnel or the LAN, and one bound to "
                            "127.0.0.1 is one only this Mac can see)")
    p.add_argument("--force", action="store_true",
                   help="install even if something else already answers on the port")
    p.set_defaults(fn=lambda a: install_host.install(
        port=a.port, bind=a.bind, label=a.label, force=a.force,
        state_dir=_path(a.state_dir)))

    p = sub.add_parser("uninstall", help="remove the LaunchAgent (state and token stay)")
    p.set_defaults(fn=lambda a: install_host.uninstall(label=a.label))

    p = sub.add_parser("status", help="is the host installed, loaded and answering")
    p.add_argument("--port", type=int, default=install_host.DEFAULT_PORT)
    p.add_argument("--state-dir", default=None)
    p.set_defaults(fn=lambda a: (_adopt(a),
                                 install_host.status(port=a.port, label=a.label))[1])

    p = sub.add_parser("doctor", help="grade every dependency this host needs")
    p.add_argument("--state-dir", default=None)
    p.set_defaults(fn=lambda a: (_adopt(a), _doctor())[1])

    p = sub.add_parser("serve", help="run the host in this terminal (no LaunchAgent)")
    _serving_args(p, bind_default="127.0.0.1",
                  bind_help="bind address (default 127.0.0.1 — `serve` is for "
                            "a foreground run you are watching; `install` is "
                            "the one that binds outward)")
    p.set_defaults(fn=lambda a: server.main(
        ["--host", a.bind, "--port", str(a.port)]
        + (["--state-dir", a.state_dir] if a.state_dir else [])))

    p = sub.add_parser("pair", help="mint an enrolment code for a device")
    p.add_argument("name", nargs="?", default="My device",
                   help="what to call the device in this host's device list")
    p.add_argument("--ttl", type=int, default=600,
                   help="seconds the code stays good (default 600)")
    p.add_argument("--open", action="store_true",
                   help="hand the code to the app on this Mac instead of "
                        "printing it — it pairs itself and opens")
    p.add_argument("--state-dir", default=None)
    p.set_defaults(fn=_cmd_pair)

    p = sub.add_parser("token", help="print this host's bearer token")
    p.add_argument("--state-dir", default=None)
    p.set_defaults(fn=_cmd_token)

    p = sub.add_parser("where", help="every path this host resolves")
    p.add_argument("--state-dir", default=None)
    p.set_defaults(fn=_cmd_where)

    p = sub.add_parser("version", help="the installed package version")
    p.set_defaults(fn=_cmd_version)
    return ap


def _path(raw):
    from pathlib import Path
    return Path(raw).expanduser() if raw else None


def _doctor() -> int:
    from . import doctor
    return doctor.report()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
