"""`mode` decides which of local / open / managed a running host is.

The taxonomy is the whole point, so most of these pin `classify` — the pure
core — against fixed facts: a fresh machine is local, a hub that publishes an
endpoint is open, a machine with a leaf daemon is managed even with its tunnel
down. The rest pin the three seams that read this machine's own state, because
each is a place the verdict could quietly start reading the wrong thing.
"""

import ipaddress

import pytest

from jstack_host import mode


# ── the taxonomy: classify() against fixed facts ──

def test_a_fresh_machine_is_local():
    v = mode.classify(leaf_installed=False, on_mesh=False,
                      is_hub=False, endpoint=False)
    assert v["mode"] == "local"
    assert v["live"] is True


def test_a_hub_that_publishes_an_endpoint_is_open():
    # A hub always holds 10.66.0.1 on its own interface, so on_mesh is True too.
    v = mode.classify(leaf_installed=False, on_mesh=True,
                      is_hub=True, endpoint=True)
    assert v["mode"] == "open"
    assert "not verified" in v["note"]


def test_a_hub_with_no_endpoint_is_local_not_open():
    # A mesh nobody outside can dial is not off-network reachability.
    v = mode.classify(leaf_installed=False, on_mesh=True,
                      is_hub=True, endpoint=False)
    assert v["mode"] == "local"


def test_a_leaf_with_its_tunnel_up_is_managed_and_live():
    v = mode.classify(leaf_installed=True, on_mesh=True,
                      is_hub=False, endpoint=False)
    assert v["mode"] == "managed"
    assert v["live"] is True


def test_a_leaf_with_its_tunnel_down_is_still_managed_but_not_live():
    v = mode.classify(leaf_installed=True, on_mesh=False,
                      is_hub=False, endpoint=False)
    assert v["mode"] == "managed"
    assert v["live"] is False
    assert "DOWN" in v["note"]


def test_on_the_mesh_without_a_leaf_record_is_still_managed():
    v = mode.classify(leaf_installed=False, on_mesh=True,
                      is_hub=False, endpoint=False)
    assert v["mode"] == "managed"
    assert "no local leaf install record" in v["note"]


def test_a_hub_is_never_read_as_managed_even_with_a_stray_leaf_plist():
    # Owning the mesh wins: a hub is independent, never a leaf of itself.
    v = mode.classify(leaf_installed=True, on_mesh=True,
                      is_hub=True, endpoint=True)
    assert v["mode"] == "open"


# ── the seams: reading this machine's own state ──

def test_leaf_installed_reflects_the_plist(tmp_path, monkeypatch):
    plist = tmp_path / "com.jremote.leaf.plist"
    monkeypatch.setattr(mode, "LEAF_PLIST", plist)
    assert mode._leaf_installed() is False
    plist.write_text("<plist/>")
    assert mode._leaf_installed() is True


def test_on_mesh_finds_a_mesh_address_and_ignores_the_rest():
    assert mode._on_mesh(["192.168.1.5", "10.66.0.7", "fe80::1"]) is True
    assert mode._on_mesh(["192.168.1.5", "not-an-ip", ""]) is False
    assert mode._on_mesh([]) is False


def test_endpoint_declared_honours_the_env_first(monkeypatch):
    monkeypatch.setenv("WG_ENDPOINT", "cafe.example:51820")
    assert mode._endpoint_declared() is True


def test_endpoint_declared_reads_the_file_when_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("WG_ENDPOINT", raising=False)
    wg_dir = tmp_path / "wireguard"
    wg_dir.mkdir()
    monkeypatch.setattr(mode.tunnel, "WG_DIR", wg_dir)
    assert mode._endpoint_declared() is False
    (wg_dir / "endpoint").write_text("home.example:51820")
    assert mode._endpoint_declared() is True


def test_current_wires_the_seams(monkeypatch):
    # No mesh, no leaf, no hub, no endpoint → the machine is local.
    monkeypatch.setattr(mode, "_leaf_installed", lambda: False)
    monkeypatch.setattr(mode.addresses, "_inet_addrs", lambda: ["192.168.1.9"])
    monkeypatch.setattr(mode.tunnel, "can_pair", lambda: False)
    monkeypatch.setattr(mode, "_endpoint_declared", lambda: False)
    assert mode.current()["mode"] == "local"
