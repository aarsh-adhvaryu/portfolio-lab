"""S89: the endpoints behind the redesigned screens and the screens themselves. His US holdings are his alone (never the paper ledger), the watchlist is capped at 25, the pair study is code (0 tokens),
a chat action waits for his Yes, the quick road holds no action tool, the road picker reaches the router, and every screen loads in a real browser on an empty store without a console error."""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from pflab.app import runtime, s89, server
from pflab.pm import store

NOW = datetime(2026, 11, 16, 10, 0)


@pytest.fixture
def app(tmp_path, monkeypatch):
    pm, data = tmp_path / "pm", tmp_path / "data"
    (data / "indices").mkdir(parents=True)
    monkeypatch.setenv("PFLAB_DATA_DIR", str(data))
    from pflab.llm import claude_plan as cp
    monkeypatch.setattr(cp, "signin_fn", lambda: {"ok": True, "method": "claude.ai", "detail": ""})
    con = store.connect(tmp_path / "l.duckdb")
    rt = runtime.Runtime(pm, data, tmp_path, con=con, clock=lambda: NOW)
    return rt, TestClient(server.create_app(rt))


def test_mine_is_empty_with_a_plain_reason_and_home_answers(app):
    rt, c = app
    j = c.get("/api/mine").json()
    assert j["rows"] == [] and "No holdings yet" in j["empty"] and j["summary"]["value_inr"] is None
    h = c.get("/api/home").json()
    assert set(h) >= {"banner", "needs", "heard", "eyes", "plan", "paper", "mine"} and h["mine"]["value_inr"] is None
    assert h["banner"]["kind"] == "kite"                                                       # no Kite token on this profile: the banner says so, from real state


def test_us_entry_validates_and_never_reaches_the_paper_ledger(app):
    rt, c = app
    con = rt.cursor()
    before = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("paper_cash", "paper_days", "paper_decisions")}
    for bad in ({"ticker": "nv$a", "shares": 1, "avg_price": 1}, {"ticker": "NVDA", "shares": 0, "avg_price": 1}, {"ticker": "NVDA", "shares": 1, "avg_price": -3},
                {"ticker": "NVDA", "shares": 1, "avg_price": 1, "bought_on": "2027-01-01"}, {"ticker": "NVDA", "shares": "x", "avg_price": 1}):
        assert c.post("/api/mine/us", json={"action": "add", **bad}).status_code == 400
    assert c.post("/api/mine/us", json={"action": "add", "ticker": "nvda", "shares": 6, "avg_price": 136.1, "bought_on": "2026-02-11"}).json()["ticker"] == "NVDA"
    assert c.post("/api/mine/us", json={"action": "add", "ticker": "NVDA", "shares": 1, "avg_price": 1}).status_code == 400          # change, do not add twice
    assert c.post("/api/mine/us", json={"action": "set", "ticker": "NVDA", "shares": 4}).json()["shares"] == 4
    rows = c.get("/api/mine?tab=us").json()["rows"]
    assert len(rows) == 1 and rows[0]["qty"] == 4 and rows[0]["market"] == "us" and rows[0]["value_inr"] is None      # no price stored yet: "next check", not a made-up number
    assert c.post("/api/mine/us", json={"action": "remove", "ticker": "NVDA"}).status_code == 200 and c.get("/api/mine?tab=us").json()["rows"] == []
    after = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in before}
    assert before == after                                                                       # nothing entered by hand ever lands in the paper book
    for t in ("paper_cash", "paper_days", "paper_decisions"):
        assert "mine_us" not in t


