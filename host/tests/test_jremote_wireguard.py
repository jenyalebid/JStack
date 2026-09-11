"""The WireGuard mesh tooling actually ships, and the three readers of its
state agree on where that state is.

`test_jremote_tunnel` drives `tunnel.py` against a *fake* `wg_peer.py`, which is
the right shape for testing the pairing gate but proves nothing about the real
script — a payload that shells out to `hostenv.peer_script()` is worth exactly
as much as the file being there. Before these tests the file was there on no
install: `hostenv.peer_script()` named a path nothing shipped, so `can_pair()`
was permanently False and every host was local-only whatever mode it claimed.

Two things are pinned here that a fake cannot pin:
  1. the real script and its leaf templates ship at the path the package names;
  2. the *one* directory the hub keeps its keys in has three independent readers
     — `install_hub.sh` (writes it, under sudo), `wg_peer.py` (the tool that
     edits the peer table), and `tunnel.py` (the server that shells out to it) —
     and a default that drifts between them is a hub that pairs into a directory
     its own server never reads.

Everything runs against a fake `wg` binary and a temp state dir; nothing here
brings up an interface or touches the network.
"""

import ipaddress
import os
import subprocess
import sys
from pathlib import Path

import pytest

from jstack_host import hostenv, tunnel


WG_ROOT = hostenv.peer_script().parent
LEAF_TEMPLATES = ("wg_up.sh", "wg_leaf_watch.sh", "install_leaf.sh")
HUB_SCRIPTS = ("wg_sync.sh", "install_hub.sh")


# --- 1. the payload actually ships ------------------------------------------

def test_the_pairing_tool_ships_at_the_path_the_package_names():
    """`hostenv.peer_script()` is a promise; this is the file keeping it."""
    script = hostenv.peer_script()
    assert script.is_file(), f"the payload names {script} but nothing ships there"
    assert script.name == "wg_peer.py"


def test_the_leaf_templates_ship_beside_the_tool():
    """`wg_peer.py add --leaf` copies these out of its own directory into the
    bundle it emits — a missing one is a leaf that installs and cannot come up,
    and it fails at pairing time on the hub, far from where anyone would look."""
    for name in LEAF_TEMPLATES:
        assert (WG_ROOT / name).is_file(), f"leaf bundle would be missing {name}"


def test_the_hub_scripts_ship_beside_the_tool():
    for name in HUB_SCRIPTS:
        assert (WG_ROOT / name).is_file(), f"a hub cannot be stood up without {name}"


# --- 2. one location, three readers -----------------------------------------

def _wg_peer_default_dir() -> Path:
    """`wg_peer.py`'s own default, computed the way the script computes it:
    `parents[2]/Credentials/wireguard` from the script's location."""
    return hostenv.peer_script().resolve().parents[2] / "Credentials" / "wireguard"


def _tunnel_default_dir() -> Path:
    """What the server resolves with `WG_PEER_DIR` out of the picture — the
    profile's answer, which for the default profile is the package root."""
    return hostenv.wireguard_dir()


@pytest.mark.skipif("WG_PEER_DIR" in os.environ,
                    reason="WG_PEER_DIR is set, so both readers are honouring "
                           "it and the defaults are not what is in play")
def test_the_tool_and_the_server_default_to_the_same_directory():
    """The reconciliation this file exists for: `wg_peer.py` writing one
    directory while `tunnel.py` reads another is a hub that pairs a device and
    then reports it cannot pair, because `can_pair()` looks at the wrong conf.

    Asserted against the *tool this host actually runs* rather than against a
    fixed path, which is the half that was missing: `peer_script()` has always
    been a profile answer and `WG_DIR` was not, so a host whose tooling lives
    outside the package tree read `<package>/Credentials/wireguard` while its
    own daemons drove another directory entirely. That is jStack#42 — the Mac
    holding `10.66.0.1` and five peers reporting itself `local`, with
    `/tunnel/pair` answering 503 on the one machine that owns the mesh. The
    relationship, not the literal, is what has to hold on every profile.
    """
    assert _wg_peer_default_dir() == _tunnel_default_dir()


def test_the_directory_is_a_profile_answer_and_follows_the_tool(monkeypatch):
    """A host whose mesh predates the package: the profile names both, and the
    server has to follow it rather than the tree it was imported from."""
    class Elsewhere:
        def peer_script(self):
            return Path("/opt/mesh/scripts/wireguard/wg_peer.py")

        def wireguard_dir(self):
            return Path("/opt/mesh/Credentials/wireguard")

    monkeypatch.delenv("WG_PEER_DIR", raising=False)
    monkeypatch.setattr(hostenv, "profile", lambda: Elsewhere())
    assert hostenv.wireguard_dir() == Path("/opt/mesh/Credentials/wireguard")


