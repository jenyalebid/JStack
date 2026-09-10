"""`open_mode` guides a host into open mode and — the load-bearing half — tells
the truth about whether the forward actually works.

The feature's whole claim is that it never asserts reachability it did not
observe, so most of these pin the honest path: NAT-PMP answers parsed from canned
router bytes (no router), handshake evidence parsed from canned `wg show` output
(no interface, no network), and `verify()`/`guide()` driven against those. Every
external edge is injected exactly so this can be true without touching a machine.
"""

import socket
import struct
import types

import pytest

from jstack_host import open_mode


# ── fakes for the injected edges ──

class FakeSock:
    """A NAT-PMP socket that answers by the opcode of what was sent.

    `open_mode` passes this in, so no real datagram leaves the test. `sendto`
    records the request and remembers its opcode (byte 1); `recvfrom` returns
    the canned response registered for that opcode, or b"" for "router silent".
    """

    def __init__(self, responses):
        self.responses = responses
        self.sent = []
        self._opcode = None

    def sendto(self, payload, addr):
        self.sent.append((payload, addr))
        self._opcode = payload[1]

    def recvfrom(self, _n):
        return self.responses.get(self._opcode, b""), ("gw", open_mode.NATPMP_PORT)


def _extip_response(ip, *, opcode=128, result=0, epoch=42):
    # version(1) opcode(1) result(2) epoch(4) ip(4)
    return struct.pack("!BBHI", 0, opcode, result, epoch) + socket.inet_aton(ip)


def _map_response(ext_port, *, opcode=129, result=0, epoch=42,
                  internal=51820, lifetime=7200):
    # version opcode result epoch internal-port external-port lifetime
    return struct.pack("!BBHIHHI", 0, opcode, result, epoch,
                       internal, ext_port, lifetime)


def _runner(outputs):
    """A subprocess.run stand-in that answers `wg show <iface> <field>` and
    `route -n get default` from a dict keyed on the distinguishing arg."""
    def run(argv, **_kw):
        if argv[:2] == ["/sbin/route", "-n"]:
            return types.SimpleNamespace(stdout=outputs.get("route", ""))
        # [wg, "show", iface, field]
        return types.SimpleNamespace(stdout=outputs.get(argv[3], ""))
    return run


# ── NAT-PMP: external IP (opcode 0 → 128) ──

def test_external_ip_reads_the_router_answer():
    sock = FakeSock({0: _extip_response("203.0.113.9")})
    assert open_mode.natpmp_external_ip("192.168.1.1", sock) == "203.0.113.9"
    # It asked opcode 0 of the gateway on the NAT-PMP port.
    payload, addr = sock.sent[0]
    assert payload == struct.pack("!BB", 0, 0)
    assert addr == ("192.168.1.1", open_mode.NATPMP_PORT)


def test_external_ip_empty_when_no_gateway():
    assert open_mode.natpmp_external_ip("", FakeSock({})) == ""


def test_external_ip_empty_on_nonzero_result_code():
    sock = FakeSock({0: _extip_response("203.0.113.9", result=3)})
    assert open_mode.natpmp_external_ip("192.168.1.1", sock) == ""


def test_external_ip_empty_when_router_silent():
    assert open_mode.natpmp_external_ip("192.168.1.1", FakeSock({})) == ""


def test_external_ip_empty_on_wrong_opcode():
    sock = FakeSock({0: _extip_response("203.0.113.9", opcode=200)})
    assert open_mode.natpmp_external_ip("192.168.1.1", sock) == ""


# ── NAT-PMP: map UDP (opcode 1 → 129) ──

def test_map_udp_reports_the_mapped_port():
    sock = FakeSock({1: _map_response(51820)})
    r = open_mode.natpmp_map_udp("192.168.1.1", 51820, sock=sock)
    assert r["ok"] is True
    assert r["external_port"] == 51820
    # opcode 1 (UDP), internal and suggested-external both the asked port.
    payload, _ = sock.sent[0]
    op, port_internal = payload[1], struct.unpack("!H", payload[4:6])[0]
    assert op == 1 and port_internal == 51820


