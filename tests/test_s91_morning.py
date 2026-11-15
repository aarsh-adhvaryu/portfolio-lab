"""S91: the morning's visible work. The day's saved study waits with a stated reason until today's complete Kite snapshot is in, runs once (a refresh, a second tick, a second thread or a restart never
repeats it), records its period, numbers and artifact, and takes over a run cut off by a crash; Home shows the release, the snapshot, the latest closed candle, the study and the next action.
Synthetic data only (AAAA..EEEE)."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pflab.app import investigation as inv
from pflab.app import runtime, s89, server
from pflab.pm import store

NOW = datetime(2026, 11, 16, 10, 30)
SYMS = ["AAAA", "BBBB", "CCCC"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    pm, data = tmp_path / "pm", tmp_path / "data"
    (data / "indices").mkdir(parents=True)
    monkeypatch.setenv("PFLAB_DATA_DIR", str(data))
    monkeypatch.setenv("PFLAB_PM_DIR", str(pm))
    from pflab.llm import claude_plan as cp
    monkeypatch.setattr(cp, "signin_fn", lambda: {"ok": True, "method": "claude.ai", "detail": ""})
    rt = runtime.Runtime(pm, data, tmp_path, con=store.connect(tmp_path / "l.duckdb"), clock=lambda: NOW)
    con = rt.cursor()
    s89.ensure(con)
    idx = pd.bdate_range("2023-01-02", periods=800)
    rng = np.random.default_rng(3)
    common = np.cumsum(rng.normal(0, 0.01, len(idx)))
    px = {s: pd.Series(100 * np.exp(common * w + np.cumsum(rng.normal(0, 0.004, len(idx)))), index=idx) for s, w in zip(SYMS, (1.0, 0.9, 0.2))}
    monkeypatch.setattr("pflab.agents.tradecheck.isin_of", lambda c, s: "ISIN_" + s if s in SYMS else None)
    monkeypatch.setattr("pflab.hq.stocks.closes", lambda c, root, isin, asof: px[isin[5:]])
    return rt, con


def _snap(con, when=NOW, n=3):
    con.execute("DELETE FROM mine_in_s89")
    for i, s in enumerate(SYMS[:n]):
        con.execute("INSERT INTO mine_in_s89 VALUES (?,?,'NSE',10,100,?,0,?)", [s, "ISIN_" + s, 110 - i, when])


def test_it_waits_with_a_reason_until_todays_complete_snapshot_is_in(env):
    rt, con = env
    assert "log in to Kite" in inv.run(rt, con, NOW)["why"]
    _snap(con, NOW - timedelta(days=1))
    r = inv.run(rt, con, NOW)
    assert r["state"] == "waiting" and "waiting for today's complete Kite snapshot" in r["why"] and inv.get(con, NOW.date())["status"] == "waiting"
    _snap(con, n=1)
    assert "at least two" in inv.run(rt, con, NOW)["why"]


def test_it_runs_once_records_its_period_numbers_and_artifact_and_never_repeats(env):
    rt, con = env
    _snap(con)
    out = inv.run(rt, con, NOW)
    assert out["state"] == "done"
    row = inv.get(con, NOW.date())
    assert row["status"] == "done" and row["attempts"] == 1 and row["period_from"] < row["period_to"] and row["subject"] in ("AAAA and BBBB", "AAAA and CCCC", "BBBB and CCCC")
    assert set(row["result"]) >= {"a", "b", "days", "p_value", "correlation", "verdict", "pairs_tried"} and row["result"]["pairs_tried"] == 3
    art = rt.data_root / "operator" / "research"
    assert __import__("pathlib").Path(row["artifact"]).exists()
    j = next(art.glob("pair_*.json"))
    assert json.loads(j.read_text(encoding="utf-8"))["days"] == row["result"]["days"]
    chat = con.execute("SELECT count(*) FROM chat_messages WHERE post_key LIKE 'investigation:%'").fetchone()[0]
    assert chat == 1
    again = inv.run(rt, con, NOW + timedelta(minutes=20))                                        # the next tick, a refresh, a restart: the same day, the same row
    assert again["state"] == "skipped" and con.execute("SELECT count(*) FROM investigations_s91").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM chat_messages WHERE post_key LIKE 'investigation:%'").fetchone()[0] == 1
    assert len(list(art.glob("pair_*.md"))) == 1


def test_two_threads_at_once_run_it_once(env):
    rt, con = env
    _snap(con)
    results = []
    cons = [rt.cursor() for _ in range(2)]
    ts = [threading.Thread(target=lambda c=c: results.append(inv.run(rt, c, NOW)["state"])) for c in cons]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert sorted(results) in (["done", "skipped"], ["done", "waiting"]) or results.count("done") == 1
    assert con.execute("SELECT count(*) FROM investigations_s91 WHERE status='done'").fetchone()[0] == 1


def test_a_run_cut_off_by_a_crash_is_taken_over_after_ten_minutes_and_attempts_are_capped(env):
    rt, con = env
    _snap(con)
    inv.ensure(con)
    con.execute("INSERT INTO investigations_s91 (day, kind, status, attempts, started_at) VALUES (?, 'pair', 'running', 1, ?)", [NOW.date(), NOW - timedelta(minutes=3)])
    assert inv.run(rt, con, NOW)["state"] == "skipped"                                           # someone is running it (3 minutes ago)
    r = inv.run(rt, con, NOW + timedelta(minutes=12))                                            # 15 minutes: it was cut off
    assert r["state"] == "done" and inv.get(con, NOW.date())["attempts"] == 2
    con.execute("UPDATE investigations_s91 SET status='failed', attempts=3 WHERE day=?", [NOW.date()])
    assert inv.run(rt, con, NOW + timedelta(hours=1))["state"] == "skipped"                       # three attempts: no more today


def test_home_shows_release_snapshot_candle_study_and_next_action(env, monkeypatch):
    rt, con = env
    c = TestClient(server.create_app(rt))
    h = c.get("/api/home").json()["status"]
    names = {r["name"]: r for r in h["rows"]}
    assert {"Running release", "Your holdings (Kite)", "Latest closed 5-minute candle", "Saved study today"} <= set(names)
    assert names["Your holdings (Kite)"]["state"] == "wait" and "log in to Kite" in names["Your holdings (Kite)"]["text"]
    assert "Log in to Kite" in h["next"] and names["Saved study today"]["state"] == "wait"
    _snap(con)
    inv.run(rt, con, NOW)
    con.execute("INSERT INTO bars_5m_s91 VALUES ('ISIN_AAAA', TIMESTAMP '2026-11-13 15:25:00', 1,1,1,1,1, now())") if con.execute("SELECT 1 FROM information_schema.tables WHERE table_name='bars_5m_s91'").fetchone() else None
    h = c.get("/api/home").json()["status"]
    st = {r["name"]: r for r in h["rows"]}
    assert st["Saved study today"]["state"] == "ok" and "to" in st["Saved study today"]["text"] and st["Your holdings (Kite)"]["text"].startswith("complete snapshot")
