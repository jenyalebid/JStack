"""showdoc.py — a markdown file onto the screen the session is driven from.

`/pict` renders a document on the Mac and the user may be holding an iPad. These
pin the three seams that decide whether they ever see it: the link's shape, the
fence asked *before* a window opens (a doc outside it would open a window onto
an error), and the routing — device driver gets the frame, everything else
gets the desk, including every failure.
"""

import types

import pytest

from jstack_host import showdoc


# ── the link ──

def test_doc_url_carries_the_path_not_the_text():
    url = showdoc.doc_url("/Users/x/Agents/A/s/pad/x.md", "x · pict")
    assert url.startswith("jremote://doc?")
    assert "path=%2FUsers%2Fx%2FAgents%2FA%2Fs%2Fpad%2Fx.md" in url
    assert "title=x%20%C2%B7%20pict" in url


def test_doc_url_never_encodes_a_space_as_plus():
    """The app parses a plain URI query, where `+` is a literal plus — not
    the form-encoded space `urlencode` defaults to. A title arrived reading
    `chat+·+pict`, and a path with a space would have resolved to nothing."""
    url = showdoc.doc_url("/Users/x/Agents/A/my seat/pad/x.md", "a b")
    assert "+" not in url
    assert "my%20seat" in url and "title=a%20b" in url


def test_doc_url_omits_an_empty_title():
    assert showdoc.doc_url("/a/b.md") == "jremote://doc?path=%2Fa%2Fb.md"


# ── the fence, asked before any window exists ──

def test_show_refuses_a_file_outside_the_read_roots(tmp_path):
    doc = tmp_path / "secret.md"
    doc.write_text("# nope")
    with pytest.raises(PermissionError):
        showdoc.show(str(doc))


def test_show_refuses_a_non_markdown_file(monkeypatch, tmp_path):
    from dashboard.shared import context_inventory
    monkeypatch.setattr(context_inventory, "_READ_ROOTS", (tmp_path,))
    doc = tmp_path / "render.txt"
    doc.write_text("plain")
    with pytest.raises(PermissionError):
        showdoc.show(str(doc))


def test_show_refuses_a_missing_file(monkeypatch, tmp_path):
    from dashboard.shared import context_inventory
    monkeypatch.setattr(context_inventory, "_READ_ROOTS", (tmp_path,))
    with pytest.raises(FileNotFoundError):
        showdoc.show(str(tmp_path / "gone.md"))


# ── routing ──

@pytest.fixture
def fenced(monkeypatch, tmp_path):
    """A real markdown file the fence accepts."""
    from dashboard.shared import context_inventory
    monkeypatch.setattr(context_inventory, "_READ_ROOTS", (tmp_path.resolve(),))
    doc = tmp_path / "pict-chat.md"
    doc.write_text("# render")
    return doc


def test_device_driven_never_opens_a_mac_window(monkeypatch, fenced):
    from jstack_host import desk, spawn
    monkeypatch.setattr(spawn, "origin_sid", lambda: "sid-live")
    monkeypatch.setattr(showdoc, "_route", lambda origin, url: "device")
    monkeypatch.setattr(desk, "open_url",
                        lambda url: pytest.fail("opened on the Mac"))
    route, url = showdoc.show(str(fenced))
    assert route == "device"
    assert str(fenced.resolve()) in url.replace("%2F", "/")


def test_desk_driven_opens_on_the_mac(monkeypatch, fenced):
    from jstack_host import desk
    opened = []
    monkeypatch.setattr(showdoc, "_route", lambda origin, url: "mac")
    monkeypatch.setattr(desk, "open_url", lambda url: opened.append(url) or True)
    route, url = showdoc.show(str(fenced))
    assert route == "mac"
    assert opened == [url]


def test_nothing_took_the_link_says_so(monkeypatch, fenced):
    """A document has no board row to be found by later — a window that did
    not open is reported, never swallowed."""
    from jstack_host import desk
    monkeypatch.setattr(showdoc, "_route", lambda origin, url: "mac")
    monkeypatch.setattr(desk, "open_url", lambda url: False)
    route, _ = showdoc.show(str(fenced))
    assert route == "none"


def test_route_is_mac_without_an_origin_session():
    assert showdoc._route("", "jremote://doc?path=/a.md") == "mac"


def test_route_is_mac_when_the_dashboard_is_down(monkeypatch):
    from jstack_host import spawn
    monkeypatch.setattr(spawn, "_dashboard_post",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    assert showdoc._route("sid-1", "jremote://doc?path=/a.md") == "mac"


def test_route_is_mac_when_the_endpoint_refuses(monkeypatch):
    from jstack_host import spawn
    monkeypatch.setattr(spawn, "_dashboard_post",
                        lambda *a, **k: types.SimpleNamespace(status_code=400))
    assert showdoc._route("sid-1", "jremote://doc?path=/a.md") == "mac"


def test_route_takes_the_endpoints_answer(monkeypatch):
    from jstack_host import spawn
    sent = {}

    def post(url, json=None, headers=None, timeout=None):
        sent["url"], sent["json"] = url, json
        return types.SimpleNamespace(status_code=200,
                                     json=lambda: {"route": "device"})

    monkeypatch.setattr(spawn, "_dashboard_post", post)
    assert showdoc._route("sid-7", "jremote://doc?path=/a.md") == "device"
    assert sent["url"].endswith("/sessions/sid-7/route-open")
    assert sent["json"] == {"url": "jremote://doc?path=/a.md"}


# ── the CLI's exit codes — what a skill reads to know what happened ──

def test_main_exits_77_outside_the_fence(tmp_path, capsys):
    doc = tmp_path / "x.md"
    doc.write_text("#")
    assert showdoc.main([str(doc)]) == 77
    assert "outside the context roots" in capsys.readouterr().err


def test_main_exits_66_for_a_missing_file(monkeypatch, tmp_path, capsys):
    from dashboard.shared import context_inventory
    monkeypatch.setattr(context_inventory, "_READ_ROOTS", (tmp_path.resolve(),))
    assert showdoc.main([str(tmp_path / "gone.md")]) == 66
    assert "no such file" in capsys.readouterr().err


def test_main_exits_75_when_no_window_opened(monkeypatch, fenced, capsys):
    monkeypatch.setattr(showdoc, "show", lambda p, t="": ("none", "jremote://doc"))
    assert showdoc.main([str(fenced)]) == 75
    assert "did not take the link" in capsys.readouterr().err


def test_main_reports_the_screen_it_landed_on(monkeypatch, fenced, capsys):
    monkeypatch.setattr(showdoc, "show", lambda p, t="": ("device", "jremote://doc"))
    assert showdoc.main([str(fenced)]) == 0
    assert "device driving this session" in capsys.readouterr().out