def test_map_udp_not_ok_when_router_silent():
    r = open_mode.natpmp_map_udp("192.168.1.1", 51820, sock=FakeSock({}))
    assert r["ok"] is False
    assert "by hand" in r["detail"]


def test_map_udp_not_ok_on_refusal_result_code():
    sock = FakeSock({1: _map_response(0, result=2)})
    r = open_mode.natpmp_map_udp("192.168.1.1", 51820, sock=sock)
    assert r["ok"] is False
    assert "refused" in r["detail"]


def test_map_udp_not_ok_when_no_gateway():
    r = open_mode.natpmp_map_udp("", 51820, sock=FakeSock({}))
    assert r["ok"] is False
    assert "gateway" in r["detail"]


def test_natpmp_exchange_survives_a_socket_error():
    class Boom:
        def sendto(self, *a):
            raise OSError("no route to host")
        def recvfrom(self, _n):
            raise AssertionError("should not be reached")
    assert open_mode._natpmp_exchange("192.168.1.1", b"\0\0", Boom()) == b""


# ── the default gateway ──

def test_default_gateway_parses_route_output():
    out = ("   route to: default\ndestination: default\n"
           "       gateway: 192.168.1.1\n     interface: en0\n")
    assert open_mode.default_gateway(_runner({"route": out})) == "192.168.1.1"


def test_default_gateway_empty_when_no_default_route():
    assert open_mode.default_gateway(_runner({"route": "not in table"})) == ""


# ── LAN address ──

def test_lan_ip_takes_the_first_lan_address(monkeypatch):
    monkeypatch.setattr(open_mode.addresses, "reachable",
                        lambda *a, **k: [{"kind": "mesh", "host": "10.66.0.1"},
                                         {"kind": "lan", "host": "192.168.1.5"}])
    assert open_mode.lan_ip() == "192.168.1.5"


def test_lan_ip_empty_when_no_lan_address(monkeypatch):
    monkeypatch.setattr(open_mode.addresses, "reachable",
                        lambda *a, **k: [{"kind": "mesh", "host": "10.66.0.1"}])
    assert open_mode.lan_ip() == ""


# ── what counts as a public source ──

def test_is_public_boundaries():
    # Genuinely routable addresses — the shape of a cellular device's
    # carrier-egress source as the hub's WireGuard sees it. (RFC-5737
    # documentation ranges look public but Python's is_private flags them, so
    # they are the wrong fixture for "public" here.)
    assert open_mode._is_public("8.8.8.8") is True
    assert open_mode._is_public("1.1.1.1") is True
    # private, loopback, link-local, the mesh itself, and garbage are all not it
    assert open_mode._is_public("192.168.1.9") is False
    assert open_mode._is_public("10.0.0.4") is False
    assert open_mode._is_public("127.0.0.1") is False
    assert open_mode._is_public("169.254.1.1") is False
    assert open_mode._is_public("10.66.0.5") is False
    assert open_mode._is_public("not-an-ip") is False


# ── which port to forward ──

def test_wg_port_reads_the_endpoint_file(tmp_path, monkeypatch):
    from jstack_host import tunnel
    monkeypatch.setattr(tunnel, "WG_DIR", tmp_path)
    (tmp_path / "endpoint").write_text("home.example.net:53211\n")
    assert open_mode.wg_port() == 53211


def test_wg_port_falls_back_when_no_endpoint_file(tmp_path, monkeypatch):
    from jstack_host import tunnel
    monkeypatch.setattr(tunnel, "WG_DIR", tmp_path)
    assert open_mode.wg_port() == open_mode.DEFAULT_WG_PORT


# ── finding the wg binary ──

def test_wg_bin_prefers_the_env(monkeypatch):
    monkeypatch.setenv("WG", "/custom/wg")
    assert open_mode.wg_bin() == "/custom/wg"


def test_wg_bin_falls_back_to_path(monkeypatch):
    monkeypatch.delenv("WG", raising=False)
    monkeypatch.setattr(open_mode.shutil, "which", lambda _: "/usr/bin/wg")
    assert open_mode.wg_bin() == "/usr/bin/wg"


