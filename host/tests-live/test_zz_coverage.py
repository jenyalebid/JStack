"""The gate: every route the host serves was exercised against a real host.

This is the file that makes "we test every action" a fact instead of a claim.
The inventory is read off the routers at runtime, so a route added tomorrow is
uncovered tomorrow — there is no second list to keep in sync, because a second
list is how coverage claims rot.

**`zz` is load-bearing.** pytest collects files in alphabetical order and this
one reads what every other file recorded, so it has to sort last. A prettier
name would make the gate pass by having nothing to check yet.

A route may be left uncovered only by appearing in `UNCOVERED` with a reason
that is true. That list is the suite's own honesty: it prints on every run, so
a skip cannot hide in a green suite. Adding to it is a decision someone makes
out loud, not a silence.
"""

from __future__ import annotations

import pytest

from conftest import BASE_URL


#: Routes with no live test, and why. Every entry prints on every run.
#:
#: Keep this empty where you can. Each line is a live action nobody has proven
#: on a real host, and "it is hard to test" is how a surface stays untested
#: for a year.
UNCOVERED: dict[tuple[str, str], str] = {
    ("POST", "/api/jremote/v1/tunnel/pair"):
        "mints a WireGuard peer bundle. The guest-to-guest handshake is a "
        "proven dead end on this Mac (~/Systems/vm/SYSTEM.md), so a live "
        "call here would enrol a peer that can never complete — the install "
        "path is covered by the mesh runbook instead.",
}


def _inventory() -> set[tuple[str, str]]:
    """Every (METHOD, path) the host serves, read off the routers themselves."""
    from jstack_host.router import router, unauthenticated_router
    from jstack_host.pty import ws_router

    found: set[tuple[str, str]] = set()
    for r in (router, unauthenticated_router, ws_router):
        for route in r.routes:
            methods = getattr(route, "methods", None)
            if not methods:  # a websocket route has no HTTP method
                found.add(("WS", route.path))
                continue
            for m in methods:
                if m in ("HEAD", "OPTIONS"):  # starlette adds these itself
                    continue
                found.add((m, route.path))
    return found


@pytest.mark.skipif(not BASE_URL, reason="live suite is opt-in")
def test_every_route_was_exercised_against_a_real_host(exercised):
    inventory = _inventory()
    missing = sorted(inventory - exercised - set(UNCOVERED))

    for route, reason in sorted(UNCOVERED.items()):
        print(f"  UNCOVERED {route[0]:6} {route[1]} — {reason}")
    print(f"  live coverage: {len(inventory) - len(missing) - len(UNCOVERED)}"
          f"/{len(inventory)} routes exercised, {len(UNCOVERED)} declared "
          f"uncovered, {len(missing)} untested")

    assert not missing, (
        "routes the host serves that no live test called:\n  "
        + "\n  ".join(f"{m:6} {p}" for m, p in missing)
        + "\n\nAdd a live test, or add the route to UNCOVERED with a reason.")


@pytest.mark.skipif(not BASE_URL, reason="live suite is opt-in")
def test_the_uncovered_list_has_no_stale_entries(exercised):
    """An excuse for a route that no longer exists, or that is now tested, is
    an excuse nobody rechecked. Both directions are a failure: the first means
    the list is fiction, the second means it is understating coverage."""
    inventory = _inventory()
    gone = sorted(set(UNCOVERED) - inventory)
    assert not gone, f"UNCOVERED names routes the host does not serve: {gone}"

    now_tested = sorted(set(UNCOVERED) & exercised)
    assert not now_tested, (
        f"UNCOVERED claims these are untestable, but a test called them: "
        f"{now_tested}. Delete the excuse.")


def test_the_inventory_is_not_empty():
    """A router that imported to nothing would make every coverage claim above
    vacuously true. Runs without a live host on purpose — this one is about
    the gate, not the machine."""
    assert len(_inventory()) > 50
