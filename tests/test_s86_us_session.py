"""S86 H4 the US session loop (`core/us_session.py`): the phases from the market calendar, quotes with their delay, a stop that fills at the NEXT quote, a stale quote that never fills, pre-market
orders that wait for the open, one name never bought and sold on one US day, a laptop opened late starts at the open hour it finds. Synthetic data; a fake quote feed; nothing reaches the net."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest

from pflab.core import exits, us_session as uss
from pflab.pm import store
from pflab.us import book

ISIN, SYM = "ZZ0000999999", "NVX"
FXR = {"rate": 90.0, "source": "FBIL", "rate_day": date(2026, 11, 9), "label": "FBIL reference rate"}
OPEN = datetime(2026, 11, 10, 20, 0)                       # Tuesday 10 Nov 2026: New York is on winter time, the regular session is 20:00 IST to 02:30 IST


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("INSERT INTO fx_rates VALUES (?, 'USDINR_FBIL', 90.0, 'test')", [date(2026, 11, 9)])
    c.execute("INSERT INTO paper_cash VALUES (?,?,?,?,?,?)", [store.next_id(c, "paper_cash", "entry_id"), date(2026, 10, 1), 1_000_000.0, "seed", "test cash", OPEN])
    c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'FOREIGN', TRUE, ?, 'Nvx Corp', 'synthetic', now())", [ISIN, SYM])
    book.open_account(c, OPEN, date(2026, 11, 9), 200_000.0, FXR, 0.10)
    o = book.place(c, OPEN - timedelta(days=1), date(2026, 11, 9), ISIN, SYM, "buy", amount_usd=1_000.0, reason="test seed")
    book.fill_one(c, OPEN - timedelta(days=1), date(2026, 11, 9), [x for x in book.open_orders(c) if x["order_id"] == o][0], 100.0, 0.0)
    monkeypatch.setattr(uss, "on", lambda: True)
    monkeypatch.setattr(uss, "symbols_for", lambda con_, now, root: ["SPY", SYM])
    monkeypatch.setattr("pflab.think.watch.run", lambda *a, **k: {"signals": [], "cases_opened": []})
    return c


def feed(prices, end):
    """A fake chart feed: every symbol's last 1-minute bar ENDS at `end` (IST) with the price in `prices`."""
    def get(url):
        sym = url.split("chart/")[1].split("?")[0]
        start = (end - timedelta(minutes=1) - timedelta(hours=5, minutes=30)).replace(tzinfo=timezone.utc)
        return json.dumps({"chart": {"result": [{"timestamp": [int(start.timestamp()) - 60, int(start.timestamp())], "indicators": {"quote": [{"close": [prices[sym] * 0.999, prices[sym]]}]}}]}})
    return get


def test_phases_come_from_the_calendar_winter_and_summer():
    assert uss.phase(datetime(2026, 11, 10, 20, 30))[0] == "regular" and uss.phase(datetime(2026, 11, 11, 2, 0))[0] == "regular"
    assert uss.phase(datetime(2026, 11, 10, 16, 0))[0] == "pre" and uss.phase(datetime(2026, 11, 11, 3, 0))[0] == "post" and uss.phase(datetime(2026, 11, 11, 7, 0))[0] == "closed"
    assert uss.phase(datetime(2026, 7, 14, 19, 30))[0] == "regular" and uss.phase(datetime(2026, 7, 14, 18, 59))[0] == "pre"          # summer: the open is 19:00 IST
    assert uss.phase(datetime(2026, 11, 14, 21, 0))[0] == "closed"                                                                  # a Saturday


def test_quotes_are_stored_with_their_delay(con):
    now = datetime(2026, 11, 10, 21, 0)
    r = uss.tick(con, now, get=feed({"SPY": 450.0, SYM: 100.0}, now - timedelta(minutes=3)))
    assert r["phase"] == "regular" and r["quotes"] == 2 and r["median_delay_min"] == pytest.approx(3.0, abs=0.1)
    assert con.execute("SELECT count(*), max(delay_min) FROM us_quotes_s86").fetchone()[0] == 2


def _stop(monkeypatch, level=95.0):
    monkeypatch.setattr(exits, "_plans", lambda con, market=None, *a, **k: [{"isin": ISIN, "stop": level, "plan_id": 1}])


