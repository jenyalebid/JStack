"""One-time enrolment codes — authorization that travels, so the device doesn't.

Both credential paths this host owns are gated on the caller's source address:
`POST /devices` mints a token only from the LAN, `POST /tunnel/pair` issues a
peer config only from the LAN. That gate is not a permission check — it is a
*reachability* check standing in for one. On the LAN, being there is the proof.

Which is fine until the machine that needs enrolling is never on the LAN. A
second Mac in another building has no way in: root on it dissolves nothing,
because the thing it lacks is an address the hub will accept. Carrying a
config over by hand is the manual step this whole channel exists to remove.

So the proof gets carried explicitly instead of inferred from where the packet
came from (docs/multi-host-access.md, P3):

> **Enrolment is authorized, not located.** The hub mints a one-time,
> short-lived enrolment code. It is typed once into the new machine. That
> machine redeems it for its own device token and, on a host that owns a mesh,
> its own WireGuard peer.

Four properties carry the safety the address gate used to:

  · **Single-use**, enforced by a conditional UPDATE in the store, so two
    machines racing the same code cannot both win.
  · **Short-lived** — ten minutes by default, an hour at the most.
  · **Minted by an authenticated party**, and the row records *which* device
    minted it. Enrolment is attributable, permanently.
  · **Rate-limited** through the same two-tier limiter as bearer auth, keyed
    per-address, because redemption is by definition unauthenticated.

WHAT THIS WIDENS, PLAINLY. Before this module a stolen device token could not
mint more credentials from outside the LAN; now it can mint a code, and the code
mints a device. That is the deliberate trade the design named, and two things
bound it: the `created_by` column makes every enrolment traceable to the
credential that authorized it, and a code whose creator has since been revoked
is refused at redemption — so revoking a lost phone also kills the codes it left
outstanding, rather than leaving them live for their whole TTL.

The codes table never syncs, for the same reason `devices` never does. See the
schema comment in store.py.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time

from . import auth, devices, hostenv

# No 0/O/1/I. A code is read off one screen and typed into another machine, so
# the character pairs that look alike are the ones that turn a good code into a
# failed enrolment nobody can debug — and the failure is terminal either way,
# because the attempt that consumed it is the only one there was.
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
CODE_LEN = 8          # 32**8 = 2**40, against a ten-minute window and a limiter
GROUP = 4             # displayed XXXX-XXXX; grouping is display, never content

DEFAULT_TTL = 600     # ten minutes — the doc's number, and long enough to walk
MIN_TTL = 60
MAX_TTL = 3600

# The limiter scope redemption counts under. Not a device id — there is no
# device yet, which is the whole point — so every redemption from one address
# shares a bucket, and guessing codes trips the same lockout and the same alert
# as guessing tokens.
LIMITER_SCOPE = "enrol"

# One refusal message for every cause. Unknown, expired, already used and
# mistyped must be indistinguishable in the response, or the endpoint becomes
# an oracle telling an attacker which of its guesses was structurally right.
REFUSED = "that enrolment code is not valid — ask for a new one"

# What a code enrols. A device gets a token and, where the host owns a mesh, a
# peer; a host gets those *and* a row in `hosts`, so every device mirroring this
# one learns the machine exists without anybody typing its address in.
#
# The kind is fixed at mint. It cannot be a field on the redemption request:
# whoever redeems is by definition unauthenticated, and one that could declare
# itself a host would write its own row into the grid the user reads to decide
# which machines to trust.
KIND_DEVICE = "device"
KIND_HOST = "host"
KINDS = (KIND_DEVICE, KIND_HOST)

# A host key is the redeeming machine's own `/host` id — minted there, never
# here, because local-first routing compares it against what the host on
# loopback answers. Free-form (JREMOTE_HOST_ID overrides it), so this bounds the
# shape rather than the format.
HOST_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")

DEFAULT_PORT = 9090


class EnrolmentError(Exception):
    """The code was not one this host will honour."""


class HostKeyRefused(Exception):
    """The machine's declared key or port is not one we can record.

    Its own exception, and it is raised BEFORE any code is looked up. A refusal
    that came after the lookup would answer differently depending on whether the
    code existed, which is exactly the oracle `REFUSED` exists to deny — so this
    one may say what is wrong, because at the point it is raised this host has
    not yet learned anything about the code.
    """


class EnrolmentLockedOut(Exception):
    """Too many bad codes from this address. Carries the seconds remaining."""

    def __init__(self, seconds: int):
        super().__init__("too many failed enrolment attempts — locked out")
        self.seconds = seconds


def _store():
    """The store holding the codes. A seam, so tests point enrolment at their
    own file instead of this Mac's — same shape as devices._store."""
    from .store import get_store
    return get_store()


