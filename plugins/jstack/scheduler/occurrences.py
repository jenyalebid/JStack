"""RRULE expansion, cron→RRULE conversion, next-fire computation.

All occurrence math is server-side, tz-aware, wall-clock in the job's zone
(dateutil rrule with a ZoneInfo dtstart recurs on wall time — DST-correct).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from . import config

def get_rrulestr():
    """`dateutil.rrule.rrulestr`, imported on first recurring-schedule use.

    dateutil is this package's only third-party dependency, and it is needed
    by exactly one kind of job. Imported at module top it became a dependency
    of the whole CLI: `scheduler.cli` imports this module, so on a machine
    without dateutil even `add-once` died at import — and one-shot jobs are
    how a message wake and a self-scheduled follow-up are delivered. Both
    call sites below sit past the `kind == "once"` early return, so the
    entire one-shot path now runs on a stock interpreter.

    The failure, when it does come, names the one job kind that needs it
    rather than the import line."""
    try:
        from dateutil.rrule import rrulestr
    except ImportError as e:  # noqa: TRY003 — the fix belongs in the message
        raise ImportError(
            "recurring schedules need the 'python-dateutil' package "
            "(pip install python-dateutil); one-shot jobs do not"
        ) from e
    return rrulestr


_CRON_FIELDS = ("minute", "hour", "day-of-month", "month", "day-of-week")
_CRON_BOUNDS = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day-of-month": (1, 31),
    "month": (1, 12),
    "day-of-week": (0, 7),  # 0 and 7 are both Sunday
}
_DOW_NAMES = {0: "SU", 1: "MO", 2: "TU", 3: "WE", 4: "TH", 5: "FR", 6: "SA", 7: "SU"}


def _parse_cron_field(name: str, raw: str) -> list[int] | None:
    """Parse one cron field: '*' → None (unrestricted), else sorted values.

    Supports fixed values, lists and ranges. Steps ('*/5') are unconvertible
    to a clean RRULE and raise, naming the field.
    """
    if raw == "*":
        return None
    values: set[int] = set()
    for part in raw.split(","):
        if "/" in part:
            raise ValueError(f"cron {name}: step values not supported ({raw!r})")
        if "*" in part:
            raise ValueError(f"cron {name}: '*' cannot appear in a list ({raw!r})")
        if "-" in part:
            a_s, _, b_s = part.partition("-")
            try:
                a, b = int(a_s), int(b_s)
            except ValueError:
                raise ValueError(f"cron {name}: bad range {part!r}") from None
            if a > b:
                raise ValueError(f"cron {name}: inverted range {part!r}")
            values.update(range(a, b + 1))
        else:
            try:
                values.add(int(part))
            except ValueError:
                raise ValueError(f"cron {name}: bad value {part!r}") from None
    lo, hi = _CRON_BOUNDS[name]
    for v in values:
        if not lo <= v <= hi:
            raise ValueError(f"cron {name}: {v} out of range {lo}-{hi}")
    return sorted(values)


def cron_to_rrule(expr: str) -> str:
    """Convert a 5-field cron expression to an RRULE string.

    Unconvertible input raises ValueError naming the offending field.
    """
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"cron expression needs 5 fields, got {len(parts)}: {expr!r}")
    minute, hour, dom, month, dow = (
        _parse_cron_field(name, raw) for name, raw in zip(_CRON_FIELDS, parts)
    )
    if dom is not None and dow is not None:
        # cron fires on (dom OR dow) when both are restricted — one RRULE
        # cannot express that union.
        raise ValueError(
            "cron day-of-month + day-of-week both restricted — OR semantics "
            "cannot be expressed as a single RRULE"
        )

    if minute is None:
        freq = "MINUTELY"
    elif hour is None:
        freq = "HOURLY"
    elif dow is not None:
        freq = "WEEKLY"
    elif month is not None and dom is not None:
        freq = "YEARLY"
    elif dom is not None:
        freq = "MONTHLY"
    else:
        # includes month-only restriction: DAILY + BYMONTH filter
        freq = "DAILY"

    out = [f"FREQ={freq}"]
    if month is not None:
        out.append("BYMONTH=" + ",".join(map(str, month)))
    if dom is not None:
        out.append("BYMONTHDAY=" + ",".join(map(str, dom)))
    if dow is not None:
        days = list(dict.fromkeys(_DOW_NAMES[v] for v in dow))
        out.append("BYDAY=" + ",".join(days))
    if hour is not None:
        out.append("BYHOUR=" + ",".join(map(str, hour)))
    if minute is not None:
        out.append("BYMINUTE=" + ",".join(map(str, minute)))
    return ";".join(out)


def job_tz(job: dict) -> ZoneInfo:
    sched = job.get("schedule") or {}
    return ZoneInfo(sched.get("tz") or config.DEFAULT_TZ)


def parse_dtstart(schedule: dict) -> datetime:
    """Aware dtstart in the job's zone. Naive input = wall clock in that zone."""
    tz = ZoneInfo(schedule.get("tz") or config.DEFAULT_TZ)
    dt = datetime.fromisoformat(schedule["dtstart"])
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def next_fires(job: dict, n: int = 1, after: "datetime|None" = None,
               until: "datetime|None" = None) -> "list[datetime]":
    """Next n occurrences strictly after `after` (default: now). tz-aware.

    `until` (optional, tz-aware) caps expansion at a horizon: stop as soon as a
    fire lands at/after it. Lets callers that only want a window (e.g. the
    dashboard's 7-day view) avoid expanding the full `n` — a daily job over a
    week is ~7 fires, not 500. `n` remains the hard safety cap."""
    sched = job.get("schedule") or {}
    tz = job_tz(job)
    dtstart = parse_dtstart(sched)
    if after is None:
        after = datetime.now(tz)
    elif after.tzinfo is None:
        after = after.replace(tzinfo=tz)
    after = after.astimezone(tz)

    if sched.get("kind") == "once":
        return [dtstart] if dtstart > after else []

    rule = get_rrulestr()(sched["rrule"], dtstart=dtstart)
    out: list[datetime] = []
    cur = after
    for _ in range(n):
        nxt = rule.after(cur)
        if nxt is None:
            break
        if until is not None and nxt >= until:
            break
        out.append(nxt)
        cur = nxt
    return out


def last_fire(job: dict, before: "datetime|None" = None, inc: bool = True) -> "datetime|None":
    """Most recent scheduled occurrence at/before `before` (default: now).

    The mirror of `next_fires` for the past — what the outcome validator needs
    to ask "has the most recent *scheduled* fire actually run?" rather than
    assuming a fixed cadence. Returns None if the schedule has produced no
    occurrence yet. tz-aware, wall-clock in the job's zone (DST-correct)."""
    sched = job.get("schedule") or {}
    tz = job_tz(job)
    dtstart = parse_dtstart(sched)
    if before is None:
        before = datetime.now(tz)
    elif before.tzinfo is None:
        before = before.replace(tzinfo=tz)
    before = before.astimezone(tz)

    if sched.get("kind") == "once":
        if inc:
            return dtstart if dtstart <= before else None
        return dtstart if dtstart < before else None

    rule = get_rrulestr()(sched["rrule"], dtstart=dtstart)
    return rule.before(before, inc=inc)
