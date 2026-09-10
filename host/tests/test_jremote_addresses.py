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


def test_mesh_comes_before_lan():
    """Order is advice. The mesh address is the one that still works after the
    person carrying the laptop leaves the building, so it reads first."""
    out = addresses.classify(["192.168.0.106", "10.66.0.1"], "mac", 9090)
    assert [a["kind"] for a in out] == ["mesh", "lan", "local"]


def test_public_and_link_local_are_dropped():
    """A public IP on an interface here is this machine's view of itself, not
    a route anyone else has; 169.254 is what an interface holds when DHCP has
    already failed."""
    out = addresses.classify(["97.120.113.78", "169.254.3.9", "10.66.0.1"],
                             "mac", 9090)
    assert [a["kind"] for a in out] == ["mesh", "local"]


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


def test_every_entry_carries_the_shape_the_app_draws():
    out = addresses.classify(["10.66.0.1", "192.168.0.106"], "mac", 9090)
    assert out
    for a in out:
        assert set(a) == {"kind", "host", "url", "note"}
        assert a["url"].startswith("http://")
        assert a["note"]
