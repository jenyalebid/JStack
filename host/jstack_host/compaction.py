"""What a session weighs the moment it is compacted.

A context reading normally comes from an API call: the input size of the
newest assistant turn is what the next turn will re-read. A compaction breaks
that. It throws most of the conversation away and writes no assistant turn, so
the newest call on file is still the one from before — and the meter would go
on reporting the weight the user just paid to get rid of, until they send another
message. The reading has to move when the session moves, not one turn later.

The transcript does record the event: a `system` line with subtype
`compact_boundary`, carrying `preTokens` and `postTokens`. Those two are *not*
measured the same way, and the difference is the whole reason this module
exists. `preTokens` matches an API reading — the request as it was sent, system
prompt and tools included. `postTokens` counts only the conversation that
survived: the summary and the preserved tail. The fixed overhead every request
carries is missing from it, so a compaction that truly lands at ~60k reports
~16k, and a meter fed that number calls a working session fresh.

So the overhead is added back, measured from the session's own first reading
rather than assumed: whatever a request cost before anything had accumulated
is what a request costs again with nothing accumulated. Against real
compactions that estimate lands 3–13% above the next real reading — high,
which is the side to be wrong on, since the one answer a load meter must never
give is "lighter than you are".

The estimate is transient by construction: the next assistant turn writes a
real reading and overwrites it.
"""

from pathlib import Path

#: Below this, a usage block is a continuation fragment rather than a request
#: reading. Both scanners share the cut so their numbers can't diverge.
MIN_READING = 1000

# --- The load meter's cuts -------------------------------------------------
#
# light | working | heavy | extreme, in tokens of context. These are MEASURED
# and absolute: they say what a turn costs to keep paying, and that price does
# not change when `autoCompactWindow` does. Raising the client's window from
# 200k to 300k moved where the client gives up; it moved nothing about where a
# session stops being worth continuing.
#
# Deriving a compaction point from the auto-compact trigger was the bug this
# replaces. It ties the decision to a setting a RUNNING session never re-reads
# — the client resolves its window once at startup — so an edit to settings.json
# silently desynchronised the hooks from the client for the life of every open
# session. The hooks read a 267k trigger while the client was still using 167k
# and reported 40% of headroom left at the moment the client showed 4%. A check
# that lies is worse than no check.
#
# The same three numbers are drawn by `dashboard/shared/ui.py` (the ctx chip)
# and `jRemoteKit/Models.swift` (`SessionLoad.grade`), and all three copies are
# held together by tests/test_load_meter_cuts.py.
WORKING = 100_000
HEAVY = 160_000
EXTREME = 200_000

#: Median opening reading across every compaction on this Mac (n=76). Used only
#: when a session's own floor could not be measured.
TYPICAL_FLOOR = 53_000

#: What a compaction adds on top of the floor: summary plus preserved tail.
#: Near-constant regardless of session size (slope +0.03 tokens per token),
#: which is why compacting *gains* as a session grows rather than weakening.
SUMMARY_COST = 10_000

#: Below this much reclaimable, compacting is churn: it buys a handful of turns
#: and returns to the same place, because what fills the window is the
#: session's own fixed overhead rather than anything a summary can drop.
LITTLE = 40_000


def landing(floor: int = 0) -> int:
    """Where `/compact` would leave a session: its own floor plus the summary.

    Against 76 real compactions this model is within 15k of the true
    post-compact reading 99% of the time (median error +223 tokens). A floor of
    0 means "not measured" and falls back to the fleet median.
    """
    return (floor if floor > 0 else TYPICAL_FLOOR) + SUMMARY_COST


def recoverable(context: int, floor: int = 0) -> int:
    """Tokens a compaction would take off **every remaining turn**.

    This, not the raw context, is what decides whether compacting is worth
    doing: a 190k session sitting on a 170k floor has almost nothing to give
    back, while a 190k session on a 40k floor has been overpaying for a while.
    """
    return max(0, context - landing(floor))

#: How many lines of a transcript to read looking for the first reading. The
#: opening exchange is at the top of the file; a session that somehow buries
#: its first assistant turn deeper than this simply reports no floor.
_HEAD_LINES = 400


def boundary_tokens(entry: dict) -> tuple[int, int] | None:
    """`(pre, post)` if this JSONL entry is a compaction boundary, else None."""
    if entry.get("type") != "system" or entry.get("subtype") != "compact_boundary":
        return None
    meta = entry.get("compactMetadata") or {}
    try:
        return int(meta.get("preTokens") or 0), int(meta.get("postTokens") or 0)
    except (TypeError, ValueError):
        return None


def request_tokens(usage: dict) -> int:
    """Input size of one request — the three input counters, which the API
    reports separately by cache disposition and which only sum to the context
    when taken together."""
    return (usage.get("input_tokens", 0)
            + usage.get("cache_creation_input_tokens", 0)
            + usage.get("cache_read_input_tokens", 0))


def reading_after(post: int, floor: int, pre: int = 0) -> int:
    """The context a compacted session carries before its next reply.

    `floor` is the session's own overhead (see ``first_reading``); zero when
    it couldn't be measured, which reports the bare `post` — understated, but
    still the drop that just happened rather than the weight before it.
    """
    estimate = post + max(floor, 0)
    # Compacting cannot have made the session heavier. Where the floor is
    # overstated — an opening turn that carried a large message of its own —
    # the pre-compact reading is the ceiling the estimate can't pass.
    return min(estimate, pre) if pre > 0 else estimate


def first_reading(path: str | Path, loads) -> int:
    """The session's fixed overhead, read off its opening turn.

    `loads` is the caller's JSON decoder, kept a parameter so this module
    stays a leaf: the two scanners that need it parse lines their own way.
    Returns 0 when the head carries no reading — an honest "not measured".
    """
    try:
        with open(path, "r", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= _HEAD_LINES:
                    break
                if '"assistant"' not in line:
                    continue
                try:
                    entry = loads(line)
                except Exception:
                    continue
                if entry.get("type") != "assistant":
                    continue
                tokens = request_tokens((entry.get("message") or {})
                                        .get("usage") or {})
                if tokens > MIN_READING:
                    return tokens
    except OSError:
        pass
    return 0
