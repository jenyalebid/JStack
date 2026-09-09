"""jRemote `/usage/spend` — the app's Spend section.

`spend.py` is where the classification and the arithmetic live and is
tested against real transcripts elsewhere. What this pins is the wire: the
route reads today off ONE scan, trims to the fields the phone draws, and keeps
the host's ordering and percentages intact.

The trim is the part worth a test. The dashboard's own card carries a
per-category agent split and the day's most expensive sessions; this payload
rides a 15-second poll to a phone and draws neither, so growing it back by
accident is a regression nothing else would notice.

The second contract is the window: every day in the trend carries its own
breakdown, because the app's chart is tappable and a tap must not be a round
trip. Off ONE scan — six extra aggregations of records already in memory, not
six extra reads of the disk.
"""

import pytest
from fastapi.testclient import TestClient

from jstack_host.server import create_app

app = create_app()
from jstack_host import auth
from jstack_host import spend as token_usage


@pytest.fixture
def client(monkeypatch):
    # Bypass the bearer gate for the test client.
    monkeypatch.setattr(auth, "_expected_token", lambda: "test-token")
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer test-token"})
    return c


DAILY = {
    "day": "2026-08-27",
    "total": 259_900_000,
    "output": 1_500_000,
    "sessions": 26,
    "autonomous": 50_700_000,
    "interactive": 209_200_000,
    "autonomous_pct": 19.5,
    "catch_all_sessions": 0,
    "categories": [
        {"category": "chat", "label": "Boss chat", "kind": "interactive",
         "pct": 80.5, "total": 209_200_000, "output": 900_000,
         "cache_read": 200_000_000, "sub_tokens": 12_000, "turns": 310,
         "sessions": 3, "agents": [{"agent": "mario", "total": 209_200_000}]},
        {"category": "social-control", "label": "Social · control",
         "kind": "autonomous", "pct": 12.9, "total": 33_600_000,
         "output": 400_000, "cache_read": 30_000_000, "sub_tokens": 0,
         "turns": 120, "sessions": 6, "agents": []},
    ],
}

YESTERDAY = {
    "day": "2026-08-26",
    "total": 24_000_000,
    "output": 300_000,
    "sessions": 4,
    "autonomous": 24_000_000,
    "interactive": 0,
    "autonomous_pct": 100.0,
    "catch_all_sessions": 0,
    "categories": [
        {"category": "social-control", "label": "Social · control",
         "kind": "autonomous", "pct": 100.0, "total": 24_000_000,
         "output": 300_000, "cache_read": 20_000_000, "sub_tokens": 0,
         "turns": 40, "sessions": 4, "agents": []},
    ],
}

DAYS = {"2026-08-26": YESTERDAY, "2026-08-27": DAILY}

SERIES = [
    {"day": "2026-08-26", "total": 24_000_000, "by_category": {"chat": 24_000_000}},
    {"day": "2026-08-27", "total": 259_900_000, "by_category": {"chat": 209_200_000}},
]


@pytest.fixture
def stub(monkeypatch):
    """Two fixed days, and a counter proving the scan happens exactly once.

    `records` is a list of dicts because the route buckets it by day before
    aggregating — a stub of bare strings would pass the old route and blow up
    on the new one for a reason that has nothing to do with the assertion."""
    calls = {"scan": 0, "daily": []}
    monkeypatch.setattr(token_usage, "scan", lambda *a, **k: calls.__setitem__(
        "scan", calls["scan"] + 1) or [{"day": "2026-08-27"}])
    monkeypatch.setattr(token_usage, "today", lambda: "2026-08-27")
    monkeypatch.setattr(token_usage, "daily", lambda day, records=None:
                        calls["daily"].append(day) or DAYS[day])
    monkeypatch.setattr(token_usage, "series",
                        lambda days=14, records=None: SERIES[-days:])
    return calls


def test_requires_token():
    """The gate is the router's, but a spend breakdown naming every job the
    operation runs is exactly the payload that must never answer unauthed."""
    assert TestClient(app).get("/api/jremote/v1/usage/spend").status_code == 401


def test_serves_todays_breakdown(client, stub):
    body = client.get("/api/jremote/v1/usage/spend").json()
    assert body["day"] == "2026-08-27"
    assert body["total"] == 259_900_000
    assert body["output"] == 1_500_000
    assert body["sessions"] == 26
    assert body["autonomous_pct"] == 19.5
    assert [c["category"] for c in body["categories"]] == ["chat", "social-control"]


def test_one_scan_serves_both_halves(client, stub):
    """The day and the trend come off the SAME records. Scanning twice would
    double the cost of a poll that already runs every fifteen seconds, and let
    the sparkline's last bar disagree with the total printed above it."""
    client.get("/api/jremote/v1/usage/spend")
    assert stub["scan"] == 1


