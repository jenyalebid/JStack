"""`jstack-host` — the one command a person types on their own Mac.

    jstack-host install          turn this Mac into a host, and keep it one
    jstack-host pair "iPhone"    a code to type into the app
    jstack-host pair --open      pair the app on this Mac, no code typed
    jstack-host attach CODE --parent URL   join a parent hub as a managed hub
    jstack-host open             guide this Mac into open mode, and prove it
    jstack-host welcome          open the app on a session that checks this Mac
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
    from . import devices, enrolment
    if not devices.provisioned():
        print("this host has no token yet — run `jstack-host install` first.",
              file=sys.stderr)
        return 1
    row = enrolment.mint_code(args.name, created_by="", ttl=args.ttl)
    if getattr(args, "open", False):
        return _hand_to_app(row)

    from . import addresses
    port = getattr(args, "port", None) or addresses.DEFAULT_PORT
    found = addresses.reachable(port)

    if getattr(args, "json", False):
        # One parseable answer for the surfaces that draw this themselves.
        # The menu bar dialog renders it as a QR — the one thing stdout prose
        # cannot carry — so it asks for the parts, not the paragraph.
        import json
        from urllib.parse import urlencode
        payload = {"name": row["name"], "code": row["code"],
                   "expires_in": row["expires_in"], "port": port,
                   "addresses": found}
        if found:
            query = {"code": row["code"], "url": found[0]["url"]}
            if row["name"]:
                query["name"] = row["name"]
            payload["link"] = "jremote://pair?" + urlencode(query)
        print(json.dumps(payload))
        return 0

    mins = row["expires_in"] // 60
    print(f"\n    {row['code']}\n")
    print(f"for {row['name']} — good for {mins} minute{'' if mins == 1 else 's'}.")

    # The address, printed — not named.
    #
    # This line used to read "this Mac's address, and this code", which tells
    # somebody standing at another device to type a thing it never tells them.
    # The host is the only party that knows what to put there (the app on the
    # new device cannot ask a machine it has not reached yet), `addresses` has
    # answered it since the `/host` work, and nothing was printing it. A code
    # beside a blank is half a pairing, and the half that was missing is the
    # half people got stuck on.
    print("\nIn the app on that device: Instances › Add a Mac.")
    if found:
        print("\nAddress — use the first one that fits:\n")
        for a in found:
            print(f"    {a['url']:<34}  {a['note']}")
    else:
        # Never silence. A host that cannot name an address is a host somebody
        # has to go find one for, and saying so beats printing nothing.
        print("\n  This Mac could not work out its own address — check "
              "`jstack-host where` and your network.")
    print(f"\nThen the code above: {row['code']}")
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


# How long to wait for the app to actually spend the code, and how often to
# look. Seconds, not milliseconds: the app this fires at has, by definition,
# never been opened on this Mac — it has to clear Gatekeeper on a bundle
# downloaded minutes ago, launch, restore its scenes, stand up the board, and
# run one round trip against loopback. Bounded, because the honest answer when
# it does not land is the code itself, and eight characters typed by hand beats
# an installer that sits there.
PAIR_WAIT = 30.0
PAIR_POLL = 0.5


def _pairing_landed(code: str) -> bool:
    """Did an app actually redeem `code`? Blocks up to `PAIR_WAIT`.

    `desk.open_url` returning True means Launch Services accepted a URL. It
    does not mean an app received it, and it certainly does not mean an app
    spent it — this exact gap shipped a pairing step that printed success on
    every fresh Mac while enrolling nothing, because the app dropped the link
    at cold launch (no board window yet, and the pairing sheet lives on the
    board). The store's used bit is the only place the truth is written down,
    so that is what this reads.
    """
    import time
    from . import enrolment

    deadline = time.monotonic() + PAIR_WAIT
    while True:
        if enrolment.state(code) == "used":
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(PAIR_POLL)


def _hand_to_app(row: dict) -> int:
    """Fire the pair link at the local app, and wait to see it spent.

    Exit 0 means this Mac is in the app's grid — nothing else. A machine with
    no app, an app that ignores the link, an app that never comes up: all of
    them are a normal outcome of `--open` (the app step is declinable), the
    code is already minted and still good, so the fallback is to print it
    exactly as the plain form would and exit non-zero. The caller in
    `install.sh` branches on that status to decide whether to claim the two
    halves have met.

    `desk.open_url` rather than a bare `open`, because it pins the link to
    the copy in /Applications. On a machine that has ever built the app, a
    stale bundle in derivedData is registered for the same URL scheme and
    Launch Services is free to prefer it — a pairing that lands in a build
    nobody is looking at, reported here as success.
    """
    from . import desk, install_host

    port = install_host.installed_port() or install_host.DEFAULT_PORT
    link = pair_link(row["code"], port, hostenv.host_name())
    if desk.open_url(link) and _pairing_landed(row["code"]):
        print(f"paired the app on this Mac as {row['name']} — this machine is "
              "in its grid now")
        return 0
    mins = row["expires_in"] // 60
    print("the app on this Mac did not take that link — open it, then type "
          "this code into it:")
    print(f"\n    {row['code']}\n")
    print(f"good for {mins} minute{'' if mins == 1 else 's'}.")
    return 1


# The first thing anyone sees after an install finishes. Addressed to the
# agent, not to the person: the session opens already working, and what it is
# working on is the machine it was just installed on.
#
# It says "check, then say" and not "say" on purpose. An agent that opens by
# congratulating someone on a working install it never looked at is worse than
# an empty window — the empty window at least does not lie, and the first
# impression this makes is the one that decides whether anything it says later
# gets believed.
WELCOME_PROMPT = (
    "You have just been installed on this Mac and this window is the first "
    "thing your owner sees. Do not greet them with a status you have not "
    "checked.\n\n"
    "Run `jstack-doctor` first. Read what it actually says, then tell them in "
    "plain words what works and what does not — no jargon they did not ask "
    "for, and no clean bill of health you did not verify. Repair what you can "
    "repair from here, and say plainly which parts need them.\n\n"
    "Then, briefly: what they now have. This app is where sessions like this "
    "one open; the host running on this Mac is what serves it; you are an "
    "agent with a workspace of your own, and this is it. Keep it to a few "
    "sentences.\n\n"
    "Finish by asking what they want to know, and answer it."
)


def _cmd_welcome(args) -> int:
    """Open the app on a session that explains the install that just ran.

    The install ends with a working machine and no idea what to do with it.
    This is the difference between the two: a session that comes up already
    running, in a real workspace, with the first prompt spent on checking the
    machine rather than on being typed.

    Everything here is a part that already existed — `desk.create` makes the
    managed session, `desk.open_thread` puts it in front of someone. The only
    new thing is which agent gets it and what it is asked to do first.
    """
    _adopt(args)
    import os.path
    from . import desk
    agents = hostenv.active_agents()
    if not agents:
        print("no agent workspaces on this host yet — nothing to open a "
              "session for.", file=sys.stderr)
        return 1
    agent_id = args.agent or sorted(agents)[0]
    if agent_id not in agents:
        known = ", ".join(sorted(agents))
        print(f"no agent {agent_id!r} on this host — there is: {known}",
              file=sys.stderr)
        return 1
    cwd = str(hostenv.workspace(agent_id))
    if not os.path.isdir(cwd):
        print(f"{agent_id}'s workspace is missing at {cwd}", file=sys.stderr)
        return 1
    try:
        sid = desk.create(cwd, nudge=WELCOME_PROMPT)
    except (OSError, RuntimeError) as e:
        print(f"could not start a session: {e}", file=sys.stderr)
        return 1
    if desk.open_thread(sid, cwd):
        print(f"opened a session with {agents[agent_id].get('name') or agent_id}"
              " — it is checking this install over now")
        return 0
    # The session is real and on the board whether or not a window came up, so
    # this is a note about the window, not a failure of the command.
    print(f"started a session ({sid[:8]}) — no app on this Mac took the link, "
          "so open it from the board when you have one.")
    return 0


def _cmd_attach(args) -> int:
    """Join a parent hub's mesh with a code minted on that parent.

    The one deliberate step that turns this Mac into a managed hub: redeem the
    host code, install the leaf tunnel it hands back, and report the mode the
    machine ended up in. `_adopt` first, like every command that reads or writes
    this host's state — the token this earns and the parent record it writes
    belong to the installed host, not to whatever a bare shell would resolve.

    Not gated behind a confirmation: attaching is already the explicit act — a
    person typed `attach`, an address and a one-time code. What it must not do is
    claim success it did not check, so it reads `mode` off the machine afterwards
    and prints that, rather than asserting "managed" because the installer
    returned zero.
    """
    _adopt(args)
    from . import attach_parent, hostenv, mode
    try:
        result = attach_parent.attach(
            args.code, args.parent, host_key=hostenv.host_id(), port=args.port)
    except attach_parent.AttachError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    m = mode.current()
    if getattr(args, "json", False):
        import json
        print(json.dumps({**result, "mode": m}))
        return 0

    host = result.get("host") or {}
    name = host.get("name") or hostenv.host_name()
    verb = "re-attached" if result["superseded"] else "attached"
    print(f"{verb} {name} to {result['parent_url']} — this Mac is a managed "
          "hub now.")
    print(f"\nmode  {m['mode']}{'' if m['live'] else '  (not live)'}")
    print(f"      {m['note']}")
    if m["mode"] != "managed":
        # The installer returned success but the machine does not read as
        # managed — say so instead of letting the mode line be the only tell.
        print("\n  The leaf installed but this machine is not reading as a "
              "managed hub yet — check `jstack-host doctor` and the leaf "
              "daemon logs.", file=sys.stderr)
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


def _cmd_mode(args) -> int:
    """Which of local / open / managed this host is — the question a person
    asks before they know whether a device off this network can reach it.

    The same verdict the menu bar shows, on a terminal: the mode, whether it is
    live right now, and the one line that says what that mode does and does not
    prove. `_adopt` first, for the same reason `where` does — a host installed
    with `--state-dir` keeps its tunnel state somewhere this shell would
    otherwise not look."""
    _adopt(args)
    from . import mode
    m = mode.current()
    live = "" if m["live"] else "  (not live)"
    print(f"mode  {m['mode']}{live}")
    print(f"      {m['note']}")
    return 0


def _cmd_open(args) -> int:
    """Guide this Mac into open mode, and prove the forward before claiming it.

    Open mode is a host holding its OWN way in from outside — a UDP port forward
    on the router to this Mac's WireGuard endpoint. This walks that: it names the
    exact one-line forward to enter, asks the router to make it automatically
    (NAT-PMP) where it can, and finishes with the honest verification — which is
    not a scan but an observation, because a WireGuard endpoint is silent to any
    packet without a valid key and cannot be probed from outside. So the last
    line asks the one thing that DOES prove it: bring a paired device onto
    cellular and open the app; the handshake that lands is the proof.

    `--verify` skips the setup and reports only that observation — the command to
    run after producing the evidence. `_adopt` first, like every command that
    reads this host's tunnel state.

    Setting the endpoint stays advisory on purpose: this prints the
    `install_hub.sh --endpoint` line to run rather than editing the live tunnel
    behind a `mode`-shaped command. Turning a declaration into a persisted config
    is a deliberate step, not a side effect of asking about reachability.
    """
    _adopt(args)
    from . import open_mode
    if getattr(args, "verify", False):
        v = open_mode.verify()
        if getattr(args, "json", False):
            import json
            print(json.dumps(v))
            return 0
        mark = "verified" if v["verified"] else "not yet verified"
        print(f"off-network reachability: {mark}")
        print(f"  {v['note']}")
        return 0

    try:
        g = open_mode.guide()
    except open_mode.OpenModeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        import json
        print(json.dumps(g))
        return 0

    fwd = g["forward"]
    print("To make this Mac reachable off-network, forward one UDP port on your "
          "router:\n")
    print(f"    {fwd['line']}\n")
    print(f"    protocol       UDP")
    print(f"    external port  {fwd['external_port']}")
    print(f"    to this Mac    {fwd['internal_ip']}:{fwd['internal_port']}")

    mapping = g["mapping"]
    if mapping["ok"]:
        print(f"\nThe router accepted this automatically — {mapping['detail']}.")
    else:
        print(f"\nDo it by hand in the router's admin page — {mapping['detail']}.")

    if g["endpoint"]:
        print(f"\nYour public endpoint is {g['endpoint']}. Record it so devices "
              "off-network can dial in:\n")
        print(f"    sudo bash install_hub.sh --endpoint {g['endpoint']}")
    elif g["public_ip"]:
        print(f"\nYour public endpoint is {g['public_ip']}:{g['wg_port']}.")
    else:
        print("\nThe router did not reveal its public address over NAT-PMP — "
              "find it in the router's status page, then the endpoint is "
              f"<that address>:{g['wg_port']}.")

    v = g["verification"]
    print("\nReachability is not something this Mac can prove by scanning — a "
          "WireGuard endpoint stays silent to any packet without a key. The one "
          "proof is a real connection from outside:\n")
    if v["verified"]:
        print(f"  ✓ {v['note']}")
    else:
        print(f"  {v['note']}")
        print("\n  When you have, run `jstack-host open --verify`.")
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
        description="The jStack host: the API a phone, an iPad or another Mac "
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
    p.add_argument("--json", action="store_true",
                   help="print the code, addresses and pair link as JSON — "
                        "what the menu bar dialog draws its QR from")
    p.add_argument("--state-dir", default=None)
    p.set_defaults(fn=_cmd_pair)

    p = sub.add_parser("attach",
                       help="join a parent hub's mesh — make this Mac a managed hub")
    p.add_argument("code", help="the host code minted on the parent "
                                "(kind=host)")
    p.add_argument("--parent", required=True,
                   help="the parent host's address, e.g. http://studio.local:9090")
    p.add_argument("--port", type=int, default=install_host.DEFAULT_PORT,
                   help="the port THIS Mac serves on, recorded on the parent "
                        f"(default {install_host.DEFAULT_PORT})")
    p.add_argument("--json", action="store_true",
                   help="print the outcome and resulting mode as JSON")
    p.add_argument("--state-dir", default=None)
    p.set_defaults(fn=_cmd_attach)

    p = sub.add_parser("welcome",
                       help="open the app on a session that checks this install")
    p.add_argument("--agent", default="",
                   help="which agent gets the session (default: the first one "
                        "on this host)")
    p.add_argument("--state-dir", default=None)
    p.set_defaults(fn=_cmd_welcome)

    p = sub.add_parser("token", help="print this host's bearer token")
    p.add_argument("--state-dir", default=None)
    p.set_defaults(fn=_cmd_token)

    p = sub.add_parser("where", help="every path this host resolves")
    p.add_argument("--state-dir", default=None)
    p.set_defaults(fn=_cmd_where)

    p = sub.add_parser("mode", help="is this host local, open or managed")
    p.add_argument("--state-dir", default=None)
    p.set_defaults(fn=_cmd_mode)

    p = sub.add_parser("open",
                       help="guide this Mac into open mode and prove it's reachable")
    p.add_argument("--verify", action="store_true",
                   help="skip the setup; only report whether an off-network "
                        "device has been observed reaching this Mac")
    p.add_argument("--json", action="store_true",
                   help="print the guide (or --verify result) as JSON")
    p.add_argument("--state-dir", default=None)
    p.set_defaults(fn=_cmd_open)

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