def test_india_snapshot_is_replaced_not_accumulated_and_read_only(app):
    rt, c = app
    con = rt.cursor()

    class K:
        def __init__(self, rows):
            self.rows = rows

        def holdings(self):
            return self.rows
    rows = [{"tradingsymbol": "AAAA", "isin": "INE000A01011", "exchange": "NSE", "quantity": 10, "t1_quantity": 0, "average_price": 100.0, "last_price": 110.0, "day_change_percentage": 1.5}]
    s89.refresh_india(rt, con, NOW, force=True, kite=K(rows))
    s89.refresh_india(rt, con, NOW, force=True, kite=K([{**rows[0], "tradingsymbol": "BBBB", "quantity": 5}]))
    names = [r[0] for r in con.execute("SELECT symbol FROM mine_in_s89").fetchall()]
    assert names == ["BBBB"]                                                                     # only the latest snapshot, no history
    assert s89.refresh_india(rt, con, NOW, kite=K([]))["cached"] is True                         # at most every 5 minutes
    j = c.get("/api/mine?tab=in").json()
    assert j["rows"][0]["value_inr"] == 550.0 and j["state"]["kite"] == "ok"
    assert not hasattr(K, "place_order")


def test_watchlist_is_capped_at_25_and_validated(app):
    rt, c = app
    for i in range(25):
        assert c.post("/api/mine/watch", json={"action": "add", "symbol": f"AB{i}", "market": "India"}).status_code == 200
    r = c.post("/api/mine/watch", json={"action": "add", "symbol": "ONEMORE"})
    assert r.status_code == 400 and "25" in r.json()["detail"]
    assert c.post("/api/mine/watch", json={"action": "add", "symbol": "AB3", "why": "again"}).status_code == 200            # an update is not a new name
    assert c.post("/api/mine/watch", json={"action": "add", "symbol": "bad name!"}).status_code == 400
    j = c.get("/api/mine/watch").json()
    assert j["count"] == 25 and j["cap"] == 25
    assert c.post("/api/mine/watch", json={"action": "remove", "symbol": "AB3"}).json()["removed"] == "AB3"


def test_the_alarm_scope_includes_his_watchlist_and_holdings(app, monkeypatch):
    rt, c = app
    con = rt.cursor()
    s89.ensure(con)
    from pflab.think import watch
    monkeypatch.setattr("pflab.agents.tradecheck.isin_of", lambda con_, s: {"WLNAME": "INE000W01011", "HELD": "INE000H01011"}.get(s))
    con.execute("INSERT INTO watch_s89 VALUES ('WLNAME','India','why','[]', now())")
    con.execute("INSERT INTO mine_in_s89 VALUES ('HELD','INE000H01011','NSE',10,100,110,0,now())")
    sc = watch.scope(con, NOW.date())
    why = {e["symbol"]: e["why"] for e in sc}
    assert "his watchlist" in why.get("WLNAME", []) and "his real holding (read-only)" in why.get("HELD", [])


def test_pair_is_worked_out_by_code(app, monkeypatch):
    import numpy as np
    import pandas as pd
    rt, c = app
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2023-01-02", periods=500)
    common = np.cumsum(rng.normal(0, 0.01, 500))
    a = pd.Series(100 * np.exp(common + rng.normal(0, 0.004, 500)), index=idx)
    b = pd.Series(50 * np.exp(common + rng.normal(0, 0.004, 500)), index=idx)
    monkeypatch.setattr("pflab.agents.tradecheck.isin_of", lambda con, s: "ISIN_" + s)
    monkeypatch.setattr("pflab.hq.stocks.closes", lambda con, root, isin, asof: a if isin.endswith("AAAA") else b)
    j = c.post("/api/lab/pair", json={"a": "AAAA", "b": "BBBB"}).json()
    assert j["verdict"] in ("tied", "loose", "not tied") and len(j["series_a"]) == len(j["series_b"]) == j["days"] and j["series_a"][0] == 100.0
    assert j["label"] == "worked out by the Lab tools, 0 tokens" and set(j) >= {"gap_z", "p_value", "hedge_ratio", "half_life_days", "correlation"}
    assert c.post("/api/lab/pair", json={"a": "", "b": "x"}).status_code == 400


