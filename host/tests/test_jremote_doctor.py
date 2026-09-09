"""The setup validator — a green doctor and a working host are the same fact.

Pins that every check reports through the same seams the host runs on (a
binary the shell can see but the spawn path cannot is a FAIL), that a
crashing check is a failure rather than a hidden one, and that the report's
exit status is the worst grade.
"""

import io
import json
import os

import pytest

from jstack_host import doctor, hostenv


@pytest.fixture
def machine(tmp_path, monkeypatch):
    agents = tmp_path / "Agents"
    (agents / "Ops" / "chat").mkdir(parents=True)
    (agents / "agents.json").write_text(json.dumps({"ops": {"emoji": "🛠️"}}))
    monkeypatch.setenv("JREMOTE_HOST_PROFILE", "default")
    monkeypatch.setenv("JREMOTE_INSTANCE_ROOT", str(agents))
    monkeypatch.setenv("JREMOTE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("JSTACK_AGENT_REGISTRY", raising=False)
    hostenv.reset_profile()
    yield tmp_path
    hostenv.reset_profile()


def test_every_check_answers_with_a_grade(machine):
    results = doctor.checks()
    names = [r["name"] for r in results]
    assert names == ["python", "claude", "tmux", "websocket", "open files", "token",
                     "profile", "agents", "registry", "timeline", "transcripts",
                     "scheduler", "allowance", "repos", "service"]
    assert all(r["grade"] in (doctor.OK, doctor.WARN, doctor.FAIL) for r in results)
    by = {r["name"]: r for r in results}
    assert by["token"]["grade"] == doctor.FAIL, "no token minted in this state dir"
    assert by["agents"]["grade"] == doctor.OK and "1 with an emoji" in by["agents"]["detail"]
    assert by["registry"]["grade"] == doctor.OK


def test_a_binary_the_spawn_path_cannot_see_is_a_failure(machine, monkeypatch):
    empty = machine / "empty-bin"
    empty.mkdir()
    monkeypatch.setattr(hostenv, "spawn_path", lambda *a, **k: str(empty))
    by = {r["name"]: r for r in doctor.checks()}
    assert by["tmux"]["grade"] == doctor.FAIL and "brew install tmux" in by["tmux"]["hint"]
    assert by["claude"]["grade"] == doctor.FAIL and str(empty) in by["claude"]["hint"]


def test_a_crashing_check_is_a_failure_not_a_hole(machine, monkeypatch):
    def boom():
        raise RuntimeError("kaput")
    boom.__name__ = "check_open_files"
    monkeypatch.setattr(doctor, "CHECKS", (boom,))
    (r,) = doctor.checks()
    assert r["grade"] == doctor.FAIL and "kaput" in r["detail"] and r["name"] == "open files"


def test_the_report_exits_with_the_worst_grade(machine, monkeypatch):
    monkeypatch.setattr(doctor, "CHECKS", (
        lambda: doctor._check("a", doctor.OK, "fine"),
        lambda: doctor._check("b", doctor.WARN, "later", "do this"),
    ))
    out = io.StringIO()
    assert doctor.report(out) == 1
    text = out.getvalue()
    assert "warn  b" in text and "→ do this" in text and "some screens wait" in text
    monkeypatch.setattr(doctor, "CHECKS", (lambda: doctor._check("c", doctor.FAIL, "no"),))
    assert doctor.report(io.StringIO()) == 2
    monkeypatch.setattr(doctor, "CHECKS", (lambda: doctor._check("d", doctor.OK, "yes"),))
    assert doctor.report(io.StringIO()) == 0


def test_status_and_doctor_adopt_the_installed_agents_environment(machine, tmp_path, monkeypatch):
    """Typed into a shell, `doctor` has none of the plist's environment. It
    reads the plist so it grades the host that is installed, not one the
    shell would have resolved on its own — and an explicit export still wins."""
    from jstack_host import install_host
    plist = tmp_path / "com.jremote.host.plist"
    plist.write_bytes(install_host.render_plist(
        state_dir=tmp_path / "state",
        environment={"JREMOTE_INSTANCE_ROOT": str(tmp_path / "Agents"),
                     "JREMOTE_HOST_PROFILE": "default"}))
    assert install_host.installed_environment(plist) == {
        "JREMOTE_INSTANCE_ROOT": str(tmp_path / "Agents"),
        "JREMOTE_HOST_PROFILE": "default",
        "JREMOTE_STATE_DIR": str(tmp_path / "state")}
    monkeypatch.delenv("JREMOTE_INSTANCE_ROOT")
    monkeypatch.setenv("JREMOTE_STATE_DIR", str(tmp_path / "elsewhere"))
    install_host.adopt_installed_environment(plist)
    assert os.environ["JREMOTE_INSTANCE_ROOT"] == str(tmp_path / "Agents")
    assert os.environ["JREMOTE_STATE_DIR"] == str(tmp_path / "elsewhere"), "the shell's export wins"
    assert install_host.installed_environment(tmp_path / "missing.plist") == {}
