"""Scheduler paths, install config, and job defaults.

The package is IDENTICAL on every machine — installs differ by config only.
Two layers, and they answer different questions:

  scheduler.json  (this module, `install()`)  — what this MACHINE is: its
      timezone, what env a spawn carries, how an agent id becomes a workspace.
      Read once at import; a change needs a daemon restart.

  schedule.json   (`load_defaults()`, registry) — what the JOBS are: the
      registry plus the defaults/categories a job's settings resolve through.
      Reloaded live on mtime change.

`SCHEDULER_HOME` roots both dirs (default: the package's parent, which is the
single-tree layout). The finer-grained SCHEDULER_*_DIR overrides win over it
and exist so the e2e sandbox can point a real daemon at tmp dirs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

HOME = Path(os.environ.get("SCHEDULER_HOME", str(Path(__file__).resolve().parent.parent)))

CONFIG_DIR = Path(os.environ.get("SCHEDULER_CONFIG_DIR", str(HOME / "config")))
STATE_DIR = Path(os.environ.get("SCHEDULER_STATE_DIR", str(HOME / "state" / "scheduler")))
CREDENTIALS_DIR = Path(os.environ.get("SCHEDULER_CREDENTIALS_DIR", str(HOME / "Credentials")))

SCHEDULE_FILE = CONFIG_DIR / "schedule.json"
INSTALL_FILE = Path(os.environ.get("SCHEDULER_INSTALL_FILE", str(CONFIG_DIR / "scheduler.json")))
STATE_FILE = STATE_DIR / "state.json"
RUNS_DIR = STATE_DIR / "runs"
LOGS_DIR = STATE_DIR / "logs"
LOCK_FILE = STATE_DIR / ".registry.lock"
FEED_TOKEN_FILE = CREDENTIALS_DIR / "scheduler-feed-token"

API_PORT = int(os.environ.get("SCHEDULER_API_PORT", "9091"))
TICK_SECONDS = float(os.environ.get("SCHEDULER_TICK_SECONDS", "20"))

LOG_RETENTION_DAYS = 14
# An occurrence later than this behind now is a miss (catch-up semantics);
# within it is a normal same-tick fire.
MISFIRE_THRESHOLD_SECONDS = 120


def _local_tz_name() -> str:
    """The machine's IANA zone name.

    A scheduler whose timezone is wrong fires everything at the wrong hour, so
    guess only from sources that carry a real zone NAME: $TZ, then the
    /etc/localtime symlink (…/zoneinfo/America/Los_Angeles on macOS and Linux
    alike). Never fall back to a fixed offset — UTC is the honest last resort
    and an install that cares states `timezone` outright.
    """
    tz = os.environ.get("TZ")
    if tz:
        return tz
    try:
        target = os.readlink("/etc/localtime")
        marker = "zoneinfo/"
        if marker in target:
            return target.split(marker, 1)[1]
    except OSError:
        pass
    return "UTC"


# Per-machine seams. Every value here is something an install legitimately
# differs on; nothing here is a job-level setting (those live in schedule.json).
BUILTIN_INSTALL = {
    # Zone for wall-clock job times, the ics feed, and reading the reset clock
    # out of a usage-limit message.
    "timezone": None,  # None → _local_tz_name()
    # Name subscribers see for the ics calendar.
    "calendar_name": "Schedule",
    # Env every spawned run carries, on top of the daemon's own environment.
    "spawn_env": {},
    # Dirs prepended to the child PATH (agent-facing tools live here).
    "spawn_path_prepend": [],
    # Canonical binary search path for daemon-spawned children. launchd hands a
    # daemon a stripped PATH, so a spawn cannot inherit its way to `claude`.
    "spawn_dirs": [
        "~/.local/bin",  # claude native installer
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ],
    # "module:function" called with the job dict to produce a workspace path.
    # Absent → the built-in agent_root / agent_registry resolution.
    "workspace_resolver": None,
    # Extra sys.path entries so a workspace_resolver's module is importable.
    "python_path": [],
    # Fallback workspace resolution: {agent_root}/{Name}/ plus an optional
    # registry mapping agent id → workspace.
    "agent_root": "~/Agents",
    "agent_registry": None,
    # Sub-seat redirection: an agent id ending in `suffix` runs in the named
    # subdir when that subdir has its own CLAUDE.md.
    "seat_rules": [],
}

BUILTIN_DEFAULTS = {
    "model": "opus",
    "timeout_seconds": 1800,
    "stall_timeout_seconds": 900,
    "ttft_timeout_seconds": 180,
    "max_concurrent_runs": 6,
    "catch_up_grace_seconds": 43200,
    "claude_bin": "claude",
    # An unattended run has nobody to answer a permission prompt, so bypass is
    # what makes it autonomous at all. It resolves through the same
    # job → category → default chain as any other setting, so a single job or a
    # whole category can be narrowed without touching the daemon's default.
    "permission_mode": "bypassPermissions",
}

_install: "dict|None" = None


def install() -> dict:
    """The machine's scheduler.json merged over built-ins. Cached: these are
    daemon-lifetime facts, and re-reading per spawn would let a half-written
    file change a run's environment mid-flight."""
    global _install
    if _install is None:
        merged = dict(BUILTIN_INSTALL)
        try:
            raw = json.loads(INSTALL_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            raw = {}
        for k, v in raw.items():
            if v is not None:
                merged[k] = v
        if not merged.get("timezone"):
            merged["timezone"] = _local_tz_name()
        _install = merged
    return _install


def reset_install_cache() -> None:
    """Drop the cached install config (tests point the daemon at tmp dirs)."""
    global _install
    _install = None


def default_tz() -> str:
    return install()["timezone"]


# Back-compat alias: modules and tests that read a module-level constant. This
# is evaluated at import, so SCHEDULER_INSTALL_FILE must be set before import
# (the daemon's launch env does; tests use default_tz()).
DEFAULT_TZ = default_tz()


def expand(path: str) -> Path:
    return Path(os.path.expanduser(str(path)))


def load_defaults() -> dict:
    """Registry `defaults` merged over built-ins (registry may omit keys)."""
    merged = dict(BUILTIN_DEFAULTS)
    try:
        raw = json.loads(SCHEDULE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return merged
    for k, v in (raw.get("defaults") or {}).items():
        if v is not None:
            merged[k] = v
    return merged