def test_categories_are_trimmed_to_the_wire(client, stub):
    """Five fields, and no more. The agent split and the per-category token
    counters stay on the dashboard — the section draws neither."""
    body = client.get("/api/jremote/v1/usage/spend").json()
    assert set(body["categories"][0]) == {"category", "label", "kind", "pct", "total"}
    assert set(body["series"][0]["categories"][0]) == {
        "category", "label", "kind", "pct", "total"}


def test_every_day_in_the_window_carries_its_breakdown(client, stub):
    """The app's chart is tappable, and a tap re-labels the whole section to
    the day it landed on. If only today carried categories, every tap would be
    a round trip on a section that exists to be glanced at."""
    body = client.get("/api/jremote/v1/usage/spend").json()
    assert [d["day"] for d in body["series"]] == ["2026-08-26", "2026-08-27"]
    for day in body["series"]:
        assert set(day) == {"day", "total", "output", "sessions",
                            "autonomous_pct", "catch_all_sessions", "categories"}
    older = body["series"][0]
    assert older["autonomous_pct"] == 100.0
    assert older["sessions"] == 4
    assert [c["label"] for c in older["categories"]] == ["Social · control"]


def test_top_level_is_today_not_the_last_bar(client, stub):
    """The top-level fields are today's, and they are the same object the last
    series entry is — a build predating the tappable trend reads this payload
    exactly as it read the old one."""
    body = client.get("/api/jremote/v1/usage/spend").json()
    today = body["series"][-1]
    assert body["day"] == today["day"] == "2026-08-27"
    assert {k: body[k] for k in today} == today


def test_the_window_is_aggregated_off_one_scan(client, stub):
    """A week of breakdown, one read of the disk. `daily` is called per day —
    that is arithmetic over records already in memory — but `scan`, the part
    that touches every transcript on the Mac, happens exactly once."""
    client.get("/api/jremote/v1/usage/spend")
    assert stub["scan"] == 1
    assert stub["daily"] == ["2026-08-26", "2026-08-27"]


def test_host_order_and_percentages_survive(client, stub):
    """The app must never re-sort or re-derive: the dashboard and the phone
    read the same classification, so a share shown on one is the share on the
    other."""
    body = client.get("/api/jremote/v1/usage/spend").json()
    assert [c["pct"] for c in body["categories"]] == [80.5, 12.9]
    assert [c["total"] for c in body["categories"]] == [209_200_000, 33_600_000]


def test_catch_all_is_carried_not_swallowed(client, monkeypatch, stub):
    """A job type missing from the category map means some of the spend above
    is filed under a label that does not describe it. The app says so."""
    monkeypatch.setattr(token_usage, "daily",
                        lambda day, records=None: {**DAILY, "catch_all_sessions": 3})
    body = client.get("/api/jremote/v1/usage/spend").json()
    assert body["catch_all_sessions"] == 3


def test_days_narrows_the_trend(client, stub):
    body = client.get("/api/jremote/v1/usage/spend?days=1").json()
    assert [d["day"] for d in body["series"]] == ["2026-08-27"]


def test_live_route_answers_off_the_real_machine(client):
    """No stubs: the real scan, against this Mac's own transcripts.

    The shape is asserted, not the numbers — a quiet day is legitimately zero.
    This is the half a mocked test cannot cover: that `spend.py` still
    returns the keys this route reaches into, so a rename there surfaces here
    rather than as an empty section on Boss's phone.
    """
    body = client.get("/api/jremote/v1/usage/spend").json()
    assert set(body) == {"day", "total", "output", "sessions", "autonomous_pct",
                         "catch_all_sessions", "categories", "series"}
    assert len(body["day"]) == 10
    assert isinstance(body["total"], int)
    assert len(body["series"]) == 7
    assert body["series"][-1]["day"] == body["day"]
    for day in body["series"]:
        assert set(day) == {"day", "total", "output", "sessions",
                            "autonomous_pct", "catch_all_sessions", "categories"}
        for c in day["categories"]:
            assert set(c) == {"category", "label", "kind", "pct", "total"}
            assert c["kind"] in {"autonomous", "interactive"}
        # Shares are computed against that day's own total, so a day can never
        # be more than all of itself — including the thirteen the app only
        # reaches by tapping, which no other test looks at.
        assert sum(c["pct"] for c in day["categories"]) <= 100.5
        # A day with spend has a breakdown behind it. The app tells "nothing
        # happened" from "the host didn't serve it" on exactly this pair, and
        # draws a warning for the second — so the host must never produce it.
        assert day["total"] == 0 or day["categories"]