def test_wg_bin_empty_when_absent(monkeypatch):
    monkeypatch.delenv("WG", raising=False)
    monkeypatch.setattr(open_mode.shutil, "which", lambda _: None)

    class _NoFile:
        def __truediv__(self, _other):
            return self
        def is_file(self):
            return False
    monkeypatch.setattr(open_mode, "Path", lambda _p: _NoFile())
    assert open_mode.wg_bin() == ""


# ── the interface name ──

def test_wg_iface_reads_the_name_file(tmp_path):
    f = tmp_path / "jremote-wg.name"
    f.write_text("utun6\n")
    assert open_mode.wg_iface(str(f)) == "utun6"


def test_wg_iface_empty_when_tunnel_not_up(tmp_path):
    assert open_mode.wg_iface(str(tmp_path / "absent.name")) == ""


# ── the honest evidence: off_network_handshake ──

def _wg_outputs(peers):
    """Build `endpoints` and `latest-handshakes` text from
    {pubkey: (source_ip_port, handshake_unixtime)}."""
    ep = "\n".join(f"{k}\t{src}" for k, (src, _) in peers.items())
    hs = "\n".join(f"{k}\t{when}" for k, (_, when) in peers.items())
    return {"endpoints": ep, "latest-handshakes": hs}


def test_handshake_picks_a_fresh_public_source():
    now = 1_000_000
    peers = {
        "kPUB":  ("8.8.8.8:41000", now - 100),        # public, fresh — the one
        "kLAN":  ("192.168.1.9:41000", now - 50),     # private source
        "kMESH": ("10.66.0.5:41000", now - 10),       # mesh source
        "kOLD":  ("9.9.9.9:41000", now - 5000),       # public but stale
    }
    hs = open_mode.off_network_handshake("utun4", "wg", now,
                                         _runner(_wg_outputs(peers)))
    assert hs is not None
    assert hs["source"] == "8.8.8.8"
    assert hs["age"] == 100


def test_handshake_prefers_the_freshest_public_peer():
    now = 1_000_000
    peers = {
        "kA": ("8.8.8.8:41000", now - 400),
        "kB": ("1.1.1.1:41000", now - 40),   # fresher public — wins
    }
    hs = open_mode.off_network_handshake("utun4", "wg", now,
                                         _runner(_wg_outputs(peers)))
    assert hs["source"] == "1.1.1.1"


def test_handshake_none_when_only_private_sources():
    now = 1_000_000
    peers = {"kLAN": ("192.168.1.9:41000", now - 20),
             "kMESH": ("10.66.0.5:41000", now - 5)}
    assert open_mode.off_network_handshake("utun4", "wg", now,
                                           _runner(_wg_outputs(peers))) is None


def test_handshake_ignores_never_connected_and_malformed_lines():
    now = 1_000_000
    outputs = {
        "endpoints": ("kNONE\t(none)\n"          # never connected — no host:port
                      "kBAD\tgarbage\n"
                      "kPUB\t8.8.8.8:41000\n"),
        "latest-handshakes": ("kNONE\t0\n"        # zero handshake — skip
                              "kBAD\tnot-a-number\n"
                              "kPUB\t" + str(now - 30) + "\n"),
    }
    hs = open_mode.off_network_handshake("utun4", "wg", now, _runner(outputs))
    assert hs["source"] == "8.8.8.8"


def test_handshake_none_without_iface_or_binary():
    assert open_mode.off_network_handshake("", "wg", 0, _runner({})) is None
    assert open_mode.off_network_handshake("utun4", "", 0, _runner({})) is None


# ── verify(): the four states ──

def test_verify_unverified_when_tunnel_down(monkeypatch):
    monkeypatch.setattr(open_mode, "wg_iface", lambda: "")
    v = open_mode.verify(now=0)
    assert v["verified"] is False
    assert "not up" in v["note"]


