"""Tunnel pairing — the LAN-only gate and the re-pair rule.

The gate is the whole security value of this endpoint: a caller who is already
inside the tunnel must not be able to mint more peers. These tests drive the
real module against a fake `wg_peer.py`, so the subnet the gate uses is read the
same way production reads it.
"""

import subprocess
import sys
import textwrap

import pytest

from jstack_host import tunnel


FAKE_PEER_SCRIPT = textwrap.dedent('''
    """Stand-in for wg_peer.py — same CLI, same file outputs, no real WireGuard."""
    import sys
    from pathlib import Path

    SUBNET_PREFIX = "10.66.0"
    CLIENTS = Path(__file__).parent / "clients"

    def main():
        cmd = sys.argv[1]
        if cmd == "list":
            CLIENTS.mkdir(exist_ok=True)
            for conf in sorted(CLIENTS.glob("*.conf")):
                if not (CLIENTS / f"{conf.stem}.revoked").exists():
                    print(f"{conf.stem}  10.66.0.9  added 2026-08-28")
            return 0
        if cmd == "add":
            name = sys.argv[2]
            CLIENTS.mkdir(exist_ok=True)
            path = CLIENTS / f"{name}.conf"
            if path.exists():
                print(f"device {name!r} already paired", file=sys.stderr)
                return 1
            path.write_text(
                "[Interface]\\nPrivateKey = KEY-FOR-" + name + "\\n"
                "Address = 10.66.0.9/32\\n\\n[Peer]\\n"
                "PublicKey = SERVERPUB\\nAllowedIPs = 10.66.0.0/24\\n"
                "Endpoint = wg.example.com:51820\\nPersistentKeepalive = 25\\n")
            print(f"paired {name} at 10.66.0.9")
            return 0
        return 2

    sys.exit(main())
''')


@pytest.fixture
def wg(tmp_path, monkeypatch):
    """A hub the tests own end to end: pairing script, conf, clients dir.

    The conf is what makes this a hub rather than just a machine with the
    tools on it — see `can_pair`. A fixture that supplied only the script
    would be modelling a host that cannot exist.
    """
    script = tmp_path / "wg_peer.py"
    script.write_text(FAKE_PEER_SCRIPT)
    conf = tmp_path / "wg0.conf"
    conf.write_text("[Interface]\nPrivateKey = SERVERPRIV\nListenPort = 51820\n")
    monkeypatch.setattr(tunnel, "PEER_SCRIPT", script)
    monkeypatch.setattr(tunnel, "HUB_CONF", conf)
    monkeypatch.setattr(tunnel, "CLIENTS_DIR", tmp_path / "clients")
    return tmp_path


# --- the LAN gate -----------------------------------------------------------

def test_a_caller_inside_the_tunnel_cannot_pair_another_device(wg):
    """The one that matters: a peer must not be able to mint more peers."""
    with pytest.raises(tunnel.PairingRefused, match="own network"):
        tunnel.pair("work-mac", "10.66.0.4")


def test_the_whole_peer_subnet_is_refused_not_just_the_first_address(wg):
    for ip in ("10.66.0.1", "10.66.0.2", "10.66.0.200", "10.66.0.254"):
        with pytest.raises(tunnel.PairingRefused):
            tunnel.pair("work-mac", ip)


def test_a_public_address_cannot_pair(wg):
    # A routable address, not a documentation range — Python counts 203.0.113.0/24
    # as private, so using one here would pass for the wrong reason.
    for ip in ("8.8.8.8", "97.120.113.78"):
        with pytest.raises(tunnel.PairingRefused, match="own network"):
            tunnel.pair("work-mac", ip)


def test_an_unparseable_address_cannot_pair(wg):
    """A missing or malformed client address is refused, never waved through."""
    for ip in ("", "not-an-ip", "10.66.0"):
        with pytest.raises(tunnel.PairingRefused):
            tunnel.pair("work-mac", ip)


def test_a_lan_caller_can_pair(wg):
    result = tunnel.pair("work-mac", "192.168.1.44")
    assert result["created"] is True
    assert "KEY-FOR-work-mac" in result["config"]


def test_loopback_can_pair(wg):
    """The Mac pairing itself against its own host is the desk case."""
    assert tunnel.pair("desk-mac", "127.0.0.1")["created"] is True


def test_the_subnet_is_read_from_the_pairing_script_not_restated(wg, tmp_path):
    """Move the subnet in the script and the gate must move with it.

    Guards the failure this indirection exists to prevent: a hardcoded second
    copy that keeps passing after the real one changed.
    """
    script = tmp_path / "wg_peer.py"
    script.write_text(FAKE_PEER_SCRIPT.replace('SUBNET_PREFIX = "10.66.0"',
                                               'SUBNET_PREFIX = "10.77.0"'))
    assert tunnel.is_lan_caller("10.66.0.4") is True    # no longer the tunnel
    assert tunnel.is_lan_caller("10.77.0.4") is False   # now it is


