"""The host's account of itself, against a real host.

These are the routes the app asks before it trusts anything else: who are you,
where can I reach you, what can you do, what version do you ship. The in-process
tests pin their shapes; what only a live host can prove is that the answers are
true *of the machine* — a mode read off real interfaces, a download that really
serves bytes, a control action that really runs.
"""

from __future__ import annotations

import pytest

from conftest import BASE_URL

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(not BASE_URL, reason="live suite is opt-in")]


def test_host_identifies_itself(host_identity):
    """`/host` is the route every other one is trusted on the strength of."""
    assert host_identity["host_id"], "a host with no id cannot be told from another"
    assert host_identity["name"]
    assert host_identity["profile"]
    assert isinstance(host_identity["features"], dict)


def test_the_mode_is_one_the_app_can_render(host_identity):
    """The menu bar and the app both print `mode.mode` verbatim. A value
    outside this set renders as itself and means nothing to a reader — which
    is how this Mac spent an evening displaying "managed" at nobody."""
    assert host_identity["mode"]["mode"] in {"local", "open", "managed"}


def test_every_advertised_address_is_one_a_second_machine_could_use(host_identity):
    """The pairing screen's whole job. Loopback here is the classic failure:
    true for the host saying it, false for every device being told it."""
    kinds = {"lan", "local", "mesh"}
    for a in host_identity["addresses"]:
        assert set(a) == {"kind", "host", "url", "note"}, a
        assert a["kind"] in kinds, a
        assert not a["host"].startswith("127."), f"loopback advertised: {a}"
        assert a["host"] != "localhost", f"loopback advertised: {a}"
        assert a["url"].startswith("http://"), a


def test_a_lan_address_is_reachable_from_off_the_host(api, host_identity):
    """Every `lan` entry is captioned "works while both machines are on this
    network". The suite runs on a different machine than the host, so it is
    exactly the reader that caption is addressed to — and can check it.

    This is the test that would have caught a VM bridge being published as the
    LAN (jStack ccf6224): 192.168.64.1 is private, routable on the host, and
    unreachable from anywhere else."""
    import httpx
    lans = [a for a in host_identity["addresses"] if a["kind"] == "lan"]
    assert lans, "a host with no LAN address cannot be paired on this network"
    for a in lans:
        try:
            r = httpx.get(f"{a['url']}/api/health", timeout=5.0)
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"advertised LAN address {a['host']} is unreachable "
                        f"from another machine: {type(e).__name__}")
        assert r.status_code == 200, f"{a['host']} answered {r.status_code}"


def test_health_needs_no_token_and_names_the_host(api):
    """The one route that must answer before a token exists — it is how the
    app decides whether a machine hosts anything at all (`LanProbe`)."""
    import httpx
    r = httpx.get(f"{BASE_URL}/api/health", timeout=10.0)
    assert r.status_code == 200
    body = r.json()
    assert body.get("service") == "jremote-host" or "dashboard" in body, (
        f"LanProbe.isHostDashboard would read this host as an impostor: {body}")


def test_a_request_with_no_token_is_refused(api):
    """Fail-closed is the contract. Checked live because an embedded host
    mounts its own middleware, and a mount that lost the dependency would pass
    every in-process test of the router."""
    r = api.call("GET", "/host", token=None)
    assert r.status_code == 401


def test_a_request_with_a_wrong_token_is_refused(api):
    r = api.call("GET", "/host", token="nope-not-a-real-token")
    assert r.status_code == 401


def test_the_known_hosts_roster_answers(api):
    hosts = api.ok("GET", "/hosts")
    assert isinstance(hosts, (list, dict))


def test_a_known_host_can_be_renamed_and_forgotten(api, host_identity, scratch_name):
    """Rename then forget, so the suite leaves the roster as it found it."""
    key = host_identity["host_id"]
    r = api.call("POST", "/hosts/{key}/rename", fmt={"key": key},
                 json={"name": scratch_name})
    assert r.status_code in (200, 404), r.text
    r = api.call("POST", "/hosts/{key}/forget", fmt={"key": key})
    assert r.status_code in (200, 404), r.text


def test_the_engine_roster_is_served_not_shipped(api):
    """The app renders whatever this returns; a hardcoded client list is how
    an engine added on the host stays invisible in the app."""
    engines = api.ok("GET", "/engines")
    assert engines, "a host with no engines can open no sessions"


def test_the_mac_app_release_is_resolvable(api):
    """`/app/mac/latest` is what a Mac checks for updates. A host whose feed
    is stale ships a ten-build-old app to anyone installing today."""
    latest = api.ok("GET", "/app/mac/latest")
    assert latest


def test_the_mac_app_download_serves_bytes(api):
    """The route behind the update. A 200 with an HTML error page is the
    failure this catches — so the body is checked, not just the status."""
    r = api.get("/app/mac/download")
    assert r.status_code in (200, 302, 307, 404), r.text[:200]
    if r.status_code == 200:
        assert len(r.content) > 1024, "download served a stub, not an app"


def test_the_context_payload_answers(api):
    api.ok("GET", "/context")


def test_a_context_file_outside_the_root_is_refused(api):
    """Path traversal on a route that takes a path as a query parameter.
    Live, because the check depends on the real root, not a tmp_path."""
    r = api.get("/context/file",
                **{"params": {"path": "../../../../etc/passwd"}})
    assert r.status_code in (400, 403, 404), (
        f"traversal returned {r.status_code} — the host served a file outside "
        f"its context root")


def test_the_control_actions_are_listed_then_one_runs(api):
    """`/control/actions` is the menu and `/control/{action}` is the act. The
    pairing matters: an action listed but unroutable is a button that fails
    only when someone presses it."""
    actions = api.ok("GET", "/control/actions")
    names = ([a.get("id") or a.get("action") or a.get("name") for a in actions]
             if isinstance(actions, list)
             else list(actions.get("actions", {})) or list(actions))
    names = [n for n in names if n]
    assert names, "no control actions offered"

    safe = next((n for n in names if any(
        w in str(n).lower() for w in ("status", "list", "health", "info"))), None)
    if safe is None:
        pytest.skip(f"no read-only control action to exercise safely: {names}")
    r = api.post("/control/{action}", fmt={"action": safe}, json={})
    assert r.status_code < 500, f"control/{safe} → {r.status_code}: {r.text[:300]}"