def _hash(code: str) -> str:
    return "sha256:" + hashlib.sha256(code.encode()).hexdigest()


def normalize(raw: str) -> str:
    """A typed code → its canonical form, or "" when it cannot be one.

    Case and grouping are presentation: `mfq4-7k2p`, `MFQ47K2P` and `mfq4 7k2p`
    are one code. Characters outside the alphabet are dropped rather than
    mapped — they are excluded precisely *because* they are ambiguous, so a
    typed `O` has no single right answer, and dropping it yields the wrong
    length, which fails cleanly instead of silently redeeming something else.
    """
    cleaned = "".join(c for c in raw.upper() if c in ALPHABET)
    return cleaned if len(cleaned) == CODE_LEN else ""


def display(code: str) -> str:
    return f"{code[:GROUP]}-{code[GROUP:]}"


# ── minting ──

def mint_code(name: str, created_by: str, ttl: int = DEFAULT_TTL,
              kind: str = KIND_DEVICE) -> dict:
    """A new code for a device to be called `name`. Returned once, never stored.

    The name travels with the code rather than being chosen at redemption: the
    person minting it knows which machine it is for, and a redeemer that got to
    name itself could enrol under the name of a device the user already trusts,
    in the very registry they read to decide what to revoke. `kind` travels for
    the same reason, and a harder one — see the constants above.
    """
    if kind not in KINDS:
        raise EnrolmentError(f"unknown enrolment kind {kind!r}")
    try:
        ttl = int(ttl)
    except (TypeError, ValueError):
        ttl = DEFAULT_TTL
    ttl = max(MIN_TTL, min(MAX_TTL, ttl))
    now = int(time.time())
    store = _store()
    store.sweep_enrolment_codes(now)
    for _ in range(3):
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
        if store.add_enrolment_code(_hash(code), name, now + ttl,
                                    created_by, kind):
            return {"code": display(code), "name": name, "kind": kind,
                    "expires_at": now + ttl, "expires_in": ttl}
    raise RuntimeError("could not mint an enrolment code")  # 3 collisions in 2**40


# ── redemption ──

def _creator_revoked(row: dict) -> bool:
    """Was the code minted by a credential that has since been revoked?

    Checked before the code is consumed, so a revoked phone's outstanding codes
    die with it instead of staying live for the rest of their TTL. A creator
    this host has no row for is not treated as revoked — codes minted by the
    host's own tooling carry no device id, and refusing those would break
    provisioning to close nothing.
    """
    creator = (row.get("created_by") or "").strip()
    if not creator:
        return False
    device_row = _store().device(creator)
    return device_row is not None and device_row["revoked_at"] is not None


PEER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")


