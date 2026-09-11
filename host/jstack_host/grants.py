"""Delegated minting — a device trusted by the hub gets into a leaf without
being paired to it.

This is the half of managed mode that made the promise untrue. `attach_parent`
puts a machine on the parent's mesh and writes it into the parent's `hosts`
table, so every device already paired to the parent can *reach* it and can *see*
that it exists. Then it hits a wall that has nothing to do with the network:
every host runs the identical package, owns its own `devices` table and mints
its own tokens, and a credential for the hub proves nothing on the leaf. The
user, who joined a machine to a hub precisely so they would not have to go and
set it up, is asked to go and set it up.

`POST /devices` cannot be the answer and should not become it: minting is
LAN/loopback-only and explicitly refuses the mesh subnet (`devices.
mint_allowed_from`), because a caller inside the tunnel turning one credential
into an unbounded supply of them is the exact thing that gate exists to stop.
So the hub gets a narrower key, and one door it opens.

## The shape

Attach is where the trust is established, in both directions at once:

  · the leaf redeems a host code and receives a device token **for the hub** —
    that half already existed;
  · the leaf mints a **grant** on itself and hands it to the hub in the same
    request. The hub keeps it (`host_grants`, in the clear, because presenting
    it is the job). The leaf keeps its digest (`parent_grants`).

Afterwards a device asks the hub — `POST /hosts/{key}/grant` — for access to a
machine the hub adopted. The hub presents its grant to that machine's
`POST /delegate/mint`, the machine mints an ordinary device row of its own and
returns the token, and the hub hands it back to the device. The device stores a
credential minted BY the leaf, revocable AT the leaf, and nobody typed anything.

## What a grant can do, and the reason it is not a device row

Exactly one route. A grant is not in `devices`, so it authenticates nothing that
takes `require_token`: it cannot drive an agent, read a session, list devices or
pair a phone. It mints, and the thing it mints is an ordinary device row that
shows up in the roster under a name the user reads, and dies when they revoke it.

That narrowness is structural on purpose. A `devices` row with an `is_parent`
flag would have been fewer lines and would have put the whole API behind a
credential whose only intended power is minting — protected by every future
route remembering to check a flag. A separate gate cannot be forgotten into.

## The trade, stated

A hub holding grants means **compromising the hub is minting rights on every
machine attached to it**. Boss ruled yes on that on 2026-09-02 (decision 1 in
docs/multi-host-access.md) with the trade named: the hub is the machine that
already holds every credential on it, so this widens the blast radius on paper
and not in fact. The fallback if that ever stops being true is in the same
document — a per-device code typed once per machine — and it needs no new
mechanism, only for the hub to stop being asked.

Revocation exists at both ends and they mean different things. The leaf revoking
(`parent_grants`) is authority actually ending, because the leaf is what
verifies. The hub revoking (`host_grants`) is the hub choosing to stop
delegating — useful, and NOT a security control: a hub that still holds the
plaintext could put it back. Anything meant as a lockout happens on the leaf.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid

#: Grant tokens are their own namespace. `jr1.` is a device token and `jrg1.` is
#: a grant, and the prefix is what makes a grant presented to `require_token`
#: fail as an unknown credential rather than being parsed as a device id — two
#: credential formats sharing a prefix is how one gets accepted where the other
#: was meant.
GRANT_PREFIX = "jrg1"

#: The route a grant authenticates. One constant, named here, so the module that
#: *holds* a grant and the module that *verifies* one cannot drift apart on it.
MINT_PATH = "/api/jremote/v1/delegate/mint"


class GrantError(Exception):
    """Delegated minting could not be completed. The message is meant for the
    person who asked for the access, not for a log."""


def _store():
    from .store import get_store
    return get_store()


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def parse(presented: str) -> tuple[str, str]:
    """`jrg1.<id>.<secret>` → (id, secret), or ("", "") for anything else."""
    parts = (presented or "").split(".")
    if len(parts) != 3 or parts[0] != GRANT_PREFIX:
        return "", ""
    return parts[1], parts[2]


# ── the leaf's end: issuing and verifying ──

def issue(parent: str) -> str:
    """Mint a grant for `parent` and return it. The token exists only in this
    return value — the caller's one job is to hand it over and forget it.

    `parent` is a label, not an authority: it is what the grant roster shows a
    person, and nothing branches on it. Two grants from two parents are two
    independent credentials, each revocable alone.
    """
    grant_id = uuid.uuid4().hex[:12]
    secret = secrets.token_urlsafe(32)
    _store().put_parent_grant(_hash(secret), parent or "")
    return f"{GRANT_PREFIX}.{grant_id}.{secret}"


def authenticate(presented: str) -> str | None:
    """The parent label behind a live grant, or None.

    Hashed compare against the stored digest, constant-time, the same posture
    `devices.authenticate` holds — and like it, this never grandfathers anything
    into existence. A host with no grants issued authenticates nobody, which is
    the correct answer for a machine that has never been attached to anything.
    """
    _, secret = parse(presented)
    if not secret:
        return None
    row = _store().parent_grant(_hash(secret))
    if row is None:
        return None
    # The digest IS the key, so a row coming back is already the match. The
    # compare stays as the explicit, constant-time statement of that — a future
    # lookup that widens (by id, say) must not silently become a bare equality.
    if not hmac.compare_digest(row["token_hash"], _hash(secret)):
        return None
    return row["parent"] or "(unnamed parent)"


def note_used(presented: str) -> None:
    _, secret = parse(presented)
    if secret:
        _store().note_parent_grant_used(_hash(secret))


def revoke_issued(parent: str = "") -> int:
    """Revoke grants this machine issued — one parent's, or every one. This is
    the revocation that actually ends authority, because this is the end that
    verifies."""
    return _store().revoke_parent_grants(parent)


def issued() -> list[dict]:
    return _store().list_parent_grants()


# ── the hub's end: holding and spending ──

def remember(host_key: str, token: str, parent_url: str = "") -> None:
    """Keep the grant a machine issued at attach. Silently ignores an empty
    token: a leaf running a build from before this existed sends none, and it is
    a machine that joined the mesh without delegating, not an error."""
    if token:
        _store().put_host_grant(host_key, token, parent_url)


def held(host_key: str) -> str:
    row = _store().host_grant(host_key)
    return (row or {}).get("token", "")


def forget(host_key: str) -> bool:
    return _store().revoke_host_grant(host_key)


def holdings() -> list[dict]:
    """Which machines this host can mint on — never the tokens themselves."""
    return _store().list_host_grants()


def _httpx_post(url: str, payload: dict, token: str) -> tuple[int, dict]:
    import httpx
    try:
        resp = httpx.post(url, json=payload, timeout=20.0,
                          headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError as exc:
        raise GrantError(f"could not reach {url}: {exc}")
    try:
        body = resp.json()
    except ValueError:
        body = {}
    return resp.status_code, body if isinstance(body, dict) else {}


def mint_on(host_row: dict, name: str, poster=None) -> dict:
    """Spend this host's grant on `host_row`'s machine and return what it minted.

    The address comes off the registry row — the mesh address the machine was
    handed when it joined — and never from the caller. A device naming the host
    it wants a token from would be a device pointing this host's credential at
    a machine of its choosing, which turns a grant into an oracle.

    Returns the leaf's own answer plus the facts a device needs to store the
    result: which machine, at which address, on which port.
    """
    poster = poster or _httpx_post
    key = host_row.get("key") or ""
    token = held(key)
    if not token:
        raise GrantError(
            f"this host holds no grant for {host_row.get('name') or key} — it "
            "joined the mesh without delegating, or the grant was revoked here. "
            "Re-attach that machine to restore it.")
    address = (host_row.get("address") or "").strip()
    if not address:
        raise GrantError(
            f"{host_row.get('name') or key} has no address in the registry — it "
            "enrolled without a mesh peer, so there is nothing to reach.")
    port = int(host_row.get("port") or 9090)
    url = f"http://{address}:{port}{MINT_PATH}"

    status, body = poster(url, {"name": name}, token)
    if status == 200:
        _store().note_host_grant_used(key)
        return {"host": key, "name": body.get("device", {}).get("name", name),
                "address": address, "port": port,
                "device": body.get("device") or {},
                "token": body.get("token", "")}
    detail = body.get("detail") or f"HTTP {status}"
    if status in (401, 403):
        raise GrantError(
            f"{host_row.get('name') or key} refused this host's grant — it was "
            f"revoked there ({detail}). Re-attach that machine to restore it.")
    raise GrantError(f"{host_row.get('name') or key} could not mint ({status}): "
                     f"{detail}")


def stamp(ts) -> str:
    """An epoch second as a readable line, or "" — shared by the CLI surfaces
    that print a grant roster."""
    if not ts:
        return ""
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))