def test_a_profile_that_predates_the_question_still_resolves(monkeypatch):
    """An external profile is somebody else's file. A package upgrade that
    raises AttributeError on their machine is a package that broke them, so the
    seam falls back to the package default instead of insisting."""
    class Older:
        pass

    monkeypatch.delenv("WG_PEER_DIR", raising=False)
    monkeypatch.setattr(hostenv, "profile", lambda: Older())
    assert hostenv.wireguard_dir() == (
        hostenv.package_root() / "Credentials" / "wireguard")


def test_adopting_the_agents_environment_carries_the_mesh_and_rebinds(
        tmp_path, monkeypatch):
    """The other half of #42, from the other side: a shell has none of the
    installed agent's environment, and `WG_PEER_DIR` is the variable that says
    where the mesh is. Adopted after `tunnel` already resolved, it has to move
    the paths that were bound at import — a process reading one directory while
    its own daemons write another is the whole defect."""
    from jstack_host import install_host

    plist = tmp_path / "com.jremote.host.plist"
    mesh = tmp_path / "elsewhere" / "wireguard"
    plist.write_bytes(install_host.plistlib.dumps({
        "Label": "com.jremote.host",
        "EnvironmentVariables": {"JREMOTE_STATE_DIR": str(tmp_path / "state"),
                                 "WG_PEER_DIR": str(mesh)},
    }))
    assert install_host.installed_environment(plist)["WG_PEER_DIR"] == str(mesh)

    # Pinned so monkeypatch puts them back: `rebind()` reassigns module state,
    # and a test that leaves the process pointed at a tmp dir breaks the ones
    # after it rather than itself.
    for name in ("PEER_SCRIPT", "WG_DIR", "CLIENTS_DIR", "HUB_CONF"):
        monkeypatch.setattr(tunnel, name, getattr(tunnel, name))
    monkeypatch.delenv("WG_PEER_DIR", raising=False)
    monkeypatch.setattr(os, "environ", dict(os.environ))
    install_host.adopt_installed_environment(plist)
    assert tunnel.WG_DIR == mesh
    assert tunnel.HUB_CONF == mesh / "wg0.conf"
    assert tunnel.CLIENTS_DIR == mesh / "clients"


def test_the_env_wins_over_the_profile(monkeypatch):
    """`WG_PEER_DIR` is the variable `wg_peer.py` itself honours, so it has to
    outrank the profile here too — the tool and its readers move together or
    the split comes back under a different name."""
    class Elsewhere:
        def wireguard_dir(self):
            return Path("/opt/mesh/Credentials/wireguard")

    monkeypatch.setenv("WG_PEER_DIR", "/tmp/somewhere-else")
    monkeypatch.setattr(hostenv, "profile", lambda: Elsewhere())
    assert hostenv.wireguard_dir() == Path("/tmp/somewhere-else")


def test_install_hub_writes_into_that_same_directory():
    """`install_hub.sh` derives `WG_DIR` from `$SRC/../../Credentials/wireguard`.
    With the scripts at `scripts/wireguard/`, that is the package root — the
    same place the other two readers resolve to. Pinned by reading the script,
    so a relocation that breaks the chain fails here, not on a customer's Mac."""
    src = (hostenv.peer_script().read_text(), (WG_ROOT / "install_hub.sh").read_text())
    hub = src[1]
    assert 'WG_DIR="$(cd "$SRC/../.." && pwd)/Credentials/wireguard"' in hub, (
        "install_hub.sh no longer roots WG_DIR at <package>/Credentials/wireguard "
        "— reconcile it with tunnel.WG_DIR or the hub pairs where nothing reads")


@pytest.mark.skipif("WG_PEER_DIR" in os.environ,
                    reason="WG_PEER_DIR is set, so the module is honouring it, "
                           "not the default this asserts")
def test_the_server_uses_that_default_when_nothing_relocates_it():
    assert tunnel.WG_DIR == _tunnel_default_dir()


