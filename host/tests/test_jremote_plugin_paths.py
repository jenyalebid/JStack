"""Where this machine's JStack adapters are.

Nine call sites — the pict renderer, the dub adapter, `msg`, `log_event`,
`place-issue`, `task-create`, the relay's PATH, the webhook doctor, the test
suite's scheduler import — used to spell `~/JStack/plugins/jstack/bin/<name>`
in full. That path is the install location only where the marketplace is a
`directory` source. Install the plugin from its github marketplace and there is
no `~/JStack`: the working copy is the versioned one under `plugins/cache/`,
which is also the copy Claude Code itself runs. The app is meant to work on any
machine that has JStack, so this pins all three shapes.

No fixtures, no app import: this file must pass on a bare leaf, which is the
kind of machine that broke.
"""

import json
from pathlib import Path

import pytest

from jstack_host import plugin_paths


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


def _cached(home: Path, version: str) -> Path:
    b = home / ".claude/plugins/cache/JStack/jstack" / version / "bin"
    b.mkdir(parents=True)
    (b / "pict").write_text("#!/bin/sh\n")
    return b / "pict"


def _dev(home: Path) -> Path:
    b = home / "JStack/plugins/jstack/bin"
    b.mkdir(parents=True)
    (b / "pict").write_text("#!/bin/sh\n")
    return b / "pict"


def _marketplace(home: Path, source: dict):
    live = home / "JStack"
    (live / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (live / ".claude-plugin" / "marketplace.json").write_text(json.dumps(
        {"name": "JStack",
         "plugins": [{"name": "jstack", "source": "./plugins/jstack"}]}))
    mk = home / ".claude/plugins/known_marketplaces.json"
    mk.parent.mkdir(parents=True, exist_ok=True)
    mk.write_text(json.dumps({"JStack": {"source": source,
                                         "installLocation": str(live)}}))


def test_a_github_install_answers_from_the_cache(home):
    """The shape that broke: no `~/JStack` on disk at all. Answering the dev
    path here is a 501 on a machine that has the renderer."""
    _marketplace(home, {"source": "github", "repo": "example-org/JStack"})
    want = _cached(home, "0.57.1")
    assert plugin_paths.jstack_bin("pict") == want
    assert plugin_paths.jstack_bin("pict").exists()


def test_the_newest_cached_version_wins_and_the_sort_parses(home):
    """Lexicographic order ranks 0.8.0 over 0.29.0 and would pin a machine to a
    version three releases stale, silently, forever."""
    _marketplace(home, {"source": "github", "repo": "example-org/JStack"})
    for v in ("0.8.0", "0.29.0", "0.10.0"):
        _cached(home, v)
    assert plugin_paths.jstack_bin("pict").parent.parent.name == "0.29.0"


def test_a_directory_marketplace_answers_from_the_checkout(home):
    """On the machine that maintains the plugin the checkout IS the install:
    an edit is live in the next session, while the cache stays frozen."""
    _marketplace(home, {"source": "directory", "path": str(home / "JStack")})
    want = _dev(home)
    _cached(home, "9.9.9")
    assert plugin_paths.jstack_bin("pict") == want


def test_an_unregistered_checkout_still_beats_the_cache(home):
    """A clone the marketplace never registered is still the maintainer's tree."""
    want = _dev(home)
    _cached(home, "9.9.9")
    assert plugin_paths.jstack_bin("pict") == want


def test_no_jstack_at_all_returns_a_path_to_probe_not_an_error(home):
    """Callers decide what absence means — pict answers 501, the timeline
    answers "no vocabulary" — so the resolver must hand back a path, never
    raise and never None."""
    p = plugin_paths.jstack_bin("pict")
    assert isinstance(p, Path) and not p.exists()
