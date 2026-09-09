"""One-time enrolment codes — the P3 contract (docs/multi-host-access.md).

What matters here is not that a code round-trips. It is that the four
properties standing in for the source-address gate actually hold: single-use
survives a race, expiry is enforced where it is redeemed, the refusal is one
answer for every cause so the endpoint is not an oracle, and guessing is
metered by the same limiter as bearer auth. Plus the two that make the widening
survivable — every enrolment is attributable, and revoking the minting device
kills the codes it left outstanding.

Each test names the break it would catch.
"""

import time

import pytest
from fastapi.testclient import TestClient

from jstack_host.server import create_app

app = create_app()
from jstack_host import auth, devices, enrolment, tunnel
from jstack_host.store import SessionStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = SessionStore(db_path=tmp_path / "enrolment.sqlite")
    monkeypatch.setattr(devices, "_store", lambda: s)
    monkeypatch.setattr(enrolment, "_store", lambda: s)
    return s


@pytest.fixture(autouse=True)
def _no_live_tunnel_and_no_alerts(monkeypatch):
    """This Mac ships wg_peer.py, so an unguarded redemption test would add a
    real peer to the live tunnel config. Off by default; the pairing tests
    stub `issue` explicitly. Alerts are captured rather than printed so the
    announce path is asserted instead of merely tolerated."""
    monkeypatch.setattr(tunnel, "can_pair", lambda: False)
    sent = []
    monkeypatch.setattr("jstack_host.hostenv.security_alert", sent.append)
    return sent


def _mint(store, name="work-mac", created_by="", ttl=600):
    """A code, minted through the module — returns its canonical form."""
    out = enrolment.mint_code(name, created_by, ttl)
    return enrolment.normalize(out["code"]), out


# ── the code itself ──────────────────────────────────────────────────────────

def test_a_minted_code_is_grouped_and_carries_no_lookalike_characters(store):
    _, out = _mint(store)
    assert out["code"][4] == "-" and len(out["code"]) == 9
    body = out["code"].replace("-", "")
    assert len(body) == enrolment.CODE_LEN
    assert not (set(body) & set("01IO")), "a code read aloud must not be ambiguous"


def test_the_table_stores_a_hash_never_the_code(store):
    code, out = _mint(store)
    rows = store.list_enrolment_codes()
    assert code not in str(rows) and out["code"] not in str(rows)
    assert rows[0]["code_hash"].startswith("sha256:")


def test_normalize_treats_case_and_grouping_as_presentation(store):
    code, out = _mint(store)
    typed = out["code"].lower().replace("-", " ")
    assert enrolment.normalize(typed) == code
    assert enrolment.normalize(out["code"]) == code


def test_normalize_refuses_anything_that_is_not_a_whole_code():
    """A dropped ambiguous character shortens the string, and a short string
    must fail loudly rather than hash to something that might match."""
    assert enrolment.normalize("MFQ4-7K2") == ""       # seven
    assert enrolment.normalize("MFQ4-7K2PP") == ""     # nine
    assert enrolment.normalize("MFQO-47K2") == ""      # O dropped → seven
    assert enrolment.normalize("") == ""


def test_ttl_is_clamped_to_the_declared_window(store):
    assert _mint(store, ttl=5)[1]["expires_in"] == enrolment.MIN_TTL
    assert _mint(store, ttl=99999)[1]["expires_in"] == enrolment.MAX_TTL
    assert _mint(store, ttl="nonsense")[1]["expires_in"] == enrolment.DEFAULT_TTL


# ── redemption ───────────────────────────────────────────────────────────────

def test_redeeming_yields_a_working_token_named_by_the_code(store):
    code, _ = _mint(store, name="Boss Work Mac")
    out = enrolment.redeem(code, "198.51.100.4")
    assert devices.authenticate(out["token"]) == out["device"]["id"]
    assert out["device"]["name"] == "Boss Work Mac"
    assert out["token"] not in str(store.list_devices())


def test_a_code_is_spent_exactly_once(store):
    """The whole anti-farming property. A second redemption must never mint."""
    code, _ = _mint(store)
    enrolment.redeem(code, "198.51.100.4")
    with pytest.raises(enrolment.EnrolmentError):
        enrolment.redeem(code, "198.51.100.5")
    assert len(store.list_devices()) == 1


