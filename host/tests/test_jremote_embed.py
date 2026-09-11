"""embed — the record a host with no LaunchAgent leaves for the shell.

The failure these pin is one machine answering two ways about itself. A host
mounted inside another server is described by a profile importable only from
that server's import root, so `jstack-host` typed into a terminal imported
nothing, fell back to the default profile, and reported a live host as `not
installed` with `NO TOKEN` and a state dir nothing was reading. See #34 — the
wrong answer cost a session and nearly a second host installed beside the real
one.
"""

import json
import os
import sys
from pathlib import Path

import pytest

from jstack_host import doctor, embed, hostenv, install_host

#: The variables `embed.adopt` writes. It sets them on `os.environ` directly —
#: it has to, because the whole job is changing what the *process* resolves —
#: so monkeypatch cannot undo them and the fixture below does it by hand.
ADOPTED = ("JREMOTE_PROFILE_MODULE", "JREMOTE_STATE_DIR", "JREMOTE_TOKEN_PATH")


class Embedded:
    """The shape of a profile that declares itself mounted elsewhere."""

    name = "jj"
    embedded_in = "the dashboard"

    def __init__(self, state: Path):
        self._state = state

    def state_dir(self) -> Path:
        return self._state

    def token_path(self, state: Path) -> Path:
        return state.parent / "Credentials" / "jremote-api-token"


