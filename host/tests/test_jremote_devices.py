"""Per-device tokens — the P2 contract (docs/multi-host-access.md).

What is worth pinning here is not "a token round-trips" but the security
posture: the table is the ONLY authority once it exists, revocation is
absolute and immediate (live connections included), the shared file is a
one-time migration source and never a back door, and failures lock an address
out. Each test names the break it would catch.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from jstack_host.server import create_app

app = create_app()
from jstack_host import auth, devices
from jstack_host.store import SessionStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = SessionStore(db_path=tmp_path / "devices.sqlite")
    monkeypatch.setattr(devices, "_store", lambda: s)
    return s


@pytest.fixture
def legacy_file(tmp_path, monkeypatch):
    """A pre-P2 host: one shared token in a file, table empty."""
    path = tmp_path / "api-token"
    path.write_text("the-shared-token")
    monkeypatch.setattr(auth, "_cache", None)
    monkeypatch.setattr("jstack_host.hostenv.token_path", lambda: path)
    return path


# ── minting and the token shape ──────────────────────────────────────────────

def test_a_minted_token_authenticates_as_its_device(store):
    row, token = devices.mint("my-iphone")
    assert token.startswith("jr1.")
    assert devices.authenticate(token) == row["id"]
    assert store.device(row["id"])["name"] == "my-iphone"


def test_the_table_stores_a_hash_never_the_token(store):
    _, token = devices.mint("my-iphone")
    secret = token.split(".", 2)[2]
    for row in store.list_devices():
        assert token not in str(row.values())
        assert secret not in str(row.values())
        assert row["token_hash"].startswith("sha256:")


def test_a_right_id_with_a_wrong_secret_is_refused(store):
    row, _ = devices.mint("my-iphone")
    assert devices.authenticate(f"jr1.{row['id']}.wrong-secret") is None


def test_a_malformed_jr1_token_never_falls_through_to_legacy(store, legacy_file):
    """`jr1.` + the shared token must not be judged against the legacy row —
    a mangled new-style token that authenticated as `legacy` would make the
    prefix a disguise."""
    assert devices.authenticate("the-shared-token") == "legacy"  # migrates
    assert devices.authenticate("jr1.the-shared-token") is None
    assert devices.authenticate("jr1..secret") is None
    assert devices.authenticate("jr1.id.") is None


def test_empty_and_absent_tokens_fail_closed(store):
    assert devices.authenticate("") is None
    assert devices.authenticate("anything") is None  # empty table, no file


# ── the legacy grandfather ───────────────────────────────────────────────────

def test_the_file_token_becomes_row_legacy_on_first_use(store, legacy_file):
    """The user's phone, iPad and laptop all carry the file token today — the
    upgrade must not lock out a single one of them."""
    assert devices.authenticate("the-shared-token") == "legacy"
    row = store.device("legacy")
    assert row is not None and row["revoked_at"] is None
    assert devices.authenticate("the-shared-token") == "legacy"  # and again


def test_rotating_the_file_after_migration_does_nothing(store, legacy_file):
    """Once the table exists, the file is history. A file write that minted a
    working credential would be a back door around revocation."""
    assert devices.authenticate("the-shared-token") == "legacy"
    legacy_file.write_text("a-brand-new-token")
    auth._cache = None
    assert devices.authenticate("a-brand-new-token") is None
    assert devices.authenticate("the-shared-token") == "legacy"


def test_host_internal_minting_first_does_not_block_the_grandfather(
        store, legacy_file, tmp_path, monkeypatch):
    """On a restarted host the spawn-routing call races the user's phone for the
    first request. If the host's self-minted row counted as "the table has
    decided", whichever boot had a machine call land first would lock every
    installed device out for good."""
    monkeypatch.setenv("JREMOTE_STATE_DIR", str(tmp_path / "state"))
    from jstack_host import hostenv
    hostenv.reset_profile()
    try:
        assert devices.internal_token()          # host-internal row exists…
        assert devices.authenticate("the-shared-token") == "legacy"  # …still migrates
    finally:
        monkeypatch.delenv("JREMOTE_STATE_DIR")
        hostenv.reset_profile()


def test_a_minted_device_blocks_the_grandfather(store, legacy_file):
    """A REAL device row is a decision: once one exists, the file is history
    and writing one mints nothing."""
    devices.mint("my-iphone")
    assert devices.authenticate("the-shared-token") is None


def test_a_revoked_legacy_is_not_regrandfathered(store, legacy_file):
    assert devices.authenticate("the-shared-token") == "legacy"
    assert devices.revoke("legacy")
    assert devices.authenticate("the-shared-token") is None


# ── revocation ───────────────────────────────────────────────────────────────

def test_revoke_is_immediate_and_idempotent(store):
    row, token = devices.mint("my-iphone")
    assert devices.authenticate(token) == row["id"]
    assert devices.revoke(row["id"]) is True
    assert devices.authenticate(token) is None
    assert devices.revoke(row["id"]) is False  # second tap: nothing to do
    assert devices.is_revoked(row["id"])


def test_revoking_one_device_leaves_the_others_alone(store):
    """The whole point of P2 — one lost phone is one dead token."""
    phone, phone_tok = devices.mint("my-iphone")
    ipad, ipad_tok = devices.mint("my-ipad")
    devices.revoke(phone["id"])
    assert devices.authenticate(phone_tok) is None
    assert devices.authenticate(ipad_tok) == ipad["id"]


def test_an_unknown_device_reads_as_revoked(store):
    assert devices.is_revoked("never-minted")


def test_wait_revoked_resolves_on_revoke(store):
    """The PTY holds this watcher — if it never resolved, a revoked phone's
    terminal would keep typing until it next reconnected."""
    row, _ = devices.mint("my-iphone")

    async def scenario():
        waiter = asyncio.create_task(devices.wait_revoked(row["id"]))
        await asyncio.sleep(0)  # let it register
        assert not waiter.done()
        devices.revoke(row["id"])
        await asyncio.wait_for(waiter, timeout=2)

    asyncio.run(scenario())


def test_wait_revoked_on_an_already_revoked_device_returns_at_once(store):
    row, _ = devices.mint("my-iphone")
    devices.revoke(row["id"])

    async def scenario():
        await asyncio.wait_for(devices.wait_revoked(row["id"]), timeout=2)

    asyncio.run(scenario())


# ── the registry ─────────────────────────────────────────────────────────────

def test_rename_and_last_seen(store):
    row, token = devices.mint("phone")
    assert devices.rename(row["id"], "my-iphone")
    assert store.device(row["id"])["name"] == "my-iphone"
    assert store.device(row["id"])["last_seen_at"] is None
    devices.authenticate(token)
    assert store.device(row["id"])["last_seen_at"] is not None


def test_the_devices_table_never_rides_sync(store):
    """If tokens travelled with MetaSync, revoking one device would revoke all
    and every host's credentials would pool in one store. The sync payload
    must not know the table exists."""
    devices.mint("my-iphone")
    payload = store.changes_since(0)
    assert "devices" not in payload
    assert "token_hash" not in str(payload)


# ── the host's own credential ────────────────────────────────────────────────

def test_internal_token_mints_once_and_is_stable(store, tmp_path, monkeypatch):
    monkeypatch.setenv("JREMOTE_STATE_DIR", str(tmp_path / "state"))
    from jstack_host import hostenv
    hostenv.reset_profile()
    try:
        first = devices.internal_token()
        assert devices.authenticate(first) == devices.INTERNAL_ID
        assert devices.internal_token() == first
    finally:
        monkeypatch.delenv("JREMOTE_STATE_DIR")
        hostenv.reset_profile()


def test_a_revoked_internal_row_stays_revoked(store, tmp_path, monkeypatch):
    """The host may re-key itself, never resurrect itself — a revoke the user
    made must not be quietly undone by the next spawn routing call."""
    monkeypatch.setenv("JREMOTE_STATE_DIR", str(tmp_path / "state"))
    from jstack_host import hostenv
    hostenv.reset_profile()
    try:
        token = devices.internal_token()
        assert token
        devices.revoke(devices.INTERNAL_ID)
        assert devices.internal_token() == ""
        assert devices.authenticate(token) is None
    finally:
        monkeypatch.delenv("JREMOTE_STATE_DIR")
        hostenv.reset_profile()


# ── the rate limiter ─────────────────────────────────────────────────────────

def test_five_guesses_at_one_credential_lock_that_credential_and_alert(
        store, monkeypatch):
    alerts = []
    monkeypatch.setattr("jstack_host.hostenv.security_alert", alerts.append)
    ip = "192.168.1.66"
    row, token = devices.mint("my-iphone")
    device_id = row["id"]
    for _ in range(5):
        with pytest.raises(Exception) as e:
            auth._gate(ip, f"Bearer jr1.{device_id}.wrongsecret")
        assert e.value.status_code == 401
    with pytest.raises(Exception) as e:
        auth._gate(ip, f"Bearer jr1.{device_id}.wrongsecret")
    assert e.value.status_code == 429
    # Even the RIGHT secret is refused: this credential is what was hammered.
    with pytest.raises(Exception) as e:
        auth._gate(ip, f"Bearer {token}")
    assert e.value.status_code == 429
    deadline = time.time() + 2
    while not alerts and time.time() < deadline:  # alert is threaded
        time.sleep(0.02)
    assert len(alerts) == 1 and ip in alerts[0] and device_id in alerts[0]


def test_a_wrong_row_does_not_lock_out_the_device_s_working_row(store):
    """The live 2026-09-03 failure: a phone whose work-Mac row pointed at the
    home Mac burned five rejects, and a per-address lockout took its correct
    home-Mac row down with it for fifteen minutes.

    Both rows come from one address — that is the whole point. Only the
    credential actually being refused may be locked.
    """
    ip = "10.66.0.2"
    _, good = devices.mint("my-iphone")
    foreign = "jr1.670f3e8827e3." + "x" * 40      # another host's device id
    for _ in range(6):
        with pytest.raises(Exception):
            auth._gate(ip, f"Bearer {foreign}")
    with pytest.raises(Exception) as e:           # the bad row is locked
        auth._gate(ip, f"Bearer {foreign}")
    assert e.value.status_code == 429
    assert auth._gate(ip, f"Bearer {good}")       # the good row still works


def test_spraying_many_device_ids_still_locks_the_address(store, monkeypatch):
    """Per-credential keying must not become a way to probe forever. No real
    client presents more than its handful of tokens, so the address ceiling is
    unreachable by mistake and reachable by a scanner."""
    monkeypatch.setattr("jstack_host.hostenv.security_alert", lambda _b: None)
    # The bound is written out, not read from the module: a test that derives
    # its ceiling from the constant it is testing passes for any ceiling,
    # including one raised until the tier never fires.
    assert auth._SPRAY_MAX == 50
    ip = "203.0.113.9"
    for i in range(50):
        with pytest.raises(Exception) as e:
            auth._gate(ip, f"Bearer jr1.{i:012x}.guess")
        assert e.value.status_code == 401, f"locked too early at attempt {i}"
    _, good = devices.mint("my-iphone")
    with pytest.raises(Exception) as e:           # address is out, all rows
        auth._gate(ip, f"Bearer {good}")
    assert e.value.status_code == 429


def test_a_locked_credential_reports_the_longer_of_the_two_lockouts(store,
                                                                    monkeypatch):
    """Retry-After must never under-promise when both tiers hold a lock."""
    monkeypatch.setattr("jstack_host.hostenv.security_alert", lambda _b: None)
    ip = "203.0.113.10"
    now = time.time()
    auth._locked_until[f"{ip}|abc"] = now + 60
    auth._locked_until[ip] = now + 600
    try:
        assert auth._locked_out(ip, f"{ip}|abc") > 500
    finally:
        auth.reset_limiter()


def test_loopback_is_exempt_from_lockout_never_from_auth(store):
    """The health probe sends deliberate bad tokens from loopback; the Mac app
    lives there too. They must never brick the host — but a bad token is
    still a 401."""
    for _ in range(10):
        with pytest.raises(Exception) as e:
            auth._gate("127.0.0.1", "Bearer wrong")
        assert e.value.status_code == 401


def test_failures_from_different_addresses_do_not_pool(store):
    for i in range(4):
        with pytest.raises(Exception):
            auth._gate(f"192.168.1.{i}", "Bearer wrong")
    with pytest.raises(Exception) as e:
        auth._gate("192.168.1.99", "Bearer wrong")
    assert e.value.status_code == 401  # 5th failure, but 1st from this address


def test_tokens_with_no_readable_id_share_one_bucket(store):
    """Absent and malformed tokens name no credential, so they cannot be told
    apart. Pooling them is the conservative read — the alternative is an
    unbounded set of un-lockable scopes."""
    ip = "192.168.1.77"
    assert auth._scope(ip, "") == auth._scope(ip, "jr1.")
    for _ in range(5):
        with pytest.raises(Exception):
            auth._gate(ip, "Bearer jr1.")
    with pytest.raises(Exception) as e:
        auth._gate(ip, "")                        # different shape, same bucket
    assert e.value.status_code == 429


# ── the endpoints ────────────────────────────────────────────────────────────

@pytest.fixture
def client(store):
    _, token = devices.mint("test-device")
    c = TestClient(app)
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


def test_the_device_list_marks_the_caller(client, store):
    r = client.get("/api/jremote/v1/devices")
    assert r.status_code == 200
    rows = r.json()["devices"]
    assert [d["name"] for d in rows] == ["test-device"]
    assert rows[0]["current"] is True
    assert "token_hash" in rows[0]  # digest only — nothing usable


def test_minting_is_refused_off_the_lan(client, monkeypatch):
    """TestClient's address is not a LAN address, which is exactly the deny
    branch: an in-tunnel or unknown caller must not mint credentials."""
    r = client.post("/api/jremote/v1/devices", json={"name": "intruder"})
    assert r.status_code == 403


def test_minting_on_the_lan_hands_the_token_out_exactly_once(client, store, monkeypatch):
    monkeypatch.setattr(devices, "mint_allowed_from", lambda ip: True)
    r = client.post("/api/jremote/v1/devices", json={"name": "my-ipad"})
    assert r.status_code == 200
    token = r.json()["token"]
    assert devices.authenticate(token) == r.json()["device"]["id"]
    assert token not in str(store.list_devices())


def test_mint_gate_tells_lan_from_tunnel_and_garbage():
    assert devices.mint_allowed_from("127.0.0.1")
    assert devices.mint_allowed_from("192.168.1.20")
    assert not devices.mint_allowed_from("10.66.0.3")  # inside the wg tunnel
    assert not devices.mint_allowed_from("8.8.8.8")
    assert not devices.mint_allowed_from("testclient")


def test_mint_gate_fallback_still_refuses_the_mesh(monkeypatch):
    """A leaf host has no wg_peer.py to read, so the gate falls back to shape
    alone — and 10.66.0.x is `is_private`, so without the explicit mesh
    exclusion a tunnel caller could mint on any leaf."""
    import jstack_host.tunnel as tunnel

    def no_script(ip):
        raise RuntimeError("no wg script on this host")

    monkeypatch.setattr(tunnel, "is_lan_caller", no_script)
    assert devices.mint_allowed_from("127.0.0.1")
    assert devices.mint_allowed_from("192.168.1.20")
    assert not devices.mint_allowed_from("10.66.0.7")
    assert not devices.mint_allowed_from("8.8.8.8")
    assert not devices.mint_allowed_from("testclient")


def test_revoking_over_the_api_kills_the_token(client, store):
    row, token = devices.mint("my-old-phone")
    r = client.post(f"/api/jremote/v1/devices/{row['id']}/revoke")
    assert r.status_code == 200 and r.json()["self"] is False
    assert devices.authenticate(token) is None
    assert client.post(f"/api/jremote/v1/devices/{row['id']}/revoke").status_code == 404


def test_a_revoked_device_cannot_use_the_registry(client, store):
    """Its own row included — revocation ends the credential everywhere."""
    row, token = devices.mint("my-old-phone")
    devices.revoke(row["id"])
    c = TestClient(app)
    c.headers.update({"Authorization": f"Bearer {token}"})
    assert c.get("/api/jremote/v1/devices").status_code == 401


def test_rename_endpoint(client, store):
    row, _ = devices.mint("phone")
    r = client.post(f"/api/jremote/v1/devices/{row['id']}/rename",
                    json={"name": "My iPhone 17"})
    assert r.status_code == 200
    assert store.device(row["id"])["name"] == "My iPhone 17"
    assert client.post("/api/jremote/v1/devices/nope/rename",
                       json={"name": "x"}).status_code == 404


# ── why a 401 happened ───────────────────────────────────────────────────────
#
# The response body is deliberately one sentence for every failure — telling a
# caller which half of its credential was wrong is a probing oracle. That
# leaves the host's log as the only place the four causes are distinguishable,
# and a device that will not connect is diagnosed from there or by guessing.

def test_deny_reason_separates_the_four_ways_a_token_fails(store):
    row, token = devices.mint("my-ipad")
    device_id = row["id"]

    assert "no bearer token" in devices.deny_reason("")
    assert "malformed" in devices.deny_reason("jr1.")
    assert "malformed" in devices.deny_reason("jr1.only-two-parts")
    assert f"unknown device id {'0' * 12}" in devices.deny_reason(f"jr1.{'0' * 12}.x")
    assert f"wrong secret for {device_id}" in devices.deny_reason(f"jr1.{device_id}.wrong")

    devices.revoke(device_id)
    reason = devices.deny_reason(token)
    assert "revoked" in reason and device_id in reason


def test_deny_reason_names_the_trailing_newline_a_paste_carries(store):
    """The failure this exists for: a token copied out of a fenced code block
    is character-for-character right and still 401s. Without the shape note the
    log reads 'wrong secret' and sends the reader to re-mint a good token."""
    _row, token = devices.mint("my-ipad")
    assert devices.authenticate(token + "\n") is None
    assert "UNTRIMMED" in devices.deny_reason(token + "\n")
    assert "UNTRIMMED" not in devices.deny_reason(token[:-1])


def test_deny_reason_never_echoes_the_secret(store):
    """It goes to a log file. A reason that quoted what was presented would
    write every valid token of every device that ever mistyped a host URL."""
    _row, token = devices.mint("my-ipad")
    secret = token.split(".", 2)[2]
    for presented in (token + "\n", f"jr1.{_row['id']}.{secret}x", secret, "jr1.x.y"):
        assert secret not in devices.deny_reason(presented)