def test_an_expired_code_is_refused_even_though_it_is_still_in_the_table(store):
    """Expiry is enforced at redemption, not by the sweep — a sweep that has
    not run yet must not become a window in which a stale code still works."""
    code = "MFQ47K2P"
    store.add_enrolment_code(enrolment._hash(code), "late", int(time.time()) - 1, "")
    with pytest.raises(enrolment.EnrolmentError):
        enrolment.redeem(code, "198.51.100.4")


def test_every_bad_code_gets_the_same_answer(store):
    """Unknown, expired and already-used must be indistinguishable, or the
    endpoint tells a guesser which of its tries was structurally right."""
    used, _ = _mint(store)
    enrolment.redeem(used, "198.51.100.4")
    expired = "MFQ47K2P"
    store.add_enrolment_code(enrolment._hash(expired), "late",
                             int(time.time()) - 1, "")
    answers = set()
    for code in (used, expired, "22222222", "not-a-code"):
        with pytest.raises(enrolment.EnrolmentError) as e:
            enrolment.redeem(code, "198.51.100.4")
        answers.add(str(e.value))
    assert answers == {enrolment.REFUSED}


def test_the_row_records_which_device_the_code_let_in(store):
    """The audit trail that makes the widening survivable — an enrolment with
    no device id on it cannot be traced back from the registry."""
    code, _ = _mint(store)
    out = enrolment.redeem(code, "198.51.100.4")
    row = store.enrolment_code(enrolment._hash(code))
    assert row["used_at"] is not None
    assert out["device"]["id"] in row["used_by"]
    assert "198.51.100.4" in row["used_by"]


def test_an_enrolment_announces_itself(store, _no_live_tunnel_and_no_alerts):
    """A credential minted from off the LAN is the event the address gate used
    to make impossible. It must not be silent."""
    code, _ = _mint(store, name="work-mac")
    enrolment.redeem(code, "198.51.100.4")
    for _ in range(50):                       # _announce is threaded
        if _no_live_tunnel_and_no_alerts:
            break
        time.sleep(0.02)
    assert any("work-mac" in b and "198.51.100.4" in b
               for b in _no_live_tunnel_and_no_alerts)


# ── revoking the minter revokes its codes ────────────────────────────────────

def test_a_code_minted_by_a_revoked_device_is_dead(store):
    """Revoking a lost phone must also kill what it left outstanding —
    otherwise a stolen token buys enrolments for the whole TTL after the user
    has already done the one thing they were told would stop it."""
    row, _ = devices.mint("boss-iphone")
    code, _ = _mint(store, created_by=row["id"])
    devices.revoke(row["id"])
    with pytest.raises(enrolment.EnrolmentError):
        enrolment.redeem(code, "198.51.100.4")


def test_refusing_a_revoked_minters_code_does_not_burn_it(store):
    """The check runs before the consume. A refused code that came back marked
    used could never be honoured again even if the revoke were undone."""
    row, _ = devices.mint("boss-iphone")
    code, _ = _mint(store, created_by=row["id"])
    devices.revoke(row["id"])
    with pytest.raises(enrolment.EnrolmentError):
        enrolment.redeem(code, "198.51.100.4")
    assert store.enrolment_code(enrolment._hash(code))["used_at"] is None


def test_a_code_from_an_unknown_minter_still_works(store):
    """Host tooling mints with no device id. Treating unknown as revoked would
    break provisioning to close nothing."""
    code, _ = _mint(store, created_by="")
    assert enrolment.redeem(code, "198.51.100.4")["token"]


# ── the limiter ──────────────────────────────────────────────────────────────

def test_guessing_codes_locks_the_address_out(store, monkeypatch):
    """Redemption is unauthenticated by design, so without this it is the one
    unmetered guessing surface on the host. The bound is written out rather
    than read from the module — a test that derives its ceiling from the
    constant it is testing passes for any ceiling."""
    assert auth._FAIL_MAX == 5
    ip = "203.0.113.44"
    for i in range(5):
        with pytest.raises(enrolment.EnrolmentError):
            enrolment.redeem(f"2222222{enrolment.ALPHABET[i]}", ip)
    good, _ = _mint(store)
    with pytest.raises(enrolment.EnrolmentLockedOut) as e:
        enrolment.redeem(good, ip)
    assert e.value.seconds > 0
    assert store.enrolment_code(enrolment._hash(good))["used_at"] is None


