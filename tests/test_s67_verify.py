"""S67 the local acceptance command (`pflab verify`) and the independent-operation drill, exercised here with fakes and a real worker process on
a temporary record. The things only his PC can show (a real sleep, Docker, Kite, Gmail) come out as "needs you" with the exact step, never as
passes. Synthetic; no network."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from pflab import release, verify
from pflab.agents import sandbox as sb
from pflab.pm import store

NOW = datetime(2026, 11, 4, 21, 0)


def make_app(tmp_path: Path) -> Path:
    folder = tmp_path / "PortfolioLabApp"
    (folder / "app").mkdir(parents=True)
    (folder / "pm" / "app").mkdir(parents=True)
    (folder / "data").mkdir()
    release.write(folder / "app", folder, "v2026.10.28.11")
    con = store.connect(folder / "pm" / "ledger.duckdb")
    con.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZERODHA', 'demat', 'Zerodha')")
    con.execute("INSERT INTO questions VALUES (1, ?, 'x', 'k1', 'a question', 'open', NULL, NULL)", [NOW])
    con.close()
    (folder / "pm" / "app" / "settings.json").write_text(json.dumps({"preset": "full", "brain": "economy", "telegram_send": False}), encoding="utf-8")
    return folder


@pytest.fixture
def no_docker(monkeypatch):
    monkeypatch.setattr(sb, "status", lambda *a, **k: {"ok": False, "why": "Docker is not installed"})


def test_a_run_changes_nothing_of_his_names_the_candidate_and_asks_for_what_only_he_can_do(tmp_path, no_docker, monkeypatch):
    app = make_app(tmp_path)
    monkeypatch.setattr(verify, "restart_drill", lambda ctx, rep, **k: rep.add("restart drill", verify.SKIP, "stubbed here"))
    from pflab.app import runtime as rtm
    monkeypatch.setattr(rtm, "token_valid", lambda now=None: False)
    monkeypatch.setattr("pflab.ingest.gmail.connected", lambda: False)
    before = verify.fingerprint(app / "pm" / "ledger.duckdb")
    rep = verify.run(app, report=tmp_path / "out" / "report.txt", now=NOW)
    assert verify.fingerprint(app / "pm" / "ledger.duckdb") == before                              # the live ledger: same size, time, hash
    by = {c.name: c for c in rep.checks}
    assert by["live record untouched"].status == verify.PASS
    assert rep.identity["candidate_commit"] != "unknown" and rep.identity["installed_tag"] == "v2026.10.28.11"
    assert rep.identity["candidate_schema"] == max(m[0] for m in store.MIGRATIONS) and rep.identity["installed_schema"] == max(m[0] for m in store.MIGRATIONS)
    assert by["migration rehearsal"].status == verify.PASS and by["rollback rehearsal"].status == verify.PASS
    assert by["sandbox (Docker)"].status == verify.NEEDS and "docker build -t pflab-sandbox:2" in by["sandbox (Docker)"].fix       # not passed on a mock
    assert by["Gmail read"].status == verify.NEEDS and "pflab mail connect" in by["Gmail read"].fix
    assert by["Kite read"].status == verify.NEEDS and by["Windows sleep and wake"].status == verify.NEEDS
    assert by["live model call"].status == verify.SKIP
    assert rep.verdict.startswith("CLOUD-TESTED CANDIDATE")
    text = (tmp_path / "out" / "report.txt").read_text(encoding="utf-8")
    assert "candidate :" in text and "installed :" in text and "Next, in order:" in text
    assert json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))["verdict"] == rep.verdict
    assert str(tmp_path) not in text.replace(str(release.ROOT), "")                                      # no private folder in the report except the code root shown


def test_the_installed_apps_own_code_is_not_a_candidate(tmp_path, monkeypatch):
    app = make_app(tmp_path)
    monkeypatch.setattr(release, "is_app", lambda root=None: True)
    rep = verify.Report(started="x")
    verify.identity(verify.Ctx(release.ROOT, app, app / "pm", app / "data", NOW, tmp_path), rep)
    assert rep.checks[0].status == verify.FAIL and "validates nothing about a candidate" in rep.checks[0].detail
    assert rep.verdict.startswith("NOT READY")


def test_a_failing_migration_on_the_copy_is_a_failure_and_the_live_record_is_still_unchanged(tmp_path, no_docker, monkeypatch):
    app = make_app(tmp_path)
    import pflab.update as up
    monkeypatch.setattr(up, "rehearse", lambda copy: (_ for _ in ()).throw(RuntimeError("Parser Error in migration 44")))
    before = verify.fingerprint(app / "pm" / "ledger.duckdb")
    rep = verify.run(app, skip=("recovery", "prerequisites", "connectors", "freshness", "local model", "sandbox"), now=NOW)
    by = {c.name: c for c in rep.checks}
    assert by["migration rehearsal"].status == verify.FAIL and "migration 44" in by["migration rehearsal"].detail
    assert by["live record untouched"].status == verify.PASS and verify.fingerprint(app / "pm" / "ledger.duckdb") == before
    assert rep.verdict.startswith("NOT READY")


def test_the_report_carries_no_personal_text():
    t = verify.sanitize(f"{Path.home()}/x opened by someone@example.com account 123456789012 and ABCDE1234F")
    assert "someone@example.com" not in t and "123456789012" not in t and "ABCDE1234F" not in t and str(Path.home()) not in t


def test_the_sleep_and_wake_check_reads_what_the_app_wrote_across_a_real_sleep(tmp_path):
    app = make_app(tmp_path)
    hb = app / "pm" / "app" / "heartbeat.json"
    ctx = verify.Ctx(release.ROOT, app, app / "pm", app / "data", NOW, tmp_path)

    def check():
        rep = verify.Report()
        verify.wake_check(ctx, rep)
        return rep.checks[0]
    assert check().status == verify.NEEDS and "heartbeat" in check().detail                       # the app has not run with this version yet
    import os
    fresh = (NOW - timedelta(seconds=30)).isoformat(timespec="seconds")
    hb.write_text(json.dumps({"at": "2026-11-04T18:00:00", "pid": os.getpid(), "last_wake": None, "wakes": 0, "catching_up": None}), encoding="utf-8")
    assert check().status == verify.NEEDS and "old heartbeat" in check().detail                    # an old beat is not evidence about now
    hb.write_text(json.dumps({"at": fresh, "pid": 999999999, "last_wake": None, "wakes": 0, "catching_up": None}), encoding="utf-8")
    assert check().status == verify.NEEDS and "process is gone" in check().detail                 # a fresh-looking beat from a dead process
    hb.write_text(json.dumps({"at": fresh, "pid": os.getpid(), "last_wake": None, "wakes": 0, "catching_up": None}), encoding="utf-8")
    assert check().status == verify.NEEDS and "no wake has been seen" in check().detail
    hb.write_text(json.dumps({"at": fresh, "pid": os.getpid(), "catching_up": "woke after 7 min away", "wakes": 1,
                              "last_wake": {"at": "2026-11-04T20:00:00", "away_min": 7, "recovered": {"tasks_recovered": 0}}}), encoding="utf-8")
    assert check().status == verify.NEEDS and "still catching up" in check().detail
    hb.write_text(json.dumps({"at": fresh, "pid": os.getpid(), "catching_up": None, "wakes": 1, "last_wake": {"at": "2026-11-04T20:00:00", "away_min": 7,
                                                                                     "recovered": {"tasks_recovered": 1}, "settled_at": "2026-11-04T20:03:00"}}), encoding="utf-8")
    c = check()
    assert c.status == verify.PASS and "data caught up" in c.detail
    hb.write_text(json.dumps({"at": fresh, "pid": os.getpid(), "last_wake": {"at": "t", "recovered": "failed"}}), encoding="utf-8")
    assert check().status == verify.FAIL


def test_the_runtime_writes_the_heartbeat_a_wake_leaves(tmp_path, monkeypatch):
    from pflab.app import runtime, system
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(system, "_ollama", lambda: {"up": True, "models": []})
    t = {"now": datetime(2026, 11, 4, 10, 0)}
    rt = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: t["now"])
    rt.beat()
    t["now"] += timedelta(minutes=1)
    rt.beat()
    t["now"] += timedelta(hours=2)                                                                  # the laptop slept
    assert rt.beat().startswith("woke after 120")
    d = json.loads((tmp_path / "pm" / "app" / "heartbeat.json").read_text(encoding="utf-8"))
    assert d["wakes"] == 1 and d["last_wake"]["away_min"] == 120 and set(d["last_wake"]["recovered"]) >= {"tasks_recovered", "cases_recovered"}
    con.execute("INSERT INTO prices VALUES ('INE000A01011', DATE '2026-11-03', 1.0, 'EQ', 'x', now())")      # the catch-up brought the session in
    t["now"] += timedelta(minutes=1)
    assert rt.beat() is None
    d = json.loads((tmp_path / "pm" / "app" / "heartbeat.json").read_text(encoding="utf-8"))
    assert d["last_wake"]["settled_at"]


# --- independent operation: a real worker process on a temporary record -------------------------------------------------------------------------

def test_a_force_killed_worker_with_work_in_flight_recovers_once_and_stops_cleanly(tmp_path):
    ctx = verify.Ctx(release.ROOT, None, tmp_path / "pm", tmp_path / "data", NOW, tmp_path)
    rep = verify.Report()
    t0 = time.time()
    verify.restart_drill(ctx, rep, seconds=120)
    c = rep.checks[0]
    assert c.status == verify.PASS, c.detail
    assert "work in flight recovered at start" in c.detail and "force-killed" in c.detail and "restarted" in c.detail and "stopped cleanly" in c.detail
    assert time.time() - t0 < 200


def test_the_screen_stays_responsive_while_a_slow_dependency_and_a_slow_job_run(tmp_path, monkeypatch):
    """Slow Docker and Ollama probes, and a backfill job that sleeps in the scheduler thread, must not hold up the status call.
    The measured times are printed (pytest -s) and bounded."""
    from fastapi.testclient import TestClient

    from pflab.app import readiness, runtime, system
    from pflab.app.server import create_app
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    SLOW = 3.0
    calls = {"docker": 0, "ollama": 0}

    def slow_docker():
        calls["docker"] += 1
        time.sleep(SLOW)
        return "running"
    monkeypatch.setattr(system, "_docker_probe", slow_docker)
    monkeypatch.setattr(sb, "status", lambda *a, **k: (time.sleep(SLOW), {"ok": True, "why": ""})[1])

    class SlowResp:
        def __enter__(self):
            calls["ollama"] += 1
            time.sleep(SLOW)
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"models": [{"name": "qwen3:8b-q8_0"}, {"name": "nomic-embed-text:latest"}]}).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: SlowResp())
    rt = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con)
    app = create_app(rt)
    client = TestClient(app)
    stop = {"go": True}

    def slow_backfill():                                   # a backfill step running for the whole test, in another thread
        rt.busy = "backfill"
        while stop["go"]:
            time.sleep(0.05)
        rt.busy = None
    import threading
    th = threading.Thread(target=slow_backfill, daemon=True)
    th.start()
    times = []
    try:
        for _ in range(6):
            t = time.time()
            r = client.get("/api/system")
            times.append(time.time() - t)
            assert r.status_code == 200
        first, rest = times[0], times[1:]
        d = r.json()
        assert any(w["job"] == "backfill" for w in d["work"]["running"])                    # the slow job is visible, and did not block the call
        print(f"status call, slow Ollama+Docker ({SLOW:.0f} s each) and a running backfill: first {first:.2f} s, then max {max(rest):.2f} s")
        assert first < SLOW * 0.9, times                                                     # the very first look did not wait for the slow probes
        assert max(rest) < 2.0, times
        time.sleep(SLOW + 1.0)                                                                # the background refreshes finish
        t = time.time()
        d2 = client.get("/api/system").json()
        assert time.time() - t < 2.0 and calls["docker"] >= 1 and calls["ollama"] >= 1
        assert {c["id"]: c for c in d2["connectors"]}["local"]["state"] == "ok"             # the real answer arrived in the background
    finally:
        stop["go"] = False
        th.join(2)
