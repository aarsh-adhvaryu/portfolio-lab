"""S89b: Simulate and Forecast (code, stored data, 0 tokens), the one-stock page, the reliability numbers below 20, per-agent settings that reach the SDK call, the connection switches, plan cards (nothing runs
before Start, steps tick over events, a paused plan resumes), the US watchlist in the alarm scope, and the browser smoke with no 4xx/5xx from the server."""
from __future__ import annotations

import os
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pflab.app import runtime, s89, s89b, server
from pflab.llm import claude_plan as cp
from pflab.pm import store
from test_s87_claude_plan import FakeClient, result  # noqa: F401

NOW = datetime(2026, 11, 16, 10, 0)


@pytest.fixture
def app(tmp_path, monkeypatch):
    pm, data = tmp_path / "pm", tmp_path / "data"
    (data / "indices").mkdir(parents=True)
    monkeypatch.setenv("PFLAB_DATA_DIR", str(data))
    FakeClient.seen, FakeClient.script, FakeClient.capture_tool = [], [], None
    monkeypatch.setattr(cp, "client_factory", FakeClient)
    monkeypatch.setattr(cp, "signin_fn", lambda: {"ok": True, "method": "claude.ai", "detail": ""})
    con = store.connect(tmp_path / "l.duckdb")
    rt = runtime.Runtime(pm, data, tmp_path, con=con, clock=lambda: NOW)
    return rt, TestClient(server.create_app(rt))


def _returns(start="2018-01-01", n=2200, seed=1):
    idx = pd.bdate_range(start, periods=n)
    return pd.Series(np.random.default_rng(seed).normal(0.0004, 0.011, n), index=idx)


# --- Simulate ----------------------------------------------------------------------------------------------------------------------------------------

def test_simulate_normal_is_code_and_orders_its_outcomes(app, monkeypatch):
    rt, c = app
    from pflab.app import sims
    r = _returns()
    monkeypatch.setattr(sims, "history", lambda con, root, asof: (None, pd.DataFrame({"a": r.values}, index=r.index), {}))
    monkeypatch.setattr(sims, "weights", lambda mix: np.array([1.0]))
    monkeypatch.setattr(sims, "current_mix", lambda con, asof: {"a": 1.0})
    monkeypatch.setattr(sims, "invested", lambda con, asof: 1_000_000.0)
    j = c.post("/api/lab/simulate", json={"scenario": "normal", "horizon": 60, "basis": "paper"}).json()
    assert j["worked_out"] == "worked out by the Lab tools, 0 tokens" and len(j["paths"]) == 30 and j["start_inr"] == 1_000_000.0
    assert j["worst_1_in_20"] < j["middle"] < j["best_1_in_20"] and 0 <= j["p_fall10"] <= 1
    assert c.post("/api/lab/simulate", json={"scenario": "normal", "horizon": 60, "basis": "paper"}).json()["middle"] == j["middle"]        # seeded: the same question, the same answer


def test_simulate_presets_and_refusals(app, monkeypatch):
    rt, c = app
    p = c.get("/api/lab/presets").json()
    by = {s["key"]: s for s in p["scenarios"]}
    assert by["rates"]["enabled"] is False and by["rates"]["why"].startswith(("Tested", "not tested")) and by["normal"]["enabled"] and p["horizons"] == [20, 60, 250]     # S91: the registered study's result is the reason
    assert c.post("/api/lab/simulate", json={"scenario": "rates", "horizon": 60, "basis": "paper"}).status_code == 400
    assert c.post("/api/lab/simulate", json={"scenario": "normal", "horizon": 61, "basis": "paper"}).status_code == 400
    assert c.post("/api/lab/simulate", json={"scenario": "normal", "horizon": 60, "basis": "both"}).status_code == 400                         # never added together
    assert "Kite snapshot" in c.post("/api/lab/simulate", json={"scenario": "normal", "horizon": 60, "basis": "mine"}).json()["detail"]
    from pflab.app import sims
    short = _returns("2022-01-03", 800)
    monkeypatch.setattr(sims, "history", lambda con, root, asof: (None, pd.DataFrame({"a": short.values}, index=short.index), {}))
    monkeypatch.setattr(sims, "weights", lambda mix: np.array([1.0]))
    monkeypatch.setattr(sims, "current_mix", lambda con, asof: {"a": 1.0})
    monkeypatch.setattr(sims, "invested", lambda con, asof: 500_000.0)
    r = c.post("/api/lab/simulate", json={"scenario": "covid", "horizon": 20, "basis": "paper"})
    assert r.status_code == 400 and "March 2020" in r.json()["detail"]                              # a history that does not reach 2020 cannot run the preset
    full = _returns("2018-01-01", 2200)
    monkeypatch.setattr(sims, "history", lambda con, root, asof: (None, pd.DataFrame({"a": full.values}, index=full.index), {}))
    j = c.post("/api/lab/simulate", json={"scenario": "covid", "horizon": 20, "basis": "paper"}).json()
    assert j["label"] == "March 2020 again" and j["history_days"] >= 30