def test_a_stop_hit_at_2210_fills_at_the_next_quote_not_the_one_that_triggered_it(con, monkeypatch):
    _stop(monkeypatch)
    t1 = datetime(2026, 11, 10, 22, 10)
    r1 = uss.tick(con, t1, get=feed({"SPY": 450.0, SYM: 94.0}, t1))                    # the quote that triggers: 94 under the stop 95
    assert len(r1["stops"]) == 1 and r1["fills"] == []                               # the order is placed, NOT filled on the quote it was decided on
    assert con.execute("SELECT status FROM us_orders_s81 WHERE side='sell'").fetchone()[0] == "open"
    t2 = datetime(2026, 11, 10, 22, 15)
    r2 = uss.tick(con, t2, get=feed({"SPY": 450.0, SYM: 93.0}, t2 - timedelta(minutes=1)))
    assert len(r2["fills"]) == 1 and r2["fills"][0]["price"] == pytest.approx(93.0 * (1 - 0.0005), rel=1e-6)
    f = con.execute("SELECT decision_ts, quote_ts, delay_min, est_bps FROM us_fills_s86").fetchone()
    assert f[1] > f[0] and f[2] == pytest.approx(1.0, abs=0.1) and f[3] == 5.0
    assert book.positions(con).get(ISIN, 0.0) == pytest.approx(0.0, abs=1e-6)


def test_a_stale_quote_never_fills(con, monkeypatch):
    _stop(monkeypatch)
    t1 = datetime(2026, 11, 10, 22, 10)
    uss.tick(con, t1, get=feed({"SPY": 450.0, SYM: 94.0}, t1))
    t2 = datetime(2026, 11, 10, 22, 40)
    r = uss.tick(con, t2, get=feed({"SPY": 450.0, SYM: 93.0}, t2 - timedelta(minutes=25)))      # the newest quote is 25 minutes old
    assert r["fills"] == [] and con.execute("SELECT status FROM us_orders_s81 WHERE side='sell'").fetchone()[0] == "open"


def test_pre_market_news_makes_an_order_for_the_open_not_a_fill(con):
    t0 = datetime(2026, 11, 10, 17, 0)                                                   # 06:30 in New York: pre-market
    oid = book.place(con, t0, date(2026, 11, 9), ISIN, SYM, "sell", qty=5.0, reason="a case sold it on pre-market news")
    r = uss.tick(con, t0 + timedelta(minutes=1), get=feed({"SPY": 450.0, SYM: 90.0}, t0))
    assert r["phase"] == "pre" and r["fills"] == [] and con.execute("SELECT status FROM us_orders_s81 WHERE order_id=?", [oid]).fetchone()[0] == "open"
    t1 = datetime(2026, 11, 10, 20, 5)                                                   # the open: the first quote strictly after the decision fills it
    r2 = uss.tick(con, t1, get=feed({"SPY": 450.0, SYM: 91.0}, t1 - timedelta(minutes=1)))
    assert len(r2["fills"]) == 1 and r2["fills"][0]["order_id"] == oid


def test_a_name_is_never_bought_and_sold_on_one_us_day(con):
    t0 = datetime(2026, 11, 10, 20, 30)
    book.place(con, t0 - timedelta(minutes=10), date(2026, 11, 10), ISIN, SYM, "sell", qty=2.0, reason="first")
    uss.tick(con, t0, get=feed({"SPY": 450.0, SYM: 101.0}, t0 - timedelta(minutes=1)))
    assert con.execute("SELECT count(*) FROM us_trades_s81 WHERE day=? AND side='sell'", [date(2026, 11, 10)]).fetchone()[0] == 1
    b = book.place(con, t0 + timedelta(minutes=1), date(2026, 11, 10), ISIN, SYM, "buy", amount_usd=500.0, reason="a buy the same day")
    t1 = t0 + timedelta(minutes=5)
    r = uss.tick(con, t1, get=feed({"SPY": 450.0, SYM: 100.0}, t1 - timedelta(minutes=1)))
    assert r["fills"] == [] and con.execute("SELECT status FROM us_orders_s81 WHERE order_id=?", [b]).fetchone()[0] == "open"


def test_a_closed_market_does_nothing_and_a_laptop_opened_at_2300_starts_there(con):
    assert uss.tick(con, datetime(2026, 11, 11, 7, 0), get=feed({}, datetime(2026, 11, 11, 7, 0)))["skipped"]
    r = uss.tick(con, datetime(2026, 11, 10, 23, 0), get=feed({"SPY": 450.0, SYM: 100.0}, datetime(2026, 11, 10, 22, 58)))
    assert r["phase"] == "regular" and r["quotes"] == 2


def test_off_hours_are_looked_at_every_fifteen_minutes_only(con):
    t = datetime(2026, 11, 10, 17, 0)
    uss.tick(con, t, get=feed({"SPY": 450.0, SYM: 100.0}, t))
    assert uss.tick(con, t + timedelta(minutes=5), get=feed({"SPY": 450.0, SYM: 100.0}, t + timedelta(minutes=5)))["skipped"]
    assert uss.tick(con, t + timedelta(minutes=16), get=feed({"SPY": 450.0, SYM: 100.0}, t + timedelta(minutes=16)))["quotes"] == 2
