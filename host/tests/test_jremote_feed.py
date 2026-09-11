"""The package's day feed — six sources off a jStack machine's own stores.

Pins that each producer reads the store it is given (through `hostenv`, never
a path of its own), that the merge is newest-first with the facets off the
whole day, that the two indexed producers fold their sources in, and that the
signature moves when the day does. Every store here is a temp file; nothing
reads this Mac's.
"""

import json
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from jstack_host import hostenv, feed, store

TODAY = datetime.now().strftime("%Y-%m-%d")


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A jStack machine in a temp dir: agents + registry, timeline store,
    scheduler journal, one checkout with one commit, and the host's own
    session store."""
    agents = tmp_path / "Agents"
    (agents / "Ops" / "chat").mkdir(parents=True)
    (agents / "agents.json").write_text(json.dumps(
        {"ops": {"name": "Ops", "emoji": "🛠️", "repos": ["Widget"]}}))
    monkeypatch.setenv("JREMOTE_HOST_PROFILE", "default")
    monkeypatch.setenv("JREMOTE_INSTANCE_ROOT", str(agents))
    monkeypatch.delenv("JSTACK_AGENT_REGISTRY", raising=False)
    monkeypatch.delenv("JSTACK_REPO_ROOT", raising=False)

    # jStack's timeline, with the two tables the feed reads.
    tl = tmp_path / "Timeline"
    tl.mkdir()
    monkeypatch.setenv("JSTACK_TIMELINE_DIR", str(tl))
    db = sqlite3.connect(tl / "timeline.db")
    db.executescript("""
        CREATE TABLE entries (id INTEGER PRIMARY KEY, date TEXT, time TEXT, agent TEXT,
          submode TEXT, headline TEXT, details TEXT, pipeline_task TEXT, session_id TEXT,
          verdict TEXT, verdict_note TEXT, created_at TEXT, context TEXT, origin TEXT);
        CREATE TABLE messages (id INTEGER PRIMARY KEY, created_at TEXT, from_seat TEXT,
          to_agent TEXT, to_seat TEXT, subject TEXT, body TEXT, attachments TEXT,
          wake INTEGER, reply_to INTEGER, thread_id TEXT, state TEXT);
    """)
    db.execute("INSERT INTO entries VALUES (1,?, '09:15','ops','chat','Fixed the leak',"
               "'[\"closed the connection\"]','','sid-1','','', ?, '', 'direct')",
               (TODAY, f"{TODAY}T09:15:00"))
    db.execute("INSERT INTO messages VALUES (7,?, 'ops/chat','atlas','atlas/chat',"
               "'Please rebuild','the map is stale','',1,NULL,'t1','open')",
               (f"{TODAY}T10:00:00",))
    db.commit(); db.close()

    # jStack's scheduler: a registry naming the job, and a journal line.
    sched = tmp_path / "scheduler"
    (sched / "config").mkdir(parents=True)
    runs = sched / "state" / "scheduler" / "runs"
    runs.mkdir(parents=True)
    monkeypatch.setenv("SCHEDULER_HOME", str(sched))
    (sched / "config" / "schedule.json").write_text(json.dumps(
        {"jobs": [{"id": "job1", "name": "Nightly", "agent_id": "ops-chat"}]}))
    (runs / "job1.jsonl").write_text(json.dumps({
        "ts": int(time.time() * 1000), "jobId": "job1", "runId": "r1",
        "action": "finished", "status": "ok", "summary": "did it",
        "sessionId": "sid-2", "durationMs": 1200, "exitCode": 0}) + "\n")

    # One checkout beside the agents, owned by ops per the registry.
    repo = tmp_path / "Widget"
    repo.mkdir()
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x", "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    subprocess.run(["/usr/bin/git", "-C", str(repo), "init", "-q"], check=True, env=env)
    (repo / "a.txt").write_text("a")
    subprocess.run(["/usr/bin/git", "-C", str(repo), "add", "a.txt"], check=True, env=env)
    subprocess.run(["/usr/bin/git", "-C", str(repo), "commit", "-q", "-m", "Ship widget"],
                   check=True, env=env)

    # The host's own session index, with one session spawned today.
    sdb = tmp_path / "store.sqlite"
    store.SessionStore(db_path=sdb)
    con = sqlite3.connect(sdb)
    con.execute("INSERT INTO sessions (session_id, agent_id, sub_mode, spawned, "
                "first_msg, entrypoint) VALUES (?,?,?,?,?,?)",
                ("sid-3", "ops", "chat", f"{TODAY}T11:30:00.000000",
                 "[cron:job1 Nightly] do the thing", "cli"))
    con.commit(); con.close()
    monkeypatch.setattr(store, "DB_PATH", sdb)
    monkeypatch.setattr(feed, "DB_PATH", tmp_path / "feed.sqlite")
    hostenv.reset_profile()
    yield tmp_path
    hostenv.reset_profile()


def test_the_day_merges_every_source_newest_first(machine):
    assert feed.refresh() == 2, "one commit and one finished run indexed"
    d = feed.day(TODAY)
    counts = {s["id"]: s["count"] for s in d["sources"]}
    assert counts == {"timeline": 1, "session": 1, "commit": 1, "run": 1,
                      "message": 1, "ping": 0}, counts
    assert all(s["ok"] for s in d["sources"])
    stamps = [e["ts"] for e in d["events"]]
    assert stamps == sorted(stamps, reverse=True)
    assert d["agents"] == ["ops"] and d["truncated"] is False
    assert d["signature"] and d["date"] == TODAY


def test_each_event_carries_its_source_shape(machine):
    feed.refresh()
    by = {e["source"]: e for e in feed.day(TODAY)["events"]}
    tl = by["timeline"]
    assert tl["title"] == "Fixed the leak" and tl["body"] == "• closed the connection"
    assert tl["seat"] == "ops/chat" and tl["kind"] == "direct" and tl["session_id"] == "sid-1"
    sess = by["session"]
    assert sess["title"] == "do the thing", "the cron marker is shed"
    assert sess["seat"] == "ops/chat" and sess["session_id"] == "sid-3"
    commit = by["commit"]
    assert commit["title"] == "Ship widget" and commit["meta"]["repo"] == "Widget"
    assert commit["agent"] == "ops", "the registry's owner, so the commit filters by seat"
    run = by["run"]
    assert run["title"] == "Nightly — ok" and run["agent"] == "ops"
    assert run["meta"]["duration_ms"] == 1200 and run["session_id"] == "sid-2"
    msg = by["message"]
    assert msg["title"].startswith("ops/chat → atlas/chat: Please rebuild")
    assert msg["kind"] == "task" and msg["agent"] == "ops"


def test_a_second_pass_costs_no_rows_and_a_change_costs_one(machine):
    feed.refresh()
    assert feed.refresh() == 0, "watermarks: nothing moved, nothing re-read"
    runs = machine / "scheduler" / "state" / "scheduler" / "runs" / "job1.jsonl"
    with runs.open("a") as fh:
        fh.write(json.dumps({"ts": int(time.time() * 1000), "jobId": "job1", "runId": "r2",
                             "action": "skipped", "status": "", "summary": ""}) + "\n")
    assert feed.refresh() == 1


def test_the_signature_moves_with_the_day(machine):
    before = feed.signature(TODAY)
    db = sqlite3.connect(machine / "Timeline" / "timeline.db")
    db.execute("INSERT INTO entries VALUES (2,?, '12:00','ops','chat','Another',"
               "'[]','','','','', ?, '', 'direct')", (TODAY, f"{TODAY}T12:00:00"))
    db.commit(); db.close()
    assert feed.signature(TODAY) != before


def test_a_missing_store_is_an_empty_source_not_a_failure(machine, monkeypatch):
    monkeypatch.setenv("JSTACK_TIMELINE_DIR", str(machine / "nowhere"))
    hostenv.reset_profile()
    d = feed.day(TODAY)
    counts = {s["id"]: (s["count"], s["ok"]) for s in d["sources"]}
    assert counts["timeline"] == (0, True) and counts["message"] == (0, True)


def test_the_day_is_read_only_on_every_foreign_store(machine):
    """The whole reason each store opens `mode=ro`: a read must not be able
    to become a write, whatever a producer does."""
    tl = machine / "Timeline" / "timeline.db"
    before = tl.stat().st_mtime_ns
    feed.day(TODAY)
    feed.signature(TODAY)
    assert tl.stat().st_mtime_ns == before


# ── contracts carried over from the retired lib/orgfeed suite ──

def _entry(machine, *, time="12:00", agent="ops", submode="chat",
           headline="did a thing", origin="direct", details=None, date=TODAY):
    db = sqlite3.connect(machine / "Timeline" / "timeline.db")
    db.execute(
        "INSERT INTO entries(date,time,agent,submode,headline,details,origin,"
        " created_at,session_id,pipeline_task,verdict,verdict_note,context)"
        " VALUES(?,?,?,?,?,?,?,?, '', '', '', '', '')",
        (date, time, agent, submode, headline, json.dumps(details or []),
         origin, f"{date}T{time}:00"))
    db.commit()
    db.close()


def test_the_day_excludes_neighbouring_days(machine):
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    _entry(machine, headline="yesterday's news", date=yesterday)
    titles = {e["title"] for e in feed.day(TODAY)["events"]}
    assert "Fixed the leak" in titles
    assert "yesterday's news" not in titles


def test_edges_of_the_local_day_are_included(machine):
    """00:00 and 23:59 are inside the day. An off-by-one here silently drops
    the first and last hours of every day the feed shows."""
    _entry(machine, time="00:00", headline="first minute")
    _entry(machine, time="23:59", headline="last minute")
    titles = {e["title"] for e in feed.day(TODAY)["events"]}
    assert {"first minute", "last minute"} <= titles


def test_origin_survives_as_the_kind(machine):
    """direct vs indirect is the split that keeps a busy day readable — it
    has to reach the client as a filterable facet, not get flattened."""
    _entry(machine, time="10:00", headline="cron drove this", origin="indirect")
    kinds = {e["title"]: e["kind"]
             for e in feed.day(TODAY)["events"] if e["source"] == "timeline"}
    assert kinds["cron drove this"] == "indirect"
    assert kinds["Fixed the leak"] == "direct"


def test_facets_are_computed_before_truncation(machine):
    """The filter menu exists FOR busy days. Building it from the served page
    would drop an agent exactly when filtering matters, and a hidden agent is
    indistinguishable from one that did nothing."""
    for i, agent in enumerate(["alpha", "beta", "gamma", "delta"]):
        _entry(machine, time=f"{i + 9:02d}:00", agent=agent, headline=f"h{i}")
    d = feed.day(TODAY, limit=1)
    assert len(d["events"]) == 1
    assert d["truncated"] is True
    assert {"alpha", "beta", "delta", "gamma"} <= set(d["agents"])
    assert d["agents"] == sorted(d["agents"])


def test_an_unreadable_source_reports_not_ok(machine, monkeypatch):
    """An empty feed and an unreadable store must not look identical: the
    reader would take 'nothing happened' from 'couldn't see'."""
    src = next(s for s in feed.SOURCES if s["id"] == "timeline")

    def boom(*_a, **_k):
        raise sqlite3.OperationalError("disk gone")

    monkeypatch.setitem(src, "fetch", boom)
    d = feed.day(TODAY)
    by = {s["id"]: s for s in d["sources"]}
    assert by["timeline"]["ok"] is False
    # and the rest of the feed still answers
    assert all(s["ok"] for s in d["sources"] if s["id"] != "timeline")


