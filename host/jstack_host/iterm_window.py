"""Open — and close — real iTerm WINDOWS via iTerm's Python API.

The jremote managed layer uses this so "Show on Mac" opens a window, not a
tab. The API rides iTerm's unix socket (EnableAPIServer), so no Apple events
and no TCC — the one-time cost is iTerm's own "allow this program" consent.

**The window goes on the desk without taking the keyboard.** Whatever holds
focus when this is called holds it when it returns: a window that steals focus
mid-sentence swallows the next thing typed into a fresh shell, which breaks the
work it was opened to support. Being visible is the requirement; being focused
never was.

Closing is the same door in the other direction: a session ending and its
window closing are one event, so whoever ends a session hands the ttys it was
living in to `close_sessions` and the desk is left as clean as if the window
had been closed by hand.

CLI: .venv/bin/python3 -m jstack_host.iterm_window "<shell command>"
     .venv/bin/python3 -m jstack_host.iterm_window --close /dev/ttys004 [...]
Exit 0 = done; non-zero = caller should fall back (tab path) or log.
"""

import subprocess
import sys

ITERM_BUNDLE_ID = "com.googlecode.iterm2"


def _iterm2():
    """iTerm's Python API, imported when it is about to be used.

    Not at module scope: `iterm2` is a third-party package, and this package
    ships to Macs whose only dependencies are the payload's own wheels. A
    top-level import makes the module unimportable there — which
    `tests/test_jremote_standalone.py` refuses on the whole package's behalf,
    because a host that cannot import one of its own modules is a host nobody
    can tell is broken until a route touches it. Callers already treat a
    non-zero exit as "fall back to the tab path", and a missing iTerm API is
    exactly that.
    """
    import iterm2
    return iterm2


def frontmost_bundle_id() -> str:
    """Bundle id of the app holding the keyboard right now, "" if unknown.

    `lsappinfo` reads LaunchServices directly — no Apple events, so this works
    from a launchd daemon where System Events is TCC-blocked."""
    try:
        asn = subprocess.run(["lsappinfo", "front"], capture_output=True,
                             text=True, timeout=5).stdout.strip()
        if not asn:
            return ""
        out = subprocess.run(["lsappinfo", "info", "-only", "bundleid", asn],
                             capture_output=True, text=True, timeout=5).stdout
        # `"CFBundleIdentifier"="com.googlecode.iterm2"`
        return out.split("=", 1)[1].strip().strip('"') if "=" in out else ""
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def open_window(command: str) -> None:
    front_before = frontmost_bundle_id()

    iterm2 = _iterm2()

    async def main(connection):
        app = await iterm2.async_get_app(connection)
        # The session that owns the keyboard right now, so it can be handed
        # back the moment the new window exists. Captured before creating —
        # afterwards `current_terminal_window` is the new one.
        restore = None
        if front_before == ITERM_BUNDLE_ID:
            win = app.current_terminal_window
            tab = win.current_tab if win else None
            restore = tab.current_session if tab else None

        await iterm2.Window.async_create(connection, command=command)

        if restore is not None:
            await restore.async_activate(select_tab=True, order_window_front=True)

    # Connects over ~/Library/Application Support/iTerm2/private/socket and
    # runs the coroutine once; raises if iTerm or its API server is absent.
    iterm2.run_until_complete(main)

    # Focus was in another app entirely: if creating the window pulled iTerm
    # forward, put that app back. (Nothing to do when iTerm never took it.)
    if front_before and front_before != ITERM_BUNDLE_ID:
        if frontmost_bundle_id() == ITERM_BUNDLE_ID:
            subprocess.run(["open", "-b", front_before], check=False)


def close_sessions(ttys) -> int:
    """Close the iTerm sessions living on these ttys. Returns how many closed.

    Matched on the tty and nothing else — the one fact that ties a process we
    just ended to a rectangle on the desk. A session id, a title or a window
    order would all be guesses, and the cost of a wrong guess here is closing
    a window the user is working in.

    Closes the *session* (`async_close`), so a tab in a shared window takes
    only its own tab with it; iTerm closes the window when it was the last one.
    Absent ttys are simply not found — closing an already-closed window is a
    no-op, which is what makes this safe to call after any teardown path."""
    wanted = {t for t in (ttys or []) if t}
    if not wanted:
        return 0
    closed = 0

    iterm2 = _iterm2()

    async def main(connection):
        nonlocal closed
        app = await iterm2.async_get_app(connection)
        for window in list(app.terminal_windows):
            for tab in list(window.tabs):
                for session in list(tab.sessions):
                    tty = await session.async_get_variable("tty")
                    if tty in wanted:
                        await session.async_close(force=True)
                        closed += 1

    iterm2.run_until_complete(main)
    return closed


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--close":
        if len(args) < 2:
            print("usage: python3 -m jstack_host.iterm_window --close <tty> [tty...]",
                  file=sys.stderr)
            sys.exit(2)
        try:
            print(close_sessions(args[1:]))
        except Exception as e:  # noqa: BLE001 — the caller logs and moves on
            print(f"iterm close failed: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)
    if len(args) != 1 or not args[0].strip():
        print("usage: python3 -m jstack_host.iterm_window '<command>'", file=sys.stderr)
        sys.exit(2)
    try:
        open_window(args[0])
    except Exception as e:  # noqa: BLE001 — any failure means: use the fallback
        print(f"iterm window failed: {e}", file=sys.stderr)
        sys.exit(1)
