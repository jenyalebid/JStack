"""Working→idle edges on managed sessions become pushes.

Consumes board snapshots (registered as a `board_watch` consumer at dashboard
startup) and watches one thing: a managed (tmux) session's turn closing
(`turn_open` → false — the reply landed, or the session stopped to wait on
The user). That edge — after a stretch long enough to mean work, not conversation
— is "the session is done processing", iTerm's done-bell pointed at the
phone. A reply faster than a watcher tick is never even observed as working,
which is the conversational filter working by construction.

Only managed rows notify: raw iTerm windows are desk work, headless workers
are the pipeline's business. A session that stops because it is *waiting on
The user* (permission prompt reads idle by design) fires the same way — that is
the moment a tap on the shoulder is most wanted.

Edges, never states: a sid's first observation only seeds it, so a dashboard
restart into a busy Mac stays silent, and a vanished row (closed session) is
forgotten, not "finished".

Second job, same snapshots: the progress relay. While a turn stays open past
PROGRESS_MIN_TURN, the narration lines the model writes between tool calls
(they surface as the row's `last_reply`) are pushed as throttled "working"
updates — free progress reporting, gated by its own per-agent toggle
(`notify.progress`).

Everything that fires here — done/waiting/error edges and progress relays —
is also recorded to the events log (`events.py`), whether the push went out
or was suppressed: the phone syncs that log as each session's timeline.
"""

import time

from . import events, notify

# A working stretch shorter than this is conversation — the user is in the loop
# already; the ping is for the build they walked away from.
MIN_WORKING = 10.0

# Progress relay: a turn younger than MIN_TURN is not yet "the long session"
# the updates are for, and two updates closer than COOLDOWN are noise. The
# text itself costs nothing — it's narration the model already wrote.
PROGRESS_MIN_TURN = 60.0
PROGRESS_COOLDOWN = 180.0

# sid -> (working, since). In-memory on purpose: edges are observations of
# the running Mac, and a restart should re-seed rather than trust a file.
_state: dict[str, tuple[bool, float]] = {}

# sid -> progress-relay state for the CURRENT turn: `baseline` is the reply
# text the turn opened on (the previous turn's answer — never a progress
# update), `last` the narration already pushed, `sent_at` its clock.
_progress: dict[str, dict] = {}

# sid -> the session's last prompt when its unread mark landed. A DIFFERENT
# prompt later is interaction — someone typed into the session — and catches
# the case the turn_open edge cannot: an exchange that opens and closes inside
# one tick is never observed working, but the prompt behind it is still there
# to read afterwards.
#
# The prompt, not the transcript's mtime, which this used to key on. A quiet
# transcript does NOT change for no other reason: an idle session's JSONL gets
# rewritten with no new content at all (observed 22 minutes after a done, with
# the turn marker gone and not one line appended), and every such write read as
# The user having seen the answer — the dot went grey on a session nobody had
# opened. mtime is evidence of a byte, and only a prompt is evidence of a read.
_marked: dict[str, str] = {}

# sid -> when its done edge fired, held until the session's next turn opens
# and answers for it (`_audit_reopen`). A done nobody follows up on inside the
# window was simply the last one of the session — the entry expires unjudged.
_fired_done: dict[str, float] = {}

# A turn reopening within this of a done is close enough to be the same turn
# resuming; past it, a session going back to work is its own new turn.
FALSE_DONE_WINDOW = 300.0