# --- names ------------------------------------------------------------------

@pytest.mark.parametrize("name", ["", "Work Mac", "../etc/passwd", "UPPER",
                                  "x" * 40, "-leading"])
def test_bad_device_names_are_refused(wg, name):
    with pytest.raises(tunnel.PairingRefused):
        tunnel.pair(name, "192.168.1.44")


# --- re-pairing -------------------------------------------------------------

def test_repairing_returns_the_same_config_and_does_not_rotate_keys(wg):
    first = tunnel.pair("work-mac", "192.168.1.44")
    second = tunnel.pair("work-mac", "192.168.1.44")
    assert second["created"] is False
    assert second["config"] == first["config"]


def test_a_stale_conf_with_no_live_peer_is_not_treated_as_paired(wg):
    """A config file whose peer the host has revoked must not be re-issued —
    handing it back would give the device a key that no longer opens anything."""
    tunnel.pair("work-mac", "192.168.1.44")
    (wg / "clients" / "work-mac.revoked").write_text("")
    assert tunnel.existing_config("work-mac") is None


# --- failures are raised, never returned as an empty success ----------------

def test_a_failing_pairing_script_raises(wg, tmp_path):
    script = tmp_path / "wg_peer.py"
    script.write_text("import sys\nSUBNET_PREFIX='10.66.0'\nsys.exit(3)\n")
    with pytest.raises(tunnel.TunnelError, match="failed"):
        tunnel.pair("work-mac", "192.168.1.44")


def test_a_script_that_claims_success_but_writes_nothing_raises(wg, tmp_path):
    script = tmp_path / "wg_peer.py"
    script.write_text("import sys\nSUBNET_PREFIX='10.66.0'\n"
                      "print('paired')\nsys.exit(0)\n")
    with pytest.raises(tunnel.TunnelError, match="wrote no config"):
        tunnel.pair("work-mac", "192.168.1.44")


def test_a_missing_pairing_script_raises_rather_than_reporting_no_peers(wg, tmp_path):
    """A layer that cannot look must raise, not return the empty shape."""
    import ipaddress
    tunnel.PEER_SCRIPT.unlink()
    with pytest.raises(tunnel.TunnelError):
        tunnel._peer_subnet()


# --- the hub/leaf line ------------------------------------------------------

def test_only_the_host_that_owns_the_mesh_reports_it_can_pair(wg):
    """`can_pair` is the hub test, and the hub is whoever holds `wg0.conf`."""
    assert tunnel.can_pair() is True
    tunnel.HUB_CONF.unlink()
    assert tunnel.can_pair() is False


def test_carrying_the_pairing_tool_does_not_make_a_host_a_hub(wg):
    """The regression the payload introduced, pinned.

    `wg_peer.py` ships to every host now — a Mac cannot be told at install
    time whether it will be a hub. If presence of the script still answered
    this, every leaf would advertise a pairing button whose only possible
    outcome is a failure against a `wg0.conf` it does not have.
    """
    tunnel.HUB_CONF.unlink()
    assert tunnel.PEER_SCRIPT.is_file()
    assert tunnel.can_pair() is False


def test_a_leaf_calls_pairing_unsupported_not_broken(wg):
    """The work Mac's screen, written as a test.

    A leaf has no mesh of its own, and before this the button answered
    `cannot read the pairing script at …/wg_peer.py` — a missing-file error
    for a file that was never meant to be there, on the one machine where
    pairing is nothing to do. The refusal must name the arrangement, and must
    not send anyone looking for a path.
    """
    tunnel.HUB_CONF.unlink()
    with pytest.raises(tunnel.PairingUnsupported) as caught:
        tunnel.pair("jenyas-macbook-pro", "127.0.0.1")
    assert "wg_peer.py" not in str(caught.value)
    assert "does not run the tunnel" in str(caught.value)


def test_a_host_from_before_the_scripts_shipped_is_still_refused_cleanly(wg):
    """An install predating the payload's `scripts/` folder has neither half.
    It is not a broken hub, it is not a hub."""
    tunnel.PEER_SCRIPT.unlink()
    tunnel.HUB_CONF.unlink()
    with pytest.raises(tunnel.PairingUnsupported):
        tunnel.pair("jenyas-macbook-pro", "127.0.0.1")


def test_the_leaf_check_comes_before_the_lan_gate(wg):
    """Order matters: a leaf's own app calls from loopback, which passes the
    LAN gate. If the gate ran first the leaf would go on to shell out against
    a conf that is not there, which is the 500 this replaces."""
    tunnel.HUB_CONF.unlink()
    with pytest.raises(tunnel.PairingUnsupported):
        tunnel.pair("bad name!", "10.66.0.4")
