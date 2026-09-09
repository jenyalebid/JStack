"""Account allowance — how much of each provider's window is spent. The
app's Usage bars.

This is NOT token accounting. `spend.py` answers "what did today cost" by
summing transcripts. This answers a different question with a different
source: **how close is the account to being cut off**, which is a percentage
of a provider-side allowance we do not compute and cannot derive from our own
transcripts. The two never merge — one is spend, one is headroom, and a
number that looked like both would be trusted as neither.

The package's own reader, the standalone counterpart of the dashboard's
`lib/usage_caps` (which the router prefers where it imports), producing the
same payload the app already decodes.

## Where the numbers come from

Two tiers, and a host has the first one the moment Claude Code is installed:

1. **The CLI's own cache.** Claude Code fetches the account's utilization for
   its `/usage` screen and keeps the answer in `~/.claude.json`
   (`cachedUsageUtilization`: `five_hour` and `seven_day`, each a percentage
   and a reset clock, stamped when fetched). Every interactive session
   refreshes it. Free, no auth, no hook to wire — the reason a fresh install
   shows bars without anyone configuring anything.
2. **A recorded sample.** `record()` stores what a sampler saw — a status-line
   hook handed `rate_limits` on every render, a poll of the provider's usage
   endpoint. Whichever tier's sample is newest is the one served.

Refusals are a third fact, deliberately not merged with either: the provider
actually turned a request away. JStack's scheduler already sees that from a
HEADLESS run — it parses "You've hit your limit · resets 9:40am" out of a
run's output and scores it `rate_limited` — so `sync_from_scheduler()` reads
its state as a free probe of exactly the sessions the cache cannot see.

## Staleness is a first-class answer

A sample older than `STALE_AFTER` is reported `stale: true` with its age. It
is NOT dropped and NOT rounded to a fresh-looking figure. An overnight stretch
legitimately has no interactive session in it, so the meter going stale is
the honest reading — "last seen 6h ago at 61%" is actionable, "61%" alone is a
lie about when it was true.

A provider that has never reported is **absent**, not zero: `read()` returns
`None` for it and the app draws "not connected". Zeroing an unsampled
provider would paint an unknown as healthy, which is the one answer a
headroom meter exists to prevent.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import hostenv

STATE = hostenv.state_dir() / "allowance.json"
LOCK = hostenv.state_dir() / ".allowance.lock"
CLI_CONFIG = Path.home() / ".claude.json"

#: Providers we know how to render. A provider listed here but never sampled
#: reads as None (not connected) — never as zero.
PROVIDERS = {
    "claude": "Claude",
    "codex": "Codex",
}

#: A sample older than this no longer describes now.
STALE_AFTER = 900
#: A refusal with no parseable reset clock still blocks for a while.
REFUSAL_ASSUMED_SECONDS = 2700
WARN_PCT = 80
CRITICAL_PCT = 95
SOURCES = ("statusline", "poll", "refusal", "rollout", "cli-cache")

#: Claude Code's window ids, and what the app calls them. Order is fixed so
#: the readout never reshuffles between fetches.
_CLI_WINDOWS = (("five_hour", "Session (5h)"), ("seven_day", "Week"))

#: Severity ladder. `capped` is a window MEASURED at 100; `refused` is the
#: provider actually turning a request away.
_BAND_ORDER = {None: 0, "warn": 1, "critical": 2, "capped": 3, "refused": 4}


# ---------------------------------------------------------------- state io

def _now() -> float:
    return time.time()


def _read_raw() -> dict:
    try:
        d = json.loads(STATE.read_text())
    except (OSError, json.JSONDecodeError):
        d = {}
    d.setdefault("providers", {})
    d.setdefault("scheduler_watermark_ms", 0)
    return d


def _write_raw(d: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, indent=2, sort_keys=True))
    os.replace(tmp, STATE)


class _Lock:
    """Cross-process lock. Several samplers may write concurrently — one per
    live session, every render — so read-modify-write must not interleave."""

    def __enter__(self):
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(LOCK, "w")
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()
        return False


def _provider_slot(d: dict, provider: str) -> dict:
    slot = d["providers"].setdefault(provider, {})
    slot["label"] = PROVIDERS.get(provider, provider)
    slot.setdefault("windows", [])
    slot.setdefault("refusal", None)
    return slot


# ---------------------------------------------------------------- recording

def _norm_window(w: dict) -> dict:
    pct = w.get("pct")
    if pct is not None:
        pct = max(0.0, min(100.0, float(pct)))
    return {
        "id": str(w["id"]),
        "label": str(w.get("label") or w["id"]),
        "pct": pct,
        "resets_at": w.get("resets_at"),
    }


def record(provider: str, windows: list[dict], source: str = "statusline",
           sampled_at: float | None = None) -> None:
    """Store a measured sample for `provider`.

    `windows` is a list of `{id, label, pct, resets_at}`. Whatever a provider
    calls its windows is the provider's business — nothing here reads an id.

    A recorded sample does NOT clear a standing refusal. The two are different
    observations and the refusal expires on its own clock.
    """
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r} (expected one of {SOURCES})")
    ts = sampled_at if sampled_at is not None else _now()
    norm = [_norm_window(w) for w in windows]
    with _Lock():
        d = _read_raw()
        slot = _provider_slot(d, provider)
        slot["source"] = source
        slot["sampled_at"] = ts
        slot["windows"] = norm
        _write_raw(d)


def note_refusal(provider: str, *, resets_at: str | None = None,
                 detail: str = "", at: float | None = None) -> None:
    """Record that the provider actually turned a request away.

    Provider-level and percentage-free by design. Merges into the existing
    sample rather than replacing it, so a refusal does not erase what we last
    knew about the windows.
    """
    ts = at if at is not None else _now()
    with _Lock():
        d = _read_raw()
        slot = _provider_slot(d, provider)
        prev = slot.get("refusal") or {}
        # Keep the earliest observation of a refusal that is still the same
        # outage: the reset clock identifies it, and the first sighting is
        # when the outage actually began.
        same = prev.get("resets_at") == resets_at and _refusal_active(prev)
        slot["refusal"] = {
            "at": prev.get("at") if same else ts,
            "last_seen": ts,
            "resets_at": resets_at,
            "detail": detail[:300],
        }
        slot.setdefault("source", "refusal")
        slot.setdefault("sampled_at", ts)
        _write_raw(d)


# ---------------------------------------------------------------- the CLI's cache

def cli_cache_sample(path: Path | None = None) -> dict | None:
    """Claude Code's own reading, as a provider slot — or None when the CLI
    has never fetched one on this machine.

    `~/.claude.json` is the CLI's file and this is a read of it, nothing
    more: the key, the window names and the stamp are whatever it wrote. A
    file that is missing, unreadable, or carries no utilization block answers
    None, which `read()` renders as "not connected" — never as zero.
    """
    path = path or CLI_CONFIG
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    cached = raw.get("cachedUsageUtilization") if isinstance(raw, dict) else None
    if not isinstance(cached, dict):
        return None
    util = cached.get("utilization")
    if not isinstance(util, dict):
        return None
    windows = []
    for wid, label in _CLI_WINDOWS:
        w = util.get(wid)
        if not isinstance(w, dict):
            continue
        pct = w.get("utilization")
        if pct is None:
            continue
        try:
            pct = float(pct)
        except (TypeError, ValueError):
            continue
        windows.append({"id": wid, "label": label, "pct": pct,
                        "resets_at": w.get("resets_at")})
    if not windows:
        return None
    fetched = cached.get("fetchedAtMs")
    try:
        sampled_at = float(fetched) / 1000.0
    except (TypeError, ValueError):
        sampled_at = 0.0
    return {"label": PROVIDERS["claude"], "source": "cli-cache",
            "sampled_at": sampled_at,
            "windows": [_norm_window(w) for w in windows], "refusal": None}


# ---------------------------------------------------------------- reading

def _parse_iso(s) -> float | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _refusal_active(refusal: dict | None) -> bool:
    """Is the refusal still presumed to be blocking? Decided by the clock,
    never by "did something newer arrive"."""
    if not refusal:
        return False
    reset = _parse_iso(refusal.get("resets_at"))
    if reset is not None:
        return _now() < reset
    return _now() - float(refusal.get("at") or 0) < REFUSAL_ASSUMED_SECONDS


def _window_band(w: dict) -> str | None:
    pct = w.get("pct")
    if pct is None:
        return None
    if pct >= 100:
        return "capped"
    if pct >= CRITICAL_PCT:
        return "critical"
    if pct >= WARN_PCT:
        return "warn"
    return None


def _worst(bands: list) -> str | None:
    return max(bands, key=lambda b: _BAND_ORDER.get(b, 0)) if bands else None


def _merged_providers() -> dict:
    """Recorded slots, with the CLI's cache standing in for Claude wherever it
    is the newer reading. A refusal recorded against Claude survives either
    way — it is a different fact from the windows."""
    d = _read_raw()
    providers = dict(d["providers"])
    cli = cli_cache_sample()
    if cli is not None:
        have = providers.get("claude") or {}
        # A slot holding only a refusal has no windows to be newer than: its
        # stamp is the outage's, not a reading's, and the cache is the only
        # reading there is.
        recorded = have.get("sampled_at") if have.get("windows") else None
        if float(cli["sampled_at"]) >= float(recorded or 0):
            merged = dict(have, **cli)
            merged["refusal"] = have.get("refusal")
            providers["claude"] = merged
    return providers


def read() -> dict:
    """Full state, with staleness and refusal expiry resolved at read time.

    Every provider in `PROVIDERS` appears. One never sampled is `None` — the
    caller must render "not connected", never a zero meter."""
    providers = _merged_providers()
    now = _now()
    out: dict = {"generated_at": datetime.now(timezone.utc).isoformat(),
                 "stale_after_seconds": STALE_AFTER,
                 "thresholds": {"warn": WARN_PCT, "critical": CRITICAL_PCT},
                 "providers": {}}
    for pid, label in PROVIDERS.items():
        p = providers.get(pid)
        if not p or (not p.get("windows") and not p.get("refusal")):
            out["providers"][pid] = None
            continue
        age = now - float(p.get("sampled_at") or 0)
        windows = [dict(w, band=_window_band(w)) for w in p.get("windows") or []]
        refusal = p.get("refusal")
        active = _refusal_active(refusal)
        bands = [w.get("band") for w in windows]
        if active:
            bands.append("refused")
        out["providers"][pid] = {
            "label": p.get("label") or label,
            "source": p.get("source"),
            "sampled_at": p.get("sampled_at"),
            "age_seconds": round(age, 1),
            "stale": age > STALE_AFTER,
            "windows": windows,
            "refusal": (dict(refusal, active=active) if refusal else None),
            "worst_band": _worst(bands),
        }
    return out


def available() -> bool:
    """Can this host say anything at all — a sample on file, or a CLI cache
    to read. Nothing on either is the one case the screen is honest to hide."""
    if cli_cache_sample() is not None:
        return True
    return any(p and (p.get("windows") or p.get("refusal"))
               for p in _read_raw()["providers"].values())


# ------------------------------------------------- headless tier: scheduler

def _reset_from_next_run(state: dict) -> str | None:
    ms = state.get("next_run_at_ms")
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat() \
            if ms else None
    except (TypeError, ValueError, OverflowError):
        return None


def sync_from_scheduler(state_path: Path | None = None) -> bool:
    """Turn the scheduler's `rate_limited` runs into a refusal. True if one
    new outage was folded in.

    JStack's scheduler is the one component that already sees a cap from a
    HEADLESS session. Its per-job state carries `last_status` and
    `last_run_at_ms`; a watermark on the latter keeps one outage from being
    re-recorded on every read. The state file is either a map of jobs or a
    `{"jobs": {...}}` wrapper, depending on the scheduler's vintage.
    """
    path = state_path or (hostenv.scheduler_dir() / "state" / "scheduler" / "state.json")
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    jobs = raw.get("jobs") if isinstance(raw, dict) and isinstance(raw.get("jobs"), dict) \
        else raw
    if not isinstance(jobs, dict):
        return False
    with _Lock():
        mark = int(_read_raw().get("scheduler_watermark_ms") or 0)
    newest, hit = mark, None
    for st in jobs.values():
        if not isinstance(st, dict) or st.get("last_status") != "rate_limited":
            continue
        ran = int(st.get("last_run_at_ms") or 0)
        if ran > newest:
            newest, hit = ran, st
    if hit is None:
        return False
    note_refusal("claude", resets_at=_reset_from_next_run(hit),
                 detail=f"scheduler run rate-limited (last_error={hit.get('last_error')})",
                 at=newest / 1000)
    with _Lock():
        d = _read_raw()
        d["scheduler_watermark_ms"] = newest
        _write_raw(d)
    return True
