"""Live PTY attachments — which app instance is showing (and driving) a session.

Every thread view the app holds — iPad, iPhone, the Mac app — is a PTY
WebSocket onto its session (pty.py). That connection is the only live fact
tying a session to the *instance* showing it, so it answers two questions
nothing else can:

* **Who drove this session last?** A handoff typed on the iPad must open its
  window on the iPad, never the Mac. Keystrokes are the driving fact: every
  binary input frame stamps its attachment, and `driver_for` returns the
  most recent stamp inside DRIVER_WINDOW. A driver whose socket died mid-turn
  (iOS drops sockets in background) is still remembered — `recent_driver` —
  so a device-driven spawn degrades to "create quietly", never to a Mac
  window over a device's handoff.

* **Who else is showing this thread?** "Close on other instances" orders
  every other attachment of the sid shut with CLOSE_ELSEWHERE (4412): the
  view dismisses, the session keeps running.

State is process-local to the dashboard and mutated only on the event loop
(pty_ws registers/unregisters; async routes read) — no locks. A dashboard
restart forgets it, and every fallback is today's behavior.
"""

import time

#: How long a keystroke keeps its instance "the driver". Generous: a handoff
#: writes its doc for minutes between the typed command and the spawn.
DRIVER_WINDOW = 15 * 60.0

#: Server-ordered view dismissal: the thread closes on that instance, the
#: session lives. Sits beside 4411 (session ended) in the close-code family.
CLOSE_ELSEWHERE = 4412
CLOSE_ELSEWHERE_REASON = "dismissed from another device"


class Attachment:
    """One live PTY connection: identity plus the hooks to reach it.

    `send_text` enqueues a JSON control frame onto the connection's outbound
    pump; `order_close` tells the pump to finish with a specific close code.
    Both are called from async routes on the same loop the pump runs on.
    """

    def __init__(self, sid: str, instance: str, platform: str,
                 send_text, order_close):
        self.sid = sid
        self.instance = instance
        self.platform = platform
        self.send_text = send_text
        self.order_close = order_close
        self.last_input = 0.0


_live: list[Attachment] = []
#: sid -> (instance, platform, ts) — the last driver seen, surviving its
#: socket. Only consulted when no live attachment drives the sid.
_recent: dict[str, tuple[str, str, float]] = {}


def reset() -> None:
    """Test hook — a clean registry."""
    _live.clear()
    _recent.clear()


def register(att: Attachment) -> None:
    if att not in _live:
        _live.append(att)


def unregister(att: Attachment) -> None:
    if att in _live:
        _live.remove(att)


def any_live() -> bool:
    """Is any device inside a terminal right now?

    Asked by `board_watch` to decide how hard to work: a device in a thread has
    the board behind a full-screen terminal, and the board observation is the
    most expensive thing this process does — so it is not worth running at the
    board's pace for a screen nobody can see, in the same interpreter that owes
    that terminal its next frame (#30)."""
    return bool(_live)


def note_input(att: Attachment, now: float | None = None) -> None:
    """A binary frame arrived — this instance is typing into the session."""
    ts = time.time() if now is None else now
    att.last_input = ts
    _recent[att.sid] = (att.instance, att.platform, ts)


def driver_for(sid: str, now: float | None = None) -> Attachment | None:
    """The live attachment that most recently typed into sid, or None."""
    ts = time.time() if now is None else now
    best = None
    for att in _live:
        if att.sid != sid or not att.last_input:
            continue
        if ts - att.last_input > DRIVER_WINDOW:
            continue
        if best is None or att.last_input > best.last_input:
            best = att
    return best


def recent_driver(sid: str, now: float | None = None) -> tuple[str, str] | None:
    """(instance, platform) that last drove sid, socket alive or not."""
    ts = time.time() if now is None else now
    rec = _recent.get(sid)
    if not rec or ts - rec[2] > DRIVER_WINDOW:
        return None
    return rec[0], rec[1]


#: Platforms whose driver claims a spawn's window. Anything else — "mac",
#: or the empty tag of a stale app build — keeps today's Mac window.
DEVICE_PLATFORMS = {"pad", "phone"}


def spawn_route(sid: str, now: float | None = None) -> tuple[str, "Attachment | None"]:
    """Where a spawn driven from inside `sid` should open its window.

    ("device", driver) — a device typed it; the open frame goes down that
    socket. ("mac", …) — desk-driven, unknown, or nobody: today's behavior.
    ("none", None) — a device drove it but its socket is gone: create
    quietly, the board row is the visibility."""
    driver = driver_for(sid, now=now)
    if driver:
        route = "device" if driver.platform in DEVICE_PLATFORMS else "mac"
        return route, driver
    recent = recent_driver(sid, now=now)
    if recent and recent[1] in DEVICE_PLATFORMS:
        return "none", None
    return "mac", None


def send_open(att: Attachment, url: str) -> None:
    """Hand the driving instance the new session's jremote:// link."""
    att.send_text({"type": "open", "url": url})


def close_others(sid: str, instance: str) -> int:
    """Order every other instance's view of sid shut. Returns the count."""
    n = 0
    for att in list(_live):
        if att.sid == sid and att.instance != instance:
            att.order_close(CLOSE_ELSEWHERE, CLOSE_ELSEWHERE_REASON)
            n += 1
    return n
