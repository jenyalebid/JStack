"""Scheduler — deterministic cron for unattended agent runs.

One package, every machine. What differs per install is config, never code:
`config/scheduler.json` carries the machine's timezone, the environment its
runs carry, and how an agent id becomes a workspace. Daemon entry is
`python3 -m scheduler`; all mutations go through `python3 -m scheduler.cli`.
"""

from . import config as _config  # noqa: E402  (must precede the path bootstrap)
from .spawn import _bootstrap_python_path

# An install may point `workspace_resolver` at a module of its own. Put its
# `python_path` on sys.path at package import, before anything tries to load
# that hook — callers reach this package from any cwd (launchd, the CLI, tests)
# and cannot be relied on to have set it up.
_bootstrap_python_path()
