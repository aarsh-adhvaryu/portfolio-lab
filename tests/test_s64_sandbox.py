"""S64 Phase 4: the workshop's sandbox (agents/sandbox.py): the Docker command and its kill on a timeout, the availability
check and its cache, the choice between Docker and the local subprocess, the `contained` flag through a run, the launcher
starting Docker Desktop, the security agent's count. One test marked `docker` runs the real container when it works."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from pflab.agents import sandbox as sb
from pflab.agents import workshop as wk


class FakeRun:
    """A stand-in for subprocess.run that records its calls."""
    def __init__(self, results=None, raise_on=None):
        self.calls, self.results, self.raise_on = [], list(results or []), raise_on

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.raise_on and cmd[:2] == self.raise_on[:2] and cmd[1] == "run":
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 0))
        r = self.results.pop(0) if self.results else 0
        return SimpleNamespace(returncode=r, stdout=b"", stderr=b"")


def test_the_docker_command_has_every_isolation_flag():
    box = sb.Docker(runner=FakeRun())
    cmd = box.command(Path("C:/tmp/work"), "pflab-wk-test", Path("C:/tmp/out"))
    s = " ".join(cmd)
    for flag in ("--rm", "--network none", "--read-only", "--tmpfs /tmp", "--memory 2g", "--memory-swap 2g", "--cpus 2", "--pids-limit 256",
                 "--cap-drop ALL", "--security-opt no-new-privileges", "-w /work", "pflab-sandbox:2 python -I /app/runner.py /work"):
        assert flag in s
    assert "-v" in cmd and cmd[cmd.index("-v") + 1].endswith(":/work:ro")          # S67: the job folder is read-only
    assert box.contained is True and sb.Local().contained is False


def test_a_timeout_kills_the_container():
    fake = FakeRun(raise_on=["docker", "run"])
    box = sb.Docker(runner=fake)
    with pytest.raises(subprocess.TimeoutExpired):
        box.run(Path("C:/tmp/work"), 5)
    kill = [c for c, _ in fake.calls if c[:2] == ["docker", "kill"]]
    assert len(kill) == 1 and kill[0][2].startswith("pflab-wk-")
    run_cmd = fake.calls[0][0]
    assert run_cmd[run_cmd.index("--name") + 1] == kill[0][2]             # the same container is the one killed


def test_available_needs_docker_and_the_image_and_is_remembered(monkeypatch):
    monkeypatch.setattr(sb, "RETRY_S", 0.01)
    ok = FakeRun([0, 0])
    assert sb.available(ok, now=1000.0, force=True) is True and len(ok.calls) == 2
    assert sb.available(FakeRun([1]), now=1100.0) is True                   # inside the 10 minutes: not asked again
    assert sb.available(FakeRun([1]), now=1000.0 + sb.CACHE_S + 1) is False  # docker info fails
    assert sb.available(FakeRun([0, 1, 1]), now=3000.0, force=True) is False  # docker works, the image is missing (looked at twice)

    def boom(*a, **k):
        raise FileNotFoundError("docker")
    assert sb.available(boom, now=4000.0, force=True) is False             # docker is not installed


def test_pick_follows_availability_and_the_environment(monkeypatch):
    monkeypatch.delenv("PFLAB_SANDBOX", raising=False)
    monkeypatch.setattr(sb, "status", lambda *a, **k: {"ok": True, "why": ""})
    assert isinstance(sb.pick(), sb.Docker)
    monkeypatch.setattr(sb, "status", lambda *a, **k: {"ok": False, "why": "Docker Desktop is not running"})
    with pytest.raises(sb.SandboxUnavailable):                              # S67: no automatic fallback to the host
        sb.pick()
    monkeypatch.setenv("PFLAB_SANDBOX", "local")
    monkeypatch.setattr(sb, "available", lambda *a, **k: True)
    assert isinstance(sb.pick(), sb.Local)


def _spec():
    return wk.Spec(["d"], "def compute(data):\n    return {'total': float(data['d']['x'].sum())}\n",
                   {"data": {"d": [{"x": 1.0}, {"x": 2.0}]}, "expected": {"total": 3.0}, "tol": 1e-9})


class LocalAsContained(sb.Local):
    contained = True                                                        # the local runner standing in for a container


def test_the_contained_flag_travels_with_the_run():
    frames = {"d": pd.DataFrame({"x": [1.0, 2.0, 3.0]})}
    inside = wk.run(_spec(), frames, sandbox=LocalAsContained())
    outside = wk.run(_spec(), frames, sandbox=sb.Local())
    assert inside.ok and inside.contained is True and inside.result == {"total": 6.0}
    assert outside.ok and outside.contained is False
    assert wk.run(_spec(), frames).contained is False                       # the suite's default is the local subprocess


def test_a_timeout_in_the_box_is_a_failed_run_not_a_crash():
    class Slow:
        contained = True

        def run(self, work, time_limit):
            raise subprocess.TimeoutExpired("x", time_limit)
    r = wk.run(_spec(), {"d": pd.DataFrame({"x": [1.0]})}, sandbox=Slow(), time_limit=3)
    assert not r.ok and "stopped after 3 s" in r.problems[0] and r.contained is True


def test_statsmodels_is_an_allowed_import_but_sockets_are_not():
    ok = "import statsmodels.api as sm\nfrom statsmodels.tsa.stattools import adfuller\ndef compute(data):\n    return {'a': 1.0}\n"
    assert wk.static_check(ok) == []
    assert any("socket" in p for p in wk.static_check("import socket\ndef compute(data):\n    return {'a': 1.0}\n"))


def test_launcher_starts_docker_desktop_only_when_installed_and_not_running(tmp_path):
    from pflab.app import launcher
    log = SimpleNamespace(info=lambda *a: None, warning=lambda *a: None)
    exe = tmp_path / "Docker Desktop.exe"
    started = []
    assert launcher.start_docker(log, exe, running=False, popen=lambda *a, **k: started.append(a)) == "not installed"
    exe.write_bytes(b"x")
    assert launcher.start_docker(log, exe, running=True, popen=lambda *a, **k: started.append(a)) == "already running"
    assert started == []
    assert launcher.start_docker(log, exe, running=False, popen=lambda *a, **k: started.append(a)) == "started"
    assert len(started) == 1

    def refuse(*a, **k):
        raise OSError("blocked")
    assert launcher.start_docker(log, exe, running=False, popen=refuse).startswith("failed")


def test_security_counts_uncontained_runs(tmp_path, monkeypatch):
    from pflab.hq import security
    for i, (status, contained) in enumerate((("checked", True), ("checked", False), ("failed", False), ("checked", False))):
        d = tmp_path / "workshop" / f"c{i}"
        d.mkdir(parents=True)
        (d / "meta.json").write_text(json.dumps({"status": status, "contained": contained}), encoding="utf-8")
    monkeypatch.setattr(sb, "available", lambda *a, **k: False)
    out = security.uncontained(SimpleNamespace(pm_dir=tmp_path))
    assert out == {"uncontained_runs": 2, "of": 4, "docker_now": False}


@pytest.mark.docker
def test_the_real_container_runs_a_calculation_and_blocks_the_network(tmp_path):
    if not sb.available(force=True):
        pytest.skip("Docker is not running or the pflab-sandbox:2 image is not built")
    r = wk.run(_spec(), {"d": pd.DataFrame({"x": [1.0, 2.0, 3.0]})}, sandbox=sb.Docker())
    assert r.ok and r.contained and r.result == {"total": 6.0}
    # code that reaches for the network, run straight through the runner (the static check would stop it earlier)
    work = tmp_path / "w"
    work.mkdir()
    (work / "code.py").write_text("def compute(data):\n    import socket\n    s = socket.create_connection(('1.1.1.1', 80), 3)\n"
                                  "    return {'a': 1.0}\n", encoding="utf-8")
    (work / "job.json").write_text(json.dumps({"datasets": [], "test": {"data": {}, "expected": {"a": 1.0}}, "params": {}}),
                                   encoding="utf-8")
    sb.Docker().run(work, 60)
    out = json.loads((work / "out.json").read_text(encoding="utf-8"))
    assert "error" in out and out["test_ok"] is False                       # no network inside: the connect failed
    # a read-only root: the model's code cannot write outside /work and /tmp
    (work / "code.py").write_text("def compute(data):\n    open('/etc/pflab_x', 'w').write('x')\n    return {'a': 1.0}\n",
                                  encoding="utf-8")
    (work / "out.json").unlink()
    sb.Docker().run(work, 60)
    assert "error" in json.loads((work / "out.json").read_text(encoding="utf-8"))
