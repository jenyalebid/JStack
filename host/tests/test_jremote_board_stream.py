"""The board is pushed, not polled.

A poll can only ever be as fresh as its interval: a window closed just after a
tick shows as open on the phone until the next one, and the app claims a
session is on the Mac that ended seconds ago. The watcher exists to remove that
gap, so what it must guarantee is tested here:

  * a connecting app gets a board immediately, without waiting for a change;
  * a change reaches it within a tick;
  * an unchanged board sends nothing at all (no traffic, no repaint);
  * a failed observation is never broadcast as an empty board;
  * one watcher serves every client, and stops entirely once nobody is looking.
"""

import asyncio
import threading

import pytest

from jstack_host import board_watch


@pytest.fixture
def fast(monkeypatch):
    """A short tick, and a clean module between tests."""
    monkeypatch.setattr(board_watch, "TICK", 0.05)
    monkeypatch.setattr(board_watch, "_subscribers", set())
    monkeypatch.setattr(board_watch, "_watcher", None)
    monkeypatch.setattr(board_watch, "_wake", None)
    monkeypatch.setattr(board_watch, "_loop", None)
    monkeypatch.setattr(board_watch, "_latest", None)
    monkeypatch.setattr(board_watch, "_digest", None)


def _rows(monkeypatch, source):
    """Point the watcher at a scripted board; count the observations."""
    calls = []

    def snapshot():
        calls.append(1)
        value = source() if callable(source) else source
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(board_watch, "_snapshot", snapshot)
    return calls


async def _next(q, timeout=1.0):
    return await asyncio.wait_for(q.get(), timeout=timeout)


def test_first_frame_arrives_without_waiting_for_a_change(fast, monkeypatch):
    """The app paints on connect. Waiting for the board to change first would
    show an empty screen for as long as the Mac is quiet."""
    _rows(monkeypatch, [{"session_id": "a", "on_mac": True}])

    async def main():
        async with board_watch.subscription() as q:
            return await _next(q)

    assert asyncio.run(main()) == [{"session_id": "a", "on_mac": True}]


def test_a_change_is_pushed(fast, monkeypatch):
    """The point of the whole seam: a window closing on the Mac reaches the
    phone within a tick, not within a poll interval."""
    state = {"rows": [{"session_id": "a", "on_mac": True}]}
    _rows(monkeypatch, lambda: state["rows"])

    async def main():
        async with board_watch.subscription() as q:
            first = await _next(q)
            state["rows"] = [{"session_id": "a", "on_mac": False}]
            return first, await _next(q)

    first, second = asyncio.run(main())
    assert first[0]["on_mac"] is True
    assert second[0]["on_mac"] is False


def test_an_unchanged_board_sends_nothing(fast, monkeypatch):
    """An idle board must be an idle connection — otherwise every phone pays
    for a Mac that isn't doing anything."""
    _rows(monkeypatch, [{"session_id": "a", "live": False}])

    async def main():
        async with board_watch.subscription() as q:
            await _next(q)
            with pytest.raises(asyncio.TimeoutError):
                await _next(q, timeout=0.4)   # ~8 ticks of no change

    asyncio.run(main())


def test_a_failed_observation_is_not_an_empty_board(fast, monkeypatch):
    """A transient psutil error must never clear every app's screen: the last
    known truth stands until a real observation replaces it."""
    state = {"rows": [{"session_id": "a"}]}
    _rows(monkeypatch, lambda: state["rows"])

    async def main():
        async with board_watch.subscription() as q:
            first = await _next(q)
            state["rows"] = RuntimeError("scan blew up")
            with pytest.raises(asyncio.TimeoutError):
                await _next(q, timeout=0.4)
            return first

    assert asyncio.run(main()) == [{"session_id": "a"}]


def test_one_watcher_serves_every_client(fast, monkeypatch):
    """The observation is the expensive part, so N phones cost what one costs.
    A watcher per client would multiply a full psutil scan by the audience."""
    calls = _rows(monkeypatch, [{"session_id": "a"}])

    async def main():
        async with board_watch.subscription() as first:
            await _next(first)
            async with board_watch.subscription() as second:
                # The second client is current immediately — an unchanged board
                # is still the truth, so it gets the last one observed.
                assert await _next(second) == [{"session_id": "a"}]
                before = len(calls)
                await asyncio.sleep(0.3)
                return before, len(calls)

    before, after = asyncio.run(main())
    ticks = after - before
    assert 1 <= ticks <= 12, f"two clients drove {ticks} scans in 6 ticks"


