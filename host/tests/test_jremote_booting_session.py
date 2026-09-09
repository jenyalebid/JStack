"""A booting session is not a missing one.

jRemote registers a managed sid on the board *before* the pane execs `claude`
(`record_open`), and the CLI then takes ~10s to flush its first line to disk.
Measured on this Mac: pane up 15:13:08, JSONL born 15:13:20. For those twelve
seconds a live session has no transcript, and both read surfaces used to call
that "not found".

What it cost was not the wording. The app latches `error` — only re-attaching
clears it, and `start()` attaches *before* it loads history — and its watch
task dies on one throw with nothing to restart it. So a thread opened during
boot showed a permanent red "Session file not found" under a working terminal
AND never streamed a message or a busy flag again, for the life of the window.
Closing and reopening was the only cure.

So: while the session is live, no-transcript-yet reads as pending (history) and
as waiting (stream), and only a sid with no session behind it is an error.
"""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from jstack_host import managed, messages, router


# ── history: GET /sessions/{sid} ──

def test_booting_session_is_pending_not_an_error(monkeypatch):
    """The one that put red text under the user's working terminal."""
    monkeypatch.setattr(messages, "_find_session_file", lambda sid: None)
    monkeypatch.setattr(managed, "is_open", lambda sid: True)

    body = messages.parse_session("a" * 32)

    assert body == {"messages": [], "pending": True}
    assert "error" not in body


def test_sid_with_no_session_behind_it_still_errors(monkeypatch):
    """The error has a real job: a thread that opens blank on a session that
    genuinely isn't there reads as data loss. Only liveness excuses it."""
    monkeypatch.setattr(messages, "_find_session_file", lambda sid: None)
    monkeypatch.setattr(managed, "is_open", lambda sid: False)

    assert messages.parse_session("a" * 32)["error"] == "Session file not found"


def test_a_broken_tmux_probe_does_not_swallow_the_error(monkeypatch):
    """`is_open` shells out. If that fails we know nothing about liveness, and
    guessing "pending" would hide a real missing session behind a spinner."""
    def boom(sid):
        raise OSError("no tmux")

    monkeypatch.setattr(messages, "_find_session_file", lambda sid: None)
    monkeypatch.setattr(managed, "is_open", boom)

    assert messages.parse_session("a" * 32)["error"] == "Session file not found"


def test_an_invalid_sid_is_never_called_pending(monkeypatch):
    """Shape is checked before liveness — a malformed id is a client bug, and
    naming it "booting" would send the app into an endless wait."""
    monkeypatch.setattr(managed, "is_open", lambda sid: True)

    assert messages.parse_session("not-a-sid")["error"] == "Invalid session ID"


# ── live tail: GET /sessions/{sid}/stream ──

class _Request:
    """A client that stays connected for `frames` polls, then hangs up."""

    def __init__(self, frames=200):
        self.frames = frames

    async def is_disconnected(self):
        self.frames -= 1
        return self.frames < 0


@pytest.fixture
def projects(tmp_path, monkeypatch):
    """A throwaway ~/.claude/projects — `_tail_path` reads it via Path.home()."""
    home = tmp_path / "home"
    (home / ".claude" / "projects" / "proj").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    assert Path.home() == home
    return home / ".claude" / "projects" / "proj"


def _line(text):
    return json.dumps({"type": "assistant",
                       "message": {"role": "assistant", "content": text}}) + "\n"


def test_stream_waits_for_a_booting_session_instead_of_404ing(projects, monkeypatch):
    """The load-bearing one. A 404 here is a thread deaf for its whole life,
    because the client's watch task never restarts."""
    monkeypatch.setattr(managed, "is_open", lambda sid: True)
    sid = "b" * 32
    jsonl = projects / f"{sid}.jsonl"

    async def main():
        resp = await router.stream_session(sid, _Request())
        seen = []

        async def drain():
            async for chunk in resp.body_iterator:
                seen.append(chunk)
                if "hello from the other side" in chunk:
                    return

        task = asyncio.create_task(drain())
        await asyncio.sleep(0.3)          # the boot window: no file yet
        assert not jsonl.exists()
        jsonl.write_text(_line("hello from the other side"))
        await asyncio.wait_for(task, timeout=5)
        return "".join(seen)

    out = asyncio.run(main())
    # Taken from the top, not from the end: nothing in this file was ever sent
    # to this client, so seeking to EOF would drop the session's whole opening.
    assert "hello from the other side" in out


def test_stream_404s_a_sid_with_no_session_behind_it(projects, monkeypatch):
    monkeypatch.setattr(managed, "is_open", lambda sid: False)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(router.stream_session("c" * 32, _Request()))
    assert raised.value.status_code == 404


def test_an_existing_transcript_still_tails_from_the_end(projects, monkeypatch):
    """The unchanged path: a session with history replays none of it here —
    the app already loaded that over /sessions/{sid}."""
    monkeypatch.setattr(managed, "is_open", lambda sid: True)
    from jstack_host import transcripts
    monkeypatch.setattr(transcripts, "_find_session_cwd", lambda sid: "/tmp")
    sid = "d" * 32
    jsonl = projects / f"{sid}.jsonl"
    jsonl.write_text(_line("old news"))

    async def main():
        resp = await router.stream_session(sid, _Request())
        seen = []

        async def drain():
            async for chunk in resp.body_iterator:
                seen.append(chunk)
                if "fresh" in chunk:
                    return

        task = asyncio.create_task(drain())
        await asyncio.sleep(0.3)
        with jsonl.open("a") as f:
            f.write(_line("fresh"))
        await asyncio.wait_for(task, timeout=5)
        return "".join(seen)

    out = asyncio.run(main())
    assert "fresh" in out
    assert "old news" not in out
