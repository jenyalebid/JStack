"""`jstack-host attach` — join another Mac's mesh, on purpose, in one command.

Managed mode is the third shape a host can be (mode.py): a Mac that dials OUT
to a parent hub and rides its mesh, so every device already paired to that
parent reaches this machine with no per-device setup of its own. That is the
whole product promise of a managed hub, and until now it had no front door —
the pieces existed on both ends (the parent mints a host code, `install_leaf.sh`
stands up the tunnel) but nothing on the joining machine tied them together.
A person had to redeem the code by hand, find the leaf bundle in the response,
write six files out with the right permissions, and run the installer from the
right directory. Every one of those steps was a place to get it wrong.

This is that sequence, made one deliberate action:

  1. redeem a **host-kind** enrolment code against the parent's public
     `POST /api/jremote/v1/enrolment/redeem` — the same unauthenticated
     path a leaf uses, carrying this machine's own `/host` id as `host_key`
     so the parent can record which machine just joined;
  2. take the leaf bundle the parent hands back (`response["tunnel"]["bundle"]`,
     the six `tunnel.LEAF_FILES`), write it out, and
  3. run `install_leaf.sh` from inside it — which installs the leaf daemons and
     brings the tunnel up.

Deliberate, never inferred. Attaching to a parent changes what off-network
devices can reach; it is a thing a person chooses and types a code for, not a
mode a Mac drifts into. So it is a command, and it reports the mode it left the
machine in rather than claiming success it did not check.

Why the bundle, not a client `.conf`: a machine joining the mesh for good runs
a LaunchDaemon that dials out, where a device toggles a VPN. The two artefacts
come off the same peer entry and are NOT interchangeable — `jrleaf.conf` is
`wg setconf`-style and deliberately carries no `Address` line. Redeeming a
*device* code here would hand back the wrong one, so a device code is refused
before anything is written (`kind` is fixed at mint and cannot be re-declared).

Re-attach is not a second machine. If this Mac was attached before, the token
it was given then is presented alongside the new code, so the parent re-keys the
one device row it already holds for this machine instead of leaving a second one
behind — the same RE-PAIRING rule enrolment.py enforces for a phone re-running
the installer.

Every external edge is injectable — the HTTP POST (`poster`), the installer
invocation (`runner`), the bundle destination (`dest_dir`) — so the whole
sequence is driven in tests against a recorder and the real `install_leaf.sh`
under `LEAF_DEST`, with nothing brought up and no root required.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from . import hostenv, tunnel
from .enrolment import HOST_KEY_RE

#: The parent route this redeems against — the unauthenticated leaf/host
#: redemption path, mounted at the package's one API prefix.
REDEEM_PATH = "/api/jremote/v1/enrolment/redeem"

#: The port a host serves on when nobody says otherwise. Same number as
#: enrolment.DEFAULT_PORT and install_host.DEFAULT_PORT — the CLI passes the
#: real one through, so this only stands in for a caller that omitted it.
DEFAULT_PORT = 9090

#: Where this machine records the parent it attached to. Not the mesh — that
#: lives in the leaf daemons — but the device token the parent handed back,
#: which is the only copy there will ever be and is what a re-attach presents so
#: the parent re-keys rather than minting a second row. In the state dir, 0600,
#: beside the bearer token, because it is one.
PARENT_RECORD = "parent.json"

#: Per-file permissions for the bundle written to disk. `jrleaf.conf` carries a
#: private key; the shell scripts are executed. `install_leaf.sh` re-installs
#: everything under its own modes anyway, but it reads these first, and a
#: world-readable private key on the way in is still a leaked key.
_MODE = {
    "jrleaf.conf": 0o600,
    "leaf.env": 0o644,
    "install_leaf.sh": 0o755,
    "wg_up.sh": 0o755,
    "wg_leaf_watch.sh": 0o755,
    "README.md": 0o644,
}


class AttachError(Exception):
    """Attaching to the parent could not be completed. Carries a message meant
    to be printed to the person who ran the command."""


def _httpx_post(url: str, payload: dict) -> tuple[int, dict]:
    """POST `payload` as JSON, return (status, decoded body).

    httpx, the same client apns.py and spawn.py already depend on. A body that
    is not JSON comes back as {} — every status this cares about (200 success,
    FastAPI's {"detail": …} errors) is JSON, and a non-JSON 500 is handled by
    the caller as "no detail" rather than a decode crash.
    """
    import httpx
    try:
        resp = httpx.post(url, json=payload, timeout=30.0)
    except httpx.HTTPError as exc:
        raise AttachError(f"could not reach the parent at {url}: {exc}")
    try:
        body = resp.json()
    except ValueError:
        body = {}
    return resp.status_code, body if isinstance(body, dict) else {}


def _prior_token(state: Path) -> str:
    """The device token this machine was given last time it attached, or "".

    Presented as `device_token` so a re-attach re-keys the existing row on the
    parent instead of adding a second one. Absent, unreadable or malformed all
    fall through to "" — a plain first-time attach — because by the time this is
    read the only cost of getting it wrong is one extra device row, which the
    parent already treats as the normal case.
    """
    try:
        rec = json.loads((state / PARENT_RECORD).read_text())
        return str(rec.get("token") or "")
    except (OSError, ValueError):
        return ""


def _write_bundle(bundle: dict, dest: Path) -> Path:
    """Write the six leaf files to `dest`, each with the mode its job needs.

    Refuses a bundle that is missing any of `tunnel.LEAF_FILES` before writing a
    single byte — a partial bundle installs a tunnel that cannot come up, and it
    should fail here with the missing name, not later inside `install_leaf.sh`.
    """
    missing = [n for n in tunnel.LEAF_FILES if n not in bundle]
    if missing:
        raise AttachError(
            "the parent's leaf bundle is missing " + ", ".join(missing)
            + " — it would install a tunnel that cannot start")
    dest.mkdir(parents=True, exist_ok=True)
    for name in tunnel.LEAF_FILES:
        path = dest / name
        path.write_text(bundle[name])
        os.chmod(path, _MODE.get(name, 0o644))
    return dest


def _record_parent(state: Path, parent_url: str, result: dict) -> None:
    """Persist the token the parent handed back, 0600, so it is not lost.

    The redeem response is the only place this token ever appears. Dropping it
    would mean a re-attach mints a second device row on the parent every time —
    the exact multiplication enrolment.py's re-pairing path exists to stop.
    """
    device = result.get("device") or {}
    rec = {
        "parent_url": parent_url,
        "device_id": device.get("id", ""),
        "token": result.get("token", ""),
    }
    state.mkdir(parents=True, exist_ok=True)
    path = state / PARENT_RECORD
    path.write_text(json.dumps(rec, indent=2))
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def _redeem(parent_url: str, payload: dict, poster) -> dict:
    """Spend the code on the parent, mapping its status codes to plain words.

    The parent's answers are the router's: 400 for a bad host key or port
    (decided from the request, so it may be specific), 429 with a lockout, 401
    for every kind of bad code (deliberately indistinguishable), 200 with the
    device, token and — for a host code — the leaf bundle.
    """
    url = parent_url.rstrip("/") + REDEEM_PATH
    status, body = poster(url, payload)
    if status == 200:
        return body
    detail = body.get("detail") or f"HTTP {status}"
    if status == 429:
        raise AttachError(f"the parent is rate-limiting enrolment: {detail}")
    if status in (400, 401):
        raise AttachError(detail)
    raise AttachError(f"the parent refused the code ({status}): {detail}")


def attach(code: str, parent_url: str, *, host_key: str,
           port: int = DEFAULT_PORT, dest_dir: Path | None = None,
           poster=None, runner=None, sudo: bool = True,
           install_env: dict | None = None) -> dict:
    """Redeem a host code on `parent_url` and stand up the leaf tunnel it hands
    back, turning this Mac into a managed hub of the parent.

    Returns the facts of what happened: the device row and token the parent
    minted, the host row it recorded, whether an existing row was re-keyed, the
    bundle directory, and the reachability note. The *mode* this left the
    machine in is the CLI's to read afterwards, off the machine's own state —
    this function does the attaching and does not also grade it.

    Raises AttachError for anything a person can act on: an unusable host key, a
    parent that cannot be reached, a refused code, a device code where a host
    code was needed, a parent with no mesh to join, or an installer that failed.
    """
    poster = poster or _httpx_post
    runner = runner or subprocess.run

    if not HOST_KEY_RE.match(host_key or ""):
        raise AttachError(
            "this machine has no usable host id to present to the parent "
            f"({host_key!r}) — it should be 8 to 128 characters of letters, "
            "digits, dot, dash, underscore or colon")
    if not (parent_url.startswith("http://") or parent_url.startswith("https://")):
        raise AttachError(
            f"the parent address must be an http(s) URL, not {parent_url!r} — "
            "e.g. http://studio.local:9090")

    state = hostenv.state_dir()
    payload = {"code": code, "host_key": host_key, "port": int(port)}
    prior = _prior_token(state)
    if prior:
        payload["device_token"] = prior

    result = _redeem(parent_url, payload, poster)

    if result.get("kind") != "host":
        raise AttachError(
            "that code enrols a device, not a machine — attaching a Mac to a "
            "parent needs a host code (minted with kind=host on the parent)")

    peer = result.get("tunnel")
    if not peer or not peer.get("bundle"):
        # The code was spent and a device row exists on the parent, but the
        # parent runs no mesh, so there is nothing to dial into and this Mac is
        # not a managed hub. Say so plainly rather than reporting a success that
        # installed nothing.
        note = result.get("tunnel_note") or "the parent does not run a mesh"
        raise AttachError(
            f"the parent has no mesh to join — {note}. Nothing was installed; "
            "this machine did not become a managed hub.")

    dest = Path(dest_dir) if dest_dir else state / "leaf-bundle"
    _write_bundle(peer["bundle"], dest)
    _record_parent(state, parent_url, result)

    argv = (["sudo"] if sudo else []) + ["bash", str(dest / "install_leaf.sh")]
    env = dict(install_env) if install_env is not None else dict(os.environ)
    proc = runner(argv, cwd=str(dest), env=env,
                  capture_output=True, text=True)
    if proc.returncode != 0:
        raise AttachError(
            "the leaf installer failed: "
            + ((proc.stderr or proc.stdout or "").strip() or "no output")
            + f"\nthe bundle is at {dest} — fix the cause and re-run "
            "`sudo bash install_leaf.sh` from there")

    return {
        "device": result.get("device") or {},
        "token": result.get("token", ""),
        "host": result.get("host"),
        "superseded": bool(result.get("superseded")),
        "tunnel_note": result.get("tunnel_note", ""),
        "bundle_dir": str(dest),
        "parent_url": parent_url,
        "installer_output": (proc.stdout or "").strip(),
    }