@pytest.fixture(autouse=True)
def marker(tmp_path, monkeypatch):
    """Every test writes its own marker. Never the real one: this file lives
    at a fixed path under the user's home, and the machine the tests run on is
    usually a machine with a live embedded host recorded there."""
    path = tmp_path / "state" / "embedded.json"
    monkeypatch.setenv(embed.MARKER_ENV, str(path))
    saved = {k: os.environ.get(k) for k in ADOPTED}
    hostenv.reset_profile()
    yield path
    for key, value in saved.items():
        os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)
    hostenv.reset_profile()


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A throwaway HOME, so `~/Library/LaunchAgents` is under tmp."""
    h = tmp_path / "home"
    (h / "Library" / "LaunchAgents").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(h))
    return h


@pytest.fixture
def standalone(tmp_path, monkeypatch):
    """A host with its own state dir and no embedding tree assumptions."""
    monkeypatch.setenv("JREMOTE_HOST_PROFILE", "default")
    monkeypatch.setenv("JREMOTE_STATE_DIR", str(tmp_path / "standalone"))
    monkeypatch.setenv("JREMOTE_INSTANCE_ROOT", str(tmp_path / "Agents"))
    (tmp_path / "Agents").mkdir(exist_ok=True)
    hostenv.reset_profile()


@pytest.fixture
def embedded(tmp_path, monkeypatch):
    state = tmp_path / "dashboard" / "state"
    state.mkdir(parents=True)
    profile = Embedded(state)
    monkeypatch.setattr(hostenv, "profile", lambda: profile)
    return profile


# ── declaring ──

def test_an_embedded_host_records_what_a_shell_cannot_work_out(
        embedded, marker, monkeypatch):
    monkeypatch.setattr(hostenv, "state_dir", lambda: embedded.state_dir())
    monkeypatch.setattr(hostenv, "token_path",
                        lambda: embedded.token_path(embedded.state_dir()))

    assert embed.declare(port=9090) == marker
    record = json.loads(marker.read_text())
    assert record["server"] == "the dashboard"
    assert record["port"] == 9090
    assert record["profile"] == "jj"
    assert record["state_dir"] == str(embedded.state_dir())
    assert record["token_path"].endswith("jremote-api-token")


def test_a_standalone_host_leaves_no_record_claiming_otherwise(
        home, standalone, marker):
    """`embedded_in` decides, not the caller.

    The same answer `doctor` and `status` grade on. A standalone host that
    called this by mistake must not be able to leave a file redirecting every
    later command onto a host that isn't there.
    """
    assert embed.declare(port=9090) is None
    assert not marker.exists()


def test_the_marker_is_never_read_half_written(embedded, marker, monkeypatch):
    """Written whole and moved into place.

    A reader catching this mid-write gets no JSON, falls back to the default
    profile and reports the host as absent — the exact failure being fixed,
    arriving intermittently.
    """
    monkeypatch.setattr(hostenv, "state_dir", lambda: embedded.state_dir())
    monkeypatch.setattr(hostenv, "token_path",
                        lambda: embedded.token_path(embedded.state_dir()))
    embed.declare(port=9090)
    seen = []
    real = Path.replace

    def watched(self, target):
        seen.append((self.suffix, Path(target).exists()))
        return real(self, target)

    monkeypatch.setattr(Path, "replace", watched)
    embed.declare(port=9091)
    assert seen == [(".tmp", True)]
    assert json.loads(marker.read_text())["port"] == 9091


def test_a_hand_mangled_marker_is_no_marker(marker):
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{not json")
    assert embed.read() == {}
    assert embed.adopt() is False
    assert embed.port() is None


# ── adopting ──

def _write(marker: Path, **fields) -> None:
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(fields))


def test_adopting_imports_the_profile_off_the_recorded_root(
        marker, tmp_path, monkeypatch):
    """The whole point: the profile lives on the embedding server's import
    root, and this is how a shell reaches it."""
    root = tmp_path / "Infrastructure"
    root.mkdir()
    (root / "embedded_probe_profile.py").write_text(
        "class P:\n"
        "    name = 'jj'\n"
        "    embedded_in = 'the dashboard'\n"
        "def make_profile():\n"
        "    return P()\n")
    _write(marker, server="the dashboard", port=9090, root=str(root),
           profile_module="embedded_probe_profile")
    monkeypatch.delenv("JREMOTE_HOST_PROFILE", raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))

    assert embed.adopt() is True
    assert hostenv.profile().name == "jj"
    assert embed.server() == "the dashboard"


def test_the_recorded_root_never_goes_ahead_of_this_package(
        marker, tmp_path, monkeypatch):
    """Appended, never prepended.

    It is another application's import root — the one this was written for
    holds a `lib/` and a `dashboard/` — and ahead of `sys.path` it would shadow
    this package's own imports, and the standard library's, for the rest of the
    process.
    """
    root = tmp_path / "Infrastructure"
    root.mkdir()
    _write(marker, server="the dashboard", port=9090, root=str(root),
           profile_module="nothing_importable")
    monkeypatch.setattr(sys, "path", list(sys.path))

    assert embed.adopt() is True
    assert sys.path[-1] == str(root)


def test_a_root_that_is_gone_is_not_put_on_the_path(marker, tmp_path, monkeypatch):
    _write(marker, server="the dashboard", port=9090,
           root=str(tmp_path / "moved-away"), profile_module="nothing_importable")
    monkeypatch.setattr(sys, "path", list(sys.path))

    assert embed.adopt() is True
    assert str(tmp_path / "moved-away") not in sys.path


def test_the_recorded_answers_carry_where_the_profile_cannot_import(
        marker, tmp_path, monkeypatch):
    """The ordinary case, and the reason the marker holds answers at all.

    The embedding server runs its own virtualenv with its own modules; the
    interpreter `pip install jstack-host` put `jstack-host` in usually cannot
    import that profile however well it is pointed at it. A marker that only
    pointed would work on one Mac and not the next.
    """
    state = tmp_path / "dashboard" / "state"
    token = tmp_path / "Credentials" / "jremote-api-token"
    _write(marker, server="the dashboard", port=9090, root="",
           profile_module="a_module_this_python_cannot_import",
           state_dir=str(state), token_path=str(token))
    for key in ("JREMOTE_STATE_DIR", "JREMOTE_TOKEN_PATH"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("JREMOTE_HOST_PROFILE", "auto")

    assert embed.adopt() is True
    assert hostenv.state_dir() == state
    assert hostenv.token_path() == token
    # Still named as embedded, off the record, with no profile to ask.
    assert embed.server() == "the dashboard"


def test_an_explicit_export_still_wins(marker, tmp_path, monkeypatch):
    """Beneath the environment, exactly like the plist. `--state-dir` and a
    deliberate export are how someone asks about a *second* host."""
    mine = tmp_path / "mine"
    _write(marker, server="the dashboard", port=9090, root="",
           profile_module="a_module_this_python_cannot_import",
           state_dir=str(tmp_path / "theirs"))
    monkeypatch.setenv("JREMOTE_STATE_DIR", str(mine))

    assert embed.adopt() is True
    assert hostenv.state_dir() == mine


def test_no_marker_is_not_an_error(marker):
    assert embed.adopt() is False
    assert embed.read() == {}
    assert embed.server() == ""


def test_a_nonsense_port_is_not_a_port(marker):
    _write(marker, server="the dashboard", port=70000)
    assert embed.port() is None
    _write(marker, server="the dashboard", port=9099)
    assert embed.port() == 9099


# ── the two commands agreeing ──

def test_status_and_doctor_say_the_same_thing_about_one_machine(
        home, standalone, marker, monkeypatch, capsys):
    """Half of #34: `doctor` branched on `embedded_in` from the day it was
    written and `status` did not, so a shell that could not import the profile
    got `embedded in the dashboard` from one and `LaunchAgent not installed`
    from the other — about the same Mac, seconds apart."""
    _write(marker, server="the dashboard", port=9090, root="",
           profile_module="a_module_this_python_cannot_import")
    monkeypatch.setattr(install_host, "health", lambda *a, **k: None)
    monkeypatch.setattr(install_host, "api_answers", lambda *a, **k: True)
    monkeypatch.setattr(install_host, "is_loaded", lambda *a, **k: False)

    install_host.status()
    out = capsys.readouterr().out
    assert "embedded in the dashboard" in out
    assert "not installed" not in out
    assert doctor.check_service()["detail"] == "embedded in the dashboard"


def test_a_host_with_no_shared_token_file_is_not_a_broken_host(
        home, standalone, monkeypatch, capsys):
    """`doctor` graded the file and `status` graded the host.

    So on a machine whose devices all authenticate from the store — every
    embedded host, and any host old enough to have retired the shared file —
    `doctor` printed FAIL and *the host cannot serve chats until the failures
    above are fixed*, two lines of output away from `status` calling the same
    host provisioned.
    """
    from jstack_host import devices
    monkeypatch.setattr(devices, "provisioned", lambda: True)
    assert not hostenv.token_path().exists()

    token = doctor.check_token()
    assert token["grade"] == doctor.OK
    assert "devices authenticate from this host's store" in token["detail"]

    monkeypatch.setattr(devices, "provisioned", lambda: False)
    assert doctor.check_token()["grade"] == doctor.FAIL


def test_status_probes_the_port_the_embedded_host_declared(
        home, standalone, marker, monkeypatch, capsys):
    """`serving 9090` was right by luck on the machine this was found on.
    A dashboard on any other port would have been reported absent."""
    _write(marker, server="the dashboard", port=9099, root="",
           profile_module="a_module_this_python_cannot_import")
    probed: list[int] = []
    monkeypatch.setattr(install_host, "health", lambda p, *a, **k: probed.append(p))
    monkeypatch.setattr(install_host, "api_answers", lambda *a, **k: True)

    install_host.status()
    assert probed == [9099]
    assert "serving    9099" in capsys.readouterr().out


def test_an_installed_agent_beats_a_stale_marker(home, standalone, marker,
                                                 monkeypatch):
    """A LaunchAgent is a host somebody put there on purpose. A marker left
    over from an embedding server that has since gone must not redirect a
    command onto a different host's state."""
    theirs = Path.home() / "theirs"
    _write(marker, server="the dashboard", port=9090, root="",
           profile_module="a_module_this_python_cannot_import",
           state_dir=str(theirs))
    mine = hostenv.state_dir()
    install_host.plist_path().write_bytes(install_host.render_plist())
    monkeypatch.delenv("JREMOTE_STATE_DIR")
    hostenv.reset_profile()

    install_host.adopt_host_environment()
    assert hostenv.state_dir() == mine


