"""`python3 -m scheduler` — the daemon: engine tick loop + control API."""

from __future__ import annotations

import signal
import threading

from . import api, config
from .engine import Engine, _log


def main() -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    engine = Engine()
    server = api.make_server(engine)
    threading.Thread(target=server.serve_forever, daemon=True, name="api").start()
    _log(
        f"scheduler daemon up — api 127.0.0.1:{server.server_address[1]}, "
        f"registry {config.SCHEDULE_FILE}"
    )

    def _term(signum, frame):
        _log("shutdown signal — active runs left running; restart reconciles")
        engine.stop()

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)
    try:
        engine.run_forever()
    finally:
        server.shutdown()
        _log("scheduler daemon down")


if __name__ == "__main__":
    main()
