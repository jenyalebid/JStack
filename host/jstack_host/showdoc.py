"""Put a markdown document on the screen the session is being driven from.

A session's product is often a file, and a path printed into a terminal is
not a thing anyone read. This opens it — as its own window where windows
exist, as a full-screen cover where they don't — using the same routing rule
`spawn.py` uses for a spawn's window, because it is the same question: the
document belongs on the screen of whoever asked for it.

    ~/Operations/Infrastructure/bin/show-doc PATH [--title TITLE]

Where it lands:

- **A device is driving the session** (the user typed on the iPad or the phone,
  within `attach.DRIVER_WINDOW`) — a `jremote://doc` frame goes down that
  instance's own PTY socket. The iPad opens a window, the phone shows a
  cover; the app decides, not this.
- **Anything else** — desk-driven, no origin session, dashboard down, a
  device whose socket has since died — the Mac's jRemote app opens the
  document as its own window. Unlike a spawn, a document with nowhere to go
  is not left quiet: it has no board row to be found by later.

The link carries the path, never the text. The app asks the host for the file
back through `/context/file`, which is where the read fence lives — so a doc
outside that fence would open a window onto an error. It is refused here
instead, before a window exists, and the fence is asked rather than restated
(`context_inventory.fenced_path`).
"""

import argparse
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

_DASHBOARD = "http://127.0.0.1:9090/api/jremote/v1"


def doc_url(path: str, title: str = "") -> str:
    """The `jremote://doc` link for an absolute path.

    `quote_via=quote`, so a space is `%20` and not `+`. `urlencode`'s default
    is form encoding, where `+` means space by convention; `URLComponents` on
    the other end reads a plain URI query and hands the app a literal plus —
    a title that arrives as `chat+·+pict`, and a path with a space in it that
    resolves to nothing."""
    params = [("path", path)] + ([("title", title)] if title else [])
    return f"jremote://doc?{urlencode(params, quote_via=quote)}"


def _route(origin: str, url: str) -> str:
    """Ask the dashboard where this link belongs.

    "device" — the driving instance got the open frame, nothing to do here.
    "mac" — desk-driven, no origin, or *any* failure: the document opens on
    the desk, which is the answer that always shows something."""
    if not origin:
        return "mac"
    try:
        from .devices import internal_token
        from .spawn import _dashboard_post
        token = internal_token()
        if not token:
            return "mac"
        r = _dashboard_post(f"{_DASHBOARD}/sessions/{origin}/route-open",
                            json={"url": url},
                            headers={"Authorization": f"Bearer {token}"},
                            timeout=5)
        if r.status_code != 200:
            return "mac"
        return r.json().get("route", "mac")
    except Exception:  # noqa: BLE001 — dashboard down ⇒ desk behavior
        return "mac"


def show(path: str, title: str = "") -> tuple[str, str]:
    """Open `path` as a document. Returns (route, url).

    Raises PermissionError when the file is outside the read fence and
    FileNotFoundError when it isn't there — both before any window opens,
    because a window onto an error is worse than a clear refusal."""
    from ..shared.context_inventory import fenced_path
    from . import desk
    from .spawn import origin_sid

    resolved = fenced_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(str(resolved))

    url = doc_url(str(resolved), title)
    route = _route(origin_sid(), url)
    if route != "device":
        route = "mac" if desk.open_url(url) else "none"
    return route, url


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("path", help="the markdown file to open")
    ap.add_argument("--title", default="",
                    help="navigation title; defaults to the file name")
    a = ap.parse_args(argv)

    try:
        route, url = show(a.path, a.title)
    except PermissionError as e:
        print(f"show-doc: {e} — the app can only read markdown under "
              f"~/Agents, ~/Systems, ~/JStack and ~/.claude", file=sys.stderr)
        return 77
    except FileNotFoundError as e:
        print(f"show-doc: no such file: {e}", file=sys.stderr)
        return 66

    if route == "device":
        print(f"opened on the device driving this session — {url}")
    elif route == "mac":
        print(f"opened on the Mac — {url}")
    else:
        print("show-doc: jRemote did not take the link — "
              f"the document is at {a.path}", file=sys.stderr)
        return 75
    return 0


if __name__ == "__main__":
    sys.exit(main())
