"""S54c: buy zones (the touch chance against the reflection principle, the fair price against the implied-growth model,
the verdicts), technicals, price watches, "check my idea" and the endpoints."""
import math
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from scipy.stats import norm

from pflab.app import research as rs
from pflab.app import runtime, server
from pflab.fundamentals import pit
from pflab.plan import buyzone as bz
from pflab.pm import store
from pflab.quant import technicals as tc

NOW = datetime(2026, 10, 22, 16, 0)


def test_touch_chance_matches_the_reflection_principle():
    rng = np.random.default_rng(1)
    sd, h = 0.02, 126
    r = rng.normal(0, sd, 5000)
    t = bz.touch_chance(r, [90.0], 100.0, paths=20_000, horizon=h, block=1)
    exact = 2 * norm.cdf(math.log(0.9) / (sd * math.sqrt(h)))      # continuous monitoring: a slight upper bound
    assert exact - 0.05 < t["p"][0] <= exact + 0.01
    assert t["se"][0] == pytest.approx(math.sqrt(t["p"][0] * (1 - t["p"][0]) / 20_000))


def test_the_fair_price_is_the_price_whose_implied_growth_is_the_given_growth():
    fair = bz.fair_price(50.0, 0.15)
    assert pit.implied_growth(fair, 50.0, date(2026, 10, 22)).value == pytest.approx(15.0, abs=1e-2)   # percent
    z = bz.zone(series(), date(2026, 10, 22), eps_ttm=1.0, growth=0.05, paths=1_000)
    assert 0 < z["implied_growth"] < 1                                    # a fraction in the zone, like `growth`
    assert bz.fair_price(-5.0, 0.15) is None and bz.fair_price(50.0, None) is None


def series(n=400, end=100.0, seed=0):
    rng = np.random.default_rng(seed)
    x = np.exp(np.cumsum(rng.normal(0, 0.015, n)))
    return pd.Series(x / x[-1] * end, index=pd.bdate_range(end="2026-10-22", periods=n))


def test_zone_verdicts():
    s = series()
    z = bz.zone(s, date(2026, 10, 22), paths=5_000)
    assert z["bottom"] <= z["top"] <= z["p40"] and z["verdict"] in ("IN ZONE", "ABOVE ZONE")
    assert z["verdict"] == ("IN ZONE" if z["price"] <= z["top"] else "ABOVE ZONE")
    low = s.copy()
    low.iloc[-1] = float(s.iloc[-250:].min()) * 0.98                  # a new low: inside the zone
    assert bz.zone(low, date(2026, 10, 22), paths=5_000)["verdict"] == "IN ZONE"
    assert bz.zone(s, date(2026, 10, 22), guard="fail", paths=5_000)["verdict"] == "NO"
    short = bz.zone(s.iloc[-100:], date(2026, 10, 22))
    assert short["verdict"] == "NO DATA" and "250 needed" in short["headline"]
    rich = bz.zone(low, date(2026, 10, 22), eps_ttm=1.0, growth=0.05, paths=5_000)    # in its range, priced for growth
    assert rich["rich"] and rich["verdict"] == "RICH" and "assumes" in rich["headline"]
    assert rich["top"] == pytest.approx(rich["p40"]) and rich["fair"] < rich["price"]   # valuation never moves the zone
    unknown = bz.zone(low, date(2026, 10, 22), eps_ttm=1.0, growth=None, paths=1_000)
    assert unknown["verdict"] == "RICH" and "no growth record" in unknown["headline"]


def test_technicals_on_hand_checkable_series():
    up = pd.Series(np.arange(1.0, 40.0))
    assert tc.rsi(up).iloc[-1] == pytest.approx(100.0)
    n = 60
    c = pd.Series(np.full(n, 100.0))
    assert tc.atr(c + 1, c - 1, c).iloc[-1] == pytest.approx(2.0)
    df = pd.DataFrame({"date": pd.bdate_range(end="2026-10-22", periods=260).date, "open": 1.0, "high": 2.0, "low": 0.5,
                       "close": np.linspace(10, 20, 260), "volume": 100.0})
    s = tc.summary(df)
    assert s["ma50"] == pytest.approx(np.linspace(10, 20, 260)[-50:].mean()) and s["volume_ratio"] == pytest.approx(1.0)
    assert s["high52"] == pytest.approx(20.0) and len(s["chart"]["close"]) == 250


