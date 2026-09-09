"""The package's allowance reader — the Usage bars off Claude Code's own cache.

Pins the contract the app decodes: a provider never sampled is `null` (never a
zero meter), the CLI's cached reading is served with its real age and marked
stale rather than dropped, a newer recorded sample wins over an older cache,
a refusal is its own fact and outranks every window, and the scheduler's
`rate_limited` run becomes one refusal, not one per read.
"""

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from jstack_host import allowance


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(allowance, "STATE", tmp_path / "allowance.json")
    monkeypatch.setattr(allowance, "LOCK", tmp_path / ".lock")
    monkeypatch.setattr(allowance, "CLI_CONFIG", tmp_path / "claude.json")
    return tmp_path


def _cache(path, five=6, week=1, age_s=10):
    fetched = int((time.time() - age_s) * 1000)
    reset = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    path.write_text(json.dumps({
        "hasVisitedExtraUsage": True,
        "cachedUsageUtilization": {
            "fetchedAtMs": fetched, "accountUuid": "x",
            "utilization": {
                "five_hour": {"utilization": five, "resets_at": reset},
                "seven_day": {"utilization": week, "resets_at": reset},
            },
        },
    }))


def test_nothing_sampled_is_null_never_zero(state):
    d = allowance.read()
    assert d["providers"] == {"claude": None, "codex": None}, d
    assert allowance.available() is False


def test_the_cli_cache_is_a_reading(state):
    _cache(state / "claude.json", five=8, week=56)
    assert allowance.available() is True
    p = allowance.read()["providers"]["claude"]
    assert p["source"] == "cli-cache" and p["label"] == "Claude"
    assert [(w["id"], w["label"], w["pct"], w["band"]) for w in p["windows"]] == [
        ("five_hour", "Session (5h)", 8.0, None),
        ("seven_day", "Week", 56.0, None)]
    assert p["stale"] is False and 0 <= p["age_seconds"] < 60
    assert p["refusal"] is None and p["worst_band"] is None


def test_an_old_reading_is_served_stale_not_dropped(state):
    _cache(state / "claude.json", five=61, age_s=6 * 3600)
    p = allowance.read()["providers"]["claude"]
    assert p["stale"] is True and p["age_seconds"] > 6 * 3600 - 5
    assert p["windows"][0]["pct"] == 61.0


def test_bands_follow_the_thresholds(state):
    _cache(state / "claude.json", five=97, week=100)
    p = allowance.read()["providers"]["claude"]
    assert [w["band"] for w in p["windows"]] == ["critical", "capped"]
    assert p["worst_band"] == "capped"
    _cache(state / "claude.json", five=80, week=10)
    assert allowance.read()["providers"]["claude"]["windows"][0]["band"] == "warn"


def test_the_newest_sample_wins(state):
    _cache(state / "claude.json", five=6, age_s=600)
    allowance.record("claude", [{"id": "five_hour", "label": "Session (5h)", "pct": 40}],
                     source="statusline", sampled_at=time.time() - 300)
    p = allowance.read()["providers"]["claude"]
    assert p["source"] == "statusline" and p["windows"][0]["pct"] == 40.0
    _cache(state / "claude.json", five=9, age_s=1)
    p = allowance.read()["providers"]["claude"]
    assert p["source"] == "cli-cache" and p["windows"][0]["pct"] == 9.0


def test_a_refusal_outranks_every_window_and_survives_a_fresh_cache(state):
    _cache(state / "claude.json", five=3)
    reset = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
    allowance.note_refusal("claude", resets_at=reset, detail="hit your limit")
    p = allowance.read()["providers"]["claude"]
    assert p["refusal"]["active"] is True and p["worst_band"] == "refused"
    assert p["windows"][0]["pct"] == 3.0, "the cache reading still rides along"
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    allowance.note_refusal("claude", resets_at=past)
    assert allowance.read()["providers"]["claude"]["refusal"]["active"] is False


def test_the_scheduler_journal_is_a_headless_probe(state, tmp_path):
    st = tmp_path / "state.json"
    ran = int(time.time() * 1000)
    st.write_text(json.dumps({"job-a": {"last_status": "rate_limited",
                                        "last_run_at_ms": ran,
                                        "next_run_at_ms": ran + 3_600_000,
                                        "last_error": "rate_limited"},
                              "job-b": {"last_status": "ok", "last_run_at_ms": ran}}))
    assert allowance.sync_from_scheduler(st) is True
    assert allowance.sync_from_scheduler(st) is False, "the watermark holds"
    p = allowance.read()["providers"]["claude"]
    assert p["refusal"]["active"] is True and "rate-limited" in p["refusal"]["detail"]
    wrapped = tmp_path / "wrapped.json"
    wrapped.write_text(json.dumps({"jobs": {"job-c": {"last_status": "rate_limited",
                                                      "last_run_at_ms": ran + 5}}}))
    assert allowance.sync_from_scheduler(wrapped) is True, "either vintage of the file"


def test_an_unknown_source_is_refused(state):
    with pytest.raises(ValueError):
        allowance.record("claude", [], source="guess")


def test_a_cache_without_a_reading_is_absence(state):
    (state / "claude.json").write_text(json.dumps({"cachedUsageUtilization": {"utilization": {}}}))
    assert allowance.cli_cache_sample() is None
    (state / "claude.json").write_text("not json")
    assert allowance.cli_cache_sample() is None
