"""Where this host can be reached — the answer a pairing screen has to show.

Pairing a second machine means typing an address into it, and the address the
app already holds is the one that is guaranteed wrong: on the Mac that mints
the code, the app is talking to loopback. `http://127.0.0.1:9090` is true for
the machine saying it and false for every machine being told it, so a dialog
that echoed its own base URL would hand out an address that cannot work and
looks like it should. That failure is silent on the minting side and total on
the receiving one, which is the worst shape a setup step can have.

So the host answers for itself, off its own interfaces, in the order a reader
should try them:

  · **lan** — this network's private IPv4. True while both machines are on
    the same network, which is where pairing happens: the device being
    enrolled is, by definition, not on the mesh yet. First because it is the
    one address a new device can act on *now*.
  · **local** — the Bonjour name. Survives a DHCP move, which the numeric LAN
    address does not; second because `.local` resolution is flakier than a
    number on a guest network.
  · **mesh** — `10.66.0.x`. The address a device ends up *using* once its
    tunnel is up — and the one a device that is still pairing can never
    reach. Last, and only present on a host that has a tunnel at all: a
    pairing screen that led with it handed every new device its own
    unreachable first try, which is exactly what this module exists to stop.

**Loopback is deliberately absent.** It is never useful to a second machine,
and an address list whose first entry cannot work teaches the reader to
distrust the rest of it. The app pairing a host to ITSELF already has
loopback without being told (`LanProbe.localHost`), and that path does not
come through here.

Nothing here claims reachability. These are addresses this machine *holds* —
whether a packet from somewhere else arrives on one is a fact about the
network, and this module would be lying if it implied otherwise. The pairing
screen says "try these", never "these work".
"""

from __future__ import annotations

import ipaddress
import re
import socket
import subprocess

#: The mesh subnet, mirrored from `wg_peer.py`'s SUBNET_PREFIX the same way
#: `devices.MESH_SUBNET` mirrors it. A host with no tunnel simply never has an
#: address inside it, so this needs no guard for the leaf case.
MESH_SUBNET = ipaddress.ip_network("10.66.0.0/24")

#: `inet 192.168.0.106 netmask 0xffffff00` — BSD `ifconfig`, which is what
#: every machine this package installs on runs. A parse that finds nothing
#: degrades to an empty list, and the screen above says so rather than
#: inventing an address.
_INET_RE = re.compile(r"^\s*inet\s+(\d+\.\d+\.\d+\.\d+)", re.M)

DEFAULT_PORT = 9090


def _inet_addrs() -> list[str]:
    """Every IPv4 this machine holds. A seam, so the tests drive the
    classifier against fixed interface sets instead of the host's own."""
    try:
        out = subprocess.run(["/sbin/ifconfig"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:  # noqa: BLE001 — no interfaces readable is an empty list
        return []
    return _INET_RE.findall(out)


def _hostname() -> str:
    """A seam for the same reason `_inet_addrs` is one."""
    try:
        return socket.gethostname()
    except Exception:  # noqa: BLE001
        return ""


def classify(inets: list[str], hostname: str, port: int) -> list[dict]:
    """The address list, ordered mesh → lan → local. Pure, so the ordering
    and the exclusions are what the tests actually pin."""
    out: list[dict] = []
    mesh, lan = [], []
    for raw in inets:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_link_local or not ip.is_private:
            continue
        (mesh if ip in MESH_SUBNET else lan).append(str(ip))

    for addr in lan:
        out.append({"kind": "lan", "host": addr,
                    "url": f"http://{addr}:{port}",
                    "note": "works while both machines are on this network"})

    name = (hostname or "").strip().rstrip(".")
    if name and name.lower() != "localhost":
        if not name.endswith(".local"):
            name = name.split(".")[0] + ".local"
        out.append({"kind": "local", "host": name,
                    "url": f"http://{name}:{port}",
                    "note": "survives this Mac changing address"})

    for addr in mesh:
        out.append({"kind": "mesh", "host": addr,
                    "url": f"http://{addr}:{port}",
                    "note": "for a device already paired onto this Mac's "
                            "tunnel"})
    return out


def reachable(port: int = DEFAULT_PORT) -> list[dict]:
    """Where a second machine could try to reach this one."""
    return classify(_inet_addrs(), _hostname(), port)
