"""S54 dashboard: the server answers every screen, notes and settings persist, held Telegram alerts stay held, and the
small-numbers rule (PLAN A9) labels what it should."""
from datetime import date, datetime

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from pflab.app import runtime, server, views
from pflab.app import settings as st
from pflab.calc import smalln
from pflab.pm import store

NOW = datetime(2026, 10, 22, 11, 30)


@pytest.fixture
def app(tmp_path, monkeypatch):
    pm, data = tmp_path / "pm", tmp_path / "data"
    (data / "indices").mkdir(parents=True)
    pd.DataFrame({"date": [date(2026, 10, 15), date(2026, 10, 16)], "close": [100.0, 102.0]}).to_parquet(
        data / "indices" / "NIFTY50_PRICE.parquet")
    con = store.connect(tmp_path / "l.duckdb")
    rt = runtime.Runtime(pm, data, tmp_path, con=con, clock=lambda: NOW)
    monkeypatch.setattr(views, "market", lambda asof: {"state": "calm", "chance": 0.3, "drawdown": -0.05, "dip_active": False})
    return rt, TestClient(server.create_app(rt))


def test_every_screen_answers_and_says_what_is_missing(app):
    rt, c = app
    assert c.get("/").status_code == 200 and "Portfolio Lab" in c.get("/").text
    d = c.get("/api/command").json()
    assert d["tickers"][0] == {"name": "NIFTY 50", "value": 102.0, "date": "2026-10-16", "change": pytest.approx(0.02)}
    assert d["holdings"]["rows"] == [] and d["montecarlo"]["tail"]["text"] == "not run yet"
    assert "rows" in d["mix"] and d["kite"]["logged_in"] in (True, False)
    p = c.get("/api/portfolio").json()
    assert p["lots"] == [] and "holdings" in p
    assert any(r["job"] == "conductor" for r in c.get("/api/schedule").json()["jobs"])


def test_notes_and_settings_persist(app):
    rt, c = app
    nid = c.post("/api/notes", json={"text": "Research a company before its results"}).json()["id"]
    c.post(f"/api/notes/{nid}/toggle")
    assert c.get("/api/command").json()["notes"] == [{"id": nid, "text": "Research a company before its results", "done": True,
                                                       "at": "2026-10-22 11:30"}]
    c.delete(f"/api/notes/{nid}")
    assert c.get("/api/command").json()["notes"] == []
    assert c.post("/api/notes", json={"text": "  "}).status_code == 400
    s = c.post("/api/settings", json={"privacy": True, "theme": "light", "port": "not an int", "unknown": 1}).json()
    assert s["privacy"] is True and s["theme"] == "light" and s["port"] == 8765 and "unknown" not in s
    assert st.load(rt.pm_dir)["privacy"] is True


def test_held_alerts_stay_held_until_telegram_is_switched_on(app, monkeypatch):
    rt, _ = app
    from pflab.service import jobs
    seen = []
    monkeypatch.setattr(jobs, "is_due", lambda ctx, job: (True, "test"))
    monkeypatch.setattr(jobs, "tick", lambda ctx, only: seen.append(list(only)) or [])
    rt.scheduler_once()
    assert seen and "outbox" not in seen[-1] and "conductor" in seen[-1]
    rt.set_settings({"telegram_send": True})
    rt.scheduler_once()
    assert "outbox" in seen[-1]


def test_closing_the_last_window_is_noticed(app):
    rt, _ = app
    assert rt.idle_for() == 0.0                                  # no window has opened yet: never stop for that
    rt.client_open()
    assert rt.idle_for() == 0.0
    rt.client_closed()
    rt.clock = lambda: datetime(2026, 10, 22, 11, 31)
    assert rt.idle_for() == 60.0


def test_the_small_numbers_rule():
    assert smalln.rate(3, 7) == {"text": "3 of 7", "n": 7, "actionable": False}
    assert smalln.rate(12, 40)["text"] == "30%" and smalln.rate(12, 40)["actionable"]
    assert smalln.annualised(0.142, 120)["text"] == "needs 250 sessions (120)"
    t = smalln.tail(0.031, 10_000)
    assert t["actionable"] and t["text"] == "3.1% ± 0.17 pp"
    assert smalln.tail(0.031, 100)["text"] == "needs more paths" and not smalln.events(4)["actionable"]
    assert smalln.tail(0.0, 10_000)["text"] == "no path in 10,000 (under 0.03%)"     # never "0.0% ± 0.00"
