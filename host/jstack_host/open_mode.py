"""`jstack-host open` — make an independent host reachable off-network, and
prove it before saying so.

Open mode is the shape a host takes when it holds its OWN way in from outside,
rather than dialing out to a parent (managed) or being reachable only on the LAN
(local). The way in is a port forward on the router: one UDP port, from the
internet to this Mac's WireGuard endpoint. Everything hard about this feature is
in two words from the issue — *guided* and *honest*:

  · **Guided.** A port forward is the step most people never finish, because it
    lives in a router admin page in language that varies by vendor. This walks
    it: it finds this Mac's LAN address and the router's public address (over
    NAT-PMP, asking the gateway directly — no third-party "what is my IP"
    service, which on a product that must not phone home is the only acceptable
    source), attempts the mapping automatically where the router speaks NAT-PMP,
    and prints the exact one-line forward to enter by hand where it does not.

  · **Honest.** This is the load-bearing half, and it is why open mode could not
    just be a settings toggle. **A WireGuard endpoint is silent by design** — it
    never answers a packet that does not carry a valid peer key, so a generic
    port scanner sees an open, forwarded UDP port as indistinguishable from a
    closed one. There is no way to prove reachability by probing from outside
    with anything less than a real key. The one thing that *does* prove it is a
    genuine handshake completed from a public source address — and the hub can
    see that locally, in `wg show`: a peer whose last packet reached us from a
    routable address, with a fresh handshake, is proof that a packet from the
    internet arrived on the forwarded port and was answered. So verification is
    not a scan this host runs; it is evidence this host observes. Until that
    evidence exists, the mode says "declared, not verified" and never claims the
    host is reachable.

The guided flow closes the loop by asking the user to produce that evidence on
purpose — bring one already-paired device onto cellular (off this Wi-Fi) and
open the app — which is the only external vantage a standalone product can
honestly use: a device the user already has, genuinely off-network. The moment
that device completes a handshake, `verify()` sees it and the mode flips to
verified.

**Only the silent UDP port is ever exposed.** The HTTP API (9090) is never
forwarded and this module refuses to describe a forward that would — off-network
traffic rides the encrypted, authenticated WireGuard tunnel or it does not
arrive. That is the transport-hardening half of the issue, enforced here rather
than documented and hoped for.

Every external edge — the gateway lookup, the NAT-PMP socket, the `wg` calls —
is injected, so the whole flow is driven in tests against recorders with no
router, no interface and no network.
"""

from __future__ import annotations

import ipaddress
import os
import re
import shutil
import socket
import struct
import subprocess
import time
from pathlib import Path

from . import addresses

#: The WireGuard listen port a hub forwards. `install_hub.sh` defaults its
#: `ListenPort` to this (WG_PORT overrides), and the endpoint file carries the
#: real one as `host:port`; `wg_port()` reads that back so a hub on a custom
#: port is guided to forward the port it actually listens on.
DEFAULT_WG_PORT = 51820

#: The HTTP API port. Named here for one reason: to be the thing this module
#: refuses to forward. Off-network access is the tunnel's job; exposing this to
#: the internet would be the bare-HTTP hole the issue exists to close.
HTTP_PORT = 9090

#: NAT-PMP (RFC 6886) lives here on the default gateway. UDP.
NATPMP_PORT = 5351

#: How recent a public-source handshake must be to count as "reachable right
#: now". WireGuard rekeys roughly every two minutes while a peer is active; a
#: window several times that treats a live peer as live without calling a peer
#: that quietly went to sleep an hour ago "verified". Older evidence still
#: proves the forward once worked — `verify()` reports the age so the caller can
#: tell "reachable now" from "was reachable".
VERIFY_MAX_AGE = 900

#: How long an auto-created port mapping should live. Two hours: long enough to
#: complete the guided verification and use the host, short enough that a
#: mapping left behind by a machine that moved networks expires on its own.
MAP_LIFETIME = 7200


class OpenModeError(Exception):
    """A step of the guided setup could not be completed. Carries a message
    meant for the person running the command."""


# ── where this Mac and its router sit ───────────────────────────────────────

def lan_ip() -> str:
    """This Mac's private LAN address — the forward's internal target.

    Reuses `addresses.classify`, so the one parser of `ifconfig` output serves
    both the pairing screen and this. The first `lan` entry is the address a
    router forward points at; a host with none (no private IPv4 up) cannot be
    the target of a forward, which the caller reports rather than guessing.
    """
    for a in addresses.reachable():
        if a["kind"] == "lan":
            return a["host"]
    return ""