def test_a_locked_out_address_cannot_burn_a_valid_code(store):
    """The limiter is asked before the code is read. A guesser that got locked
    out and then guessed right must not consume it."""
    ip = "203.0.113.45"
    for i in range(5):
        with pytest.raises(enrolment.EnrolmentError):
            enrolment.redeem(f"3333333{enrolment.ALPHABET[i]}", ip)
    code, _ = _mint(store)
    with pytest.raises(enrolment.EnrolmentLockedOut):
        enrolment.redeem(code, ip)
    assert enrolment.redeem(code, "198.51.100.9")["token"]   # still spendable


# ── the registry surface ─────────────────────────────────────────────────────

def test_listing_codes_never_publishes_the_digest(store):
    """40 bits behind a published SHA-256 is not behind anything — the digest
    is the code with an afternoon of compute in front of it."""
    code, _ = _mint(store)
    rows = enrolment.list_codes()
    assert rows and "code_hash" not in rows[0]
    assert enrolment._hash(code) not in str(rows)


def test_listing_states_a_code_as_live_used_or_expired(store):
    live, _ = _mint(store, name="live")
    used, _ = _mint(store, name="used")
    enrolment.redeem(used, "198.51.100.4")
    store.add_enrolment_code(enrolment._hash("MFQ47K2P"), "expired",
                             int(time.time()) - 1, "")
    by_name = {r["name"]: r for r in enrolment.list_codes()}
    assert by_name["live"]["state"] == "live"
    assert by_name["used"]["state"] == "used"
    assert "expired" not in by_name, "an expired unused code is swept, not listed"


def test_the_sweep_never_touches_a_used_row(store):
    """A used row is the record of which device this host let in. Housekeeping
    that erased it would erase the audit trail."""
    code, _ = _mint(store, ttl=60)
    enrolment.redeem(code, "198.51.100.4")
    stale, _ = _mint(store, name="never-used", ttl=60)
    # An hour past both expiries: the used row must survive it, the unused
    # one must not. A sweep run at `now` would pass this test by doing nothing.
    assert store.sweep_enrolment_codes(int(time.time()) + 3600) == 1
    assert store.enrolment_code(enrolment._hash(stale)) is None
    assert store.enrolment_code(enrolment._hash(code)) is not None


def test_revoking_takes_an_unused_code_out_and_leaves_a_used_one(store):
    live, live_out = _mint(store, name="live")
    used, _ = _mint(store, name="used")
    enrolment.redeem(used, "198.51.100.4")
    assert enrolment.revoke(live_out["code"].lower()) is True
    assert enrolment.revoke(live) is False          # already gone
    assert enrolment.revoke(used) is False          # used rows are permanent
    with pytest.raises(enrolment.EnrolmentError):
        enrolment.redeem(live, "198.51.100.4")


def test_enrolment_codes_never_sync(store):
    """Same law as `devices`: a table of credentials-in-waiting pooling across
    hosts would let one compromised store enrol devices everywhere."""
    _mint(store)
    assert "enrolment_codes" not in store.changes_since(0)


# ── the tunnel half ──────────────────────────────────────────────────────────

def test_a_host_with_no_mesh_still_hands_over_the_token(store):
    """A leaf has no peer to mint. That is a fact about the host, not a failure
    — and the code is already burned, so losing the token here would be
    unrecoverable."""
    code, _ = _mint(store)
    out = enrolment.redeem(code, "198.51.100.4")
    assert out["token"] and out["tunnel"] is None
    assert "does not run the tunnel" in out["tunnel_note"]


def test_a_pairing_that_blows_up_never_costs_the_caller_its_token(store,
                                                                  monkeypatch):
    monkeypatch.setattr(tunnel, "can_pair", lambda: True)
    monkeypatch.setattr(tunnel, "issue", lambda d: 1 / 0)
    code, _ = _mint(store)
    out = enrolment.redeem(code, "198.51.100.4")
    assert devices.authenticate(out["token"])
    assert out["tunnel"] is None and "failed" in out["tunnel_note"]


