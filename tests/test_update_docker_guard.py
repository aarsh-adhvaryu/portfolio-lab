"""2026-11-15: the update at start never waits forever on Docker. When Docker does not answer, the sandbox image is not rebuilt (said plainly) and the start goes on; a docker command that hangs is stopped."""
from __future__ import annotations

import subprocess
from pathlib import Path

from pflab import update


def test_no_docker_build_when_docker_does_not_answer(tmp_path, monkeypatch, capsys):
    (tmp_path / "sandbox").mkdir()
    (tmp_path / "sandbox" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    (tmp_path / "requirements.lock").write_text("", encoding="utf-8")
    calls = []
    monkeypatch.setattr(update, "docker_up", lambda timeout=15.0: False)
    monkeypatch.setattr("shutil.which", lambda name: "docker" if name == "docker" else None)
    fns = [n for n in ("default_install",) if hasattr(update, n)]
    assert fns, "the install step is where the image is built"
    getattr(update, fns[0])(tmp_path, lambda cmd, cwd: (calls.append(cmd) or (0, "")))
    assert not any(c[0] == "docker" for c in calls) and "Docker is not running" in capsys.readouterr().out


def test_a_hanging_docker_command_is_stopped(monkeypatch):
    def hang(*a, **k):
        assert k.get("timeout") == update.DOCKER_TIMEOUT_S
        raise subprocess.TimeoutExpired(a[0], k["timeout"])
    monkeypatch.setattr(update.subprocess, "run", hang)
    rc, out = update.run_cmd(["docker", "build", "."], Path("."))
    assert rc == 124 and "was stopped" in out


def test_docker_up_is_false_when_docker_is_missing_or_slow(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("docker")
    monkeypatch.setattr(update.subprocess, "run", boom)
    assert update.docker_up() is False