def default_gateway(runner=subprocess.run) -> str:
    """The default route's gateway — the router NAT-PMP talks to.

    `route -n get default` is the BSD/macOS answer, the same platform every
    other shell-out in this package assumes. Absent or unparseable degrades to
    "" and the NAT-PMP steps are skipped with a reason, never crashed.
    """
    try:
        out = runner(["/sbin/route", "-n", "get", "default"],
                     capture_output=True, text=True, timeout=10).stdout
    except Exception:  # noqa: BLE001 — no route is an empty answer
        return ""
    m = re.search(r"gateway:\s*([0-9.]+)", out)
    return m.group(1) if m else ""


# ── NAT-PMP: ask the router for the public IP and the mapping ────────────────

def _natpmp_exchange(gateway: str, payload: bytes, sock=None) -> bytes:
    """One NAT-PMP request/response against the gateway. Never raises for a
    network reason — a router that does not speak NAT-PMP is the common case,
    not an error, so it comes back as b"" and the caller reports it as "could
    not, do it by hand"."""
    own = sock is None
    if own:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(2.0)
    try:
        sock.sendto(payload, (gateway, NATPMP_PORT))
        data, _ = sock.recvfrom(64)
        return data
    except OSError:
        return b""
    finally:
        if own:
            sock.close()


def natpmp_external_ip(gateway: str, sock=None) -> str:
    """The router's public IPv4, asked of the router itself (NAT-PMP opcode 0).

    No third-party reflection service — the gateway is the one party that knows
    this without the request leaving the network, which is the only source a
    product forbidden from phoning home may use. "" when the router does not
    answer or returns a non-zero result code.
    """
    if not gateway:
        return ""
    resp = _natpmp_exchange(gateway, struct.pack("!BB", 0, 0), sock)
    # version(1) opcode(1) result(2) epoch(4) ip(4)
    if len(resp) < 12 or resp[1] != 128:
        return ""
    result = struct.unpack("!H", resp[2:4])[0]
    if result != 0:
        return ""
    return socket.inet_ntoa(resp[8:12])


def natpmp_map_udp(gateway: str, port: int, lifetime: int = MAP_LIFETIME,
                   sock=None) -> dict:
    """Ask the router to forward UDP `port` to this Mac (NAT-PMP opcode 1).

    Returns {"ok", "external_port", "detail"}. Best-effort by contract: a router
    that ignores NAT-PMP leaves ok=False and the guided path falls back to the
    printed manual forward. The mapping is never treated as proof of anything —
    only an observed handshake is (see `verify`).
    """
    if not gateway:
        return {"ok": False, "external_port": 0,
                "detail": "no default gateway found"}
    # version(0) opcode(1=UDP) reserved(2) internal(2) suggested-external(2)
    # lifetime(4)
    req = struct.pack("!BBHHHI", 0, 1, 0, port, port, lifetime)
    resp = _natpmp_exchange(gateway, req, sock)
    if len(resp) < 16 or resp[1] != 129:
        return {"ok": False, "external_port": 0,
                "detail": "the router did not answer NAT-PMP — forward the port "
                          "by hand (below)"}
    result = struct.unpack("!H", resp[2:4])[0]
    if result != 0:
        return {"ok": False, "external_port": 0,
                "detail": f"the router refused the mapping (NAT-PMP result "
                          f"{result})"}
    ext_port = struct.unpack("!H", resp[10:12])[0]
    return {"ok": True, "external_port": ext_port,
            "detail": f"router mapped UDP {ext_port} to this Mac"}


# ── the WireGuard side: which port, and the honest verification ─────────────

def wg_port() -> int:
    """The port this hub actually listens on, read off the endpoint file the
    hub wrote — `host:port`. Falls back to the default when the file names no
    port, so the guide never forwards a port the hub is not on."""
    try:
        from . import tunnel
        text = (tunnel.WG_DIR / "endpoint").read_text().strip()
    except (OSError, ImportError):
        return DEFAULT_WG_PORT
    m = re.search(r":(\d+)\s*$", text)
    return int(m.group(1)) if m else DEFAULT_WG_PORT