def test_redemption_pairs_with_the_slug_of_the_device_name(store, monkeypatch):
    seen = {}
    monkeypatch.setattr(tunnel, "can_pair", lambda: True)
    monkeypatch.setattr(tunnel, "issue",
                        lambda d, leaf=False: seen.setdefault("peer", d) and
                        {"device": d, "config": "[Interface]", "created": True})
    code, _ = _mint(store, name="Boss Work Mac")
    out = enrolment.redeem(code, "198.51.100.4")
    assert seen["peer"] == "boss-work-mac"
    assert out["tunnel"]["config"] == "[Interface]"


def test_peer_name_only_yields_names_wg_peer_will_take():
    assert enrolment.peer_name("Boss Work Mac") == "boss-work-mac"
    assert enrolment.peer_name("  --Work_Mac!!  ") == "work-mac"
    assert enrolment.peer_name("!!!") == ""
    assert enrolment.peer_name("") == ""
    assert len(enrolment.peer_name("x" * 80)) == 31


def test_issue_drops_the_lan_rule_and_keeps_every_other_one(monkeypatch):
    """The enrolment path must bypass ONLY the source-address gate. A leaf
    still has no mesh, and a name wg_peer would reject is still rejected."""
    monkeypatch.setattr(tunnel, "can_pair", lambda: False)
    with pytest.raises(tunnel.PairingUnsupported):
        tunnel.issue("work-mac")
    monkeypatch.setattr(tunnel, "can_pair", lambda: True)
    with pytest.raises(tunnel.PairingRefused):
        tunnel.issue("Not A Peer Name")


# ── the endpoints ────────────────────────────────────────────────────────────

@pytest.fixture
def client(store):
    _, token = devices.mint("test-device")
    c = TestClient(app)
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


def test_redeeming_needs_no_bearer_token_at_all(client, store):
    """The entire point of P3: the caller is a machine that has no token yet,
    and getting one is what it is here for."""
    r = client.post("/api/jremote/v1/enrolment/codes", json={"name": "work-mac"})
    assert r.status_code == 200
    code = r.json()["code"]

    anon = TestClient(app)                       # no Authorization header
    assert anon.get("/api/jremote/v1/devices").status_code == 401
    r = anon.post("/api/jremote/v1/enrolment/redeem", json={"code": code})
    assert r.status_code == 200
    assert devices.authenticate(r.json()["token"]) == r.json()["device"]["id"]


def test_minting_a_code_needs_a_token_but_not_the_lan(client, store):
    """TestClient's address is not a LAN address — which refuses `POST
    /devices` — and minting a code must still work, or the person minting it
    has to be standing at the Mac, which is the trip P3 removes."""
    assert client.post("/api/jremote/v1/devices",
                       json={"name": "x"}).status_code == 403
    r = client.post("/api/jremote/v1/enrolment/codes", json={"name": "work-mac"})
    assert r.status_code == 200

    anon = TestClient(app)
    assert anon.post("/api/jremote/v1/enrolment/codes",
                     json={"name": "x"}).status_code == 401


def test_the_minting_device_is_recorded_on_the_code(client, store):
    caller = client.get("/api/jremote/v1/devices").json()["devices"][0]["id"]
    client.post("/api/jremote/v1/enrolment/codes", json={"name": "work-mac"})
    rows = client.get("/api/jremote/v1/enrolment/codes").json()["codes"]
    assert rows[0]["created_by"] == caller
    assert "code_hash" not in rows[0]


def test_a_bad_code_is_a_401_that_says_nothing(client, store):
    anon = TestClient(app)
    r = anon.post("/api/jremote/v1/enrolment/redeem", json={"code": "22222222"})
    assert r.status_code == 401
    assert r.json()["detail"] == enrolment.REFUSED


def test_revoking_over_the_api(client, store):
    code = client.post("/api/jremote/v1/enrolment/codes",
                       json={"name": "work-mac"}).json()["code"]
    r = client.post("/api/jremote/v1/enrolment/codes/revoke", json={"code": code})
    assert r.status_code == 200
    assert client.post("/api/jremote/v1/enrolment/codes/revoke",
                       json={"code": code}).status_code == 404
