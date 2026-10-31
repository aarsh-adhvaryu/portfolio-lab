"""S67 generated code is contained or it does not run: no automatic host fallback, the uncontained setting refused in an installed app,
the Docker command's flags and read-only job folder with a separate output folder, the containment probe's verdicts (through a fake Docker),
and the effect on the workshop, the chat and a waiting investigation. The real container is tested only where Docker exists (marker `docker`)."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from pflab.agents import sandbox as sb
from pflab.agents import workshop as wk
from pflab.app import chat, runtime, system
from pflab.hq import cases
from pflab.pm import store

NOW = datetime(2026, 11, 4, 21, 0)


class Docker:
    """A fake `docker` command line: answers info, image inspect, run (the probe script), kill and ps; records every call."""
    def __init__(self, probe=None, info=0, image=0, run_hangs=False, runner_sha=None):
        self.calls, self.probe, self.info, self.image, self.run_hangs, self.runner_sha = [], probe, info, image, run_hangs, runner_sha
        self.killed = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[:2] == ["docker", "info"]:
            return SimpleNamespace(returncode=self.info, stdout=b"", stderr=b"")
        if cmd[:3] == ["docker", "image", "inspect"]:
            return SimpleNamespace(returncode=self.image, stdout=b"", stderr=b"")
        if "sha256sum" in cmd:                                                       # the runner baked into the image
            return SimpleNamespace(returncode=0, stdout=(self.runner_sha or sb.runner_sha()).encode() + b"  /app/runner.py", stderr=b"")
        if cmd[:2] == ["docker", "kill"]:
            self.killed.append(cmd[2])
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        if cmd[:2] == ["docker", "ps"]:
            return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
        if cmd[:2] == ["docker", "run"]:
            if "-c" in cmd and "time.sleep" in cmd[-1]:
                raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 2))
            if "-c" in cmd:
                return SimpleNamespace(returncode=0, stdout=(json.dumps(self.probe) + "\n").encode(), stderr=b"")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


GOOD = {"network_closed": True, "dns_closed": True, "root_read_only": True, "work_read_only": True, "no_host_home": True,
        "no_secret_env": True, "not_root": True}


def test_there_is_no_fallback_to_the_host_when_docker_is_missing(monkeypatch):
    monkeypatch.delenv("PFLAB_SANDBOX", raising=False)
    for why in ("Docker Desktop is not running", "the sandbox image pflab-sandbox:2 is not built"):
        monkeypatch.setattr(sb, "status", lambda *a, _w=why, **k: {"ok": False, "why": _w})
        with pytest.raises(sb.SandboxUnavailable, match=why[:20]):
            sb.pick()


def test_status_names_what_is_missing_and_is_remembered(monkeypatch):
    sb._cache.update({"at": 0.0, "ok": False, "why": ""})
    assert sb.status(Docker(info=1), now=100.0, force=True) == {"ok": False, "why": "Docker Desktop is not running"}
    assert "is not built" in sb.status(Docker(image=1), now=200.0, force=True)["why"]

    def missing(*a, **k):
        raise FileNotFoundError("docker")
    assert sb.status(missing, now=300.0, force=True)["why"] == "Docker is not installed"
    assert sb.status(Docker(), now=400.0, force=True)["ok"] is True
    assert sb.status(missing, now=410.0)["ok"] is True                              # inside the cache window the last answer stands


def test_docker_just_started_and_still_listing_its_images_is_not_called_a_missing_image(monkeypatch):
    """Seen on the first real launch: `docker info` answered, `image inspect` failed once, the image was there. One more look settles it."""
    monkeypatch.setattr(sb, "RETRY_S", 0.01)
    answers = iter([1, 0])

    class Slow(Docker):
        def __call__(self, cmd, **kw):
            if cmd[:3] == ["docker", "image", "inspect"]:
                self.calls.append(cmd)
                return SimpleNamespace(returncode=next(answers), stdout=b"", stderr=b"")
            return super().__call__(cmd, **kw)
    d = Slow()
    assert sb.status(d, now=500.0, force=True) == {"ok": True, "why": ""}
    assert sum(c[:3] == ["docker", "image", "inspect"] for c in d.calls) == 2
    assert "is not built" in sb.status(Docker(image=1), now=600.0, force=True)["why"]      # a really missing image is still named


def test_the_uncontained_setting_is_refused_in_an_installed_app_and_never_chosen_by_itself(monkeypatch):
    monkeypatch.setenv("PFLAB_SANDBOX", "local")
    assert isinstance(sb.pick(), sb.Local) and sb.Local.contained is False           # the workshop's explicit setting (and the suite's)
    monkeypatch.setattr(sb, "installed_app", lambda: True)
    with pytest.raises(sb.SandboxUnavailable, match="refused in the installed app"):
        sb.pick()
    monkeypatch.delenv("PFLAB_SANDBOX")
    monkeypatch.setattr(sb, "status", lambda *a, **k: {"ok": False, "why": "Docker is not installed"})
    with pytest.raises(sb.SandboxUnavailable):
        sb.pick()


def test_the_docker_run_mounts_the_job_read_only_and_reads_back_only_the_out_folder(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        out = Path(cmd[cmd.index("-v", cmd.index("-v") + 1) + 1].split(":/out")[0])        # the second -v is the out folder
        (out / "out.json").write_text('{"test_ok": true}', encoding="utf-8")
        (out / "stray.txt").write_text("not returned", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    sb.Docker(runner=run).run(work, 5)
    cmd = seen["cmd"]
    assert f"{work}:/work:ro" in cmd and "PFLAB_OUT=/out" in cmd and "--cap-drop" in cmd and cmd[cmd.index("--network") + 1] == "none"
    assert json.loads((work / "out.json").read_text(encoding="utf-8")) == {"test_ok": True} and not (work / "stray.txt").exists()
    assert not any(Path(p).exists() for p in [c.split(":/out")[0] for c in cmd if c.endswith(":/out")])     # the out folder is gone


def test_the_probe_passes_only_when_every_containment_check_passes():
    ok = sb.probe(Docker(probe=GOOD))
    assert ok["ok"] and ok["checks"]["time_limit_kills"] is True and ok["checks"]["network_closed"] is True
    for broken in ("network_closed", "work_read_only", "no_secret_env"):
        bad = sb.probe(Docker(probe={**GOOD, broken: False}))
        assert not bad["ok"] and broken in bad["why"]
    assert sb.probe(Docker(probe={}))["ok"] is False                                  # a probe that printed nothing proved nothing
    assert sb.probe(Docker(info=1))["why"] == "Docker Desktop is not running"
    fake = Docker(probe=GOOD)
    sb.probe(fake)
    run_calls = [c for c in fake.calls if c[:2] == ["docker", "run"]]
    assert all("--network" in c and "none" in c and "--read-only" in c for c in run_calls)
    assert fake.killed and fake.killed[0].startswith("pflab-probe-t-")                # a run past its limit is killed by name


def test_the_probe_script_itself_runs_and_reports_names_for_every_check():
    import ast
    ast.parse(sb.PROBE_CODE)                                                           # it is valid Python
    ns = {"out": []}
    exec(compile(sb.PROBE_CODE.replace("print(json.dumps(r))", "out.append(r)"), "probe", "exec"), ns)
    assert set(ns["out"][0]) == set(GOOD)


# --- what it does to the work ---------------------------------------------------------------------------------------------------------------

def _spec():
    return wk.Spec(["d"], "def compute(data):\n    return {'total': float(data['d']['x'].sum())}\n",
                   {"data": {"d": [{"x": 1.0}, {"x": 2.0}]}, "expected": {"total": 3.0}, "tol": 1e-9})


def test_a_run_without_a_sandbox_raises_and_runs_nothing(monkeypatch):
    monkeypatch.delenv("PFLAB_SANDBOX", raising=False)
    monkeypatch.setattr(sb, "status", lambda *a, **k: {"ok": False, "why": "Docker Desktop is not running"})
    ran = []
    monkeypatch.setattr(sb.Local, "run", lambda self, work, t: ran.append(work))
    with pytest.raises(sb.SandboxUnavailable):
        wk.run(_spec(), {"d": pd.DataFrame({"x": [1.0, 2.0]})})
    assert ran == []


def test_the_writer_is_not_asked_again_when_the_sandbox_is_missing(monkeypatch):
    monkeypatch.delenv("PFLAB_SANDBOX", raising=False)
    monkeypatch.setattr(sb, "status", lambda *a, **k: {"ok": False, "why": "Docker is not installed"})
    asked = []

    def writer(prompt):
        asked.append(1)
        return json.dumps({"datasets": ["d"], "code": _spec().code, "test": _spec().test, "explain": "sum"})
    with pytest.raises(sb.SandboxUnavailable):
        wk.solve("total of x", lambda names: {"d": pd.DataFrame({"x": [1.0]})}, "Available: d", "{}", [("w", writer, 3)])
    assert asked == [1]                                                                # one writing, not three tries at nothing


def _writer_that_works(monkeypatch):
    """A model that returns valid code, so the run reaches the sandbox (the local model is not available in the suite)."""
    code = json.dumps({"datasets": ["holdings"], "code": "def compute(data):\n    return {'n': float(len(data['holdings']))}\n",
                       "test": {"data": {"holdings": [{"symbol": "A", "isin": "I", "bucket": "equity", "qty": 1.0, "cost": 1.0, "price": 1.0,
                                                       "value": 1.0, "unrealised": 0.0}]}, "expected": {"n": 1.0}, "tol": 1e-9}, "explain": "count"})
    monkeypatch.setattr(wk, "local_writer", lambda model=None: (lambda prompt: code))
    monkeypatch.setattr(wk, "_filler", lambda: None)
    monkeypatch.setattr(wk, "load_dataset", lambda name, con, root, asof: pd.DataFrame(
        [{"symbol": "A", "isin": "I", "bucket": "equity", "qty": 1.0, "cost": 1.0, "price": 1.0, "value": 1.0, "unrealised": 0.0}]))


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(system, "_ollama", lambda: {"up": True, "models": []})
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def test_the_chat_says_the_calculation_waits_for_docker_and_asks_once(rt, monkeypatch):
    monkeypatch.delenv("PFLAB_SANDBOX", raising=False)
    monkeypatch.setattr(sb, "status", lambda *a, **k: {"ok": False, "why": "Docker Desktop is not running"})
    monkeypatch.setattr("pflab.agents.analyst.config", lambda: {"adopted": False, "cap": 0, "ask_above": 0, "usd_inr": 90, "model": "m", "tijori_to_analyst": False})
    _writer_that_works(monkeypatch)
    for _ in range(2):
        out = chat.answer(rt, rt.cursor(), "What was the largest fall of my portfolio in 2024, as a calculation?", "calc")
        assert out["status"] == "failed" and "did not run" in out["text"] and "Docker" in out["text"]
    assert rt.cursor().execute("SELECT count(*) FROM questions WHERE subject_key LIKE 'workshop:sandbox:%'").fetchone()[0] == 1


def test_a_failed_containment_probe_blocks_generated_code_until_it_passes(rt, monkeypatch):
    monkeypatch.setenv("PFLAB_SANDBOX", "docker")
    con = rt.cursor()
    assert sb.blocked_by_probe(con) is None                                            # never probed: the first use may find out
    system.record_check(con, "sandbox", False, NOW, "network_closed")
    assert "probe failed" in sb.blocked_by_probe(con)
    with pytest.raises(sb.SandboxUnavailable, match="containment probe failed"):
        wk.ask(con, "anything", rt.pm_dir, rt.data_root, NOW.date(), now=NOW)
    system.record_check(con, "sandbox", True, NOW + timedelta(hours=1), "all checks passed")
    assert sb.blocked_by_probe(con) is None


def test_a_case_that_needs_a_calculation_waits_for_the_sandbox_and_resumes_when_it_is_back(rt, monkeypatch):
    from pflab.hq import tools as tl
    from pflab.hq.desk import Desk
    from pflab.hq import egress
    monkeypatch.delenv("PFLAB_SANDBOX", raising=False)
    state = {"ok": False}
    monkeypatch.setattr(sb, "status", lambda *a, **k: {"ok": state["ok"], "why": "Docker Desktop is not running"})
    con = rt.cursor()
    cid, _ = cases.open_case(con, NOW, "What is the 5-year CAGR of the equity bucket?", subject="AAA")
    cases.start_pass(con, [cid], 1, NOW)
    d = Desk(con, rt.pm_dir, rt.data_root, rt.repo, None, {"brain": "economy"}, clock=lambda: NOW)
    ctx = tl.Ctx(d, 1, "m", False, {}, egress.Gate(), NOW, case_ids=[cid])
    monkeypatch.setattr("pflab.agents.analyst.config", lambda: {"adopted": False, "cap": 0, "ask_above": 0, "usd_inr": 90, "model": "m", "tijori_to_analyst": False})
    _writer_that_works(monkeypatch)
    text, err = tl.run(ctx, "case_calculate", {"case_id": cid, "question": "CAGR of the equity bucket over 5 years"}, 1)
    res = json.loads(text)
    assert res["carried_out"] and res["wait"] and "waiting for the sandbox" in res["result"]
    assert cases.get(con, cid)["status"] == "waiting_data"
    assert cases.sweep(con, NOW + timedelta(minutes=5)) == []
    state["ok"] = True
    assert cases.sweep(con, NOW + timedelta(minutes=10)) == [(cid, "sandbox")]
    assert cases.get(con, cid)["status"] == "queued"


@pytest.mark.docker
def test_the_real_container_proves_its_own_containment():
    if not sb.status(force=True)["ok"]:
        pytest.skip("Docker is not running or the pflab-sandbox:2 image is not built")
    r = sb.probe()
    assert r["ok"], r


def test_an_image_baked_by_an_older_release_is_named_and_proves_nothing():
    """Audit F2: an update installed new Python but the image kept the old runner; the probe must say so, not pass."""
    r = sb.probe(Docker(probe=GOOD, runner_sha="0" * 64))
    assert r["ok"] is False and "different runner" in r["why"] and "docker build" in r["why"]
    assert sb.probe(Docker(probe=GOOD))["ok"] is True


def test_a_calculation_that_failed_before_any_code_ran_is_not_called_uncontained(rt, monkeypatch):
    """S68, found in the real app: today's failed tax attempts raised 'This calculation ran in the uncontained developer subprocess' although no code
    had run at all (a failed Run defaulted to contained=False). Nothing ran, so nothing is said."""
    monkeypatch.setenv("PFLAB_SANDBOX", "docker")
    monkeypatch.setattr(sb, "status", lambda *a, **k: {"ok": True})
    monkeypatch.setattr("pflab.agents.analyst.config", lambda: {"adopted": False, "cap": 0, "ask_above": 0, "usd_inr": 90, "model": "m", "tijori_to_analyst": False})
    monkeypatch.setattr(wk, "local_writer", lambda model=None: (lambda prompt: "no code here"))
    monkeypatch.setattr(wk, "_filler", lambda: None)
    out = wk.ask(rt.cursor(), "Something the writer cannot write", rt.pm_dir, rt.data_root, NOW.date(), now=NOW)
    assert out.status != "checked" and (out.run is None or out.run.contained is not False)
    assert rt.cursor().execute("SELECT count(*) FROM questions WHERE subject_key LIKE 'workshop:uncontained:%'").fetchone()[0] == 0
    assert wk.Run(False, ["x"]).contained is None                     # 'nothing ran' is not 'ran uncontained'
