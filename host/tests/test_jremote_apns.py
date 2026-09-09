"""APNs environment fallback — a device token binds to the environment of the
build that minted it, so a BadDeviceToken rejection is retried on the other
environment and the accepting one is remembered per token."""

import json

import pytest

from jstack_host import apns


class _Response:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _Client:
    """Stands in for httpx.Client: scripted responses, records post URLs."""

    posts: list[str] = []
    script: dict[str, _Response] = {}

    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, **kwargs):
        _Client.posts.append(url)
        base = url.rsplit("/3/device/", 1)[0]
        return _Client.script[base]


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setattr(apns, "_config", lambda: {
        "team_id": "T", "key_id": "K", "bundle_id": "dev.example.jRemote",
        "sandbox": True,
    })
    monkeypatch.setattr(apns, "is_configured", lambda: True)
    monkeypatch.setattr(apns, "_provider_token", lambda cfg: "jwt")
    monkeypatch.setattr(apns, "_env_cache", {})
    monkeypatch.setattr(apns.httpx, "Client", _Client)
    _Client.posts = []
    _Client.script = {}
    return _Client


BAD_TOKEN = _Response(400, json.dumps({"reason": "BadDeviceToken"}))
SENT = _Response(200)


def test_configured_environment_is_tried_first(wire):
    wire.script = {apns._SANDBOX: SENT}
    ok, detail = apns.send("tok-dev", title="t", body="b")
    assert ok
    assert wire.posts == [f"{apns._SANDBOX}/3/device/tok-dev"]


def test_bad_device_token_falls_through_to_the_other_environment(wire):
    wire.script = {apns._SANDBOX: BAD_TOKEN, apns._PROD: SENT}
    ok, detail = apns.send("tok-adhoc", title="t", body="b")
    assert ok
    assert wire.posts == [
        f"{apns._SANDBOX}/3/device/tok-adhoc",
        f"{apns._PROD}/3/device/tok-adhoc",
    ]


def test_accepting_environment_is_remembered_per_token(wire):
    wire.script = {apns._SANDBOX: BAD_TOKEN, apns._PROD: SENT}
    apns.send("tok-adhoc", title="t", body="b")
    wire.posts = []
    ok, _ = apns.send("tok-adhoc", title="t", body="b")
    assert ok
    assert wire.posts == [f"{apns._PROD}/3/device/tok-adhoc"]


def test_other_errors_do_not_probe_the_second_environment(wire):
    wire.script = {apns._SANDBOX: _Response(410, json.dumps({"reason": "Unregistered"}))}
    ok, detail = apns.send("tok-gone", title="t", body="b")
    assert not ok
    assert "410" in detail
    assert len(wire.posts) == 1


def test_bad_in_both_environments_reports_it(wire):
    wire.script = {apns._SANDBOX: BAD_TOKEN, apns._PROD: BAD_TOKEN}
    ok, detail = apns.send("tok-junk", title="t", body="b")
    assert not ok
    assert "both environments" in detail
