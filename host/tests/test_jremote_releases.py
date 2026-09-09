"""jRemote's Mac update feed — what the app updates itself from.

The Mac app cannot function without this API, so its updates ride it too: any
Mac that can run jRemote can update jRemote, over the LAN or through the
tunnel, with nothing published to the internet.

What is pinned here is mostly about *lying*. An update feed that reports
"nothing new" when it actually cannot read the release is the failure mode
that costs a week — every Mac quietly stops updating and nothing says so. So:
a missing manifest is the one honest empty, and every other broken state (a
manifest naming an artifact that isn't there, an artifact the wrong size,
unparseable JSON, a `file` that points outside the release dir) is a 500 the
app surfaces rather than a shrug it hides.
"""

import json

import pytest
from fastapi.testclient import TestClient

from jstack_host.server import create_app

app = create_app()
from jstack_host import auth, releases

LATEST = "/api/jremote/v1/app/mac/latest"
DOWNLOAD = "/api/jremote/v1/app/mac/download"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "_expected_token", lambda: "test-token")
    c = TestClient(app)
    c.headers.update({"Authorization": "Bearer test-token"})
    return c


@pytest.fixture
def release_dir(tmp_path, monkeypatch):
    """Point the module at a throwaway release dir."""
    d = tmp_path / "mac"
    d.mkdir()
    monkeypatch.setattr(releases, "RELEASE_DIR", d)
    monkeypatch.setattr(releases, "MANIFEST", d / "latest.json")
    return d


def publish(release_dir, *, build=23, body=b"PK\x03\x04zipbytes", **overrides):
    """Write a well-formed release the way release-mac.sh does."""
    name = f"jRemote-{build}.zip"
    (release_dir / name).write_bytes(body)
    manifest = {
        "version": "1.0",
        "build": build,
        "sha256": "a" * 64,
        "bytes": len(body),
        "file": name,
        "teamID": "MZ95H77RQQ",
        "notes": "What changed",
        "published": "2026-08-27T21:00:00-07:00",
    }
    manifest.update(overrides)
    (release_dir / "latest.json").write_text(json.dumps(manifest))
    return manifest


# ── Nothing published — the one honest empty


def test_no_manifest_reports_nothing_available(client, release_dir):
    r = client.get(LATEST)
    assert r.status_code == 200
    assert r.json() == {"available": False, "publishes": True}


def test_download_with_nothing_published_is_404(client, release_dir):
    assert client.get(DOWNLOAD).status_code == 404


# ── A host that is not a publisher at all
#
# This is the one that cost the user a build. A leaf runs the standalone
# host, so the app on it asked *itself* for updates, got the same empty a
# home host gives before its first release, and drew "Up to date" on build 34
# while 35 sat on the machine that builds them.


def test_a_host_that_never_publishes_says_so(client, tmp_path, monkeypatch):
    """No release dir — nothing is built here and nothing ever will be. The
    app has to be able to tell that from "the publisher has nothing newer",
    because only one of the two means "you are up to date"."""
    absent = tmp_path / "never-published" / "mac"
    monkeypatch.setattr(releases, "RELEASE_DIR", absent)
    monkeypatch.setattr(releases, "MANIFEST", absent / "latest.json")
    assert client.get(LATEST).json() == {"available": False, "publishes": False}


def test_a_publisher_with_a_release_says_it_publishes(client, release_dir):
    publish(release_dir)
    assert client.get(LATEST).json()["publishes"] is True


# ── A good release


def test_serves_the_published_release(client, release_dir):
    manifest = publish(release_dir)
    body = client.get(LATEST).json()
    assert body["available"] is True
    assert body["build"] == manifest["build"]
    assert body["version"] == "1.0"
    assert body["sha256"] == manifest["sha256"]
    assert body["bytes"] == manifest["bytes"]
    assert body["teamID"] == "MZ95H77RQQ"
    assert body["notes"] == "What changed"


def test_the_manifest_does_not_leak_the_filename(client, release_dir):
    """The client asks for `/download`; the name on disk is the host's business
    and is where a path-traversal bug would come from."""
    publish(release_dir)
    assert "file" not in client.get(LATEST).json()


def test_download_returns_the_artifact(client, release_dir):
    publish(release_dir, body=b"PK\x03\x04the-real-bytes")
    r = client.get(DOWNLOAD)
    assert r.status_code == 200
    assert r.content == b"PK\x03\x04the-real-bytes"


def test_republishing_an_older_build_rolls_back(client, release_dir):
    """Rollback is republishing an older manifest — the feed answers with the
    build the manifest names, never with the highest number on disk."""
    publish(release_dir, build=23)
    publish(release_dir, build=22)
    assert client.get(LATEST).json()["build"] == 22


# ── Broken feeds go red, not quiet


def test_a_manifest_naming_a_missing_artifact_is_an_error(client, release_dir):
    publish(release_dir)
    next(release_dir.glob("jRemote-*.zip")).unlink()
    r = client.get(LATEST)
    assert r.status_code == 500
    assert "missing artifact" in r.json()["detail"]


def test_a_half_written_artifact_is_an_error(client, release_dir):
    """The zip on disk is shorter than the manifest says — a publish that died
    mid-copy. Serving it would have every Mac download it, fail its own
    checksum, and retry forever with nothing saying why."""
    publish(release_dir, body=b"PK\x03\x04full-length-body")
    name = json.loads((release_dir / "latest.json").read_text())["file"]
    (release_dir / name).write_bytes(b"PK\x03\x04trunc")
    r = client.get(LATEST)
    assert r.status_code == 500
    assert "half-published" in r.json()["detail"]


def test_unreadable_manifest_is_an_error(client, release_dir):
    (release_dir / "latest.json").write_text("{not json")
    assert client.get(LATEST).status_code == 500


def test_manifest_missing_a_required_field_is_an_error(client, release_dir):
    publish(release_dir)
    manifest = json.loads((release_dir / "latest.json").read_text())
    del manifest["sha256"]
    (release_dir / "latest.json").write_text(json.dumps(manifest))
    r = client.get(LATEST)
    assert r.status_code == 500
    assert "sha256" in r.json()["detail"]


def test_a_file_escaping_the_release_dir_is_refused(client, release_dir):
    publish(release_dir, file="../../../../etc/passwd")
    for path in (LATEST, DOWNLOAD):
        r = client.get(path)
        assert r.status_code == 500, path
        assert "escapes" in r.json()["detail"]


def test_download_refuses_a_half_published_release(client, release_dir):
    """The download route runs the same check as /latest — a client holding a
    stale manifest can't reach past it to a broken artifact."""
    publish(release_dir, body=b"PK\x03\x04full-length-body")
    name = json.loads((release_dir / "latest.json").read_text())["file"]
    (release_dir / name).write_bytes(b"short")
    assert client.get(DOWNLOAD).status_code == 500


# ── Auth


def test_both_routes_sit_behind_the_bearer_token(release_dir):
    publish(release_dir)
    anon = TestClient(app)
    assert anon.get(LATEST).status_code == 401
    assert anon.get(DOWNLOAD).status_code == 401
