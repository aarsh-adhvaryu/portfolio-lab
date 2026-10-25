"""S58b, the investor 2026-10-24: the system works then and there. New data starts the jobs that use it (window open or not);
the dashboard picks up new code by itself (a button, or a restart once nothing runs and the window is untouched);
a declined backup is shown as his decision, never chased."""
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient

from pflab.app import runtime, server
from pflab.conductor import sync
from pflab.pm import store
from pflab.service import backup, health, jobs, runner
from pflab.service.schedule import Daily

NOW = datetime(2026, 10, 24, 19, 40)


def r(job, status="ok", detail="{}"):
    return jobs.RunResult(job, status, detail, 1)


def test_new_data_starts_the_jobs_that_use_it():
    assert jobs.followers(r("collect")) == ["prices"] and jobs.followers(r("prices")) == ["guards", "plans"]
    assert jobs.followers(r("filings", detail='{"alerts_queued": 2}')) == ["research"]
    assert jobs.followers(r("filings", detail='{"alerts_queued": 0}')) == []
    assert jobs.followers(r("research", detail='{"opus_queued": 3}')) == ["analyst"]
    assert jobs.followers(r("collect", "failed", "boom")) == []


def test_the_unattended_tick_runs_the_followers_in_the_same_tick(tmp_path, monkeypatch):
    ran = []
    for name in ("collect", "prices", "guards", "plans"):
        monkeypatch.setitem(jobs.REGISTRY, name, jobs.Job(name, Daily(23, 59), lambda ctx, n=name: ran.append(n) or {}, "t"))
    monkeypatch.setattr(jobs, "tick", lambda ctx, only: [jobs.run_job(ctx, jobs.REGISTRY["collect"])])
    ctx = jobs.Ctx(store.connect(tmp_path / "l.duckdb"), NOW, tmp_path, tmp_path, tmp_path)
    out = runner.tick_and_notify(ctx, ["collect", "prices", "guards"], send=lambda t: None)
    assert ran == ["collect", "prices", "guards"] and [x.job for x in out] == ran      # plans: not under this preset


def test_the_window_open_runs_them_next_too(tmp_path, monkeypatch):
    rt = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=store.connect(tmp_path / "l.duckdb"),
                         clock=lambda: NOW)
    for name in ("prices", "guards", "plans"):
        monkeypatch.setitem(jobs.REGISTRY, name, jobs.Job(name, Daily(23, 59), lambda ctx: {}, "t"))
    rt._after(rt._ctx(), [r("prices")])
    assert rt.wanted == ["guards", "plans"]


def test_new_code_on_disk_makes_an_update_ready_and_a_restart_waits_for_quiet(tmp_path):
    src = tmp_path / "src" / "pflab"
    src.mkdir(parents=True)
    (src / "x.py").write_text("a = 1\n", encoding="utf-8")
    rt = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=store.connect(tmp_path / "l.duckdb"),
                         clock=lambda: NOW)
    assert rt.check_update() is False and rt.quiet()
    time.sleep(0.05)
    (src / "x.py").write_text("a = 2\n", encoding="utf-8")
    assert rt.check_update() is True
    rt.wanted.append("prices")
    assert not rt.quiet()                                       # a job waiting: no restart yet


def test_the_screen_can_restart_and_says_when_it_was_used(tmp_path):
    rt = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=store.connect(tmp_path / "l.duckdb"),
                         clock=lambda: NOW)
    app = server.create_app(rt)
    c = TestClient(app)
    rt.clock = lambda: NOW + timedelta(minutes=5)
    assert c.post("/api/seen").json() == {"ok": True} and rt.last_seen == NOW + timedelta(minutes=5)
    assert c.post("/api/restart").json() == {"restarting": True}
    assert app.state.restart_requested.is_set() and app.state.shutdown_requested.is_set()


def test_a_declined_backup_is_his_decision_not_a_question(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "declined", lambda config_path=None: "2026-10-24")
    monkeypatch.setattr(backup, "target_dir", lambda config_path=None: None)
    items = {i.name: i for i in health.check(jobs.Ctx(store.connect(tmp_path / "l.duckdb"), NOW, tmp_path, tmp_path,
                                                         tmp_path))}
    assert items["backup"].status == "OK" and items["backup"].detail.startswith("off: The investor's decision of 2026-10-24")
    monkeypatch.setattr(health, "check", lambda ctx: [SimpleNamespace(name="backup", status="OK", detail=items["backup"].detail)])
    from pflab.conductor import calendar as cl
    f = {x.name: x for x in sync.service_findings(jobs.Ctx(None, NOW, tmp_path, tmp_path, tmp_path), cl.load())}
    assert f["backup"].status == "off" and f["backup"].ask_key is None
