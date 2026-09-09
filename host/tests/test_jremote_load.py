"""load.py — how heavy a session is right now.

The reading behind the app's load meter: `context` (input size of the newest
API call, which is what every further turn re-reads) and `turns`. What these
tests actually pin is the failure shape. A meter that answers "0 context, 0
turns" when it could not read the transcript tells Boss the heaviest session
on the Mac is fresh and he should keep going — the exact call the meter
exists to prevent — so an unreadable session must return None, and only a
genuinely absent transcript may read as zero.
"""

import pytest
from pathlib import Path

from jstack_host import load


# ── the numbers ──

def test_reading_reports_context_turns_and_floor(monkeypatch):
    monkeypatch.setattr(load, "_find_session_file", lambda sid: Path("/x.jsonl"))
    monkeypatch.setattr(load, "get_session_summary",
                        lambda p: {"last_context": 187_000, "calls": 142,
                                   "first_context": 44_000,
                                   "total_tokens": 96_000_000})
    assert load.reading("s1") == {"context": 187_000, "turns": 142,
                                  "floor": 44_000}


def test_unmeasured_floor_is_null_not_zero(monkeypatch):
    """The floor is what a compaction drops back to, so the app subtracts it
    to say what compacting is worth. A zero here would credit a compaction
    with recovering the preamble it cannot touch — 187k of "free" savings on
    a session that would really land at ~55k. Null routes the app to its
    fleet fallback instead, which is a stand-in that knows it is one."""
    monkeypatch.setattr(load, "_find_session_file", lambda sid: Path("/x.jsonl"))
    monkeypatch.setattr(load, "get_session_summary",
                        lambda p: {"last_context": 187_000, "calls": 142,
                                   "first_context": 0})
    assert load.reading("s1")["floor"] is None


def test_reading_ignores_the_cumulative_total(monkeypatch):
    """The number that grows forever is not the number that decides."""
    monkeypatch.setattr(load, "_find_session_file", lambda sid: Path("/x.jsonl"))
    monkeypatch.setattr(load, "get_session_summary",
                        lambda p: {"last_context": 50_000, "calls": 400,
                                   "total_tokens": 120_000_000})
    assert load.reading("s1")["context"] == 50_000


def test_missing_keys_read_as_zero(monkeypatch):
    monkeypatch.setattr(load, "_find_session_file", lambda sid: Path("/x.jsonl"))
    monkeypatch.setattr(load, "get_session_summary", lambda p: {})
    assert load.reading("s1") == {"context": 0, "turns": 0, "floor": None}


# ── the failure shape ──

def test_no_transcript_is_genuinely_weightless(monkeypatch):
    """A thread nobody has typed in carries nothing — an observation, and the
    one case where zero is the honest answer."""
    monkeypatch.setattr(load, "_find_session_file", lambda sid: None)
    assert load.reading("fresh") == {"context": 0, "turns": 0, "floor": None}


def test_unparseable_transcript_reads_as_unknown_not_light(monkeypatch):
    monkeypatch.setattr(load, "_find_session_file", lambda sid: Path("/x.jsonl"))

    def boom(path):
        raise ValueError("truncated JSONL")

    monkeypatch.setattr(load, "get_session_summary", boom)
    assert load.reading("s1") is None


def test_lookup_failure_reads_as_unknown_not_light(monkeypatch):
    def boom(sid):
        raise OSError("projects tree unreadable")

    monkeypatch.setattr(load, "_find_session_file", boom)
    assert load.reading("s1") is None


def test_empty_constant_is_never_handed_out_shared(monkeypatch):
    """Callers get their own dict — a mutated reply must not rewrite the
    module's notion of an empty session."""
    monkeypatch.setattr(load, "_find_session_file", lambda sid: None)
    first = load.reading("a")
    first["context"] = 999_999
    assert load.reading("b") == {"context": 0, "turns": 0, "floor": None}
    assert load.EMPTY == {"context": 0, "turns": 0, "floor": None}


# ── the route ──

def test_timeline_omits_load_when_unreadable(monkeypatch):
    """Omitted, not zeroed: the app draws no meter rather than a green one."""
    from jstack_host import events, router

    monkeypatch.setattr(events, "timeline", lambda sid: [])
    monkeypatch.setattr(load, "reading", lambda sid: None)
    body = router.session_timeline("11111111-2222-3333-4444-555555555555")
    assert "load" not in body
    assert body["events"] == []


def test_timeline_carries_load_when_read(monkeypatch):
    from jstack_host import events, router

    monkeypatch.setattr(events, "timeline", lambda sid: [])
    monkeypatch.setattr(load, "reading",
                        lambda sid: {"context": 131_000, "turns": 33,
                                     "floor": 48_000})
    body = router.session_timeline("11111111-2222-3333-4444-555555555555")
    assert body["load"] == {"context": 131_000, "turns": 33, "floor": 48_000}
