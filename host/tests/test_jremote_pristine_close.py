"""The open-then-back-out reap: `pristine=true` on /close kills only a session
nothing was ever said in.

The phone's half of the judgment ("no keystrokes ever reached the terminal")
goes stale the moment someone types into the session's Mac window, so the
transcript is re-checked host-side, where the fact lives. These tests pin the
direction of every uncertainty: only provably-empty dies; anything with a real
conversation line — or a transcript that can't be parsed, or a `pid-` row that
has no transcript to ask — is kept.
"""

import json

import pytest

from jstack_host import board, managed, router

SID = "dddddddd-1111-2222-3333-444444444444"


@pytest.fixture
def projects(monkeypatch, tmp_path):
    monkeypatch.setattr(board, "_CLAUDE_PROJECTS", tmp_path)
    return tmp_path


def _write(projects, lines):
    pd = projects / "-Users-jarvis-Agents-Jarvis-chat"
    pd.mkdir(parents=True, exist_ok=True)
    (pd / f"{SID}.jsonl").write_text(
        "\n".join(json.dumps(ln) for ln in lines) + "\n")


# ── the judgment itself ─────────────────────────────────────────────────────

def test_no_transcript_is_pristine(projects):
    """A fresh phone-spawned session writes no JSONL until its first message —
    the common case for open-then-back-out."""
    assert board.transcript_pristine(SID) is True


def test_metadata_and_injections_do_not_count(projects):
    """Harness lines and hook-injected `isMeta` user lines are the machine
    talking to itself — "injections considering"."""
    _write(projects, [
        {"type": "last-prompt"},
        {"type": "mode"},
        {"type": "permission-mode"},
        {"type": "user", "isMeta": True, "message": {"content": "injected"}},
    ])
    assert board.transcript_pristine(SID) is True


def test_a_real_user_line_is_not_pristine(projects):
    _write(projects, [{"type": "user", "message": {"content": "hey"}}])
    assert board.transcript_pristine(SID) is False


def test_an_assistant_line_is_not_pristine(projects):
    _write(projects, [{"type": "assistant", "message": {"content": []}}])
    assert board.transcript_pristine(SID) is False


def test_unparseable_means_kept(projects):
    """Unprovable reads as not pristine — the only destructive direction here
    is killing something Boss said something into."""
    pd = projects / "x"
    pd.mkdir()
    (pd / f"{SID}.jsonl").write_text("not json\n")
    assert board.transcript_pristine(SID) is False


# ── the endpoint's use of it ────────────────────────────────────────────────

def test_pristine_close_kills_an_empty_managed_session(projects, monkeypatch):
    killed = []
    monkeypatch.setattr(managed, "is_open", lambda sid: True)
    monkeypatch.setattr(managed, "close_managed",
                        lambda sid, review=True: killed.append((sid, review)) or True)

    out = router.close_session_managed(SID, review=False, pristine=True)

    assert out["closed"] is True and out["mode"] == "managed"
    assert killed == [(SID, False)]


def test_pristine_close_keeps_a_session_with_content(projects, monkeypatch):
    """Boss typed into the session's Mac window after the phone last looked —
    the stale "nothing was typed" judgment must not cost the work."""
    _write(projects, [{"type": "user", "message": {"content": "hold on"}}])

    def boom(sid):
        raise AssertionError("a kept session must never reach the close path")
    monkeypatch.setattr(managed, "is_open", boom)

    out = router.close_session_managed(SID, review=False, pristine=True)

    assert out == {"ok": True, "closed": False, "mode": "kept"}


def test_a_pid_row_is_always_kept(monkeypatch):
    """A raw window's transcript may simply not be correlated yet — a `pid-`
    row can't prove anything, so a pristine ask never signals it."""
    def boom():
        raise AssertionError("a pristine ask must not even scan for the pid")
    monkeypatch.setattr("jstack_host.procscan.get_claude_processes", boom)

    out = router.close_session_managed("pid-4242", review=False, pristine=True)

    assert out == {"ok": True, "closed": False, "mode": "kept"}


# ── The close history ───────────────────────────────────────────────────────
#
# Boss, after two live sessions died inside two minutes: "who the fuck just
# closed your session". Answering it took the review log, process forensics
# and another agent's transcript, because nothing recorded a close at all —
# and Kill is this same endpoint with review=false, so the endpoint that ends
# every session on this Mac was the one surface with no history.
#
# It lands in the session store, not a log file: the store is already the
# long-term home for facts about a session, keyed by the same sid, and the
# seat is a column on the session's own row rather than something the close
# re-derives.

class _Req:
    """The parts of a Request the audit reads."""
    def __init__(self, ua="jRemote/NewChatMenu (iPhone)", host="192.168.1.9"):
        self.headers = {"user-agent": ua}
        self.client = type("C", (), {"host": host})()


@pytest.fixture
def closestore(monkeypatch, tmp_path):
    """A throwaway store. The audit must never reach the production one."""
    from jstack_host.store import SessionStore
    s = SessionStore(tmp_path / "jremote_store.sqlite")
    monkeypatch.setattr("jstack_host.store.get_store", lambda: s)
    return s


