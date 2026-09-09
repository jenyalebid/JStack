"""How heavy a session is right now — the reading behind the app's load meter.

Two facts, both already folded by the session-summary parser and neither of
them a running total:

- **context** — the input size of the newest API call. This is what *every
  further turn in this session re-reads*, so it is the cost of continuing.
- **turns** — assistant replies so far, deduped by message id.
- **floor** — what one request cost this session before anything had
  accumulated: its walk-up, its tools, its preamble. It is the weight a
  `/compact` drops back to, so it is what makes the context number mean
  something — 180k is nearly nothing above a 170k floor and a great deal
  above a 40k one. Null when the opening turn couldn't be read; the app
  falls back to a fleet figure rather than pretending it measured this one.

The distinction is the whole point. A session's cumulative token count grows
forever and says nothing about whether to keep working in it; a 200-turn
session and a 20-turn one can bill the same and behave nothing alike. Context
is the per-turn price of staying, and it is the only one of the two that
starting fresh resets.

Served on `/sessions/{sid}/timeline` (the panel already polls it while open,
which is exactly the cadence a meter wants) and on the board rows. The
grading — where "light" ends and "heavy" begins — is the app's, not ours:
this module reports the numbers and nothing else, so there is one place the
facts come from and one place they are judged.

**A reading that failed is not a light session.** No transcript yet means
genuinely weightless and reads as zero; anything else — an unparseable file,
a vanished path — returns nothing at all, and the app draws no meter. Zeroing
a failed read would paint the heaviest session on the Mac as fresh and tell
The user to keep going, which is the one answer the meter exists to prevent.
"""

from .transcripts import get_session_summary
from .messages import _find_session_file

#: A session whose transcript does not exist yet — a thread nobody has typed
#: in — genuinely carries nothing. This is an observation, not a fallback.
EMPTY = {"context": 0, "turns": 0, "floor": None}


def reading(session_id: str) -> dict | None:
    """`{context, turns}` for one session, or None when it couldn't be read.

    None is the honest answer to "how heavy is this?" when the transcript
    can't be parsed — the caller omits the block and the app shows no meter,
    rather than a confident zero.
    """
    try:
        path = _find_session_file(session_id)
    except Exception:
        return None
    if not path:
        return dict(EMPTY)
    if path.name.startswith("rollout-"):
        try:
            import json
            context = turns = 0
            with path.open() as fh:
                for raw in fh:
                    e = json.loads(raw)
                    payload = e.get("payload") or {}
                    if e.get("type") == "event_msg" \
                            and payload.get("type") == "token_count":
                        usage = ((payload.get("info") or {})
                                 .get("last_token_usage") or {})
                        context = int(usage.get("input_tokens") or context)
                    elif e.get("type") == "response_item" \
                            and payload.get("type") == "message" \
                            and payload.get("role") == "assistant" \
                            and payload.get("phase") == "final_answer":
                        turns += 1
            return {"context": context, "turns": turns, "floor": None}
        except Exception:
            return None
    try:
        summary = get_session_summary(path) or {}
    except Exception:
        return None
    return {"context": int(summary.get("last_context") or 0),
            "turns": int(summary.get("calls") or 0),
            "floor": int(summary.get("first_context") or 0) or None}