# ── the label ──

def test_the_label_a_read_command_looks_under_can_be_moved(monkeypatch):
    """The one host variable no environment could move.

    `LABEL` is a literal and `--label` defaulted to it, so on a Mac whose host
    is embedded every `jstack-host` adopted a plist that does not exist and
    then answered about whatever the ambient environment held. The menu bar was
    not affected, and that is what hid it: its own LaunchAgent sets
    `JREMOTE_STATE_DIR` directly, so the tool it spawns lands on the right host
    by a different road.
    """
    monkeypatch.delenv("JREMOTE_AGENT_LABEL", raising=False)
    assert install_host.agent_label() == install_host.LABEL

    monkeypatch.setenv("JREMOTE_AGENT_LABEL", "com.jarvis.dashboard")
    assert install_host.agent_label() == "com.jarvis.dashboard"
    # An explicit flag still wins over the ambient answer.
    assert install_host.agent_label("com.jremote.host.test") == \
        "com.jremote.host.test"


@pytest.mark.parametrize("action", ["install", "uninstall"])
def test_writing_commands_never_take_the_label_from_the_environment(
        action, monkeypatch):
    """On this Mac that variable is `com.jarvis.dashboard`.

    An install honouring it would render its plist over the dashboard's own
    LaunchAgent, and an uninstall would bootout and delete it. The variable
    answers "where is the host on this Mac"; it was never a licence to write
    there.
    """
    monkeypatch.setenv("JREMOTE_AGENT_LABEL", "com.jarvis.dashboard")
    seen = {}
    monkeypatch.setattr(install_host, action,
                        lambda **kw: seen.update(kw) or 0)

    assert install_host.main([action]) == 0
    assert seen["label"] == install_host.LABEL
