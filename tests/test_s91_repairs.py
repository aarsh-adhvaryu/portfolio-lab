"""S91: four reproduced reliability defects, each with its regression test. (1) an answer session cannot run a script it wrote; (2) a simulation on partly covered holdings reports the
coverage and simulates only the covered rupees; (3) a bad Kite response leaves the last complete snapshot untouched and an older response cannot overwrite a newer one; (4) a plan
left 'running' by a killed process is recovered at the next start (a REAL process kill), and a cancel stays a cancel. Synthetic data only (AAAA, BBBB)."""
from __future__ import annotations

import subprocess
import sys
import textwrap
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pflab.app import runtime, s89, s89b, server
from pflab.oper import perms, plans
from pflab.pm import store

NOW = datetime(2026, 11, 16, 10, 0)


@pytest.fixture
def app(tmp_path, monkeypatch):
    pm, data = tmp_path / "pm", tmp_path / "data"
    (data / "indices").mkdir(parents=True)
    monkeypatch.setenv("PFLAB_DATA_DIR", str(data))
    monkeypatch.setenv("PFLAB_PM_DIR", str(pm))
    rt = runtime.Runtime(pm, data, tmp_path, con=store.connect(tmp_path / "l.duckdb"), clock=lambda: NOW)
    return rt, TestClient(server.create_app(rt))


# --- 1. an answer cannot run a script -------------------------------------------------------------------------------------------------------------------

def test_an_answer_session_runs_no_script_of_its_own(tmp_path):
    for cmd in ("python -I research/study.py", "python research/study.py", "python.exe -I research/a/b.py x=1", "python -I research/../src/x.py", "py research/x.py"):
        ok, why = perms.decide("answer", "Bash", {"command": cmd}, tmp_path)
        assert not ok, cmd
    assert perms.decide("answer", "Bash", {"command": "pflab pm networth"}, tmp_path)[0]               # the read-only pflab commands stay
    assert perms.decide("answer", "Write", {"file_path": str(tmp_path / "research" / "note.md")}, tmp_path)[0]       # notes and findings as text stay
    assert not perms.decide("answer", "Write", {"file_path": str(tmp_path / "src" / "x.py")}, tmp_path)[0]


# --- 2. partial coverage ---------------------------------------------------------------------------------------------------------------------------------

def _hist(monkeypatch, covered: dict):
    idx = pd.bdate_range("2019-01-01", periods=1500)

    def closes(con, root, isin, asof):
        if isin not in covered:
            raise KeyError(isin)
        return pd.Series(100 * np.cumprod(1 + np.full(1500, 0.001)), index=idx)
    monkeypatch.setattr("pflab.hq.stocks.closes", closes)


def test_a_mostly_uncovered_portfolio_is_simulated_on_its_covered_part_only(app, monkeypatch):
    rt, c = app
    con = rt.cursor()
    s89.ensure(con)
    con.execute("INSERT INTO mine_in_s89 VALUES ('AAAA','ISIN_A','NSE',1,100,100,0,now())")              # Rs 100 with history
    con.execute("INSERT INTO mine_in_s89 VALUES ('BBBB','ISIN_B','NSE',9,100,100,0,now())")              # Rs 900 without
    _hist(monkeypatch, {"ISIN_A": 1})
    j = c.post("/api/lab/simulate", json={"scenario": "normal", "horizon": 20, "basis": "mine"}).json()
    cov = j["coverage"]
    assert j["start_inr"] == 100.0 and cov["covered_inr"] == 100.0 and cov["uncovered_inr"] == 900.0 and cov["total_inr"] == 1000.0
    assert round(cov["covered_pct"]) == 10 and round(cov["uncovered_pct"]) == 90 and cov["uncovered_names"] == ["BBBB"]
    assert 100 < j["middle"] < 103 and "1 of your 2" in j["note"] and "90%" in j["note"]                  # the Rs 100 grew; the Rs 900 was NOT given its returns (it was Rs 1,020 before)


def test_full_and_zero_coverage_through_the_endpoint(app, monkeypatch):
    rt, c = app
    con = rt.cursor()
    s89.ensure(con)
    con.execute("INSERT INTO mine_in_s89 VALUES ('AAAA','ISIN_A','NSE',1,100,100,0,now())")
    con.execute("INSERT INTO mine_in_s89 VALUES ('BBBB','ISIN_B','NSE',9,100,100,0,now())")
    _hist(monkeypatch, {"ISIN_A": 1, "ISIN_B": 1})
    full = c.post("/api/lab/simulate", json={"scenario": "normal", "horizon": 20, "basis": "mine"}).json()
    assert full["start_inr"] == 1000.0 and full["coverage"]["uncovered_inr"] == 0 and full["coverage"]["covered_pct"] == 100.0 and full["coverage"]["uncovered_names"] == []
    _hist(monkeypatch, {})
    r = c.post("/api/lab/simulate", json={"scenario": "normal", "horizon": 20, "basis": "mine"})
    assert r.status_code == 400 and "enough stored price history" in r.json()["detail"]                    # nothing covered: no number at all


