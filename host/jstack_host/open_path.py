"""Open-on-Mac — a file link clicked in a session's terminal opens where
the files live.

A path shift-clicked on any device names a file on this Mac, so the open
happens here. The app sends the raw token it found under the click; this
module owns the reading: strip a trailing :line[:col], drop wrapping
quotes, expand ~, anchor a relative path at the session pane's current
directory (the cwd the session itself would read it against), require the
file to exist, and hand it to macOS `open`. URLs never come here — the
device that clicked opens those itself.
"""

import re
import subprocess
from pathlib import Path

from . import managed

_LINE_SUFFIX = re.compile(r"(:\d+){1,2}$")


def resolve(token: str, cwd: str) -> Path:
    """The token as the Mac path it names.

    Raises ValueError on an empty token, FileNotFoundError when the
    resolved path names nothing on disk.
    """
    t = token.strip().strip("'\"")
    t = _LINE_SUFFIX.sub("", t)
    if not t:
        raise ValueError("empty path token")
    p = Path(t).expanduser()
    if not p.is_absolute():
        p = Path(cwd) / p
    p = p.resolve()
    if not p.exists():
        raise FileNotFoundError(str(p))
    return p


def pane_cwd(sid: str) -> str:
    """The session pane's current directory — the anchor for relative paths.

    Raises KeyError when the session has no live pane to ask.
    """
    r = subprocess.run(
        managed._t("display-message", "-p", "-t", managed._name(sid),
                   "#{pane_current_path}"),
        capture_output=True, text=True)
    cwd = r.stdout.strip()
    if r.returncode != 0 or not cwd:
        raise KeyError(sid)
    return cwd


def _open(path: Path) -> None:
    subprocess.run(["open", str(path)], check=True)


def open_on_mac(sid: str, token: str) -> Path:
    """Resolve and open; returns the path that was handed to `open`."""
    path = resolve(token, pane_cwd(sid))
    _open(path)
    return path
