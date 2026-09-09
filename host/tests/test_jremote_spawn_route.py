"""Where a desk-side spawn's window opens — and closing a thread elsewhere.

A handoff typed on the iPad must not open a Mac window: the host resolves
the *driver* of the origin session (attach.py) and routes the new session's
window there — "mac" (desk-driven or unknown: today's behavior), "device"
(an open frame goes down the driver's own socket; the app decides window or
nothing), or "none" (a device drove it but its socket is gone — create
quietly, the board row is the visibility).

`dismiss-elsewhere` is the app's "Close on Other Instances": every other
attachment of the sid is ordered shut with 4412; the session keeps running.
"""

import pytest
from fastapi.testclient import TestClient

from jstack_host.server import create_app

app = create_app()
from jstack_host import attach, auth

ORIGIN = "0416a234-0000-4000-8000-123456789abc"
THREAD = "73dea234-0000-4000-8000-123456789abc"


@pytest.fixture(autouse=True)
def clean_registry():
    attach.reset()
    yield
    attach.reset()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "_expected_token", lambda: "test-token")
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer test-token"})
    return c


def _att(sid=ORIGIN, instance="i-pad", platform="pad"):
    sent, closed = [], []
    a = attach.Attachment(
        sid=sid, instance=instance, platform=platform,
        send_text=lambda payload: sent.append(payload),
        order_close=lambda code, reason: closed.append((code, reason)),
    )
    a.test_sent, a.test_closed = sent, closed
    return a


# ── the routing decision ───────────────────────────────────────────────────

def test_device_driver_routes_to_device():
    a = _att(platform="pad")
    attach.register(a)
    attach.note_input(a, now=100.0)
    assert attach.spawn_route(ORIGIN, now=110.0) == ("device", a)


def test_mac_app_driver_routes_to_mac():
    a = _att(instance="i-mac", platform="mac")
    attach.register(a)
    attach.note_input(a, now=100.0)
    assert attach.spawn_route(ORIGIN, now=110.0) == ("mac", a)


def test_unknown_platform_driver_keeps_todays_behavior():
    # A stale app build attaches with no platform tag — never mis-route it.
    a = _att(platform="")
    attach.register(a)
    attach.note_input(a, now=100.0)
    assert attach.spawn_route(ORIGIN, now=110.0) == ("mac", a)


def test_no_driver_at_all_routes_to_mac():
    assert attach.spawn_route(ORIGIN) == ("mac", None)


def test_device_driver_whose_socket_died_routes_to_none():
    a = _att(platform="phone")
    attach.register(a)
    attach.note_input(a, now=100.0)
    attach.unregister(a)
    assert attach.spawn_route(ORIGIN, now=110.0) == ("none", None)


# ── POST /sessions/{sid}/route-spawn ───────────────────────────────────────

def test_route_spawn_sends_open_frame_to_the_driving_device(client):
    a = _att(platform="pad")
    attach.register(a)
    attach.note_input(a)
    r = client.post(f"/api/jremote/v1/sessions/{ORIGIN}/route-spawn",
                    json={"new_sid": "new-sid-1", "cwd": ""})
    assert r.status_code == 200
    assert r.json()["route"] == "device"
    assert a.test_sent == [
        {"type": "open", "url": "jremote://session/new-sid-1"}]


def test_route_spawn_mac_sends_nothing(client):
    a = _att(instance="i-mac", platform="mac")
    attach.register(a)
    attach.note_input(a)
    r = client.post(f"/api/jremote/v1/sessions/{ORIGIN}/route-spawn",
                    json={"new_sid": "new-sid-1", "cwd": ""})
    assert r.status_code == 200
    assert r.json()["route"] == "mac"
    assert a.test_sent == []


def test_route_spawn_none_when_device_driver_left(client):
    a = _att(platform="pad")
    attach.register(a)
    attach.note_input(a)
    attach.unregister(a)
    r = client.post(f"/api/jremote/v1/sessions/{ORIGIN}/route-spawn",
                    json={"new_sid": "new-sid-1", "cwd": ""})
    assert r.status_code == 200
    assert r.json()["route"] == "none"


# ── POST /sessions/{sid}/dismiss-elsewhere ─────────────────────────────────

def test_dismiss_elsewhere_closes_only_other_instances(client):
    mine = _att(sid=THREAD, instance="i-pad")
    other = _att(sid=THREAD, instance="i-mac", platform="mac")
    attach.register(mine)
    attach.register(other)
    r = client.post(f"/api/jremote/v1/sessions/{THREAD}/dismiss-elsewhere",
                    json={"instance": "i-pad"})
    assert r.status_code == 200
    assert r.json() == {"dismissed": 1}
    assert mine.test_closed == []
    assert other.test_closed == [(4412, "dismissed from another device")]


def test_dismiss_elsewhere_requires_an_instance(client):
    r = client.post(f"/api/jremote/v1/sessions/{THREAD}/dismiss-elsewhere",
                    json={"instance": ""})
    assert r.status_code == 400