def test_nobody_watching_means_nothing_running(fast, monkeypatch):
    """A Mac no app is looking at does no work at all."""
    calls = _rows(monkeypatch, [{"session_id": "a"}])

    async def main():
        async with board_watch.subscription() as q:
            await _next(q)
        await asyncio.sleep(0.2)
        settled = len(calls)
        await asyncio.sleep(0.3)
        return settled, len(calls), board_watch._watcher

    settled, later, watcher = asyncio.run(main())
    assert later == settled, "the watcher kept scanning with no subscribers"
    assert watcher is None, "the watcher task outlived its audience"


def test_poke_from_another_thread_beats_the_tick(fast, monkeypatch):
    """Endpoints change the board themselves — a close, an open, a takeover —
    and the app should repaint on the action, not on the next tick. `poke()`
    runs in FastAPI's thread pool, so it must cross threads safely."""
    monkeypatch.setattr(board_watch, "TICK", 5.0)   # a tick that will not save us
    state = {"rows": [{"session_id": "a", "on_mac": True}]}
    _rows(monkeypatch, lambda: state["rows"])

    async def main():
        async with board_watch.subscription() as q:
            await _next(q)
            state["rows"] = [{"session_id": "a", "on_mac": False}]
            threading.Thread(target=board_watch.poke).start()
            return await _next(q, timeout=2.0)      # well inside one tick

    assert asyncio.run(main())[0]["on_mac"] is False


# ── a verdict rides the frame it was derived from ───────────────────────────
#
# The notify engine is a consumer: it reads a snapshot, decides on it that a
# turn ended, and marks the session unread as it does. Handing the phones that
# frame BEFORE it ran shipped "the reply landed" — new card text, and a push
# on its way — with `unread` still false, so the dot could not go orange until
# the next tick. Boss saw the update and the notification arrive ahead of the
# status circle that explains them. A consumer's verdict belongs in the frame
# that carries its own cause.

def test_a_consumer_verdict_rides_the_frame_that_caused_it(fast, monkeypatch):
    from jstack_host import notify
    marked: set = set()
    monkeypatch.setattr(notify, "unread_sids", lambda: set(marked))
    _rows(monkeypatch, lambda: [{"session_id": "a", "managed": True,
                                 "turn": "idle", "unread": "a" in marked}])
    monkeypatch.setattr(board_watch, "_consumers", [])
    board_watch.add_consumer(lambda rows: marked.add("a"))

    async def main():
        async with board_watch.subscription() as q:
            return await _next(q)

    first = asyncio.run(main())
    assert first[0]["unread"] is True, (
        "the done edge fired on this frame and the frame went out without it")


def test_a_row_the_board_gave_no_unread_state_does_not_grow_one(fast, monkeypatch):
    """Which rows carry an unread state is the board's call. The re-read
    refreshes that field where it exists and invents it nowhere."""
    from jstack_host import notify
    monkeypatch.setattr(notify, "unread_sids", lambda: {"a"})
    _rows(monkeypatch, lambda: [{"session_id": "a", "on_mac": True}])
    monkeypatch.setattr(board_watch, "_consumers", [])
    board_watch.add_consumer(lambda rows: None)

    async def main():
        async with board_watch.subscription() as q:
            return await _next(q)

    assert asyncio.run(main()) == [{"session_id": "a", "on_mac": True}]


def test_a_failed_unread_read_leaves_the_rows_as_built(fast, monkeypatch, capsys):
    """A blind re-read must never rewrite the board. The rows as built are
    still true — just one edge old, which is where they were before."""
    from jstack_host import notify

    def boom():
        raise RuntimeError("state file unreadable")

    monkeypatch.setattr(notify, "unread_sids", boom)
    _rows(monkeypatch, lambda: [{"session_id": "a", "managed": True,
                                 "unread": True}])
    monkeypatch.setattr(board_watch, "_consumers", [])
    board_watch.add_consumer(lambda rows: None)

    async def main():
        async with board_watch.subscription() as q:
            return await _next(q)

    assert asyncio.run(main())[0]["unread"] is True
    assert "unread re-read failed" in capsys.readouterr().out