def observe(rows: list[dict]) -> None:
    """board_watch consumer — one changed board snapshot per call."""
    now = time.time()
    present = set()
    unread_now = notify.unread_sids()
    for row in rows:
        if not row.get("managed"):
            continue
        sid = row.get("session_id") or ""
        present.add(sid)
        # `turn` is the sharp truth ("working" = claude owes a reply right
        # now); `live` lingers ~90s past the last write, which would both
        # delay the ping and defeat MIN_WORKING. "" means the row's turn clock
        # was never read — fall back to `live` rather than read a blank as
        # idle and push a done for a turn nobody observed ending.
        turn = row.get("turn") or ""
        working = (turn == "working") if turn else bool(row.get("live"))
        stamp = row.get("last_prompt") or ""
        if sid in unread_now:
            if sid not in _marked:
                # An unread session this process hasn't stamped yet — a mark
                # that survived a dashboard restart. Adopt its current prompt
                # so the next one still reads as interaction.
                _marked[sid] = stamp
            elif stamp and _marked[sid] != stamp:
                # `stamp and`: a blank is the transcript not being readable
                # this tick, never "the prompt went away". Judging on it would
                # clear the mark on the board's own bad pass — so an unreadable
                # row leaves the dot standing, which is the side that costs
                # the user a dot they can dismiss instead of an answer they never saw.
                del _marked[sid]
                notify.clear_unread(sid)
        else:
            _marked.pop(sid, None)   # cleared elsewhere (phone open) — done
        prev = _state.get(sid)
        if prev is None:
            _state[sid] = (working, now)
            if working:
                _seed_progress(sid, row)
            continue
        was_working, since = prev
        if working == was_working:
            if working:
                _relay_progress(sid, row, now, since)
            continue
        _state[sid] = (working, now)
        if was_working and not working and (now - since) >= MIN_WORKING:
            _progress.pop(sid, None)
            _fire(row)
        elif working and not was_working:
            # A turn opened — someone typed into it, from the Mac or the
            # phone. That is interaction: the unread mark dies with it.
            _audit_reopen(sid, now, row)
            _seed_progress(sid, row)
            notify.clear_unread(sid)
        else:
            _progress.pop(sid, None)
    for sid in list(_state):
        if sid not in present:
            del _state[sid]
            _marked.pop(sid, None)
            _progress.pop(sid, None)
            _fired_done.pop(sid, None)
            # Gone = closed (either end). A dot for a session that no longer
            # exists is noise, and its badge share with it.
            notify.clear_unread(sid)


def _seed_progress(sid: str, row: dict) -> None:
    """A turn just opened (or was first seen open): whatever reply text the
    row carries now predates this turn — never relay it as progress.

    Stripped, because the relay compares stripped: the board cuts a reply at
    120 characters, so whenever that cut lands on a space the raw text and its
    stripped self differ by the trailing byte alone — and a baseline that
    cannot equal the very text it was taken from relays the last answer back
    as this turn's progress."""
    _progress[sid] = {"baseline": (row.get("last_reply") or "").strip(),
                      "last": "", "sent_at": 0.0}


def _relay_progress(sid: str, row: dict, now: float, since: float) -> None:
    """Mid-turn narration → a progress push. The model writes a status line
    between tool calls anyway; once a turn has run PROGRESS_MIN_TURN, each
    fresh line (at most one per PROGRESS_COOLDOWN) is relayed as-is — zero
    extra model work, and the collapse id keeps it to one banner."""
    if now - since < PROGRESS_MIN_TURN:
        return
    p = _progress.get(sid)
    if p is None:
        p = _progress[sid] = {"baseline": (row.get("last_reply") or "").strip(),
                              "last": "", "sent_at": 0.0}
        return
    text = (row.get("last_reply") or "").strip()
    if not text or text == p["baseline"] or text == p["last"]:
        return
    if now - p["sent_at"] < PROGRESS_COOLDOWN:
        return
    p["last"], p["sent_at"] = text, now
    title, body = _title(row) + " · working", text[:140]
    pushed = notify.progress(sid, row.get("agent_id") or "",
                             title=title, body=body)
    events.record(sid, row.get("agent_id") or "", "progress",
                  title, body, pushed)


def _title(row: dict) -> str:
    name = row.get("agent_name") or "Session"
    emoji = row.get("emoji") or ""
    sub_mode = row.get("sub_mode") or ""
    title = " ".join(p for p in (emoji, name) if p)
    if sub_mode:
        title += f" · {sub_mode}"
    return title


