"""Tick loop: due jobs, misfire/catch-up, concurrency, schedule advance.

next_run_at is persisted (atomic state.json write) BEFORE spawning, so a
daemon restart immediately after a fire cannot double-fire. The next
occurrence always advances from the schedule (RRULE after the fired
occurrence), never from now.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timezone

from . import config, journal, occurrences, registry, runner


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


# occurrences enumerated per misfire resolution — bounds a pathological
# backlog (e.g. minutely job after a month-long outage)
_MAX_MISSED = 1000

# Rate-limit defer: when a run only hit the Claude session limit, the engine
# reschedules it to shortly after the stated reset instead of hard-failing.
# Buffer so the reset has definitely landed before we re-spawn.
_RATE_LIMIT_BUFFER_SECONDS = 300
# Backstop against all-day hammering if resets keep arriving already-exhausted:
# after this many consecutive rate-limit defers, stop pinning to reset and let
# the normal schedule take over (the next validator will surface a real gap).
_MAX_RATE_LIMIT_DEFERS = 6
# When the run WAS rate-limited but no reset time could be read out of its
# output, retry after this instead of surrendering the slot. An unparsed reset
# used to mean "the normal schedule stands" — on a daily job that is not a
# retry, it is skipping the entire day, which is how five accounts' control
# wakes died at 08:35 on 2026-07-28 and nothing published until someone noticed.
# A blind retry can be early (the limit is still up, we get rate-limited again
# and defer once more, capped); surrendering the day cannot be recovered at all.
_RATE_LIMIT_BLIND_RETRY_SECONDS = 2700


def _schedule_fp(job: dict) -> str:
    canonical = json.dumps(job.get("schedule") or {}, sort_keys=True)
    return hashlib.md5(canonical.encode()).hexdigest()


class Engine:
    def __init__(self, now_fn=None, spawn_fn=None):
        self._now = now_fn or (lambda: datetime.now(timezone.utc))
        self._spawn_fn = spawn_fn or self._spawn_run
        self.lock = threading.RLock()
        self.runs: dict[str, object] = {}
        self.state: dict = journal.load_state()
        self.registry: "dict|None" = None
        self._registry_mtime: "float|None" = None
        self._queued: dict[str, datetime] = {}  # job_id -> queued occurrence (depth 1)
        self.started_at = time.time()
        self._stop = threading.Event()
        self._last_sweep_day: "str|None" = None

    # ---------------------------------------------------------------- registry

    def _reload_registry_if_changed(self) -> None:
        try:
            mtime = config.SCHEDULE_FILE.stat().st_mtime
        except OSError:
            mtime = None
        if self.registry is None or mtime != self._registry_mtime:
            self.registry = registry.load_registry()
            self._registry_mtime = mtime

    def reload(self) -> None:
        with self.lock:
            self._registry_mtime = None
            self._reload_registry_if_changed()

    def jobs(self) -> list[dict]:
        return (self.registry or {}).get("jobs", [])

    def defaults(self) -> dict:
        merged = dict(config.BUILTIN_DEFAULTS)
        for k, v in ((self.registry or {}).get("defaults") or {}).items():
            if v is not None:
                merged[k] = v
        return merged

    def categories(self) -> dict:
        """Run-category settings map (the job → category → default middle layer)."""
        return (self.registry or {}).get("categories") or {}

    def _job_by_id(self, job_id: str) -> "dict|None":
        for job in self.jobs():
            if job.get("id") == job_id:
                return job
        return None

    # ------------------------------------------------------------------- tick

    def tick(self) -> None:
        with self.lock:
            self._reload_registry_if_changed()
            defaults = self.defaults()
            now = self._now()
            now_ms = _ms(now)
            dirty = False
            fire_list: list[tuple[datetime, dict, dict]] = []

            for job in self.jobs():
                jid = job["id"]
                st = self.state.setdefault(jid, {})
                if not job.get("enabled", True):
                    # drop (not None-out) so a later re-enable re-anchors from
                    # then-now instead of triggering catch-up over the gap
                    if "next_run_at_ms" in st:
                        del st["next_run_at_ms"]
                        dirty = True
                    continue
                eff = registry.effective(job, defaults, self.categories())
                fp = _schedule_fp(job)
                if st.get("schedule_fp") != fp:
                    if "schedule_fp" in st and "next_run_at_ms" in st:
                        # schedule definition changed — the persisted anchor
                        # belongs to the old schedule; re-anchor from now
                        # (no fire at the old time, no catch-up over the edit)
                        del st["next_run_at_ms"]
                        self._queued.pop(jid, None)
                    st["schedule_fp"] = fp
                    dirty = True
                if "next_run_at_ms" not in st:
                    st["next_run_at_ms"] = self._initial_next_run(job, now)
                    dirty = True
                nra = st.get("next_run_at_ms")
                if nra is None:
                    continue
                if nra <= now_ms:
                    target, skipped = self._resolve_due(job, eff, nra, now)
                    for occ in skipped:
                        journal.append(jid, journal.skipped_record(
                            job_id=jid, run_at_ms=_ms(occ), reason="misfire"))
                    if skipped:
                        # A dropped occurrence is a MISSED RUN, and the health
                        # surface reads job state, not the journal — so a
                        # journal-only skip is invisible. An occurrence that
                        # dies against the concurrency cap minutes past its
                        # grace means the job's work never happened, while every
                        # status view still reads `ok` from the previous day.
                        # State carries it now; the next successful run clears
                        # it like any other error.
                        st["last_status"] = "misfire"
                        st["last_error"] = (
                            f"missed occurrence {_ms(skipped[-1])} "
                            f"(past catch-up grace)")
                        st["consecutive_errors"] = int(
                            st.get("consecutive_errors") or 0) + len(skipped)
                        dirty = True
                    if target is None:
                        self._advance(job, st, after=now)
                        dirty = True
                    else:
                        fire_list.append((target, job, eff))

            # queue-policy releases (depth 1) — fire once the active run ends;
            # schedule was already advanced when the occurrence was queued
            released: list[tuple[datetime, dict, dict]] = []
            for jid, when in list(self._queued.items()):
                if self._active_run_count(jid) == 0:
                    job = self._job_by_id(jid)
                    del self._queued[jid]
                    if job and job.get("enabled", True):
                        released.append((when, job, registry.effective(job, defaults, self.categories())))

            if dirty:
                journal.save_state(self.state)

            fire_list.sort(key=lambda t: t[0])  # FIFO by scheduled time
            for scheduled_for, job, eff in fire_list:
                self._try_fire(job, eff, scheduled_for, defaults)
            for scheduled_for, job, eff in released:
                self._try_fire(job, eff, scheduled_for, defaults, advance=False)

            self._sweep_logs(now)

    def _initial_next_run(self, job: dict, now: datetime) -> "int|None":
        sched = job.get("schedule") or {}
        if sched.get("kind") == "once":
            # a just-past one-shot must still be visible to misfire logic
            return _ms(occurrences.parse_dtstart(sched))
        fires = occurrences.next_fires(job, 1, after=now)
        return _ms(fires[0]) if fires else None

    def _resolve_due(self, job: dict, eff: dict, nra_ms: int, now: datetime):
        """Return (occurrence_to_fire_or_None, occurrences_to_journal_skipped)."""
        tz = occurrences.job_tz(job)
        occs = [datetime.fromtimestamp(nra_ms / 1000, tz=tz)]
        for _ in range(_MAX_MISSED):
            nxt = occurrences.next_fires(job, 1, after=occs[-1])
            if not nxt or nxt[0] > now:
                break
            occs.append(nxt[0])
        target, older = occs[-1], occs[:-1]
        late_s = (now - target).total_seconds()
        if late_s <= config.MISFIRE_THRESHOLD_SECONDS:
            return target, older  # on-time fire; anything older was a miss
        grace = eff.get("catch_up_grace_seconds") or self.defaults().get("catch_up_grace_seconds")
        if eff.get("catch_up", True) and late_s <= grace:
            return target, older  # catch up: fire the most recent miss ONCE
        return None, occs  # skip all

    def _advance(self, job: dict, st: dict, after: datetime) -> None:
        fires = occurrences.next_fires(job, 1, after=after)
        new_ms = _ms(fires[0]) if fires else None
        cur = st.get("next_run_at_ms")
        if new_ms is not None and cur is not None and new_ms < cur:
            return  # never regress the schedule
        st["next_run_at_ms"] = new_ms

    # ------------------------------------------------------------------- fire

    def _active_run_count(self, job_id: str) -> int:
        return sum(1 for r in self.runs.values() if r.job_id == job_id)

    def _try_fire(self, job: dict, eff: dict, scheduled_for: datetime,
                  defaults: dict, retry_of: "str|None" = None,
                  advance: bool = True) -> None:
        jid = job["id"]
        st = self.state.setdefault(jid, {})
        policy = eff.get("concurrency", "skip")
        if retry_of is None and self._active_run_count(jid) > 0 and policy != "parallel":
            if policy == "queue" and jid not in self._queued:
                self._queued[jid] = scheduled_for
            else:  # skip, or queue already holding one (depth 1)
                journal.append(jid, journal.skipped_record(
                    job_id=jid, run_at_ms=_ms(scheduled_for), reason="concurrency-skip"))
            if advance:
                self._advance(job, st, after=scheduled_for)
                journal.save_state(self.state)
            return
        if len(self.runs) >= int(defaults.get("max_concurrent_runs", 4)):
            # global cap: schedule NOT advanced — stays due, retried FIFO next tick
            return
        if advance:
            self._advance(job, st, after=scheduled_for)
        journal.save_state(self.state)  # persist BEFORE spawn — no double-fire
        try:
            run = self._spawn_fn(job, eff, scheduled_for, retry_of)
        except Exception as e:
            _log(f"spawn failed for {jid}: {e!r}")
            self._spawn_failure(job, eff, scheduled_for, str(e), retry_of, defaults)
            return
        self.runs[run.run_id] = run
        st.setdefault("active_runs", []).append({
            "run_id": run.run_id,
            "session_id": run.session_id,
            "pid": run.pid,
            "pgid": run.pgid,
            "spawned_at_ms": run.spawned_at_ms,
            "scheduled_for_ms": run.scheduled_for_ms,
            "workspace": str(run.workspace) if getattr(run, "workspace", None) else None,
        })
        journal.save_state(self.state)
        _log(f"fired {jid} ({job.get('name', '')}) run={run.run_id} pid={run.pid}")

    def _spawn_run(self, job: dict, eff: dict, scheduled_for: datetime,
                   retry_of: "str|None"):
        run = runner.Run(job=eff, defaults=self.defaults(), scheduled_for=scheduled_for,
                         on_finish=self._on_run_finish, retry_of=retry_of)
        return run.spawn()

    def _spawn_failure(self, job: dict, eff: dict, scheduled_for: datetime,
                       error: str, retry_of: "str|None", defaults: dict) -> None:
        jid = job["id"]
        st = self.state.setdefault(jid, {})
        failed_run_id = f"spawnfail-{int(time.time() * 1000)}"
        now_ms = _ms(self._now())
        journal.append(jid, journal.finished_record(
            job_id=jid, agent_id=job.get("agent_id", ""), status="error",
            summary=f"spawn failure: {error}", session_id="", run_at_ms=_ms(scheduled_for),
            duration_ms=0, next_run_at_ms=st.get("next_run_at_ms"),
            model=eff.get("model") or "", run_id=failed_run_id, spawned_at_ms=now_ms,
            exit_code=None, kill_reason=None, retry_of=retry_of))
        st["last_status"] = "error"
        st["last_error"] = f"spawn failure: {error}"
        st["consecutive_errors"] = int(st.get("consecutive_errors") or 0) + 1
        journal.save_state(self.state)
        if retry_of is None and eff.get("retry_on_stall", True):
            _log(f"retrying {jid} after spawn failure")
            self._try_fire(job, eff, scheduled_for, defaults,
                           retry_of=failed_run_id, advance=False)
        elif (job.get("schedule") or {}).get("kind") == "once":
            self._finalize_once(job, "error")

    # ----------------------------------------------------------------- finish

    def _on_run_finish(self, run, status: str, exit_code: "int|None",
                       kill_reason: "str|None", summary: str) -> None:
        with self.lock:
            self.runs.pop(run.run_id, None)
            jid = run.job_id
            st = self.state.setdefault(jid, {})
            st["active_runs"] = [
                r for r in st.get("active_runs", []) if r.get("run_id") != run.run_id
            ]
            now_ms = _ms(self._now())
            duration_ms = max(0, now_ms - run.spawned_at_ms)
            journal.append(jid, journal.finished_record(
                job_id=jid,
                agent_id=run.job.get("agent_id", ""),
                status=status,
                summary=summary,
                session_id=run.session_id or "",
                run_at_ms=run.scheduled_for_ms,
                duration_ms=duration_ms,
                next_run_at_ms=st.get("next_run_at_ms"),
                model=run.model,
                run_id=run.run_id,
                spawned_at_ms=run.spawned_at_ms,
                exit_code=exit_code,
                kill_reason=kill_reason,
                retry_of=run.retry_of,
            ))
            st["last_run_at_ms"] = run.scheduled_for_ms
            st["last_status"] = status
            st["last_duration_ms"] = duration_ms
            st["last_session_id"] = run.session_id
            if status == "ok":
                st["consecutive_errors"] = 0
                st["last_error"] = None
                st["rate_limit_defers"] = 0
            elif status == "rate_limited":
                # transient usage-window exhaustion — not a job fault, so it must
                # not increment the error streak that drives alerting.
                st["last_error"] = "rate_limited"
            else:
                st["consecutive_errors"] = int(st.get("consecutive_errors") or 0) + 1
                st["last_error"] = status + (f" ({kill_reason})" if kill_reason else "")
            journal.save_state(self.state)
            _log(f"finished {jid} run={run.run_id} status={status}")

            job = self._job_by_id(jid) or run.job
            eff = registry.effective(job, self.defaults(), self.categories())

            # Rate-limited: reschedule to just after the reset (once/recurring
            # alike — a rate-limited once job must be retried, never parked).
            if status == "rate_limited":
                deferred = self._defer_for_rate_limit(job, st, run)
                # A once job that couldn't be deferred (no reset time parsed, or
                # defer cap reached) has no recurring schedule to fall back on —
                # left as-is it dangles enabled with next_run=null, a zombie that
                # reads red forever and never fires again. Finalize → park.
                if not deferred and (job.get("schedule") or {}).get("kind") == "once":
                    self._finalize_once(job, status)
                return

            retried = False
            # Retry transient faults once (same slot, tagged retry_of): a hung
            # session (stall/ttft) or a dropped/failed API connection mid-run
            # (api_error). Spawn failures retry above; rate limits defer above. A
            # genuine job error (real exception, bad content) is NOT retried — it
            # parks. Without the api_error arm a one-shot publish wake killed by a
            # transient "Connection closed mid-response" was lost silently.
            transient = kill_reason in ("stall", "ttft") or status == "api_error"
            if (status != "ok" and transient
                    and eff.get("retry_on_stall", True) and run.retry_of is None
                    and job.get("enabled", True)):
                _log(f"retrying {jid} after {kill_reason or status}")
                self._try_fire(job, eff, run.scheduled_for, self.defaults(),
                               retry_of=run.run_id, advance=False)
                retried = True
            if (job.get("schedule") or {}).get("kind") == "once" and not retried:
                self._finalize_once(job, status)

    def _defer_for_rate_limit(self, job: dict, st: dict, run) -> bool:
        """Pin next_run to just after the quoted reset so the job actually runs
        and writes its artifact. Capped so repeated same-day exhaustion doesn't
        hammer — past the cap, the already-advanced normal schedule stands.

        Returns True iff a retry was actually scheduled (next_run pinned). False
        means the defer cap was reached — the caller must decide the terminal
        outcome (recurring: normal schedule stands; once: finalize, since there
        is no schedule to fall back on). A missing reset time is no longer a
        False on its own: it retries blind, once and recurring alike."""
        jid = job["id"]
        defers = int(st.get("rate_limit_defers") or 0)
        reset_at = getattr(run, "rate_limit_reset_at", None)
        if defers < _MAX_RATE_LIMIT_DEFERS:
            if reset_at is not None:
                reset_ms = int(reset_at.timestamp() * 1000) + _RATE_LIMIT_BUFFER_SECONDS * 1000
                why = "reset"
            else:
                # Rate-limited but the reset time never made it out of the run's
                # output. Retry blind rather than surrender the slot — a daily
                # job that "falls back to the normal schedule" here is not
                # retrying, it is skipping the whole day.
                #
                # A once job takes the same arm, and used to be excluded on the
                # reasoning that a blind retry "recreates the dangling-zombie
                # failure". It does not: the zombie was a job left enabled with
                # next_run NULL, and this arm pins a real next_run before it
                # returns. Parking was never the only alternative to a zombie,
                # and treating it as one turned every unparseable rate limit on
                # a one-shot into dropped work — a one-shot publish wake fired
                # exactly on time, was rate-limited seconds in, and its post was
                # never published, with the terminal park reached before a
                # single retry. The cap below is what bounds this; past it a
                # once job still finalizes, which is the honest terminal state.
                reset_ms = _ms(self._now()) + _RATE_LIMIT_BLIND_RETRY_SECONDS * 1000
                why = "blind (no reset time parsed)"
            st["next_run_at_ms"] = reset_ms
            st["rate_limit_defers"] = defers + 1
            _log(f"rate-limited {jid} run={run.run_id} — deferred to "
                 f"{datetime.fromtimestamp(reset_ms / 1000, tz=timezone.utc).isoformat()} "
                 f"({why}, defer {defers + 1}/{_MAX_RATE_LIMIT_DEFERS})")
            journal.save_state(self.state)
            return True
        _log(f"rate-limited {jid} run={run.run_id} — defer cap "
             f"({_MAX_RATE_LIMIT_DEFERS}) reached; normal schedule stands")
        journal.save_state(self.state)
        return False

    def _finalize_once(self, job: dict, status: str) -> None:
        jid = job["id"]
        sched = job.get("schedule") or {}
        try:
            if status == "ok" and sched.get("delete_after_run"):
                self.registry = registry.mutate(
                    lambda reg: reg.update(
                        jobs=[j for j in reg["jobs"] if j.get("id") != jid]) or reg)
                self.state.pop(jid, None)
                journal.save_state(self.state)
                _log(f"one-shot {jid} completed — removed from registry")
            else:
                # A one-shot is spent the moment it finishes, either way. Its
                # dtstart is in the past, so leaving it enabled parks a corpse
                # that can never fire again but ages forever — every staleness
                # check reads it as a dead job. delete_after_run chooses
                # removal vs retention; it does not mean "stay enabled".
                def _park(reg):
                    for j in reg["jobs"]:
                        if j.get("id") == jid:
                            j["enabled"] = False
                    return reg
                self.registry = registry.mutate(_park)
                _log(f"one-shot {jid} {'completed' if status == 'ok' else 'failed'}"
                     f" — parked (enabled:false)")
        except (OSError, ValueError) as e:
            _log(f"one-shot finalize failed for {jid}: {e!r}")
        try:
            self._registry_mtime = config.SCHEDULE_FILE.stat().st_mtime
        except OSError:
            self._registry_mtime = None

    # -------------------------------------------------------------- reconcile

    def reconcile(self) -> None:
        """Daemon start: re-own recorded active runs; dead pgid → orphaned."""
        with self.lock:
            self._reload_registry_if_changed()
            defaults = self.defaults()
            dirty = False
            for jid, st in self.state.items():
                if not isinstance(st, dict):
                    continue
                remaining = []
                for entry in st.get("active_runs", []):
                    pgid = entry.get("pgid")
                    job = self._job_by_id(jid) or {"id": jid}
                    if pgid and runner.pgid_alive(pgid):
                        adopted = runner.AdoptedRun(
                            jid, entry, registry.effective(job, defaults, self.categories()),
                            defaults, self._on_run_finish).start()
                        self.runs[adopted.run_id] = adopted
                        remaining.append(entry)
                        _log(f"adopted live run {entry.get('run_id')} (pgid {pgid})")
                        continue
                    now_ms = _ms(self._now())
                    spawned = int(entry.get("spawned_at_ms") or now_ms)
                    summary = ""
                    if entry.get("workspace") and entry.get("session_id"):
                        summary = runner.last_text_block(runner.session_jsonl_path(
                            runner.Path(entry["workspace"]), entry["session_id"]))
                    journal.append(jid, journal.finished_record(
                        job_id=jid, agent_id=job.get("agent_id", ""),
                        status="orphaned", summary=summary,
                        session_id=entry.get("session_id") or "",
                        run_at_ms=int(entry.get("scheduled_for_ms") or spawned),
                        duration_ms=max(0, now_ms - spawned),
                        next_run_at_ms=st.get("next_run_at_ms"),
                        model=job.get("model") or defaults.get("model", ""),
                        run_id=entry.get("run_id") or "",
                        spawned_at_ms=spawned, exit_code=None,
                        kill_reason="orphaned", retry_of=None))
                    st["last_status"] = "orphaned"
                    dirty = True
                    _log(f"orphaned dead run {entry.get('run_id')} (pgid {pgid})")
                if len(remaining) != len(st.get("active_runs", [])):
                    st["active_runs"] = remaining
                    dirty = True
            if dirty:
                journal.save_state(self.state)

    # ------------------------------------------------------------ api surface

    def health(self) -> dict:
        with self.lock:
            self._reload_registry_if_changed()
            enabled = [j for j in self.jobs() if j.get("enabled", True)]
            next_ms = [
                self.state.get(j["id"], {}).get("next_run_at_ms") for j in enabled
            ]
            next_ms = [m for m in next_ms if m]
            next_fire = (
                datetime.fromtimestamp(min(next_ms) / 1000, tz=timezone.utc).isoformat()
                if next_ms else None
            )
            return {
                "ok": True,
                "uptime_s": int(time.time() - self.started_at),
                "active_runs": len(self.runs),
                "jobs_enabled": len(enabled),
                "next_fire_at": next_fire,
            }

    def jobs_view(self) -> list[dict]:
        with self.lock:
            self._reload_registry_if_changed()
            out = []
            for job in self.jobs():
                st = self.state.get(job["id"], {})
                merged = dict(job)
                merged["state"] = {k: v for k, v in st.items() if k != "active_runs"}
                merged["active_runs"] = st.get("active_runs", [])
                out.append(merged)
            return out

    def runs_view(self) -> list[dict]:
        with self.lock:
            return [
                {
                    "run_id": r.run_id,
                    "job_id": r.job_id,
                    "session_id": r.session_id,
                    "pid": r.pid,
                    "pgid": r.pgid,
                    "spawned_at_ms": r.spawned_at_ms,
                    "scheduled_for_ms": r.scheduled_for_ms,
                    "retry_of": r.retry_of,
                }
                for r in self.runs.values()
            ]

    def run_now(self, job_id: str) -> bool:
        with self.lock:
            self._reload_registry_if_changed()
            job = self._job_by_id(job_id)
            if job is None:
                return False
            defaults = self.defaults()
            if len(self.runs) >= int(defaults.get("max_concurrent_runs", 4)):
                return False
            eff = dict(registry.effective(job, defaults, self.categories()))
            # manual fire: schedule untouched (advance=False), policy bypassed
            eff["concurrency"] = "parallel"
            self._try_fire(job, eff, self._now(), defaults,
                           retry_of=None, advance=False)
            return True

    def kill_run(self, run_id: str) -> bool:
        with self.lock:
            run = self.runs.get(run_id)
        if run is None:
            return False
        # grace-and-escalate runs in a thread so the API replies immediately
        threading.Thread(target=run.kill, args=("manual",), daemon=True).start()
        return True

    # -------------------------------------------------------------- lifecycle

    def _sweep_logs(self, now: datetime) -> None:
        day = now.strftime("%Y-%m-%d")
        if self._last_sweep_day == day:
            return
        self._last_sweep_day = day
        cutoff = time.time() - config.LOG_RETENTION_DAYS * 86400
        if not config.LOGS_DIR.is_dir():
            return
        for f in config.LOGS_DIR.glob("*.out"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass

    def run_forever(self) -> None:
        self.reconcile()
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as e:
                _log(f"tick error: {e!r}")
            self._stop.wait(config.TICK_SECONDS)

    def stop(self) -> None:
        self._stop.set()
