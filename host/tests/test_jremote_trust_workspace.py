"""`_trust_workspace` pre-accepts Claude's one-time folder-trust dialog for the
workspaces the daemon opens managed sessions into — the gate that, unanswered,
parks a phone-opened session before it ever reads its first prompt.

The pins here are the ones that keep the fix from becoming a liability: it only
touches the tree the host manages, it never rewrites the CLI's shared file when
it has nothing to add, it preserves everything already in that file, and a
config it cannot parse is one it leaves alone rather than clobbers.
"""

import json
from pathlib import Path

import pytest

from jstack_host import managed


@pytest.fixture
def home_and_root(tmp_path, monkeypatch):
    """A fake $HOME and an instance root under it, both real directories."""
    home = tmp_path / "home"
    root = home / "jstack-root" / "Agents"
    root.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("JREMOTE_INSTANCE_ROOT", str(root))
    return home, root


def _config(home):
    return home / ".claude.json"


def test_trusts_a_workspace_under_the_instance_root(home_and_root):
    home, root = home_and_root
    seat = root / "Ada"
    seat.mkdir()

    managed._trust_workspace(str(seat))

    data = json.loads(_config(home).read_text())
    key = str(seat.resolve())
    assert data["projects"][key]["hasTrustDialogAccepted"] is True


def test_leaves_a_path_outside_the_instance_root_gated(home_and_root):
    home, root = home_and_root
    outside = home / "somewhere-else"
    outside.mkdir()

    managed._trust_workspace(str(outside))

    # Nothing to trust here — the file is not created, and if it existed the
    # outside path would never be keyed into it.
    cfg = _config(home)
    if cfg.exists():
        assert str(outside.resolve()) not in json.loads(cfg.read_text()).get("projects", {})
    else:
        assert not cfg.exists()


def test_flips_a_declined_entry_while_preserving_the_rest(home_and_root):
    home, root = home_and_root
    seat = root / "Ada"
    seat.mkdir()
    key = str(seat.resolve())
    _config(home).write_text(json.dumps({
        "numStartups": 7,
        "oauthAccount": {"keep": "me"},
        "projects": {
            key: {"hasTrustDialogAccepted": False, "allowedTools": ["Bash"]},
            "/some/other/dir": {"hasTrustDialogAccepted": True},
        },
    }))

    managed._trust_workspace(str(seat))

    data = json.loads(_config(home).read_text())
    assert data["projects"][key]["hasTrustDialogAccepted"] is True
    assert data["projects"][key]["allowedTools"] == ["Bash"]      # untouched
    assert data["projects"]["/some/other/dir"] == {"hasTrustDialogAccepted": True}
    assert data["numStartups"] == 7
    assert data["oauthAccount"] == {"keep": "me"}


def test_already_trusted_is_a_no_op_that_never_rewrites(home_and_root):
    home, root = home_and_root
    seat = root / "Ada"
    seat.mkdir()
    key = str(seat.resolve())
    cfg = _config(home)
    cfg.write_text(json.dumps({"projects": {key: {"hasTrustDialogAccepted": True}}}))
    before = cfg.read_bytes()

    managed._trust_workspace(str(seat))

    assert cfg.read_bytes() == before  # byte-identical: no write happened


def test_a_corrupt_config_is_left_untouched(home_and_root):
    home, root = home_and_root
    seat = root / "Ada"
    seat.mkdir()
    cfg = _config(home)
    cfg.write_text("{ this is not json")
    before = cfg.read_bytes()

    managed._trust_workspace(str(seat))

    assert cfg.read_bytes() == before  # never clobber a file we cannot parse


def test_creates_the_config_when_none_exists(home_and_root):
    home, root = home_and_root
    seat = root / "Ada"
    seat.mkdir()
    assert not _config(home).exists()

    managed._trust_workspace(str(seat))

    data = json.loads(_config(home).read_text())
    assert data["projects"][str(seat.resolve())]["hasTrustDialogAccepted"] is True
