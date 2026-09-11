"""Switches that belong to this MACHINE as a hub, not to any agent on it.

`agent_prefs.py` is per-agent and about sessions. This is the other axis: what
this Mac allows the machines it has adopted to do to *it*.

The one flag here exists because attach establishes trust in BOTH directions at
once, and only one of them is ever the thing somebody meant. Redeeming a host
code hands the joining machine a device token for this hub, and the same
request hands this hub a grant on that machine. The second direction is the
point — it is what lets a phone paired here reach a Mac at the office without
typing a second code. The first is a side effect nobody chose: the office Mac
can now drive this one, because it holds an ordinary device credential for it.

For a machine you own on both ends that is fine and usually wanted. For a
machine you do not fully control — a work laptop, a box someone else
administers — it is a credential on your home hub sitting on hardware whose
disk you cannot vouch for. `leaf_reachback` is the switch for that case.

Default ON, because that is what every already-adopted machine is living under
and a setting that silently cuts live access on upgrade is worse than the thing
it protects against.
"""

import json
import threading

from . import hostenv

_STATE = hostenv.state_dir() / "jremote_hub_prefs.json"
_lock = threading.Lock()

#: Every flag this hub knows, and what it is worth when nobody has said.
#:
#: `leaf_reachback` — may a machine this hub adopts hold a credential back to
#: this hub? Off means the adoption still works in the direction that was
#: asked for (this hub administers that machine, and devices paired here reach
#: it), and the return credential is revoked the moment it is minted. It is
#: minted and then revoked rather than never minted because the row is the
#: record that the machine enrolled at all — a leaf with no row is a leaf this
#: hub cannot show anyone, and the audit trail is the thing the cautious
#: setting should be strengthening, not deleting.
FLAGS = {"leaf_reachback": True}


def _load() -> dict:
    try:
        d = json.loads(_STATE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return d if isinstance(d, dict) else {}


def all() -> dict:
    """Every flag with its effective value — defaults filled in."""
    stored = _load()
    return {name: bool(stored.get(name, default))
            for name, default in FLAGS.items()}


def get(flag: str) -> bool:
    if flag not in FLAGS:
        raise KeyError(f"unknown hub flag {flag!r}")
    return bool(_load().get(flag, FLAGS[flag]))


def set(flag: str, value: bool) -> bool:
    """Store `flag` and return what it now reads.

    A flag not in `FLAGS` is refused rather than stored, for the reason
    `agent_prefs` refuses one: a typo that stores cleanly is a switch that
    appears to work and changes nothing on the Mac.
    """
    if flag not in FLAGS:
        raise KeyError(f"unknown hub flag {flag!r}")
    with _lock:
        d = _load()
        d[flag] = bool(value)
        _STATE.parent.mkdir(parents=True, exist_ok=True)
        _STATE.write_text(json.dumps(d, indent=2, sort_keys=True))
    return bool(value)


def revoke_existing_reachback() -> list[str]:
    """Revoke the credential every already-adopted machine holds back to here.

    Turning the switch off has to reach the machines already adopted or it is
    not a switch, it is a note about future ones. Named separately and never
    called from `set`, because this one ends live access and the caller should
    be the thing that decided to.

    Returns the names it revoked. Only ever revokes: the reverse is not a
    restore, since the machine is holding a token whose row is now dead and
    only a fresh attach can give it a live one. Saying that is the honest
    answer; silently re-minting a credential somebody switched off would be
    the dishonest one.
    """
    from . import devices, store as _store_mod

    store = _store_mod.SessionStore()
    leaves = {h["name"] for h in store.list_hosts() if h.get("name")}
    revoked = []
    for row in devices.list_all():
        if row.get("name") in leaves and not row.get("revoked"):
            if devices.revoke(row["id"]):
                revoked.append(row["name"])
    return revoked