def test_verify_unverified_when_wg_missing(monkeypatch):
    monkeypatch.setattr(open_mode, "wg_iface", lambda: "utun4")
    monkeypatch.setattr(open_mode, "wg_bin", lambda: "")
    v = open_mode.verify(now=0)
    assert v["verified"] is False
    assert "not installed" in v["note"]


def test_verify_unverified_when_no_handshake_yet(monkeypatch):
    monkeypatch.setattr(open_mode, "wg_iface", lambda: "utun4")
    monkeypatch.setattr(open_mode, "wg_bin", lambda: "wg")
    monkeypatch.setattr(open_mode, "off_network_handshake",
                        lambda *a, **k: None)
    v = open_mode.verify(now=0)
    assert v["verified"] is False
    assert "cellular" in v["note"]


def test_verify_verified_on_a_public_handshake(monkeypatch):
    monkeypatch.setattr(open_mode, "wg_iface", lambda: "utun4")
    monkeypatch.setattr(open_mode, "wg_bin", lambda: "wg")
    monkeypatch.setattr(open_mode, "off_network_handshake",
                        lambda *a, **k: {"source": "8.8.8.8",
                                         "when": 999, "age": 42})
    v = open_mode.verify(now=1041)
    assert v["verified"] is True
    assert v["source"] == "8.8.8.8"
    assert v["age"] == 42
    assert "verified" in v["note"]


# ── guide(): the assembled flow and its two refusals ──

def test_guide_refuses_to_forward_the_http_port(monkeypatch):
    monkeypatch.setattr(open_mode, "wg_port", lambda: open_mode.HTTP_PORT)
    with pytest.raises(open_mode.OpenModeError, match="HTTP API port"):
        open_mode.guide()


def test_guide_refuses_without_a_lan_address(monkeypatch):
    monkeypatch.setattr(open_mode, "wg_port", lambda: 51820)
    monkeypatch.setattr(open_mode, "lan_ip", lambda: "")
    with pytest.raises(open_mode.OpenModeError, match="no private LAN address"):
        open_mode.guide()


def test_guide_assembles_the_forward_endpoint_and_verification(monkeypatch):
    monkeypatch.setattr(open_mode, "wg_port", lambda: 51820)
    monkeypatch.setattr(open_mode, "lan_ip", lambda: "192.168.1.5")
    monkeypatch.setattr(open_mode, "default_gateway", lambda *a, **k: "192.168.1.1")
    monkeypatch.setattr(open_mode, "natpmp_external_ip",
                        lambda *a, **k: "203.0.113.9")
    monkeypatch.setattr(open_mode, "natpmp_map_udp",
                        lambda *a, **k: {"ok": True, "external_port": 51820,
                                         "detail": "mapped"})
    monkeypatch.setattr(open_mode, "verify",
                        lambda *a, **k: {"verified": False, "source": "",
                                         "age": None, "note": "no device yet"})
    g = open_mode.guide()
    assert g["forward"]["line"] == "UDP 51820 → 192.168.1.5:51820"
    assert g["endpoint"] == "203.0.113.9:51820"
    assert g["mapping"]["ok"] is True
    assert g["verification"]["verified"] is False


def test_guide_endpoint_blank_when_public_ip_unknown(monkeypatch):
    # No NAT-PMP external IP → no endpoint string to record, but the forward and
    # the manual-fallback path are still assembled.
    monkeypatch.setattr(open_mode, "wg_port", lambda: 51820)
    monkeypatch.setattr(open_mode, "lan_ip", lambda: "192.168.1.5")
    monkeypatch.setattr(open_mode, "default_gateway", lambda *a, **k: "")
    monkeypatch.setattr(open_mode, "natpmp_external_ip", lambda *a, **k: "")
    monkeypatch.setattr(open_mode, "natpmp_map_udp",
                        lambda *a, **k: {"ok": False, "external_port": 0,
                                         "detail": "no gateway"})
    monkeypatch.setattr(open_mode, "verify",
                        lambda *a, **k: {"verified": False, "note": "no device"})
    g = open_mode.guide()
    assert g["endpoint"] == ""
    assert g["public_ip"] == ""
    assert g["forward"]["line"] == "UDP 51820 → 192.168.1.5:51820"