def test_the_server_reads_the_subnet_out_of_the_real_script(monkeypatch):
    """`tunnel._peer_subnet()` parses `SUBNET_PREFIX` out of `wg_peer.py` rather
    than restating it. The existing suite proves that against a fake; this proves
    the *real* script still declares it in a form the parser accepts (it uses the
    `os.environ.get(..., "10.66.0")` override form, not a bare assignment)."""
    monkeypatch.setattr(tunnel, "PEER_SCRIPT", hostenv.peer_script())
    assert tunnel._peer_subnet() == ipaddress.ip_network("10.66.0.0/24")


# --- 3. the real tool pairs, lists, emits a leaf bundle, and revokes ---------

@pytest.fixture
def hub(tmp_path):
    """A hub the test owns end to end, against a fake `wg`: server keys, an
    empty conf, an endpoint, and `WG_PEER_DIR` pointing the real `wg_peer.py`
    at it. No interface, no network — just the file surgery pairing is."""
    wg_dir = tmp_path / "wireguard"
    (wg_dir / "clients").mkdir(parents=True)
    (wg_dir / "server.key").write_text("SERVER-PRIVATE-KEY\n")
    (wg_dir / "server.pub").write_text("SERVER-PUBLIC-KEY\n")
    (wg_dir / "wg0.conf").write_text(
        "[Interface]\nPrivateKey = SERVER-PRIVATE-KEY\nListenPort = 51820\n")
    (wg_dir / "endpoint").write_text("hub.example.com:51820\n")

    fake_wg = tmp_path / "fake-wg"
    fake_wg.write_text(
        "#!/bin/bash\n"
        'case "$1" in\n'
        '  genkey) echo "CLIENT-PRIVATE-KEY" ;;\n'
        '  pubkey) cat >/dev/null; echo "CLIENT-PUBLIC-KEY" ;;\n'
        "  *) exit 0 ;;\n"
        "esac\n")
    fake_wg.chmod(0o755)

    env = {
        **os.environ,
        "WG_PEER_DIR": str(wg_dir),
        "WG_BIN": str(fake_wg),
        "WG_ENDPOINT": "hub.example.com:51820",
    }
    return wg_dir, env


def _run_peer(env, *args):
    return subprocess.run(
        [sys.executable, str(hostenv.peer_script()), *args],
        capture_output=True, text=True, env=env, timeout=60)


def test_the_real_tool_pairs_a_device(hub):
    wg_dir, env = hub
    r = _run_peer(env, "add", "work-mac")
    assert r.returncode == 0, r.stderr
    assert "# device: work-mac" in (wg_dir / "wg0.conf").read_text()
    conf = (wg_dir / "clients" / "work-mac.conf").read_text()
    assert "PrivateKey = CLIENT-PRIVATE-KEY" in conf
    assert "Endpoint = hub.example.com:51820" in conf
    assert "AllowedIPs = 10.66.0.0/24" in conf


def test_the_real_tool_refuses_a_second_pairing_of_one_name(hub):
    _, env = hub
    assert _run_peer(env, "add", "work-mac").returncode == 0
    again = _run_peer(env, "add", "work-mac")
    assert again.returncode != 0
    assert "already paired" in again.stderr


def test_the_real_tool_lists_what_it_paired(hub):
    _, env = hub
    _run_peer(env, "add", "work-mac")
    _run_peer(env, "add", "phone")
    out = _run_peer(env, "list").stdout
    assert "work-mac" in out and "phone" in out


def test_a_leaf_bundle_carries_every_file_the_installer_reads(hub):
    """`tunnel.LEAF_FILES` is what the server hands back and what the leaf
    installs from; the tool must write all of them or the bundle installs a
    tunnel that cannot start. Assert against `tunnel.LEAF_FILES` so the two
    lists cannot drift apart."""
    wg_dir, env = hub
    r = _run_peer(env, "add", "--leaf", "studio")
    assert r.returncode == 0, r.stderr
    bundle = wg_dir / "clients" / "studio-leaf"
    for name in tunnel.LEAF_FILES:
        assert (bundle / name).is_file(), f"leaf bundle is missing {name}"
    assert "Address" not in (bundle / "jrleaf.conf").read_text(), (
        "jrleaf.conf is setconf-style — an Address line makes `wg setconf` reject it")


def test_revoking_removes_the_peer_and_the_client_files(hub):
    wg_dir, env = hub
    _run_peer(env, "add", "work-mac")
    assert _run_peer(env, "remove", "work-mac").returncode == 0
    assert "# device: work-mac" not in (wg_dir / "wg0.conf").read_text()
    assert not (wg_dir / "clients" / "work-mac.conf").exists()