# --- 3. the Kite snapshot -----------------------------------------------------------------------------------------------------------------------------------

class _Kite:
    def __init__(self, rows):
        self.rows = rows

    def holdings(self):
        return self.rows


GOOD = [{"tradingsymbol": "AAAA", "isin": "ISIN_A", "exchange": "NSE", "quantity": 10, "average_price": 100, "last_price": 110, "day_change_percentage": 1.0},
        {"tradingsymbol": "BBBB", "isin": "ISIN_B", "exchange": "NSE", "quantity": 5, "average_price": 200, "last_price": 210, "day_change_percentage": -1.0}]


def test_a_bad_row_keeps_the_last_complete_snapshot_and_says_so(app):
    rt, c = app
    con = rt.cursor()
    assert s89.refresh_india(rt, con, NOW, force=True, kite=_Kite(GOOD))["state"] == "ok"
    assert {r[0] for r in con.execute("SELECT symbol FROM mine_in_s89").fetchall()} == {"AAAA", "BBBB"}
    bad = [GOOD[0], {**GOOD[1], "last_price": "not a number"}]
    out = s89.refresh_india(rt, con, NOW + timedelta(minutes=10), force=True, kite=_Kite(bad))
    assert out["state"] == "error" and "ValueError" in out["error"]
    assert {r[0] for r in con.execute("SELECT symbol FROM mine_in_s89").fetchall()} == {"AAAA", "BBBB"}      # both holdings are still there
    assert s89._meta(con, "india_refresh")[0] == "error" and s89._snap_at(con) == NOW
    nan = [GOOD[0], {**GOOD[1], "last_price": float("nan")}]
    assert s89.refresh_india(rt, con, NOW + timedelta(minutes=11), force=True, kite=_Kite(nan))["state"] == "error"
    assert s89._snap_at(con) == NOW
    assert s89.refresh_india(rt, con, NOW + timedelta(minutes=12), force=True, kite=_Kite(GOOD[:1]))["state"] == "ok"     # a complete response replaces the whole snapshot
    assert [r[0] for r in con.execute("SELECT symbol FROM mine_in_s89").fetchall()] == ["AAAA"]


def test_an_older_response_never_overwrites_a_newer_snapshot(app):
    rt, c = app
    con = rt.cursor()
    s89.refresh_india(rt, con, NOW, force=True, kite=_Kite(GOOD))
    s89.refresh_india(rt, con, NOW + timedelta(minutes=5), force=True, kite=_Kite(GOOD[:1]))
    late = s89.refresh_india(rt, con, NOW + timedelta(minutes=1), force=True, kite=_Kite(GOOD))              # a slow response that started earlier
    assert late.get("cached") and [r[0] for r in con.execute("SELECT symbol FROM mine_in_s89").fetchall()] == ["AAAA"]


# --- 4. plans ------------------------------------------------------------------------------------------------------------------------------------------------

def _plan(con, steps=3):
    plans.propose(con, NOW, "A plan about the pairs", [{"text": f"step {i}"} for i in range(1, steps + 1)])
    return int(con.execute("SELECT max(plan_id) FROM plans_s89").fetchone()[0])