def test_agents_endpoint_reads_and_writes_settings(app):
    rt, c = app
    j = c.get("/api/agents").json()
    assert [a["key"] for a in j["agents"]] == ["quick", "full", "desk", "case", "alarm", "fixer", "weekly"] and j["switches"]["connectors"] is False
    assert c.post("/api/agents", json={"agent": "quick", "model": "claude-opus-5-5", "thinking": "high"}).json()["applies"] == "from the next run"
    assert c.post("/api/agents", json={"agent": "quick", "model": "gpt-9"}).status_code == 400
    assert c.post("/api/agents", json={"agent": "nobody", "model": "claude-opus-5-5"}).status_code == 400
    q = [a for a in c.get("/api/agents").json()["agents"] if a["key"] == "quick"][0]
    assert q["model"] == "claude-opus-5-5" and q["changed"] is True
    assert s89.agent_override(rt.cursor(), "quick") == ("claude-opus-5-5", "high")
    assert c.post("/api/agents", json={"switch": "connectors", "on": True}).json()["on"] is True
    assert c.get("/api/agents").json()["switches"]["connectors"] is True


# --- chat: actions wait for his Yes; the quick road holds none; the road picker reaches the router ---------------------------------------------------

def test_a_chat_action_posts_a_card_and_changes_nothing_before_yes(app):
    from pflab.entrance import cards
    from pflab.oper import actions
    rt, c = app
    con = rt.cursor()
    msg = actions.propose(con, NOW, "watch_add", {"symbol": "TATASTEEL", "alerts": ["moves 3%+"]})
    assert "Yes/No card" in msg and con.execute("SELECT count(*) FROM watch_s89").fetchone()[0] == 0
    card = con.execute("SELECT msg_id FROM cards_s85 WHERE payload_json LIKE '%chat_action%' OR kind LIKE '%chat_action%' ORDER BY card_id DESC LIMIT 1").fetchone()
    assert card, "a card was posted"
    cards.answer_card(con, card[0], "no", "laptop")
    assert con.execute("SELECT count(*) FROM watch_s89").fetchone()[0] == 0                       # No: nothing
    actions.propose(con, NOW, "us_add", {"ticker": "MSFT", "shares": 3, "avg_price": 421.6})
    mid = con.execute("SELECT msg_id FROM cards_s85 ORDER BY card_id DESC LIMIT 1").fetchone()[0]
    assert con.execute("SELECT count(*) FROM mine_us_s89").fetchone()[0] == 0
    cards.answer_card(con, mid, "yes", "laptop")
    assert con.execute("SELECT ticker, shares FROM mine_us_s89").fetchall() == [("MSFT", 3.0)]     # Yes: it is done
    assert actions.propose(con, NOW, "us_add", {"ticker": "x$", "shares": 3, "avg_price": 1}).startswith("Not proposed")


def test_quick_road_has_no_action_tool_and_full_road_has(monkeypatch):
    from pflab.oper import light, tools as otools
    ctx = SimpleNamespace(source="", con=None, now=NOW)
    assert "propose_action" not in [t[0] for t in light.tools_for(ctx)]
    assert "propose_action" in [t[0] for t in otools.items(ctx)]


def test_the_road_picker_reaches_the_router_as_an_override(app):
    from pflab.entrance import intake
    from pflab.oper import pathrouter
    rt, c = app
    assert pathrouter.choose("how is my book?", road="full")[0] == "full"
    assert pathrouter.choose("look into CCCC", road="quick")[0] == "light"
    assert pathrouter.choose("look into CCCC", road="quick", has_file=True)[0] == "full"          # a file cannot go on the quick road
    assert pathrouter.choose("how is my book?", road=None)[0] == "light"
    with pytest.raises(ValueError):
        intake.submit(rt, "laptop", "hi", road="sideways")


# --- the pages --------------------------------------------------------------------------------------------------------------------------------------

def test_the_new_shell_is_at_root_the_old_one_at_classic_and_the_phone_files_are_served(app):
    rt, c = app
    new, old = c.get("/"), c.get("/classic")
    assert new.status_code == old.status_code == 200 and "/static/s89/core.js" in new.text and "/static/app.js" in old.text and "/static/app.js" not in new.text
    m = c.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.json()["display"] == "standalone" and m.json()["start_url"] == "/"
    sw = c.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"] and sw.headers["service-worker-allowed"] == "/"
    for f in ("core", "home", "money", "manage", "book", "lab", "graph", "chat", "agents", "usage", "settings"):
        assert c.get(f"/static/s89/{f}.js").status_code == 200, f
    assert c.get("/static/s89/s89.css").status_code == 200


