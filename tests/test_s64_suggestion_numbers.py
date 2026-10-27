"""S64 Phase 5 item 5: a suggestion's price numbers come from code; an 'add' gets a price watch whose hit carries a ticket;
idle Kite cash is noticed after a week."""
from datetime import date, datetime, timedelta

import duckdb
import pytest

from pflab.app import research as rs
from pflab.hq import suggestions as sg
from pflab.pm import store
from pflab.service import tasks

NOW = datetime(2026, 10, 27, 10, 0)
ISIN = "INE000A01011"
NUM = {"price_low": 90.0, "price_high": 100.0, "max_buy": 98.0, "wrong_price": 80.0,
       "wrong_if": "it closes below 80, the 10th percentile of its 3-month price range", "stats": {"method": "stats_plain"}}


@pytest.fixture
def con(tmp_path):
    c = duckdb.connect(str(tmp_path / "pm.duckdb"))
    store.migrate(c)
    return c


def rec(con, kind="add", shadow=False, amount=20_000.0):
    return sg.record(con, pass_id=1, model="m", kind=kind, isin=ISIN, symbol="AAA", text="t", reasoning="r", data={},
                     horizon_days=30, now=NOW, shadow=shadow, facts={"guard": "ok"}, root=object(), amount=amount)


def test_an_add_gets_numbers_amount_and_a_watch(con, monkeypatch):
    monkeypatch.setattr(sg, "numbers", lambda *a, **k: NUM)
    sid = rec(con)
    r = con.execute("SELECT price_low, price_high, max_buy, amount, wrong_price, watch_id FROM hq_suggestions").fetchone()
    assert r[:5] == (90.0, 100.0, 98.0, 20_000.0, 80.0) and r[5] is not None
    assert con.execute("SELECT isin, kind, level FROM watches WHERE watch_id=?", [r[5]]).fetchone() == (ISIN, "below", 98.0)
    assert sid == 1


def test_a_shadow_add_or_a_trim_has_no_watch(con, monkeypatch):
    monkeypatch.setattr(sg, "numbers", lambda *a, **k: NUM)
    rec(con, shadow=True)
    rec(con, kind="trim")
    assert con.execute("SELECT count(*) FROM watches").fetchone()[0] == 0
    assert con.execute("SELECT amount FROM hq_suggestions WHERE kind='trim'").fetchone()[0] is None     # an amount is for buys


def test_numbers_failing_leaves_the_words(con, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no prices")
    monkeypatch.setattr(sg, "numbers", boom)
    rec(con)
    assert con.execute("SELECT max_buy, watch_id FROM hq_suggestions").fetchone() == (None, None)


def test_a_watch_hit_carries_the_ticket(con, monkeypatch):
    monkeypatch.setattr(sg, "numbers", lambda *a, **k: NUM)
    rec(con)
    con.execute("INSERT INTO prices VALUES (?, DATE '2026-10-26', 95.0, 'EQ', 'nse_bhavcopy', now())", [ISIN])
    hits = rs.check_watches_con(con, NOW, None)
    assert len(hits) == 1 and "Watch: AAA at 95.00 is below 98.00" in hits[0]
    assert "Suggestion #1: about Rs 20,000, highest buy 98.00. Wrong if it closes below 80" in hits[0]
    assert "BUY AAA 210 LIMIT 95.00" in hits[0] and "nothing is placed" in hits[0]        # 20,000 // 95 = 210
    assert con.execute("SELECT status FROM outbox").fetchone()[0] == "pending"              # a watch is urgent


def snap(con, at, amount):
    con.execute("INSERT INTO kite_snapshots (snap_id, taken_at, account_id, kind, amount) VALUES (1, ?, 'a', 'cash', ?)", [at, amount])


def test_idle_cash_needs_a_week_of_snapshots_all_above_the_floor(con):
    snap(con, NOW - timedelta(days=3), 50_000)
    assert tasks.idle_cash_days(con, NOW) is None                           # snapshots do not reach back a week
    snap(con, NOW - timedelta(days=7, hours=2), 40_000)
    snap(con, NOW, 45_000)
    assert tasks.idle_cash_days(con, NOW) == (40_000, 7)
    snap(con, NOW - timedelta(days=1), 2_000)                               # used in between
    assert tasks.idle_cash_days(con, NOW) is None