def test_the_signature_holds_when_nothing_moves(machine):
    assert feed.signature(TODAY) == feed.signature(TODAY)


def test_the_signature_survives_a_missing_store(machine, monkeypatch):
    """A failed probe must not raise into the stream loop — a dropped store
    would otherwise kill every connected client's feed."""
    monkeypatch.setenv("JSTACK_TIMELINE_DIR", str(machine / "nowhere"))
    hostenv.reset_profile()
    assert isinstance(feed.signature(TODAY), str)


def test_ro_of_a_missing_file_is_none(tmp_path):
    assert feed._ro(tmp_path / "absent.db") is None


def _fake_repo(machine, name):
    repo = machine / name
    (repo / ".git" / "logs").mkdir(parents=True)
    (repo / ".git" / "logs" / "HEAD").write_text("x")
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main")
    return repo


def _index_db():
    """The feed's own index with its schema in place — what `refresh()` does
    before it indexes, for tests that drive the indexers directly."""
    db = feed._conn()
    db.executescript(feed._SCHEMA)
    db.commit()
    return db


def test_the_commit_index_gates_on_the_ref_stamp(machine, monkeypatch):
    """The mtime gate is what keeps a fleet of repos off the request path. A
    repo whose refs have not moved must cost two stats, not a subprocess."""
    repo = _fake_repo(machine, "Gated")
    monkeypatch.setattr(hostenv, "repos", lambda: [repo])
    calls = []
    now = int(datetime.now().timestamp())

    def fake_run(cmd, **kw):
        calls.append(cmd)

        class R:
            returncode = 0
            stdout = f"abc123\x1f{now}\x1ftester\x1ffixed it\x1f\x1e"
        return R()

    monkeypatch.setattr(feed.subprocess, "run", fake_run)
    db = _index_db()
    try:
        assert feed.index_commits(db) == 1
        db.commit()
        assert len(calls) == 1
        # Unchanged refs: no second walk.
        assert feed.index_commits(db) == 0
        assert len(calls) == 1
    finally:
        db.close()
    rows = feed.day(TODAY)["events"]
    assert any(e["source"] == "commit" and e["title"] == "fixed it" for e in rows)


