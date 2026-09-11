"""Whether a machine this hub adopts holds a credential back into this hub.

Attach establishes trust in both directions in one request, and only one of
them is ever the thing somebody meant. The grant the hub receives is the point.
The token the adopted machine receives is the side effect — and on hardware the
hub's owner cannot vouch for, it is a live credential on somebody else's disk.
"""

from __future__ import annotations

import pytest

from jstack_host import hub_prefs


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(hub_prefs, "_STATE", tmp_path / "hub_prefs.json")


def test_reachback_is_on_until_somebody_turns_it_off():
    """The default is what every already-adopted machine is living under.

    A setting that silently cut live access on upgrade would be worse than the
    thing it protects against.
    """
    assert hub_prefs.get("leaf_reachback") is True


def test_the_switch_survives_being_set():
    hub_prefs.set("leaf_reachback", False)
    assert hub_prefs.get("leaf_reachback") is False
    hub_prefs.set("leaf_reachback", True)
    assert hub_prefs.get("leaf_reachback") is True


def test_an_unknown_flag_is_refused_rather_than_stored():
    """A typo that stores cleanly is a switch that appears to work and does nothing."""
    with pytest.raises(KeyError):
        hub_prefs.set("leaf_reachbak", False)
    with pytest.raises(KeyError):
        hub_prefs.get("leaf_reachbak")


def _redeem_host_code(name="work-mac"):
    """Mint a host code and spend it, the way `attach` does."""
    from jstack_host import enrolment

    row = enrolment.mint_code(name, created_by="", kind=enrolment.KIND_HOST)
    return enrolment.redeem(row["code"], "198.51.100.4", host_key="k-" + name)


def test_a_host_code_redeemed_with_reachback_off_hands_back_a_dead_token():
    """The point of the switch, asserted through the real redeem.

    The row is still written — it is the record that the machine enrolled at
    all, and a leaf with no row is a leaf no surface can show. What it must not
    be is usable.
    """
    from jstack_host import devices

    hub_prefs.set("leaf_reachback", False)
    out = _redeem_host_code()

    assert out["reachback"] is False, "the redeemer was not told"
    assert devices.is_revoked(out["device"]["id"]), \
        "the credential handed back is live — the switch did nothing"
    assert devices.authenticate(out["token"]) is None, \
        "the token still authenticates against this hub"


def test_a_host_code_redeemed_with_reachback_on_hands_back_a_live_token():
    """The default, asserted the same way — or the test above proves nothing."""
    from jstack_host import devices

    hub_prefs.set("leaf_reachback", True)
    out = _redeem_host_code("other-mac")

    assert out["reachback"] is True
    assert not devices.is_revoked(out["device"]["id"])
    assert devices.authenticate(out["token"]) is not None


def test_turning_it_off_does_not_reach_live_machines_by_itself():
    """`set` never ends live access; `revoke_existing_reachback` is its own word.

    A flag that quietly cut a running machine off would be the same class of
    surprise the setting exists to prevent — so the destructive half is named
    separately and called by the thing that decided to.
    """
    import inspect
    src = inspect.getsource(hub_prefs.set)
    assert "revoke_existing_reachback" not in src
