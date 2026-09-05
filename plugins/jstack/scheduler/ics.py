"""iCal feed — hand-rolled RFC 5545.

Text values escaped (backslash, semicolon, comma, newline), lines folded at
75 octets (UTF-8-boundary safe), CRLF endings, VTIMEZONE derived from the
install's zone. Served by the dashboard; this module only builds bytes.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, occurrences, registry

_FOLD_LIMIT = 75  # octets, per RFC 5545 §3.1

_DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
# Reference year for the recurrence rules. Any non-transitional year works —
# the rules are expressed as "nth weekday of month", not as dates.
_VTZ_YEAR = 2024


def _fmt_offset(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    sign = "-" if total < 0 else "+"
    total = abs(total)
    return f"{sign}{total // 3600:02d}{(total % 3600) // 60:02d}"


def _transitions(tz: ZoneInfo, year: int) -> list:
    """(instant, offset_before, offset_after) for each utcoffset change in `year`.

    Walks the year a day at a time, then bisects to the minute. Reading the
    zone itself is the only portable way — the DST rule differs by region (US
    switches on the 2nd Sunday of March, the EU on the last Sunday), and plenty
    of zones never switch at all.
    """
    out = []
    cur = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    prev_off = cur.astimezone(tz).utcoffset()
    while cur < end:
        nxt = min(cur + timedelta(days=1), end)
        off = nxt.astimezone(tz).utcoffset()
        if off != prev_off:
            lo, hi = cur, nxt
            # To the second: a coarser bound leaves the residue in DTSTART's
            # seconds field (02:00:28 for a 02:00:00 transition).
            while hi - lo > timedelta(seconds=1):
                mid = lo + (hi - lo) / 2
                if mid.astimezone(tz).utcoffset() == prev_off:
                    lo = mid
                else:
                    hi = mid
            out.append((hi.replace(microsecond=0), prev_off, off))
            prev_off = off
        cur = nxt
    return out


def _rule(local: datetime) -> tuple:
    """The transition date as an (ordinal, weekday) recurrence rule.

    A date in the month's final week is ordinal -1 rather than 4 or 5 — 'last
    Sunday' is the actual rule in every zone that uses one, and a literal
    5th-weekday rule simply does not fire in months that lack one.
    """
    ordinal = (local.day - 1) // 7 + 1
    if local.day + 7 > calendar.monthrange(local.year, local.month)[1]:
        ordinal = -1
    return ordinal, local.weekday()


def _anchor_1970(month: int, ordinal: int, weekday: int) -> datetime:
    """The date the rule picks out in 1970 — the conventional VTIMEZONE epoch.

    DTSTART must be a date the RRULE itself would produce; re-deriving it from
    the rule (rather than reusing the sampled year's date) keeps the two from
    contradicting each other.
    """
    last_day = calendar.monthrange(1970, month)[1]
    days = [d for d in range(1, last_day + 1)
            if datetime(1970, month, d).weekday() == weekday]
    return datetime(1970, month, days[ordinal - 1] if ordinal > 0 else days[-1])


def _component(kind: str, instant: datetime, off_from: timedelta,
               off_to: timedelta, tz: ZoneInfo) -> list:
    # DTSTART in a VTIMEZONE is local wall time under the OUTGOING offset —
    # the clock reading at the moment the change takes effect (02:00 in the US).
    local = (instant + off_from).replace(tzinfo=None)
    ordinal, weekday = _rule(local)
    anchor = _anchor_1970(local.month, ordinal, weekday)
    return [
        f"BEGIN:{kind}",
        f"TZOFFSETFROM:{_fmt_offset(off_from)}",
        f"TZOFFSETTO:{_fmt_offset(off_to)}",
        f"TZNAME:{instant.astimezone(tz).tzname()}",
        f"DTSTART:{anchor:%Y%m%d}T{local:%H%M%S}",
        f"RRULE:FREQ=YEARLY;BYMONTH={local.month};BYDAY={ordinal}{_DAYS[weekday]}",
        f"END:{kind}",
    ]


def vtimezone(tz_name: "str|None" = None) -> tuple:
    """VTIMEZONE for the install's zone, built from its real transitions.

    A zone with no DST gets a single STANDARD component with no RRULE; a fixed
    offset is still a valid zone and must not emit recurrence rules it doesn't
    have.
    """
    tz_name = tz_name or config.default_tz()
    tz = ZoneInfo(tz_name)
    lines = ["BEGIN:VTIMEZONE", f"TZID:{tz_name}"]
    trans = _transitions(tz, _VTZ_YEAR)
    if len(trans) != 2:
        jan = datetime(_VTZ_YEAR, 1, 1, tzinfo=timezone.utc)
        off = jan.astimezone(tz).utcoffset() or timedelta(0)
        lines += [
            "BEGIN:STANDARD",
            f"TZOFFSETFROM:{_fmt_offset(off)}",
            f"TZOFFSETTO:{_fmt_offset(off)}",
            f"TZNAME:{jan.astimezone(tz).tzname()}",
            "DTSTART:19700101T000000",
            "END:STANDARD",
        ]
    else:
        for instant, off_from, off_to in trans:
            kind = "DAYLIGHT" if off_to > off_from else "STANDARD"
            lines += _component(kind, instant, off_from, off_to, tz)
    lines.append("END:VTIMEZONE")
    return tuple(lines)


def escape_text(value: str) -> str:
    """RFC 5545 §3.3.11 TEXT escaping."""
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def fold_line(line: str) -> "list[str]":
    """Split a content line into ≤75-octet chunks; continuations start with
    a space. Never splits inside a UTF-8 multibyte sequence."""
    data = line.encode("utf-8")
    if len(data) <= _FOLD_LIMIT:
        return [line]
    out: list[str] = []
    prefix = b""
    while data:
        room = _FOLD_LIMIT - len(prefix)
        if len(data) <= room:
            out.append((prefix + data).decode("utf-8"))
            break
        cut = room
        while cut > 0 and (data[cut] & 0xC0) == 0x80:  # mid-codepoint
            cut -= 1
        out.append((prefix + data[:cut]).decode("utf-8"))
        data = data[cut:]
        prefix = b" "
    return out


def _fmt_local(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def build_feed() -> str:
    reg = registry.load_registry()
    defaults = config.load_defaults()
    lines: list[str] = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//JStack//Scheduler//EN",
        "CALSCALE:GREGORIAN",
        # Subscribers see this as the calendar's name, so it is the install's
        # to choose — renaming it renames an already-subscribed calendar.
        f"X-WR-CALNAME:{escape_text(config.install().get('calendar_name') or 'Schedule')}",
    ]
    lines.extend(vtimezone())
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for job in reg.get("jobs", []):
        if not job.get("enabled", True):
            continue
        sched = job.get("schedule") or {}
        tzid = sched.get("tz") or config.DEFAULT_TZ
        eff = registry.effective(job, defaults, reg.get("categories") or {})
        try:
            dtstart = occurrences.parse_dtstart(sched)
        except (KeyError, ValueError):
            continue
        dtend = dtstart + timedelta(seconds=eff.get("timeout_seconds") or 1800)
        summary = f"{job.get('name', '')} · {job.get('agent_id', '')}"
        description = (job.get("payload") or {}).get("message", "")
        lines.append("BEGIN:VEVENT")
        # The UID domain names the stack, not the first deployment that ran it.
        # Changing it re-mints every event once: a subscriber replaces the whole
        # calendar on refresh, so the old UIDs leave with the old feed rather
        # than lingering as ghosts beside the new ones.
        lines.append(f"UID:{job['id']}@jstack-scheduler")
        lines.append(f"DTSTAMP:{dtstamp}")
        lines.append(f"SUMMARY:{escape_text(summary)}")
        if description:
            lines.append(f"DESCRIPTION:{escape_text(description)}")
        lines.append(f"DTSTART;TZID={tzid}:{_fmt_local(dtstart)}")
        lines.append(f"DTEND;TZID={tzid}:{_fmt_local(dtend)}")
        if sched.get("kind") == "rrule":
            lines.append(f"RRULE:{sched['rrule']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    folded: list[str] = []
    for line in lines:
        folded.extend(fold_line(line))
    return "\r\n".join(folded) + "\r\n"