def test_the_commit_reindex_is_idempotent(machine, monkeypatch):
    """Same commit seen twice must not double a day's count — the id is the
    repo+sha, and a re-walk after a rebase or a stamp change must collapse."""
    repo = _fake_repo(machine, "Gated2")
    monkeypatch.setattr(hostenv, "repos", lambda: [repo])
    now = int(datetime.now().timestamp())

    class R:
        returncode = 0
        stdout = f"deadbeef\x1f{now}\x1fme\x1fonly once\x1f\x1e"

    monkeypatch.setattr(feed.subprocess, "run", lambda *a, **k: R())
    db = _index_db()
    try:
        feed.index_commits(db)
        db.execute("DELETE FROM watermarks")     # force the second walk
        db.commit()
        feed.index_commits(db)
        db.commit()
        n = db.execute("SELECT COUNT(*) FROM commits WHERE subject='only once'"
                       ).fetchone()[0]
    finally:
        db.close()
    assert n == 1


def test_the_runs_index_keeps_outcomes_not_starts(machine):
    """A run's *reason* comes from the session it spawned; the journal is here
    for how it ended. Indexing 'started' would double every wake."""
    runs = machine / "scheduler" / "state" / "scheduler" / "runs"
    ms = int(time.time() * 1000)
    (runs / "job9.jsonl").write_text(
        json.dumps({"ts": ms, "jobId": "job9", "runId": "r9",
                    "action": "started", "sessionId": "s9"}) + "\n"
        + json.dumps({"ts": ms, "jobId": "job9", "runId": "r9",
                      "action": "finished", "status": "ok", "sessionId": "s9",
                      "summary": "all good", "durationMs": 3, "exitCode": 0}) + "\n")
    db = _index_db()
    try:
        feed.index_runs(db)
        db.commit()
        actions = [r["action"] for r in db.execute("SELECT action FROM runs")]
    finally:
        db.close()
    assert actions and set(actions) == {"finished"}