def wg_bin() -> str:
    """The `wg` binary, found the way `install_leaf.sh` finds it — `WG` env,
    then PATH, then the two Homebrew prefixes. "" when WireGuard is not
    installed, which makes verification honestly impossible rather than crash."""
    env = os.environ.get("WG")
    if env:
        return env
    found = shutil.which("wg")
    if found:
        return found
    for pfx in ("/opt/homebrew/bin", "/usr/local/bin"):
        cand = Path(pfx) / "wg"
        if cand.is_file():
            return str(cand)
    return ""


#: Where the tunnel writes the utun name it landed on. `install_hub.sh` names
#: the HUB interface file `jremote-hub.name`, deliberately distinct from a
#: leaf's `jremote-wg.name` so a machine that ran both installers never has the
#: two collide on one file. Open mode is a hub-only concept — `verify()` runs
#: only for a hub with an endpoint — so the hub file is the one it reads. The
#: leaf name is kept as a fallback so a hand-rolled hub left on the shared
#: default is still observed rather than silently reported down; `WG_NAME_FILE`
#: overrides both, for tests and custom installs.
HUB_NAME_FILE = "/var/run/wireguard/jremote-hub.name"
LEAF_NAME_FILE = "/var/run/wireguard/jremote-wg.name"


def wg_iface(name_file: str | None = None) -> str:
    """The utun name the hub tunnel is on, read from the runtime name file the
    hub daemon writes. "" when the tunnel is not up — nothing to observe.

    An explicit `name_file` wins; then `WG_NAME_FILE`; then the hub file, then
    the leaf file. Reading `jremote-wg.name` unconditionally was the bug this
    default fixes: `install_hub.sh` writes `jremote-hub.name`, so on a real hub
    the check read an absent file and reported the tunnel down while it was up.
    """
    if name_file:
        candidates = [name_file]
    elif os.environ.get("WG_NAME_FILE"):
        candidates = [os.environ["WG_NAME_FILE"]]
    else:
        candidates = [HUB_NAME_FILE, LEAF_NAME_FILE]
    for cand in candidates:
        try:
            name = Path(cand).read_text().strip()
        except OSError:
            continue
        if name:
            return name
    return ""


def _is_public(addr: str) -> bool:
    """Whether a source address is one the packet could only have crossed the
    internet to carry — routable, not private, not loopback, not the mesh
    itself. A handshake from such an address is the proof open mode needs."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if ip in addresses.MESH_SUBNET:
        return False
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_unspecified)


def _wg_show(iface: str, field: str, wg: str, runner=subprocess.run) -> str:
    try:
        return runner([wg, "show", iface, field], capture_output=True,
                      text=True, timeout=10).stdout
    except Exception:  # noqa: BLE001
        return ""


def _run_wg(args: list[str], wg: str, runner=subprocess.run):
    """Run `wg <args>` and return (returncode, stdout, stderr), tolerant of a
    stand-in runner that only sets stdout. Any failure to spawn reads as a
    non-zero exit with no output — the same as `wg` refusing."""
    try:
        p = runner([wg, *args], capture_output=True, text=True, timeout=10)
        return (getattr(p, "returncode", 0),
                getattr(p, "stdout", "") or "",
                getattr(p, "stderr", "") or "")
    except Exception:  # noqa: BLE001
        return 1, "", ""


def _running_iface(wg: str, runner=subprocess.run) -> str:
    """The wg interface this machine has up, asked of `wg` itself.

    `wg show interfaces` needs no privilege — unlike a per-interface handshake
    table — so it answers "is the tunnel up" even when the root-only name file
    the hub daemon writes cannot be read by the unprivileged CLI. That is the
    difference between reporting "tunnel down" (false) and "cannot read without
    root" (true) when open mode is checked without privilege."""
    if not wg:
        return ""
    rc, out, _ = _run_wg(["show", "interfaces"], wg, runner)
    if rc != 0:
        return ""
    toks = out.split()
    return toks[0] if toks else ""


def _handshake_denied(iface: str, wg: str, runner=subprocess.run) -> bool:
    """Whether reading this interface's handshakes was refused for lack of
    privilege — the wg control socket is root-only, so an unprivileged reader
    gets "Unable to access interface: Permission denied", not empty output.
    Distinguishing this from an empty table is what keeps the check honest."""
    if not iface or not wg:
        return False
    rc, _, err = _run_wg(["show", iface, "latest-handshakes"], wg, runner)
    low = err.lower()
    return rc != 0 and ("permission denied" in low or "unable to access" in low)