def peer_name(name: str) -> str:
    """A device name → a name `wg_peer.py` will accept, or "".

    Device names are what the user typed ("My Laptop"); peer names are a
    filename and a config stanza key. Deriving one from the other keeps the
    enrolment to a single typed code — the alternative is asking whoever mints
    the code for a second, syntactically-constrained name they would have to
    know the rules for.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:31]
    slug = slug.rstrip("-")
    return slug if PEER_NAME_RE.match(slug) else ""


def _tunnel_for(name: str, leaf: bool = False) -> tuple[dict | None, str]:
    """This device's peer config, or None and the reason there isn't one.

    Never raises. By the time this runs the code is already burned and the
    token already minted, so an exception here would cost the caller a
    credential it can never ask for again — over a tunnel that half of the
    hosts running this package do not even have. A leaf reaching this answers
    "no mesh to join", which is a fact about the host, not a failure.

    `leaf` follows the code's kind, not the caller's word for itself: a machine
    joining the mesh for good needs the install bundle, and a device toggling a
    VPN needs the client conf. They come off the same peer entry and are not
    interchangeable.
    """
    peer = peer_name(name)
    if not peer:
        return None, f"no WireGuard peer name can be made from {name!r}"
    from . import tunnel
    try:
        return tunnel.issue(peer, leaf=leaf), ""
    except tunnel.PairingUnsupported as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 — see the docstring: never lose the token
        return None, f"pairing {peer} failed: {type(exc).__name__}: {exc}"


# A client conf carries `Address = 10.66.0.7/32`; a leaf bundle carries the
# same fact as `WG_ADDR=10.66.0.7/32` in leaf.env, because `wg setconf` rejects
# an Address line as wg-quick syntax. One pattern for both, so the registry
# cannot end up with an address for one kind of peer and a blank for the other.
MESH_ADDRESS_RE = re.compile(r"^\s*(?:Address\s*=|WG_ADDR=)\s*([0-9.]+)", re.M)


def mesh_address(peer: dict | None) -> str:
    """The address `wg_peer.py` just handed this peer, read off what it wrote.

    The registry row has to carry an address a device can dial, and the only
    thing that knows it is the artefact the tunnel wrote a moment ago — asking
    `wg_peer.py` again would be a second answer that could disagree with the
    one the machine was actually given.
    """
    if not peer:
        return ""
    text = peer.get("config") or (peer.get("bundle") or {}).get("leaf.env", "")
    match = MESH_ADDRESS_RE.search(text or "")
    return match.group(1) if match else ""


def _check_host_claim(host_key: str, port: int) -> int:
    """Validate what a machine says about itself, or refuse loudly.

    Runs before the code is even looked up, so its detailed refusals cannot
    become an oracle. Returns the port to record.
    """
    if not HOST_KEY_RE.match(host_key or ""):
        raise HostKeyRefused(
            "that is not a usable host key — it is the machine's own id from "
            "its /host response, 8 to 128 characters of letters, digits, dot, "
            "dash, underscore or colon")
    # Absent falls back; zero does not. A caller that sent a port is telling us
    # something, and quietly substituting 9090 for it would put an address in
    # the registry that nothing is listening on.
    if port in (None, ""):
        port = DEFAULT_PORT
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise HostKeyRefused("that is not a usable port")
    if not 1 <= port <= 65535:
        raise HostKeyRefused("that is not a usable port")
    return port


def redeem(raw_code: str, client_ip: str, host_key: str = "",
           port: int = DEFAULT_PORT) -> dict:
    """Spend a code: a device token, and a peer config where one applies.

    Order is deliberate. A declared host key is checked first, before this host
    has looked at the code at all — that is what lets its refusal be specific.
    The limiter is next, because a locked-out address must not get to burn a
    code it guessed. The creator check comes before the consume, because
    refusing a revoked minter's code should leave the code claimable by nobody
    rather than mark it used. Then the kind check, still before the consume: a
    host code redeemed without a key must stay claimable by the machine that was
    actually meant to have it. The consume is atomic, and everything after it
    has to succeed or degrade, never raise.
    """
    if host_key:
        port = _check_host_claim(host_key, port)

    scope = f"{client_ip}|{LIMITER_SCOPE}"
    remaining = auth.lockout_remaining(client_ip, scope)
    if remaining:
        raise EnrolmentLockedOut(int(remaining) + 1)

    code = normalize(raw_code)
    code_hash = _hash(code) if code else ""
    store = _store()
    now = int(time.time())

    row = store.enrolment_code(code_hash) if code_hash else None
    if row is None or _creator_revoked(row):
        auth.note_failure(client_ip, scope)
        raise EnrolmentError(REFUSED)
    kind = row.get("kind") or KIND_DEVICE
    if kind == KIND_HOST and not host_key:
        # The same blank refusal as an unknown code, deliberately: naming this
        # cause would tell a guesser their code was real. Unconsumed, so the
        # machine this was minted for can still spend it.
        auth.note_failure(client_ip, scope)
        raise EnrolmentError(REFUSED)
    if not store.consume_enrolment_code(code_hash, f"from {client_ip}", now):
        auth.note_failure(client_ip, scope)   # used, or expired: still a miss
        raise EnrolmentError(REFUSED)

    device_row, token = devices.mint(row["name"])
    device_row["revoked"] = False
    store.note_enrolment_device(code_hash, f"{device_row['id']} from {client_ip}")

    peer, note = _tunnel_for(row["name"], leaf=kind == KIND_HOST)
    host_row = None
    if kind == KIND_HOST:
        # After the token, and never conditional on the tunnel: a machine with
        # no route yet is still a machine this host let in, and a row with an
        # empty address says exactly that. Dropping it would lose the only
        # record of an enrolment whose code is already spent.
        host_row = _register_host(row["name"], host_key,
                                  mesh_address(peer), port)
    _announce(row, device_row, client_ip, kind)
    return {"device": device_row, "token": token,
            "tunnel": peer, "tunnel_note": note,
            "kind": kind, "host": host_row}


def _register_host(name: str, key: str, address: str, port: int) -> dict:
    row = _store().upsert_host(key, name, address, port)
    row["deleted"] = bool(row["deleted"])
    return row


def _announce(code_row: dict, device_row: dict, client_ip: str,
              kind: str = KIND_DEVICE) -> None:
    """Say out loud that a device just joined this host.

    A new credential minted from off the LAN is the exact event the address
    gate used to make impossible, so it must not be silent. Threaded for the
    same reason the limiter's alerts are: a Telegram send must never stall the
    request that earned it.
    """
    what = "machine" if kind == KIND_HOST else "device"
    body = (f"jRemote enrolment: {what} {device_row['name']} "
            f"({device_row['id']}) joined {hostenv.host_name()} from "
            f"{client_ip or 'local'}, on a code minted by "
            f"{code_row.get('created_by') or 'the host'}.")
    threading.Thread(target=hostenv.security_alert, args=(body,),
                     daemon=True).start()


# ── the registry surface ──

def list_codes() -> list[dict]:
    """Every code this host is still carrying, expired-but-unused ones swept.

    `code_hash` never leaves this function. The code is 40 bits; a published
    digest of it is not a one-way door, it is the code with an afternoon of
    compute in front of it — and unlike a device token there is no second
    factor behind it.
    """
    now = int(time.time())
    store = _store()
    store.sweep_enrolment_codes(now)
    out = []
    for row in store.list_enrolment_codes():
        row.pop("code_hash", None)
        row["state"] = ("used" if row["used_at"]
                        else "expired" if row["expires_at"] <= now
                        else "live")
        out.append(row)
    return out


def revoke(raw_code: str) -> bool:
    """Withdraw an unused code, by the code itself.

    By the code and not by an id, because the only person who can revoke one is
    the person holding it, and a ten-minute credential does not need a naming
    scheme to outlive it. A used row is never deleted — it is the record of
    which device this host let in.
    """
    code = normalize(raw_code)
    return bool(code) and _store().revoke_enrolment_code(_hash(code))


def sweep() -> int:
    """Drop expired, unused codes. Housekeeping — expiry is enforced at
    redemption, so a code this misses is already dead."""
    return _store().sweep_enrolment_codes(int(time.time()))
