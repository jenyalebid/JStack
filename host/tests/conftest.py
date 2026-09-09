"""Fixtures for the host package's own tests.

Two of these are autouse and both exist for the same reason: this package's
modules resolve their state at *call* time, against the real machine, and a
test that authenticates or opens a session would otherwise write into the
running host's live registry. The tests all pass either way — the damage lands
on the machine, not in the report, which is why the isolation is autouse and
not something each test opts into.

`app` is the standalone application, `server.create_app()`. When the host is
embedded in a larger process (this package is designed to be mountable) that
process builds its own; the package's own tests exercise the one the package
ships, so a route that only works when someone else mounts it fails here.
"""

import pytest


@pytest.fixture
def app():
    """The standalone host app, built fresh per test.

    Fresh because `create_app()` closes over module state that other fixtures
    monkeypatch — a module-level singleton would capture whichever test built
    it first.
    """
    from jstack_host.server import create_app
    return create_app()


@pytest.fixture(autouse=True)
def _isolate_devices(tmp_path, monkeypatch):
    """Every test authenticates against its own device table, never the real
    store's — auth reads (and on first use writes) the `devices` table, and a
    TestClient request must not fold a test token into this machine's live
    registry. Lazy: only tests that actually authenticate pay for a store."""
    from jstack_host import auth, devices

    holder = {}

    def _test_store():
        if "s" not in holder:
            from jstack_host.store import SessionStore
            holder["s"] = SessionStore(db_path=tmp_path / "devices-probe.sqlite")
        return holder["s"]

    monkeypatch.setattr(devices, "_store", _test_store)
    devices.reset_for_tests()
    auth.reset_limiter()


@pytest.fixture(autouse=True)
def _isolate_open_registry(tmp_path, monkeypatch):
    """Point the open-session registry at a temp file for every test.

    `managed._reg_mutate` is load-modify-SAVE: any test that reaches
    `record_open`/`record_close` — even via a monkeypatched `_reg_load` —
    rewrites the whole file at `_REG`. Against the real path that wipe is
    invisible to the tests and lands on whoever is using the host: every open
    session's registry entry is gone, so the board demotes them all to
    watch-only windows while their sessions run on untouched."""
    from jstack_host import managed
    monkeypatch.setattr(managed, "_REG", tmp_path / "jremote_open.json")