def test_a_close_records_who_asked(projects, closestore, monkeypatch):
    """The row has to name the client — a UI build verifying session controls
    drives the same endpoint Boss's phone does, and the User-Agent is the only
    thing that tells them apart."""
    _write(projects, [{"type": "user", "message": {"role": "user",
                                                   "content": "real work"}}])
    monkeypatch.setattr(router, "_close_session",
                        lambda *a, **k: {"ok": True, "closed": True,
                                         "mode": "managed"})
    router.close_session_managed(SID, request=_Req(), review=False)

    row, = closestore.recent_closes()
    assert row["session_id"] == SID
    assert row["mode"] == "managed" and row["closed"] is True
    assert row["review"] is False and row["pristine"] is False
    assert "NewChatMenu" in row["user_agent"], "the build that asked must be named"
    assert row["client"] == "192.168.1.9"
    assert row["closed_at"], "a close with no stamp answers nothing"


def test_the_seat_is_read_off_the_session_not_copied(closestore):
    """The store already knows which seat a sid belongs to. The close joins
    for it — a second copy on the close row is a second thing to keep true."""
    with closestore._conn() as db:
        db.execute("INSERT INTO sessions (session_id, agent_id, sub_mode) "
                   "VALUES (?,?,?)", (SID, "lynda", "social"))
    closestore.record_close(SID, mode="managed", closed=True, review=True,
                            pristine=False)

    row, = closestore.recent_closes()
    assert (row["agent_id"], row["sub_mode"]) == ("lynda", "social")


def test_killing_a_bare_pid_is_history_though_it_names_no_seat(closestore):
    """A `pid-` row is a running process with no session identity — it never
    joins and never will, which is the whole reason the join is LEFT. The
    SIGKILL behind it is still one of the most destructive things this
    endpoint does, so it must not vanish for lack of a name."""
    closestore.record_close("pid-4242", mode="managed", closed=True,
                            review=False, pristine=False)

    row, = closestore.recent_closes()
    assert row["session_id"] == "pid-4242" and row["agent_id"] == ""


def test_an_ask_against_nothing_is_not_history(projects, closestore):
    """`gone` reached no process at all. Nothing ended, so there is nothing to
    name — and these are cheap to provoke, so they would bury the real rows."""
    router.close_session_managed("pid-999999999", request=_Req(), review=False)
    assert closestore.recent_closes() == []


def test_reaping_an_empty_session_is_not_history(projects, closestore,
                                                 monkeypatch):
    """A successful pristine reap is the host's own proof that nothing was
    ever said in that session, and the open-then-back-out flow fires it
    constantly in ordinary phone use. A session with no transcript is not a
    session — we do not record it dying."""
    monkeypatch.setattr(managed, "is_open", lambda sid: True)
    monkeypatch.setattr(managed, "close_managed", lambda sid, review=True: True)

    out = router.close_session_managed(SID, request=_Req(), review=False,
                                       pristine=True)
    assert out["closed"] is True, "the reap itself still happens"
    assert closestore.recent_closes() == []


def test_a_declined_close_is_still_history(projects, closestore):
    """`kept` is the most useful row in the table: a close was asked for and
    refused, which is what you want to see when the session dies a minute
    later anyway."""
    _write(projects, [{"type": "user", "message": {"role": "user",
                                                   "content": "real work"}}])
    out = router.close_session_managed(SID, request=_Req(), pristine=True)
    assert out["mode"] == "kept"

    row, = closestore.recent_closes()
    assert row["mode"] == "kept" and row["closed"] is False


def test_a_close_that_raises_still_leaves_a_row(projects, closestore,
                                                monkeypatch):
    """A close that timed out mid-signal is exactly the one worth having a
    row for — so the audit sits in `finally`, not on the return path."""
    def boom(*a, **k):
        raise router.HTTPException(status_code=504, detail="didn't exit")
    monkeypatch.setattr(router, "_close_session", boom)

    with pytest.raises(router.HTTPException):
        router.close_session_managed(SID, request=_Req())

    row, = closestore.recent_closes()
    assert row["mode"] == "error"


def test_closes_can_be_read_back_for_one_session(closestore):
    """Newest first, and filterable to the session Boss is asking about."""
    for mode in ("kept", "managed"):
        closestore.record_close(SID, mode=mode, closed=mode == "managed",
                                review=True, pristine=False)
    closestore.record_close("other-sid", mode="gone", closed=False,
                            review=True, pristine=False)

    assert [r["mode"] for r in closestore.recent_closes(session_id=SID)] \
        == ["managed", "kept"]
    assert len(closestore.recent_closes()) == 3


def test_an_in_process_close_is_not_history(projects, closestore, monkeypatch):
    """The audit exists to name an HTTP client, so a direct call records
    nothing — which is also what keeps the rest of this suite (every one of
    which invokes the endpoint function directly) off the production store.

    The close here is one that would otherwise be recorded, so the missing
    request is the only thing that can explain the empty table.

    Not mutation-provable on its own: `_audit_close` never raises, so removing
    the `request is None` guard swallows the AttributeError and records
    nothing either way. Kept as a contract statement, not as a check that can
    go red."""
    _write(projects, [{"type": "user", "message": {"role": "user",
                                                   "content": "real work"}}])
    monkeypatch.setattr(router, "_close_session",
                        lambda *a, **k: {"ok": True, "closed": True,
                                         "mode": "managed"})
    router.close_session_managed(SID, review=False)
    assert closestore.recent_closes() == []
