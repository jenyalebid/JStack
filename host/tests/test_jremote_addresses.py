"""Where this host says it can be reached.

The failure these exist for is silent: a pairing dialog that shows an address
which cannot work from the machine being paired. Every test below names the
wrong address it keeps off that screen.
"""

from jstack_host import addresses


def test_loopback_never_appears():
    """The one address that is always wrong for a second machine, and always
    right for the machine generating the list — so it is the one that gets
    handed out by accident."""
    out = addresses.classify(["127.0.0.1", "192.168.0.106"], "mac", 9090)
    assert [a["host"] for a in out] == ["192.168.0.106", "mac.local"]


def test_lan_comes_first_and_mesh_last():
    """Order is advice, and the reader is a device that is still pairing —
    which by definition is not on the mesh yet. The mesh address is the one
    it can never reach right now, so it reads last, not first."""
    out = addresses.classify(["192.168.0.106", "10.66.0.1"], "mac", 9090)
    assert [a["kind"] for a in out] == ["lan", "local", "mesh"]


def test_public_and_link_local_are_dropped():
    """A public IP on an interface here is this machine's view of itself, not
    a route anyone else has; 169.254 is what an interface holds when DHCP has
    already failed."""
    out = addresses.classify(["97.120.113.78", "169.254.3.9", "10.66.0.1"],
                             "mac", 9090)
    assert [a["kind"] for a in out] == ["local", "mesh"]


def test_port_rides_into_every_url():
    """A host moved off 9090 would otherwise publish a list wrong in the one
    detail nobody re-reads."""
    out = addresses.classify(["192.168.0.106"], "mac", 8443)
    assert all(a["url"].endswith(":8443") for a in out)
    assert out[0]["url"] == "http://192.168.0.106:8443"


def test_hostname_becomes_a_bonjour_name():
    """`socket.gethostname()` answers all three of `mac`, `mac.local` and
    `mac.lan` depending on the network; the app needs one resolvable form."""
    for given in ("mac", "mac.local", "mac.lan", "mac."):
        out = addresses.classify([], given, 9090)
        assert [a["host"] for a in out] == ["mac.local"], given


def test_localhost_hostname_is_not_an_address():
    """A machine that answers `localhost` for its own name would otherwise
    publish loopback through the back door the first test closes."""
    assert addresses.classify([], "localhost", 9090) == []
    assert addresses.classify([], "", 9090) == []


def test_nothing_readable_is_an_empty_list_not_a_guess():
    """The screen above says 'ask the Mac' when this is empty. Inventing an
    address would be worse than admitting there isn't one."""
    assert addresses.classify([], "", 9090) == []


def test_a_vm_bridge_is_not_the_lan():
    """The address this module shipped wrong on the machine that owns the
    mesh. A Mac running VMs holds 192.168.64.1 on bridge100 — private, so it
    passed every filter here, and reachable by nothing but the guests on that
    bridge. It was published to a phone under 'works while both machines are
    on this network'."""
    out = addresses.classify(
        ["192.168.0.106", "192.168.64.1"], "mac", 9090,
        {"192.168.0.106": "en1", "192.168.64.1": "bridge100"})
    assert [a["host"] for a in out] == ["192.168.0.106", "mac.local"]


def test_the_bridge_number_is_not_what_is_excluded():
    """The kernel numbers these, so a check that knew `bridge100` would pass
    every test here and publish `bridge101` to the next device."""
    for iface in ("bridge0", "bridge100", "bridge101", "vmenet0", "vnic1",
                  "awdl0", "llw0"):
        out = addresses.classify(["192.168.64.1"], "", 9090,
                                 {"192.168.64.1": iface})
        assert out == [], iface


def test_the_mesh_survives_the_interface_filter():
    """The mesh lives on a utun, and it is excluded from `lan` by subnet then
    re-added as its own kind. An interface filter that reached it would delete
    the mesh address rather than reclassify it — so utun is not on the list,
    and this is the test that says so."""
    out = addresses.classify(
        ["192.168.0.106", "10.66.0.1"], "mac", 9090,
        {"192.168.0.106": "en1", "10.66.0.1": "utun0"})
    assert [a["kind"] for a in out] == ["lan", "local", "mesh"]
    assert out[-1]["host"] == "10.66.0.1"


def test_no_interface_map_keeps_every_address():
    """Callers that cannot name the interfaces — and a parse that failed —
    must narrow what can be excluded, never empty the list. The evidence is
    for dropping an entry, not a precondition for keeping one."""
    assert addresses.classify(["192.168.64.1"], "", 9090) != []
    assert addresses.classify(["192.168.64.1"], "", 9090, {}) != []


def test_inet_addrs_stays_unfiltered_for_mode():
    """`mode` asks this whether the machine holds the mesh gateway, and that
    question is about every interface. Narrowing it here to serve the pairing
    screen would demote this hub to 'managed' again."""
    held = addresses._inet_ifaces()
    assert set(addresses._inet_addrs()) == set(held)


def test_interfaces_are_read_off_the_real_machine():
    """The parse is the half a pure classifier cannot pin: `_inet_ifaces`
    must attribute loopback to `lo0` on any machine that runs this."""
    held = addresses._inet_ifaces()
    assert held.get("127.0.0.1") == "lo0"


def test_every_entry_carries_the_shape_the_app_draws():
    out = addresses.classify(["10.66.0.1", "192.168.0.106"], "mac", 9090)
    assert out
    for a in out:
        assert set(a) == {"kind", "host", "url", "note"}
        assert a["url"].startswith("http://")
        assert a["note"]
