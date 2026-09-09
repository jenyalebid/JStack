"""Per-agent session switches — the store behind the app's agent settings page.

One switch lives here today (`compact_when_done`, read by the delivery-compaction
Stop hook) and the shape is built for the next one: a list per flag, keyed on the
BASE agent, absent meaning off by construction rather than by a default someone
has to remember to pass.

Two failures are worth guarding and neither is "does a bool round-trip". The
first is a flag name that drifts between the app and the host: `set_flag` refuses
an unknown one, because a POST that stores a key nobody reads answers 200 and
leaves a switch in the app that looks exactly like a switch that worked. The
second is keying: `nova-chat` and `nova-service-call` are seats of one agent,
so a switch set from one seat's card must be on for the agent.
"""

import pytest
from fastapi.testclient import TestClient

from jstack_host.server import create_app

app = create_app()
from jstack_host import agent_prefs, auth

FLAG = "compact_when_done"


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Never touch the real switches — these tests write."""
    monkeypatch.setattr(agent_prefs, "_STATE", tmp_path / "jremote_agent_prefs.json")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "_expected_token", lambda: "test-token")
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer test-token"})
    return c


# ── The store ────────────────────────────────────────────────────────────────

def test_an_agent_nobody_touched_is_off():
    """No file, no row, no `.get(default)` — the absent case IS the default."""
    assert agent_prefs.is_on(FLAG, "nova") is False
    assert agent_prefs.prefs() == {FLAG: []}


def test_a_switch_survives_being_written_and_read():
    agent_prefs.set_flag(FLAG, "nova", True)
    assert agent_prefs.is_on(FLAG, "nova") is True
    assert agent_prefs.enabled(FLAG) == {"nova"}


def test_switching_back_off_removes_the_row():
    agent_prefs.set_flag(FLAG, "nova", True)
    agent_prefs.set_flag(FLAG, "nova", False)
    assert agent_prefs.is_on(FLAG, "nova") is False
    assert agent_prefs.prefs() == {FLAG: []}


def test_one_agents_switch_is_not_anothers():
    agent_prefs.set_flag(FLAG, "nova", True)
    assert agent_prefs.is_on(FLAG, "atlas") is False


@pytest.mark.parametrize("seat", ["nova-chat", "nova-service-call", "NOVA-Chat"])
def test_every_seat_of_an_agent_shares_the_switch(seat):
    """The page is about the agent. Setting it from one seat's card and having it
    off in another seat would be a switch that appears not to have taken."""
    agent_prefs.set_flag(FLAG, seat, True)
    assert agent_prefs.is_on(FLAG, "nova") is True
    assert agent_prefs.is_on(FLAG, "nova-social-chat") is True


@pytest.mark.parametrize("flag,agent", [
    pytest.param("compact_when_don", "nova", id="a-typo-is-not-a-flag"),
    pytest.param("anything_at_all", "nova", id="unknown-flag"),
    pytest.param(FLAG, "", id="no-agent"),
])
def test_what_cannot_be_stored_is_refused_not_swallowed(flag, agent):
    with pytest.raises(ValueError):
        agent_prefs.set_flag(flag, agent, True)


def test_an_unknown_flag_reads_as_on_for_nobody():
    assert agent_prefs.enabled("no_such_flag") == set()
    assert agent_prefs.is_on("no_such_flag", "nova") is False


def test_a_corrupt_store_reads_as_off_rather_than_raising(tmp_path):
    """This is read from a Stop hook that runs at the end of every turn. A file
    someone half-wrote must cost a compaction, never a turn."""
    (tmp_path / "jremote_agent_prefs.json").write_text("{not json")
    assert agent_prefs.is_on(FLAG, "nova") is False


# ── The endpoints ────────────────────────────────────────────────────────────

BASE = "/api/jremote/v1/agents/prefs"


def test_requires_token():
    assert TestClient(app).get(BASE).status_code == 401


def test_get_answers_every_flag_and_who_it_is_on_for(client):
    agent_prefs.set_flag(FLAG, "nova", True)
    assert client.get(BASE).json() == {FLAG: ["nova"]}


def test_post_flips_it_and_answers_the_whole_state(client):
    """The app renders the answer, so the response is the stored truth — not an
    echo of what was asked for."""
    body = client.post(BASE, json={"agent_id": "nova-chat", "flag": FLAG, "on": True})
    assert body.status_code == 200
    assert body.json() == {FLAG: ["nova"]}
    assert agent_prefs.is_on(FLAG, "nova") is True

    off = client.post(BASE, json={"agent_id": "nova-chat", "flag": FLAG, "on": False})
    assert off.json() == {FLAG: []}


def test_an_unknown_flag_is_a_400(client):
    """Never a quiet 200: a switch that posts, stores nothing and answers OK is
    indistinguishable in the app from one that worked."""
    r = client.post(BASE, json={"agent_id": "nova", "flag": "nope", "on": True})
    assert r.status_code == 400
    assert agent_prefs.prefs() == {FLAG: []}