def _wait(fn, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if fn():
            return True
        time.sleep(0.05)
    return False


def test_a_plan_left_running_by_a_dead_process_is_recovered_and_continues(app, monkeypatch):
    rt, c = app
    con = rt.cursor()
    plans.bind(type("R", (), {"bump": lambda self, *a: None, "data_root": rt.data_root})())
    pid = _plan(con)
    con.execute("UPDATE plans_s89 SET status='running' WHERE plan_id=?", [pid])                                  # the state a crash leaves behind
    con.execute("UPDATE plan_steps_s89 SET status='done', result='first result', tokens=50 WHERE plan_id=? AND n=1", [pid])
    con.execute("UPDATE plan_steps_s89 SET status='running' WHERE plan_id=? AND n=2", [pid])
    seen = []
    monkeypatch.setattr(plans, "RUN_STEP", lambda con_, plan, step, prior: (seen.append((step["n"], step.get("result"), prior)) or f"result {step['n']}", 10))
    assert plans.reconcile(con, NOW) == 1
    p = plans.get(con, pid)
    assert p["status"] == "paused" and [s["status"] for s in p["steps"]] == ["done", "pending", "pending"] and p["steps"][0]["result"] == "first result"
    assert "cut off" in p["steps"][1]["result"]
    assert plans.reconcile(con, NOW) == 0                                                                        # idempotent
    assert plans.resume_due(con, NOW) == 1
    assert _wait(lambda: plans.get(con, pid)["status"] == "done")
    p = plans.get(con, pid)
    assert [s["status"] for s in p["steps"]] == ["done"] * 3 and p["steps"][0]["result"] == "first result"       # the finished step was kept, not repeated
    assert [n for n, _, _ in seen] == [2, 3] and "first result" in seen[0][2] and seen[0][1].startswith("interrupted")


def test_a_running_plan_this_process_owns_is_not_taken_for_abandoned(app, monkeypatch):
    rt, c = app
    con = rt.cursor()
    plans.bind(type("R", (), {"bump": lambda self, *a: None, "data_root": rt.data_root})())
    pid = _plan(con, 2)
    gate = threading.Event()
    monkeypatch.setattr(plans, "RUN_STEP", lambda con_, plan, step, prior: (gate.wait(5) and f"r{step['n']}", 1))
    plans.start(con, NOW, pid)
    assert _wait(lambda: plans.get(con, pid)["steps"][0]["status"] == "running")
    assert plans.reconcile(con, NOW) == 0 and plans.get(con, pid)["status"] == "running"
    gate.set()
    assert _wait(lambda: plans.get(con, pid)["status"] == "done")


def test_a_cancel_stays_a_cancel_when_the_step_finishes_after_it(app, monkeypatch):
    rt, c = app
    con = rt.cursor()
    plans.bind(type("R", (), {"bump": lambda self, *a: None, "data_root": rt.data_root})())
    pid = _plan(con, 2)
    gate = threading.Event()
    monkeypatch.setattr(plans, "RUN_STEP", lambda con_, plan, step, prior: (gate.wait(5) and f"r{step['n']}", 7))
    plans.start(con, NOW, pid)
    assert _wait(lambda: plans.get(con, pid)["steps"][0]["status"] == "running")
    plans.cancel(con, pid)
    gate.set()
    assert _wait(lambda: pid not in plans._RUNNING)
    p = plans.get(con, pid)
    assert p["status"] == "cancelled" and [s["status"] for s in p["steps"]] == ["skipped", "skipped"]            # it did not become done, the second step never ran


CHILD = textwrap.dedent('''
    import sys, time
    from datetime import datetime
    from pathlib import Path
    from pflab.oper import plans
    from pflab.pm import store
    db, = sys.argv[1:]
    con = store.connect(Path(db))
    plans.bind(type("R", (), {"bump": lambda self, *a: None, "data_root": Path(db).parent})())
    pid = None
    plans.propose(con, datetime(2026, 11, 16, 10, 0), "A plan about the pairs", [{"text": "step 1"}, {"text": "step 2"}, {"text": "step 3"}])
    pid = int(con.execute("SELECT max(plan_id) FROM plans_s89").fetchone()[0])
    def step(con_, plan, s, prior):
        if s["n"] == 2:
            print("READY", pid, flush=True)
            time.sleep(600)                                  # the process is killed here
        return f"result {s['n']}", 5
    plans.RUN_STEP = step
    plans.start(con, datetime(2026, 11, 16, 10, 0), pid)
    time.sleep(600)
''')


def test_a_real_process_kill_in_step_two_is_recovered_on_the_next_start(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path / "pm"))
    (tmp_path / "pm").mkdir()
    db = tmp_path / "pm" / "kill.duckdb"
    script = tmp_path / "child.py"
    script.write_text(CHILD, encoding="utf-8")
    env = {**__import__("os").environ, "PFLAB_PM_DIR": str(tmp_path / "pm")}
    child = subprocess.Popen([sys.executable, str(script), str(db)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        line = child.stdout.readline()
        assert line.startswith("READY"), (line, child.stderr.read() if child.poll() is not None else "")
        pid = int(line.split()[1])
    finally:
        child.kill()                                                                                            # the real kill: no clean shutdown, no finally
        child.wait(10)
    con = store.connect(db)
    p = plans.get(con, pid)
    assert p["status"] == "running" and [s["status"] for s in p["steps"]] == ["done", "running", "pending"]       # the state a crash really leaves
    ran = []
    monkeypatch.setattr(plans, "RUN_STEP", lambda con_, plan, step, prior: (ran.append(step["n"]) or f"result {step['n']}", 5))
    plans.bind(type("R", (), {"bump": lambda self, *a: None, "data_root": tmp_path})())
    assert plans.resume_due(con, NOW) == 1
    assert _wait(lambda: plans.get(con, pid)["status"] == "done")
    assert ran == [2, 3] and plans.get(con, pid)["steps"][0]["result"] == "result 1"
