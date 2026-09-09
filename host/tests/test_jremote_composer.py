"""The compose lift — the CLI hands over its input buffer, whole.

What these pin is the one property the screen-reading version could not have:
a lift either returns the entire buffer or reports that it did not happen, and
a report that it did not happen means nothing in the CLI was touched.
"""

import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from jstack_host import composer, managed

SHIM = Path(__file__).resolve().parents[1] / "bin" / "jremote-compose-editor"


def test_managed_sessions_are_spawned_with_the_shim_as_visual():
    """VISUAL, not EDITOR — this machine's settings.json sets EDITOR=cot -w for
    The user's own ctrl+G and the CLI resolves VISUAL first, so the managed pane
    gets the shim without taking their desk editor away."""
    exports = managed._compose_exports("sid-1234")
    assert "export VISUAL=" in exports
    assert str(SHIM) in exports
    assert "export JREMOTE_SID=" in exports
    assert "export JREMOTE_COMPOSE_DIR=" in exports
    assert "EDITOR=" not in exports.replace("JREMOTE_EDITOR", "")


def test_the_shim_only_parks_the_agents_prompt_file(tmp_path):
    """VISUAL is inherited by everything else in that pane. A `git commit`
    there must reach a real editor, not block forever on a host that is not
    watching for it."""
    other = tmp_path / "COMMIT_EDITMSG"
    other.write_text("subject")
    r = subprocess.run([str(SHIM), str(other)],
                       env={**os.environ,
                            "JREMOTE_EDITOR_FALLBACK": "/bin/echo",
                            "JREMOTE_COMPOSE_DIR": str(tmp_path / "park")},
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 0
    assert str(other) in r.stdout          # the fallback ran, on that file
    assert not (tmp_path / "park").exists()  # nothing parked


def test_the_shim_parks_the_path_and_waits_to_be_released(tmp_path):
    prompt = tmp_path / "claude-prompt-abc.md"
    prompt.write_text("every word, including the ones off screen")
    park_dir = tmp_path / "park"
    env = {**os.environ, "JREMOTE_COMPOSE_DIR": str(park_dir),
           "JREMOTE_SID": "sid-1234"}
    proc = subprocess.Popen([str(SHIM), str(prompt)], env=env,
                            stdout=subprocess.DEVNULL)
    try:
        park = park_dir / "sid-1234.park"
        for _ in range(100):
            if park.exists():
                break
            time.sleep(0.05)
        assert park.exists(), "the shim never parked"
        assert park.read_text().strip() == str(prompt)
        assert proc.poll() is None, "the shim exited without waiting"

        (park_dir / "sid-1234.release").touch()
        assert proc.wait(timeout=10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    # Its leavings go with it, so the next lift can't read a stale answer.
    assert not park.exists()
    assert not (park_dir / "sid-1234.release").exists()


def test_a_lift_that_cannot_happen_says_so_and_touches_nothing(monkeypatch):
    """The refusal is the safe answer, and it has to stay reachable: an
    unmanaged session gets `lifted: false` rather than a ctrl+G fired blind
    into whatever is on screen."""
    monkeypatch.setattr(managed, "is_open", lambda sid: False)
    sent = []
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: sent.append(a) or pytest.fail("keys sent"))
    out = composer.lift("no-such-session")
    assert out["lifted"] is False
    assert out["reason"]
    assert not sent


def test_a_session_without_the_shim_is_never_sent_the_key(monkeypatch):
    """ctrl+G is not safe to press on spec. Without the shim the agent runs
    whatever $EDITOR resolves to — `cot -w` on this Mac — which puts a window
    on the desk and blocks the CLI inside it until a hand closes it."""
    monkeypatch.setattr(managed, "is_open", lambda sid: True)
    monkeypatch.setattr(managed, "open_names", lambda: {managed._name("sid-1234")})
    monkeypatch.setattr(composer, "_pane_has_shim", lambda name: False)
    sent = []
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: sent.append(a) or pytest.fail("keys sent"))
    out = composer.lift("sid-1234")
    assert out["lifted"] is False
    assert "restart" in out["reason"]
    assert not sent


def test_a_lift_returns_the_whole_file_and_leaves_the_replacement(tmp_path, monkeypatch):
    """The end-to-end shape with the shim stood in for: whatever the CLI wrote
    comes back entire, and the box is left holding exactly what was asked."""
    prompt = tmp_path / "claude-prompt-xyz.md"
    whole = " ".join(f"word{i:03d}" for i in range(1, 201))
    prompt.write_text(whole)
    monkeypatch.setattr(composer, "COMPOSE_DIR", tmp_path / "park")
    monkeypatch.setattr(managed, "is_open", lambda sid: True)
    monkeypatch.setattr(managed, "open_names", lambda: {managed._name("sid-1234")})
    monkeypatch.setattr(composer, "_pane_has_shim", lambda name: True)

    def fake_run(argv, **kw):
        # The pane's ctrl+G: a shim appears and parks, exactly as the real one
        # does, then releases when the file has been written back.
        park = tmp_path / "park" / "sid-1234.park"

        def shim():
            park.write_text(str(prompt) + "\n")
            for _ in range(200):
                if (tmp_path / "park" / "sid-1234.release").exists():
                    park.unlink()
                    return
                time.sleep(0.01)
        threading.Thread(target=shim, daemon=True).start()
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = composer.lift("sid-1234", replacement="")
    assert out["lifted"] is True
    assert out["text"] == whole          # all 200 words, not the visible tail
    assert prompt.read_text() == ""      # the box is emptied, once