def test_no_sample_numbers_ship_in_the_screens():
    root = Path(__file__).resolve().parents[1] / "src" / "pflab" / "app" / "static" / "s89"
    text = "\n".join(p.read_text(encoding="utf-8") for p in root.glob("*.js"))
    for sample in ("9,79,697", "10,42,380", "HDFCBANK", "NVDA", "+11.2%", "94%", "Thu 16:30"):                 # figures and names from the design's sample data
        assert sample not in text, sample
    assert "Math.random" not in text


EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


@pytest.mark.skipif(not os.path.exists(EDGE), reason="Microsoft Edge is not installed here")
def test_every_screen_loads_in_a_browser_on_an_empty_store_without_a_console_error(tmp_path):
    import threading
    import time

    import uvicorn
    from tests import _edge
    pm, data = tmp_path / "pm", tmp_path / "data"
    (data / "indices").mkdir(parents=True)
    os.environ["PFLAB_DATA_DIR"] = str(data)
    rt = runtime.Runtime(pm, data, tmp_path, con=store.connect(tmp_path / "e.duckdb"), clock=lambda: NOW)
    cfg = uvicorn.Config(server.create_app(rt), host="127.0.0.1", port=_edge._free(), log_level="error")
    srv = uvicorn.Server(cfg)
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.1)
    port = srv.servers[0].sockets[0].getsockname()[1]
    try:
        for name in ("home", "money", "manage", "book", "lab", "graph", "chat", "agents", "usage", "settings"):
            steps = [("document.getElementById('screen').innerText.length", 4.5), ("document.querySelectorAll('#screen .card, #screen .empty, #screen .banner').length", 0.1),
                     ("document.getElementById('screen').innerText.indexOf('Could not load') < 0", 0.1)]
            errors, res = _edge.shoot(f"http://127.0.0.1:{port}/?s89=1#/{name}", str(tmp_path / f"{name}.png"), 1600, 1000, 3, steps)
            assert errors == [], (name, errors)
            assert int(res[0]) > 20 and int(res[1]) >= 1 and res[2] in (True, "true"), (name, res)
        con = rt.cursor()                                                                            # now a fixture store: his holdings, a US entry and the watchlist
        s89.ensure(con)
        con.execute("INSERT INTO mine_in_s89 VALUES ('AAAA','INE000A01011','NSE',10,100,110,1.5, now())")
        con.execute("INSERT INTO mine_us_s89 VALUES ('BBBB', 4, 50, DATE '2026-02-11', now())")
        con.execute("INSERT INTO watch_s89 VALUES ('CCCC','India','a reason','[\"news\"]', now())")
        for name, needle in (("money", "AAAA"), ("manage", "CCCC"), ("home", "Needs you")):
            errors, res = _edge.shoot(f"http://127.0.0.1:{port}/?s89=1#/{name}", str(tmp_path / f"fx_{name}.png"), 1600, 1000, 3, [("document.getElementById('screen').innerText", 2.5)])
            assert errors == [] and needle in res[0], (name, errors, res[0][:300])
        assert "BBBB" in _edge.shoot(f"http://127.0.0.1:{port}/?s89=1#/manage", str(tmp_path / "fx2.png"), 1600, 1000, 3, [("document.getElementById('screen').innerText", 2.5)])[1][0]
        errors, res = _edge.shoot(f"http://127.0.0.1:{port}/?s89=1#/home", str(tmp_path / "phone.png"), 390, 844, 3,
                                  [("document.documentElement.scrollWidth <= window.innerWidth + 2", 0.1), ("getComputedStyle(document.getElementById('bar')).display", 0.1)])
        assert errors == [] and res[0] in (True, "true") and res[1] == "flex"                         # at 390 px: no sideways scroll, the bottom bar is there
    finally:
        srv.should_exit = True
        th.join(timeout=5)