def test_technicals_read_the_bhavcopy(tmp_path):
    d = pd.bdate_range(end="2026-10-22", periods=300).date
    df = pd.DataFrame({"date": d, "symbol": "AAA", "series": "EQ", "isin": "INE000A01011", "open": 10.0, "high": 11.0,
                       "low": 9.0, "close": np.linspace(10, 30, 300), "volume": 1000})
    for y, g in df.groupby([x.year for x in df["date"]]):
        (tmp_path / "bhavcopy" / str(y)).mkdir(parents=True)
        g.to_parquet(tmp_path / "bhavcopy" / str(y) / "part.parquet", index=False)
    s = tc.for_isin(tmp_path, "INE000A01011", date(2026, 10, 22))
    assert s["close"] == pytest.approx(30.0) and s["sessions"] == len([x for x in d if x >= date(2025, 8, 28)])
    assert tc.for_isin(tmp_path, "INE999Z01011", date(2026, 10, 22)) is None


def test_amounts_in_words():
    assert rs.parse_amount("buy for ₹50,000?") == 50_000
    assert rs.parse_amount("put 2 lakh in it") == 200_000
    assert rs.parse_amount("Rs 1.5 cr") == 15_000_000
    assert rs.parse_amount("just a question") is None


@pytest.fixture
def rt(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def test_a_watch_hits_once_a_day_and_is_held_as_a_message(rt):
    con = rt.cursor()
    con.execute("INSERT INTO prices VALUES ('INE000A01011', DATE '2026-10-22', 95.0, 'EQ', 'nse_bhavcopy', now())")
    rs.add_watch(con, "INE000A01011", "AAA", "below", 100.0, "zone top", NOW)
    rs.add_watch(con, "INE000A01011", "AAA", "above", 120.0, "", NOW)
    assert rs.check_watches(rt) == ["Watch: AAA at 95.00 is below 100.00 (close 2026-10-22)"]
    assert rs.check_watches(rt) == []                                   # once a day
    assert con.execute("SELECT kind, status FROM outbox").fetchall() == [("watch", "pending")]
    with pytest.raises(ValueError):
        rs.add_watch(con, "INE000A01011", "AAA", "sideways", 1.0, "", NOW)


def test_check_my_idea_uses_the_zone_and_the_cap(rt, monkeypatch):
    rs.write_cache(rt, "watch", {"at": NOW.isoformat(), "paths": 100_000, "rows": [
        {"isin": "INE000A01011", "symbol": "AAA", "on_list": True, "reasons": [],
         "zone": {"verdict": "IN ZONE", "headline": "in the zone 90-100", "price": 95.0, "bottom": 90.0, "top": 100.0,
                  "horizon": 126, "touch_top": {"text": "60.0% ± 0.15 pp"}}}]})
    from pflab.calc import networth as nw
    monkeypatch.setattr(nw, "build", lambda con, asof: {"positions": pd.DataFrame(columns=["isin", "value"]), "investable": 1_000_000.0})
    r = rs.idea(rt, "buy AAA for ₹50,000?")
    assert r["verdict"] == "yes" and "4.8% of investable" in r["answer"] and "ESTIMATE" in r["answer"]
    assert rs.idea(rt, "buy AAA for ₹5 lakh")["verdict"] == "no"            # past the single-stock cap
    assert rs.idea(rt, "what about ZZZ?")["verdict"] is None


def test_watch_and_research_endpoints(rt):
    c = TestClient(server.create_app(rt))
    assert c.get("/api/watch").json()["computing"] is True
    wid = c.post("/api/watches", json={"isin": "INE000A01011", "symbol": "AAA", "kind": "below", "level": 90}).json()["id"]
    assert c.get("/api/watch").json()["watches"][0]["id"] == wid
    assert c.post("/api/watches", json={"isin": "X", "kind": "below", "level": -1}).status_code == 400
    c.delete(f"/api/watches/{wid}")
    assert c.get("/api/watch").json()["watches"] == []
    d = c.get("/api/research").json()
    assert d["plans"] == [] and d["hold_off"] == [] and d["technicals"] is None
    assert c.post("/api/plan", json={"amount": 0}).status_code == 400