def off_network_handshake(iface: str, wg: str, now: int,
                          runner=subprocess.run,
                          max_age: int = VERIFY_MAX_AGE) -> dict | None:
    """The newest peer handshake that came from a public source, or None.

    Reads `wg show <iface> endpoints` (where each peer last reached us from) and
    `latest-handshakes` (when), and returns the freshest peer whose source is a
    routable address within `max_age`. That peer is a device that crossed the
    internet to reach this hub's forwarded port and completed a handshake — the
    single fact that turns "declared" into "verified".
    """
    if not iface or not wg:
        return None
    endpoints = {}
    for line in _wg_show(iface, "endpoints", wg, runner).splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and ":" in parts[1]:
            endpoints[parts[0]] = parts[1].rsplit(":", 1)[0]
    best = None
    for line in _wg_show(iface, "latest-handshakes", wg, runner).splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        key, raw = parts
        try:
            when = int(raw)
        except ValueError:
            continue
        if when <= 0 or now - when > max_age:
            continue
        src = endpoints.get(key, "")
        if _is_public(src) and (best is None or when > best["when"]):
            best = {"source": src, "when": when, "age": now - when}
    return best


def verify(now: int | None = None, runner=subprocess.run) -> dict:
    """Whether this host is provably reachable off-network right now.

    verified=True only when a public-source handshake has been observed within
    the freshness window. Everything it needs — the interface, the binary, the
    handshake table — is read off this machine; nothing is asserted.
    """
    now = int(time.time()) if now is None else now
    wg = wg_bin()
    if not wg:
        return {"verified": False, "source": "", "age": None,
                "note": "the `wg` tool is not installed, so a handshake cannot "
                        "be read"}
    # The name file is root-only on a real hub; fall back to asking `wg` which
    # interfaces are up, which needs no privilege, so an unprivileged check can
    # still tell "tunnel down" from "up but unreadable".
    iface = wg_iface() or _running_iface(wg, runner)
    if not iface:
        return {"verified": False, "source": "", "age": None,
                "note": "the WireGuard tunnel is not up, so no off-network "
                        "connection can be observed"}
    if _handshake_denied(iface, wg, runner):
        return {"verified": False, "source": "", "age": None,
                "note": "the tunnel is up, but reading its handshake table needs "
                        "root — re-run `sudo jstack-host open --verify` to prove "
                        "the forward works"}
    hs = off_network_handshake(iface, wg, now, runner)
    if not hs:
        return {"verified": False, "source": "", "age": None,
                "note": "no off-network device has connected yet — bring one "
                        "paired device onto cellular and open the app to prove "
                        "the forward works"}
    return {"verified": True, "source": hs["source"], "age": hs["age"],
            "note": f"a device reached this Mac from {hs['source']} "
                    f"{hs['age']}s ago — reachable off-network, verified"}


# ── the guided flow the CLI drives ──────────────────────────────────────────

def guide(runner=subprocess.run, sock=None, now: int | None = None) -> dict:
    """Everything the `open` command needs to walk the setup and tell the truth.

    Refuses outright if asked (by a caller that mis-set the port) to expose the
    HTTP port — the one forward this feature must never describe. Otherwise it
    gathers the LAN target, the public address and an auto-map attempt, and
    finishes with the honest verification.
    """
    port = wg_port()
    if port == HTTP_PORT:
        raise OpenModeError(
            "refusing to forward the HTTP API port — off-network access rides "
            "the encrypted WireGuard tunnel, never bare HTTP")
    lan = lan_ip()
    if not lan:
        raise OpenModeError(
            "this Mac has no private LAN address up — connect it to the network "
            "whose router will forward the port, then re-run")
    gateway = default_gateway(runner)
    public = natpmp_external_ip(gateway, sock)
    mapping = natpmp_map_udp(gateway, port, sock=sock)
    return {
        "wg_port": port,
        "lan_ip": lan,
        "gateway": gateway,
        "public_ip": public,
        "mapping": mapping,
        "forward": {
            "protocol": "UDP",
            "external_port": port,
            "internal_ip": lan,
            "internal_port": port,
            "line": f"UDP {port} → {lan}:{port}",
        },
        "endpoint": f"{public}:{port}" if public else "",
        "verification": verify(now, runner),
    }