def _local_command_reopen(path: str) -> bool:
    """Did a local slash command — not the model — reopen this turn?

    `/compact` and its kin are handled inside Claude Code: the command echoes
    into the transcript as a user line, the harness works for a minute or two,
    and its bookkeeping (caveat, command name, stdout, and a compaction's
    summary) lands after. None of it submits a prompt, so none of it stamps
    the turn marker — which is exactly the fingerprint a resumed turn leaves,
    and the reason the audit below cannot read the marker alone.

    Judged on the newest user line, the one that opened this reopening: a
    slash command or the harness's own tag-wrapped bookkeeping. A prompt that
    merely mentions a command is a `text` block inside a list, never the bare
    string content a typed command has."""
    import json
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            lines = f.read().decode("utf-8", errors="replace").splitlines()[1:]
    except OSError:
        return False
    for ln in reversed(lines):
        try:
            d = json.loads(ln)
        except (json.JSONDecodeError, ValueError):
            continue
        if d.get("type") != "user":
            if d.get("type") == "assistant":
                return False
            continue
        if d.get("isCompactSummary"):
            return True
        content = (d.get("message") or {}).get("content")
        if not isinstance(content, str):
            return False        # blocks = a real prompt or a tool result
        text = content.strip()
        return text.startswith("/") or text.startswith("<")
    return False


def _audit_reopen(sid: str, now: float, row: dict) -> None:
    """At a turn's reopening, rule on whether the done before it was real.

    Nothing observable at the instant a done fires can tell a false edge from
    a true one, because both look identical there: Stop clears the turn marker
    before the board can ever read idle, and the turn's own closing message is
    the freshest write the transcript has. Marker absent, transcript seconds
    old — that is every legitimate done, so a check standing at that moment
    can only ever come back one way.

    What separates them is what happens next. A real done is followed by a new
    turn, and a new turn is opened by a user prompt, which stamps the marker. A
    false done is followed by the same turn simply resuming: no prompt, no
    stamp. So the verdict is taken one edge later, where the two cases finally
    disagree — a marker stamped after the done means a real turn boundary, its
    absence means the turn never actually ended.

    A log line, never a guard: nothing here changes what was pushed. That is
    deliberate — this is the evidence a fix would be built on, and the cheapest
    possible place to be wrong. The known way to be wrong is a prompt whose
    board tick beats its own hook to the marker, which reads as a false done it
    isn't; a real one repeats, a straggler won't.

    The other way, found by the first hit this ever logged: a local slash
    command reopens a turn without submitting a prompt, so it leaves the same
    unmarked reopening a resumed turn does — and a real done that the user happened
    to follow with `/compact` got branded false. An unmarked reopening is only
    evidence when a prompt was the thing that could have marked it."""
    fired = _fired_done.pop(sid, None)
    if fired is None or (now - fired) > FALSE_DONE_WINDOW:
        return
    path = row.get("path") or ""
    if path and _local_command_reopen(path):
        return
    from .board import _TURN_DIR
    try:
        # Stamped *after* the done — a prompt arrived, so the turn really had
        # ended. Its own mtime, not mere existence: residue from a crashed
        # session predates the done and must not vouch for it.
        if (_TURN_DIR / sid).stat().st_mtime >= fired:
            return
    except OSError:
        pass          # no marker at all — no prompt behind this reopening
    print(f"jremote edge: FALSE DONE [{sid[:8]}] — turn reopened "
          f"{now - fired:.1f}s after a done, with no user prompt behind it",
          flush=True)


def _fire(row: dict) -> None:
    sid = row.get("session_id") or ""
    _fired_done[sid] = time.time()
    _marked[sid] = row.get("last_prompt") or ""
    title = _title(row)
    # A stop that is really a wait must not read as done — the tap is wanted
    # for a different reason. Errors keep the default: the API failure text IS
    # the session's last reply, which says it better than a label would.
    attention = row.get("attention") or ""
    if attention == "waiting":
        body = "Waiting on your OK to continue."
    else:
        body = (row.get("last_reply") or row.get("preview") or "Done.")[:140]
    pushed = notify.notify(sid, row.get("agent_id") or "",
                           title=title, body=body)
    # The event outlives the push decision: suppressed or muted, it still
    # lands in the session's timeline.
    kind = attention if attention in ("waiting", "error") else "done"
    events.record(sid, row.get("agent_id") or "", kind, title, body, pushed)