def test_an_orphan_job_reads_as_unknown_not_blank(machine):
    """Deleted jobs and delete_after_run one-shots leave run rows with nothing
    to join. That is a real state and must be labelled, never rendered blank
    as if the run had no identity."""
    runs = machine / "scheduler" / "state" / "scheduler" / "runs"
    ms = int(time.time() * 1000)
    (runs / "gone.jsonl").write_text(json.dumps(
        {"ts": ms, "jobId": "gone", "runId": "r9", "action": "finished",
         "status": "ok"}) + "\n")
    db = _index_db()
    try:
        feed.index_runs(db)
        db.commit()
    finally:
        db.close()
    assert any(e["source"] == "run" and "unknown job" in e["title"]
               for e in feed.day(TODAY)["events"])


def test_every_source_declares_a_label_and_glyph():
    """The client renders its filter chips from this, so a source added
    without them would reach every device as an unlabelled control."""
    for src in feed.SOURCES:
        assert src["id"] and src["label"] and src["glyph"]
        assert callable(src["fetch"])


def test_the_source_roster_rides_the_payload(machine):
    d = feed.day(TODAY)
    assert [s["id"] for s in d["sources"]] == [s["id"] for s in feed.SOURCES]
    assert all({"id", "label", "glyph", "count", "ok"} <= set(s)
               for s in d["sources"])


def test_one_line_collapses_never_wraps():
    assert feed._one_line("a\n\nb   c") == "a b c"
    assert feed._one_line("x" * 200).endswith("…")
    assert len(feed._one_line("x" * 200)) <= 140
