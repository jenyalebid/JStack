"""jRemote file drops — the phone→Mac upload endpoint and the drop landing.

Pins the contract the app leans on: a session-less drop (the share sheet)
lands in the seat's pad — the one shared folder the Files pane shows, marked
as the user's so an agent's cleanup leaves it — the returned path is real,
hostile filenames can't escape, and `open-new` forwards its optional first message
as the prompt-gated nudge (the share-sheet spawn). Filesystem is a tmp
dir; tmux is never touched.
"""

import pytest
from fastapi.testclient import TestClient

from jstack_host.server import create_app

app = create_app()
from jstack_host import auth, scratchpad


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "_expected_token", lambda: "test-token")
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer test-token"})
    return c


@pytest.fixture
def drop_pad(monkeypatch, tmp_path):
    """Point agent resolution at a throwaway tree for 'testa'; return the
    seat's pad, where every drop lands."""
    seat = tmp_path / "seat"
    seat.mkdir()
    def _ws(agent_id):
        if agent_id != "testa":
            raise KeyError(agent_id)
        return seat
    monkeypatch.setattr(scratchpad, "workspace", _ws)
    return seat / scratchpad.PAD


# ── the drop landing ──

def test_save_drop_lands_in_the_seats_one_pad(drop_pad):
    p = scratchpad.save_drop("testa", "photo.png", b"bytes!")
    assert p.read_bytes() == b"bytes!"
    assert p.parent == drop_pad
    assert p.name.endswith("-photo.png")
    # Theirs, so a routine agent cleanup steps over it.
    assert scratchpad.is_boss(p)


def test_cwd_slug_encodes_like_the_harness(tmp_path):
    assert scratchpad._cwd_slug("/Users/x/Agents/Testa/chat") == \
        "-Users-x-Agents-Testa-chat"
    assert scratchpad._cwd_slug("/Users/x/.claude") == "-Users-x--claude"


def test_traversal_filename_stays_inside(drop_pad):
    p = scratchpad.save_drop("testa", "../../../../etc/passwd", b"x")
    assert p.parent == drop_pad
    assert "passwd" in p.name


def test_hostile_and_empty_filenames(drop_pad):
    p = scratchpad.save_drop("testa", "we ird$$name!!.p ng", b"x")
    assert p.parent == drop_pad
    q = scratchpad.save_drop("testa", "", b"y")
    assert q.name.endswith("-file")


def test_same_second_collision_never_overwrites(drop_pad, monkeypatch):
    monkeypatch.setattr(scratchpad.time, "strftime",
                        lambda fmt: "20260815-120000")
    a = scratchpad.save_drop("testa", "shot.png", b"first")
    b = scratchpad.save_drop("testa", "shot.png", b"second")
    assert a != b
    assert a.read_bytes() == b"first" and b.read_bytes() == b"second"


# ── the endpoint ──

def test_upload_roundtrip(client, drop_pad):
    r = client.post("/api/jremote/v1/upload?agent_id=testa&filename=shot.png",
                    content=b"PNGDATA")
    assert r.status_code == 200
    body = r.json()
    from pathlib import Path
    assert Path(body["path"]).read_bytes() == b"PNGDATA"


def test_upload_unknown_agent_404(client, drop_pad):
    r = client.post("/api/jremote/v1/upload?agent_id=nobody&filename=x.png",
                    content=b"data")
    assert r.status_code == 404


def test_upload_empty_body_400(client, drop_pad):
    r = client.post("/api/jremote/v1/upload?agent_id=testa&filename=x.png",
                    content=b"")
    assert r.status_code == 400


def test_upload_oversize_413(client, drop_pad, monkeypatch):
    monkeypatch.setattr(scratchpad, "MAX_UPLOAD", 8)
    r = client.post("/api/jremote/v1/upload?agent_id=testa&filename=x.png",
                    content=b"way more than eight")
    assert r.status_code == 413


def test_upload_requires_token(monkeypatch, drop_pad):
    monkeypatch.setattr(auth, "_expected_token", lambda: "real-token")
    c = TestClient(app)
    r = c.post("/api/jremote/v1/upload?agent_id=testa&filename=x.png",
               content=b"data")
    assert r.status_code == 401


# ── open-new forwards the share text as the nudge ──

@pytest.fixture
def spawn_env(monkeypatch, tmp_path):
    import lib.agents as agents
    from jstack_host import managed, board_watch
    monkeypatch.setattr(agents, "workspace", lambda a: tmp_path)
    monkeypatch.setattr(agents, "split_id", lambda a: (a, None))
    calls = {}
    # Signatures kept in step with the real ones, model picker included: a
    # fake that is missing a kwarg the route passes fails as a TypeError from
    # inside the route, which reads as a broken endpoint rather than a stale
    # double.
    def fake_open(sid, cwd, resume=True, displace=None, nudge=None,
                  extra="", prelude="", window=False, engine="claude",
                  model="", tag=""):
        calls.update(sid=sid, cwd=cwd, resume=resume, nudge=nudge,
                     engine=engine, model=model)
    def fake_record(sid, base, name="", engine="claude", model="", tag=""):
        calls.update(recorded_engine=engine, recorded_model=model)
    monkeypatch.setattr(managed, "open_managed", fake_open)
    monkeypatch.setattr(managed, "record_open", fake_record)
    monkeypatch.setattr(board_watch, "poke", lambda: None)
    return calls


def test_open_new_with_text_nudges(client, spawn_env):
    r = client.post("/api/jremote/v1/sessions/open-new",
                    json={"agent_id": "testa",
                          "text": "Look at this: /tmp/shot.png"})
    assert r.status_code == 200
    assert spawn_env["resume"] is False
    assert spawn_env["nudge"] == "Look at this: /tmp/shot.png"


def test_open_new_without_text_spawns_waiting(client, spawn_env):
    r = client.post("/api/jremote/v1/sessions/open-new",
                    json={"agent_id": "testa"})
    assert r.status_code == 200
    assert spawn_env["nudge"] is None
    # A caller that says nothing about the engine gets claude — both at spawn
    # and in the registry, so the board row can never disagree with the process.
    assert spawn_env["engine"] == "claude"
    assert spawn_env["recorded_engine"] == "claude"


def test_open_new_blank_text_is_no_nudge(client, spawn_env):
    r = client.post("/api/jremote/v1/sessions/open-new",
                    json={"agent_id": "testa", "text": "   "})
    assert r.status_code == 200
    assert spawn_env["nudge"] is None
