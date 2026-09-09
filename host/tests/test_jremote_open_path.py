"""jRemote open-on-Mac — a file link tapped in a session's terminal opens
on the machine the path names.

The app sends the raw token it found under the click; the host owns the
reading: strip a trailing :line[:col], drop wrapping quotes, expand ~,
anchor a relative path at the session pane's current directory, require
the file to exist, and hand it to macOS `open`. Pins: resolution is
exactly that reading, a missing file or unknown session is a 404 not an
open, and the route sits behind the bearer token.
"""

import pytest
from fastapi.testclient import TestClient

from jstack_host.server import create_app

app = create_app()
from jstack_host import auth, open_path


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "_expected_token", lambda: "test-token")
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer test-token"})
    return c


# ── resolution ──

def test_absolute_path_resolves_as_itself(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x")
    assert open_path.resolve(str(p), "/nowhere") == p


def test_relative_path_anchors_at_the_pane_cwd(tmp_path):
    (tmp_path / "sub").mkdir()
    p = tmp_path / "sub" / "file.swift"
    p.write_text("x")
    assert open_path.resolve("sub/file.swift", str(tmp_path)) == p


def test_line_and_column_suffixes_are_stripped(tmp_path):
    p = tmp_path / "file.swift"
    p.write_text("x")
    assert open_path.resolve("file.swift:243", str(tmp_path)) == p
    assert open_path.resolve("file.swift:243:7", str(tmp_path)) == p


def test_wrapping_quotes_are_stripped(tmp_path):
    p = tmp_path / "with space.md"
    p.write_text("x")
    assert open_path.resolve("'with space.md'", str(tmp_path)) == p
    assert open_path.resolve('"with space.md"', str(tmp_path)) == p


def test_tilde_expands_to_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    p = tmp_path / "notes.md"
    p.write_text("x")
    assert open_path.resolve("~/notes.md", "/nowhere") == p


def test_missing_file_raises_not_opens(tmp_path):
    with pytest.raises(FileNotFoundError):
        open_path.resolve("ghost.txt", str(tmp_path))


def test_empty_token_is_a_value_error(tmp_path):
    with pytest.raises(ValueError):
        open_path.resolve("  ", str(tmp_path))
    with pytest.raises(ValueError):
        open_path.resolve("':12'", str(tmp_path))


# ── the route ──

@pytest.fixture
def opened(monkeypatch, tmp_path):
    """Route the pane cwd at tmp_path and capture what `open` receives."""
    calls = []
    monkeypatch.setattr(open_path, "pane_cwd", lambda sid: str(tmp_path))
    monkeypatch.setattr(open_path, "_open", lambda p: calls.append(p))
    return calls


def test_route_opens_the_resolved_file(client, opened, tmp_path):
    p = tmp_path / "report.pdf"
    p.write_bytes(b"x")
    r = client.post("/api/jremote/v1/sessions/abcd1234/open-path",
                    json={"path": "report.pdf:3"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "path": str(p)}
    assert opened == [p]


def test_route_404_on_missing_file(client, opened, tmp_path):
    r = client.post("/api/jremote/v1/sessions/abcd1234/open-path",
                    json={"path": "ghost.txt"})
    assert r.status_code == 404
    assert opened == []


def test_route_400_on_empty_token(client, opened):
    r = client.post("/api/jremote/v1/sessions/abcd1234/open-path",
                    json={"path": ""})
    assert r.status_code == 400
    assert opened == []


def test_route_404_on_unknown_session(client, monkeypatch):
    def _raise(sid):
        raise KeyError(sid)
    monkeypatch.setattr(open_path, "pane_cwd", _raise)
    r = client.post("/api/jremote/v1/sessions/ffff0000/open-path",
                    json={"path": "/tmp"})
    assert r.status_code == 404


def test_route_requires_token(monkeypatch):
    monkeypatch.setattr(auth, "_expected_token", lambda: "real-token")
    c = TestClient(app)
    assert c.post("/api/jremote/v1/sessions/abcd1234/open-path",
                  json={"path": "/tmp"}).status_code == 401
