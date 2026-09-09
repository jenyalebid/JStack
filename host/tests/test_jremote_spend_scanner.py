"""The package's spend scanner — transcripts to a day's cost, by job.

Pins the arithmetic the Spend screen trusts: one API turn written as several
JSONL lines is billed once (by `message.id`), a subagent's tokens belong to
its parent, a scheduled run and a typed chat land in different buckets off
the first user message, the seat is read through the profile, and a host's
own category file replaces the built-in map wholesale.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from jstack_host import hostenv, spend


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _user(text: str) -> str:
    return json.dumps({"type": "user", "timestamp": _now_iso(),
                       "message": {"role": "user", "content": text}})


def _assistant(mid: str, inp=100, cw=0, cr=2000, out=10) -> str:
    return json.dumps({"type": "assistant", "timestamp": _now_iso(),
                       "message": {"id": mid, "role": "assistant",
                                   "content": [{"type": "text", "text": "ok"}],
                                   "usage": {"input_tokens": inp,
                                             "cache_creation_input_tokens": cw,
                                             "cache_read_input_tokens": cr,
                                             "output_tokens": out}}})


@pytest.fixture
def projects(tmp_path, monkeypatch):
    agents = tmp_path / "Agents"
    (agents / "Ops" / "chat").mkdir(parents=True)
    monkeypatch.setenv("JREMOTE_HOST_PROFILE", "default")
    monkeypatch.setenv("JREMOTE_INSTANCE_ROOT", str(agents))
    monkeypatch.delenv("JSTACK_AGENT_REGISTRY", raising=False)
    hostenv.reset_profile()
    monkeypatch.setattr(spend, "CACHE", tmp_path / "cache.json")
    monkeypatch.setattr(spend, "CONFIG", tmp_path / "token_categories.json")

    key = str(agents / "Ops" / "chat").replace("/", "-")
    pdir = tmp_path / "projects" / key
    pdir.mkdir(parents=True)
    # A chat: one turn written as three lines (thinking, text, tool_use) that
    # all repeat the same message id, then a second turn.
    (pdir / "chat-1.jsonl").write_text("\n".join([
        _user("hello there"),
        _assistant("msg_1"), _assistant("msg_1"), _assistant("msg_1"),
        _assistant("msg_2", inp=50, cr=3000, out=20),
    ]) + "\n")
    # Its subagent.
    (pdir / "chat-1" / "subagents").mkdir(parents=True)
    (pdir / "chat-1" / "subagents" / "agent-a.jsonl").write_text(
        _assistant("sub_1", inp=7, cr=0, out=3) + "\n")
    # A scheduled run — the spawner's marker is the first user line.
    (pdir / "run-1.jsonl").write_text("\n".join([
        _user("[cron:job1 Nightly] do the thing"),
        _assistant("msg_9", inp=500, cr=0, out=500),
    ]) + "\n")
    yield tmp_path / "projects"
    hostenv.reset_profile()


def test_a_turn_is_billed_once_and_subagents_belong_to_the_parent(projects):
    recs = {r["session"]: r for r in spend.scan(use_cache=False, projects=projects)}
    chat = recs["chat-1"]
    # msg_1 once (100+0+2000+10) + msg_2 (50+0+3000+20) + subagent (7+0+0+3)
    assert chat["total"] == 2110 + 3070 + 10, chat
    assert chat["turns"] == 2 and chat["n_sub"] == 1 and chat["sub_tokens"] == 10
    assert chat["output"] == 33
    assert chat["agent"] == "ops/chat", "the seat, through the profile"
    assert chat["category"] == "chat" and chat["kind"] == "interactive"


def test_the_spawn_marker_files_a_run_as_autonomous(projects):
    recs = {r["session"]: r for r in spend.scan(use_cache=False, projects=projects)}
    run = recs["run-1"]
    assert run["category"] == "scheduled" and run["kind"] == "autonomous"
    assert run["first"].startswith("[cron:job1")


def test_the_day_breaks_out_by_category(projects):
    recs = spend.scan(use_cache=False, projects=projects)
    d = spend.daily(spend.today(), recs)
    assert d["sessions"] == 2 and d["total"] == 5190 + 1000
    cats = {c["category"]: c for c in d["categories"]}
    assert set(cats) == {"chat", "scheduled"}
    assert cats["chat"]["sessions"] == 1 and cats["chat"]["agents"][0]["agent"] == "ops/chat"
    assert round(cats["chat"]["pct"] + cats["scheduled"]["pct"]) == 100
    assert d["autonomous"] == 1000 and d["catch_all_sessions"] == 1
    assert d["autonomous_pct"] == round(100 * 1000 / 6190, 1)
    s = spend.series(3, recs)
    assert [x["day"] for x in s][-1] == spend.today() and s[-1]["total"] == d["total"]
    top = spend.top_sessions(spend.today(), records=recs)
    assert top[0]["session"] == "chat-1"


def test_the_cache_is_keyed_on_the_file_not_the_clock(projects, tmp_path):
    first = spend.scan(projects=projects)
    assert (tmp_path / "cache.json").exists()
    again = spend.scan(projects=projects)
    assert again == first
    with (projects.glob("*/run-1.jsonl").__next__()).open("a") as fh:
        fh.write(_assistant("msg_10", inp=5, cr=0, out=5) + "\n")
    changed = {r["session"]: r for r in spend.scan(projects=projects)}
    assert changed["run-1"]["total"] == 1010


def test_a_hosts_own_category_file_replaces_the_map(projects, tmp_path):
    (tmp_path / "token_categories.json").write_text(json.dumps({"rules": [
        {"id": "nightly", "label": "Nightly", "kind": "autonomous",
         "signature": r"^\[cron:job1"},
        {"id": "other", "label": "Other", "kind": "interactive",
         "signature": ".*", "catch_all": True},
    ]}))
    recs = {r["session"]: r for r in spend.scan(use_cache=False, projects=projects)}
    assert recs["run-1"]["category"] == "nightly" and recs["chat-1"]["category"] == "other"


def test_a_broken_category_file_keeps_the_built_in_map(projects, tmp_path):
    (tmp_path / "token_categories.json").write_text("{nope")
    recs = {r["session"]: r for r in spend.scan(use_cache=False, projects=projects)}
    assert recs["run-1"]["category"] == "scheduled"