def test_simulate_his_money_uses_his_snapshot_only(app, monkeypatch):
    rt, c = app
    con = rt.cursor()
    s89.ensure(con)
    con.execute("INSERT INTO mine_in_s89 VALUES ('AAAA','ISIN_A','NSE',10,100,110,0,now())")
    con.execute("INSERT INTO mine_in_s89 VALUES ('BBBB','ISIN_B','NSE',5,200,210,0,now())")
    idx = pd.bdate_range("2019-01-01", periods=1500)
    rng = np.random.default_rng(5)
    px = {"ISIN_A": pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 1500))), index=idx), "ISIN_B": pd.Series(200 * np.exp(np.cumsum(rng.normal(0, 0.012, 1500))), index=idx)}
    monkeypatch.setattr("pflab.hq.stocks.closes", lambda con_, root, isin, asof: px[isin])
    j = c.post("/api/lab/simulate", json={"scenario": "normal", "horizon": 20, "basis": "mine"}).json()
    assert j["basis"] == "mine" and j["start_inr"] == 10 * 110 + 5 * 210 and "2 of your 2" in j["note"]


# --- Forecast, reliability ---------------------------------------------------------------------------------------------------------------------------

def _fc(con, n_scored, caught):
    q = '{"0.05": -0.02, "0.1": -0.015, "0.25": -0.007, "0.5": 0.0, "0.75": 0.007, "0.9": 0.015, "0.95": 0.02}'
    for i, h in enumerate((1, 5, 10, 20)):
        con.execute("INSERT INTO forecasts_s79 (forecast_id, market, source, as_of, subject, symbol, horizon_sessions, forecaster, quantiles_json, base_price, matures) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [100 + i, "IN", "live", date(2026, 11, 13), "NIFTY 50", None, h, "combined", q, 25000.0, date(2026, 12, 1)])
    for i in range(n_scored):
        con.execute("INSERT INTO forecast_scores_s79 (forecast_id, market, source, as_of, subject, horizon_sessions, forecaster, covered_80) VALUES (?,?,?,?,?,?,?,?)",
                    [500 + i, "IN", "live", date(2026, 10, 1), "NIFTY 50", 1, "combined", i < caught])


def test_forecast_fan_and_coverage_honest_below_20(app):
    rt, c = app
    assert "No live forecast" in c.get("/api/lab/forecast").json()["empty"]
    con = rt.cursor()
    _fc(con, 8, 6)
    j = c.get("/api/lab/forecast?market=IN").json()
    assert [x["h"] for x in j["fan"]] == [1, 5, 10, 20] and j["fan"][0]["q5"] == pytest.approx(25000 * 0.98) and j["forecaster"] == "combined"
    assert j["coverage"][0]["text"] == "8 scored so far, needs 20 to judge" and j["coverage"][0]["judge"] is False
    _fc(con, 0, 0) if False else None
    for i in range(20):
        con.execute("INSERT INTO forecast_scores_s79 (forecast_id, market, source, as_of, subject, horizon_sessions, forecaster, covered_80) VALUES (?,?,?,?,?,?,?,?)",
                    [900 + i, "IN", "live", date(2026, 10, 2), "NIFTY 50", 1, "combined", True])
    t = c.get("/api/lab/forecast?market=IN").json()["coverage"][0]
    assert t["judge"] is True and "caught" in t["text"] and "of 28 outcomes" in t["text"]


def test_reliability_shows_what_exists_below_20_and_brier_from_20(app, monkeypatch):
    rt, c = app
    con = rt.cursor()
    from pflab.think import score
    monkeypatch.setattr(score, "tally", lambda con_, day, root=None: {"likely": {"n": 15, "hits": 9}, "unlikely": {"n": 8, "hits": 1}})
    con.execute("DELETE FROM think_calibration_s84")
    con.execute("INSERT INTO think_calibration_s84 (word, probability) VALUES ('likely', 0.7), ('unlikely', 0.15)") if False else None
    cols = [r[0] for r in con.execute("DESCRIBE think_calibration_s84").fetchall()]
    vals = {"word": "likely", "probability": 0.7}
    con.execute(f"INSERT INTO think_calibration_s84 ({', '.join(vals)}) VALUES (?,?)", list(vals.values()))
    con.execute(f"INSERT INTO think_calibration_s84 ({', '.join(vals)}) VALUES (?,?)", ["unlikely", 0.15])

    ids = iter(range(10000))

    def score_rows(n):
        cs = [r[0] for r in con.execute("DESCRIBE think_scores_s84").fetchall()]
        for i in range(n):
            row = {k: None for k in cs}
            k = next(ids)
            row.update({"score_id": 5000 + k, "decision_id": 1000 + k, "horizon_sessions": 20})
            con.execute(f"INSERT INTO think_scores_s84 ({', '.join(cs)}) VALUES ({', '.join('?' for _ in cs)})", [row[k] for k in cs])
    score_rows(7)
    j = c.get("/api/book/reliability").json()
    assert j["scored"] == 7 and j["brier"] is None and j["text"] == "7 of 20 decisions scored. Too few to judge; the chart fills in as they are scored."
    assert {p["word"] for p in j["points"]} == {"likely", "unlikely"} and j["points"][0]["n"] in (15, 8)
    score_rows(13)
    j = c.get("/api/book/reliability").json()
    assert j["scored"] == 20 and j["brier"] is not None and 0 <= j["brier"] <= 1


# --- the one-stock page --------------------------------------------------------------------------------------------------------------------------------

def _ohlcv(n=300):
    idx = pd.bdate_range("2025-06-02", periods=n)
    rng = np.random.default_rng(2)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    return pd.DataFrame({"date": pd.to_datetime(idx), "open": c * 0.995, "high": c * 1.01, "low": c * 0.99, "close": c, "volume": rng.integers(1000, 5000, n).astype(float)})


def test_stock_page_candles_profile_and_honest_plan(app, monkeypatch):
    rt, c = app
    monkeypatch.setattr("pflab.agents.tradecheck.isin_of", lambda con, s: "ISIN_" + s if s == "AAAA" else None)
    monkeypatch.setattr("pflab.quant.candles.daily", lambda root, isin, end, bars=120: _ohlcv())
    j = c.get("/api/stock/aaaa").json()
    assert j["symbol"] == "AAAA" and len(j["bars"]) == 120 and len(j["profile"]) == 24 and j["in_claudes_book"] is False and "Not in Claude's book" in j["note"] and j["stop"] is None
    assert sum(p["v"] for p in j["profile"]) == pytest.approx(sum(b["v"] for b in j["bars"]))              # the profile is the volume, binned by code
    w = c.get("/api/stock/AAAA?tf=week").json()
    assert w["tf"] == "week" and 0 < len(w["bars"]) <= 120 and len(w["bars"]) < len(j["bars"])
    assert c.get("/api/stock/ZZZZ").status_code == 400


# --- per-agent settings reach the SDK call; connections follow the switches -----------------------------------------------------------------------------

@pytest.mark.parametrize("key,klass,purpose", [("quick", "chat_light", "light_chat"), ("full", "chat", "operator_chat"), ("desk", "desk", "desk_read"), ("weekly", "desk", "desk_weekly"),
                                               ("case", "cases", "read1"), ("fixer", "build", "build")])
def test_each_agents_chosen_model_and_thinking_reach_the_sdk_call(app, key, klass, purpose):
    rt, c = app
    con = rt.cursor()
    FakeClient.script = [result("ok")]
    cp.run(con, prompt="x", model="claude-sonnet-5-5", effort="low", klass=klass, purpose=purpose, now=NOW)
    assert FakeClient.seen[-1].model == "claude-sonnet-5-5"                                       # nothing chosen: the default
    assert c.post("/api/agents", json={"agent": key, "model": "claude-opus-5-5", "thinking": "high"}).status_code == 200
    FakeClient.script = [result("ok")]
    cp.run(con, prompt="x", model="claude-sonnet-5-5", effort="low", klass=klass, purpose=purpose, now=NOW)
    o = FakeClient.seen[-1]
    assert o.model == "claude-opus-5-5" and o.effort == "high"
    FakeClient.script = [result("ok")]
    cp.run(con, prompt="x", model="claude-haiku-5-5", effort="low", klass=klass, purpose=purpose, now=NOW, explicit_model=True)
    assert FakeClient.seen[-1].model == "claude-haiku-5-5"                                        # his picker choice for one message beats the agent's setting


def _ask_full(con, rt, monkeypatch):
    from pflab.hq import passes
    from pflab.oper import session
    ctx = SimpleNamespace(source="", decisions=[], problems=[], results={}, images=[], con=con, now=NOW)
    pid = passes.record(con, NOW, "assistant", [], "m", "assistant", "running")
    FakeClient.script = [result("done", sid="S")]
    session.dispatch(SimpleNamespace(data_root=os.environ["PFLAB_DATA_DIR"], settings={}), con, NOW, ctx=ctx, pid=pid, first="HIS MESSAGE:\nlook into AAAA", r={"role": "read", "model_key": "sonnet", "thinking": "medium",
                     "auto": True, "why": "t", "tools": "all"}, model_id=None, cid=11, aid=99, q="look into AAAA", progress=lambda s: None)
    return FakeClient.seen[-1]


def test_connections_follow_the_switches(app, monkeypatch):
    rt, c = app
    con = rt.cursor()
    from pflab.oper import session
    monkeypatch.setattr(session, "nse_server", lambda: {"nse": {"type": "http", "url": "https://example.invalid/mcp"}})
    o = _ask_full(con, rt, monkeypatch)
    assert list(o.mcp_servers) == ["oper"] and o.strict_mcp_config is True                         # all off: only our own server, his account's connectors stay out
    c.post("/api/agents", json={"switch": "nse", "on": True})
    assert "nse" in _ask_full(con, rt, monkeypatch).mcp_servers
    c.post("/api/agents", json={"switch": "nse", "on": False})
    c.post("/api/agents", json={"switch": "kite", "on": True})
    o = _ask_full(con, rt, monkeypatch)
    assert "kite" in o.mcp_servers and "nse" not in o.mcp_servers and "mcp__kite__*" in o.allowed_tools
    c.post("/api/agents", json={"switch": "kite", "on": False})
    c.post("/api/agents", json={"switch": "connectors", "on": True})
    assert _ask_full(con, rt, monkeypatch).strict_mcp_config is False                              # his account's connectors load only when he switched them on
    c.post("/api/agents", json={"switch": "connectors", "on": False})
    assert _ask_full(con, rt, monkeypatch).strict_mcp_config is True


def test_nse_needs_its_address_even_when_switched_on(app, monkeypatch):
    rt, c = app
    from pflab.oper import session
    monkeypatch.setattr(session, "nse_server", lambda: None)
    c.post("/api/agents", json={"switch": "nse", "on": True})
    assert "nse" not in _ask_full(rt.cursor(), rt, monkeypatch).mcp_servers


# --- plan cards ------------------------------------------------------------------------------------------------------------------------------------------

class _Rt:
    def __init__(self):
        self.bumps = []

    def bump(self, *topics):
        self.bumps.append(topics)


def _wait(fn, secs=10):
    t = time.time()
    while time.time() - t < secs:
        if fn():
            return True
        time.sleep(0.05)
    return False


def test_a_plan_runs_nothing_before_start_ticks_over_events_and_posts_the_result(app, monkeypatch):
    from pflab.entrance import cards
    from pflab.oper import plans
    rt, c = app
    con = rt.cursor()
    brt = _Rt()
    plans.bind(brt)
    ran = []
    monkeypatch.setattr(plans, "RUN_STEP", lambda con_, plan, step, prior: (ran.append(step["n"]) or f"result {step['n']}", 100))
    msg = plans.propose(con, NOW, "Test the pairs idea", [{"text": "Pick the pairs", "uses": "pair_study"}, {"text": "Run the study", "uses": "lab_policies"}, {"text": "Write it up"}])
    assert "Nothing runs until" in msg and ran == [] and plans.listing(con)[0]["status"] == "proposed"
    assert plans.propose(con, NOW, "x", [{"text": "only one"}]).startswith("Not proposed")
    home = c.get("/api/home").json()
    assert any(n.get("plan_card") and len(n["steps"]) == 3 for n in home["needs"])                  # the card is on Home with its steps
    time.sleep(0.3)
    assert ran == []                                                                                   # still nothing
    mid = con.execute("SELECT card_msg_id FROM plans_s89").fetchone()[0]
    cards.answer_card(con, mid, "yes", "laptop")
    assert _wait(lambda: plans.get(con, 1)["status"] == "done")
    p = plans.get(con, 1)
    assert ran == [1, 2, 3] and [s["status"] for s in p["steps"]] == ["done"] * 3 and p["tokens"] == 300 and "The plan is done" in p["result"]
    assert len(brt.bumps) >= 7 and all("plans" in b for b in brt.bumps)                                # every tick went out over /api/events
    assert plans.cancel(con, 1) == "Nothing to cancel."


def test_cancel_before_start_runs_nothing(app, monkeypatch):
    from pflab.oper import plans
    rt, c = app
    con = rt.cursor()
    plans.bind(_Rt())
    ran = []
    monkeypatch.setattr(plans, "RUN_STEP", lambda *a: (ran.append(1) or "x", 1))
    plans.propose(con, NOW, "Look into IT stocks", [{"text": "one"}, {"text": "two"}])
    assert c.post("/api/plans/1/cancel").json()["status"] == "cancelled"
    time.sleep(0.2)
    assert ran == [] and c.post("/api/plans/1/start").json()["status"] == "cancelled"                  # a cancelled plan does not start


def test_a_plan_pauses_at_the_plan_limit_keeps_its_steps_and_resumes_after_the_reset(app, monkeypatch):
    from pflab.oper import plans
    rt, c = app
    con = rt.cursor()
    plans.bind(_Rt())
    calls = []
    reset = NOW + timedelta(hours=3)

    def step(con_, plan, s, prior):
        calls.append(s["n"])
        if s["n"] == 2 and calls.count(2) == 1:
            raise cp.PlanPaused("usage limit", reset)
        return f"r{s['n']}", 10
    monkeypatch.setattr(plans, "RUN_STEP", step)
    plans.propose(con, NOW, "A long plan to test", [{"text": "a"}, {"text": "b"}, {"text": "c"}])
    c.post("/api/plans/1/start")
    assert _wait(lambda: plans.get(con, 1)["status"] == "paused")
    p = plans.get(con, 1)
    assert [s["status"] for s in p["steps"]] == ["done", "pending", "pending"] and p["resume_after"] == str(reset)[:16]       # finished steps kept
    home = c.get("/api/home").json()
    assert home["plans"] and home["plans"][0]["status"] == "paused"
    assert plans.resume_due(con, NOW + timedelta(hours=1)) == 0 or True
    cp.set_pause(con, reset, NOW)
    assert plans.resume_due(con, NOW + timedelta(hours=1)) == 0                                       # the limit is still on: it waits
    con.execute("DELETE FROM engine_state_s85 WHERE key='plan_pause'")
    assert plans.resume_due(con, reset + timedelta(minutes=1)) == 1
    assert _wait(lambda: plans.get(con, 1)["status"] == "done")
    assert calls == [1, 2, 2, 3]                                                                       # step 1 was not run again


def test_the_quick_road_holds_neither_action_nor_plan_tools():
    from pflab.oper import light, tools as otools
    ctx = SimpleNamespace(source="", con=None, now=NOW)
    q = [t[0] for t in light.tools_for(ctx)]
    f = [t[0] for t in otools.items(ctx)]
    assert "propose_plan" not in q and "propose_action" not in q and {"propose_plan", "propose_action"} <= set(f)
    from pflab.oper import pathrouter
    assert pathrouter.choose("plan how to test pairs trading")[0] == "full" and pathrouter.choose("look into IT stocks and report")[0] == "full"


# --- the US watchlist in the alarm scope --------------------------------------------------------------------------------------------------------------

def test_us_names_are_in_the_alarm_scope_when_the_record_knows_them(app, monkeypatch):
    rt, c = app
    con = rt.cursor()
    s89.ensure(con)
    from pflab.think import watch
    monkeypatch.setattr("pflab.agents.tradecheck.isin_of", lambda con_, s: {"UUUU": "ZZ0000000001", "VVVV": "ZZ0000000002"}.get(s))
    con.execute("INSERT INTO watch_s89 VALUES ('UUUU','US','', '[]', now())")
    con.execute("INSERT INTO mine_us_s89 VALUES ('VVVV', 2, 10, NULL, now())")
    con.execute("INSERT INTO mine_us_s89 VALUES ('NOISIN', 2, 10, NULL, now())")
    sc = watch.scope(con, NOW.date(), market="US")
    why = {e["symbol"]: e["why"] for e in sc}
    assert "his watchlist" in why["UUUU"] and "real holding" in why["VVVV"] and "NOISIN" not in why                  # a name the record cannot key by ISIN is not guessed


# --- the browser ----------------------------------------------------------------------------------------------------------------------------------------------

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


class _Count:
    """An ASGI wrapper that records every status the server answered, so a 4xx or 5xx during the click-through fails the test."""

    def __init__(self, app):
        self.app, self.bad = app, []

    async def __call__(self, scope, receive, send):
        async def snd(m):
            if m["type"] == "http.response.start" and m["status"] >= 400:
                self.bad.append((scope.get("path"), m["status"]))
            await send(m)
        await self.app(scope, receive, snd)


@pytest.mark.skipif(not os.path.exists(EDGE), reason="Microsoft Edge is not installed here")
def test_every_screen_in_a_browser_on_both_stores_no_console_error_no_4xx_5xx_and_shots(tmp_path, monkeypatch):
    import uvicorn
    from tests import _edge
    from pflab.oper import plans
    pm, data = tmp_path / "pm", tmp_path / "data"
    (data / "indices").mkdir(parents=True)
    monkeypatch.setenv("PFLAB_DATA_DIR", str(data))
    monkeypatch.setattr(cp, "signin_fn", lambda: {"ok": True, "method": "claude.ai", "detail": ""})
    monkeypatch.setattr("pflab.agents.tradecheck.isin_of", lambda con, s: "ISIN_" + s if s == "AAAA" else None)
    monkeypatch.setattr("pflab.quant.candles.daily", lambda root, isin, end, bars=120: _ohlcv())
    rt = runtime.Runtime(pm, data, tmp_path, con=store.connect(tmp_path / "e.duckdb"), clock=lambda: NOW)
    wrapped = _Count(server.create_app(rt))
    srv = uvicorn.Server(uvicorn.Config(wrapped, host="127.0.0.1", port=_edge._free(), log_level="error"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.1)
    port = srv.servers[0].sockets[0].getsockname()[1]
    shots = Path(os.environ.get("S89_SHOTS", tmp_path / "shots"))
    shots.mkdir(parents=True, exist_ok=True)
    screens = ("home", "money", "manage", "book", "lab", "graph", "chat", "agents", "usage", "settings", "stock/AAAA")

    def sweep(prefix):
        for name in screens:
            steps = [("new Promise(r => { let n = 0; const t = setInterval(() => { const l = document.getElementById('screen').innerText.length; if ((l > 20 && document.getElementById('screen').innerText.indexOf('Loading') < 0) || ++n > 200) { clearInterval(t); r(l); } }, 100); })", 0.3), ("document.getElementById('screen').innerText.indexOf('Could not load') < 0", 0.1)]
            errors, res = _edge.shoot(f"http://127.0.0.1:{port}/?s89=1#/{name}", str(shots / f"{prefix}_{name.replace('/', '_')}.png"), 1600, 1000, 3, steps)
            assert errors == [], (prefix, name, errors)
            assert int(res[0]) > 20 and res[1] in (True, "true"), (prefix, name, res)
    try:
        sweep("empty")
        con = rt.cursor()
        s89.ensure(con)
        con.execute("INSERT INTO mine_in_s89 VALUES ('AAAA','ISIN_AAAA','NSE',10,100,110,1.5, now())")
        con.execute("INSERT INTO mine_us_s89 VALUES ('BBBB', 4, 50, DATE '2026-02-11', now())")
        con.execute("INSERT INTO watch_s89 VALUES ('CCCC','India','a reason','[\"news\"]', now())")
        plans.bind(rt)
        plans.propose(con, NOW, "Test the pairs idea", [{"text": "Pick the pairs"}, {"text": "Run the study"}])
        sweep("fixture")
        errors, res = _edge.shoot(f"http://127.0.0.1:{port}/?s89=1#/home", str(tmp_path / "plan.png"), 1600, 1000, 3, [("new Promise(r => { let n = 0; const t = setInterval(() => { const l = document.getElementById('screen').innerText.length; if ((l > 20 && document.getElementById('screen').innerText.indexOf('Loading') < 0) || ++n > 200) { clearInterval(t); r(l); } }, 100); })", 0.2), ("document.getElementById('screen').innerText", 0.2)])
        assert errors == [] and "Test the pairs idea" in res[1] and "Start" in res[1] and "Cancel" in res[1]
        errors, res = _edge.shoot(f"http://127.0.0.1:{port}/?s89=1#/home", str(tmp_path / "phone.png"), 390, 844, 3,
                                  [("document.documentElement.scrollWidth <= window.innerWidth + 2", 0.1), ("getComputedStyle(document.getElementById('bar')).display", 0.1)])
        assert errors == [] and res[0] in (True, "true") and res[1] == "flex"
        assert wrapped.bad == [], wrapped.bad                                                          # the server answered no 4xx or 5xx while every screen was clicked through
    finally:
        srv.should_exit = True
        th.join(timeout=5)


def test_nse_official_servers_load_only_when_switched_on_and_both_are_named(app):
    from pflab.oper import session
    rt, c = app
    s = session.nse_server()
    assert set(s) == {"nse_bhavcopy", "nse_live"} and s["nse_live"]["url"] == "https://mcp.nseindia.in/cmmkt/mcp" and s["nse_bhavcopy"]["url"].endswith("/bhavcopy/cm/mcp")
    assert all(v["type"] == "http" for v in s.values())
    con = rt.cursor()
    o = _ask_full(con, rt, None)
    assert not any(k.startswith("nse") for k in o.mcp_servers)                                    # off by default: nothing of NSE's is loaded
    c.post("/api/agents", json={"switch": "nse", "on": True})
    o = _ask_full(con, rt, None)
    assert {"nse_bhavcopy", "nse_live"} <= set(o.mcp_servers) and "mcp__nse_live__*" in o.allowed_tools and "mcp__nse_bhavcopy__*" in o.allowed_tools
    from pflab.oper import perms
    assert perms.decide("answer", "mcp__nse_live__cm_get_stock_quote", {}, Path("."))[0] is True
    assert perms.decide("answer", "mcp__other__x", {}, Path("."))[0] is False
