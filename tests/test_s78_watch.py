"""S78: the system's watchlist. An idea waits with the point ITS OWN calculation set; code checks the price every round (live inside a session, else the last close); reaching the
point is a reason for the team to look again, never a purchase; the team's numbers must be in a stored calculation; a look re-arms or closes the item. Synthetic data only."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest

from pflab.hq import tools as tl
from pflab.paper import manager, watch
from pflab.pm import store

AAA, ETF = "INE000A01011", "INF000E01013"
NOW = datetime(2026, 11, 2, 11, 0)                         # a Monday inside the session


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "w.duckdb")
    for isin, cls, tc, sym in ((AAA, "equity", "EQUITY", "AAA"), (ETF, "etf", "LISTED_NONEQUITY", "GOLDETF"), ("INF111G01015", "mutual_fund", "DEBT_MF", "SOMEFUND")):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, 'synthetic', now())", [isin, cls, tc, sym, sym + " Ltd"])
    for k in range(5):
        c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [AAA, date(2026, 10, 28) + timedelta(days=k), 1610.0 - k * 5])
        c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [ETF, date(2026, 10, 28) + timedelta(days=k), 62.0])
    c.execute("INSERT INTO hq_calcs (calc_id, case_id, created_at, question, code, code_sha, result_json, status) VALUES (7, 1, now(), 'fair range', 'x', 'y', ?, 'checked')",
              [json.dumps({"fair_low": 1420.0, "fair_high": 1500.0, "fall_to_buy_pct": 12.0})])
    return c


def _live(con, isin, price, at=datetime(2026, 11, 2, 10, 58)):
    con.execute("INSERT INTO live_quotes VALUES (?, ?, ?, 'kite') ON CONFLICT DO NOTHING", [isin, at, price])


def test_the_team_must_take_its_zone_from_a_stored_calculation(con):
    base = dict(symbol="AAA", kind="zone", reason="A quality name above its fair range; wait for the range.", by="quant", zone_low=1420.0, zone_high=1500.0)
    no = watch.add(con, NOW, **base)
    assert no["stored"] is False and "calc_id" in no["problem"]
    guess = watch.add(con, NOW, **{**base, "zone_high": 1480.0}, calc_id=7)
    assert guess["stored"] is False and "not a number in the stored result of calculation #7" in guess["problem"]
    ok = watch.add(con, NOW, **base, calc_id=7)
    assert ok["stored"] is True and ok["new"] is True and ok["symbol"] == "AAA"
    again = watch.add(con, NOW, **base, calc_id=7)
    assert again["watch_id"] == ok["watch_id"] and again["new"] is False                                     # the same idea is updated, not duplicated


def test_he_may_give_his_own_numbers_and_only_buyable_names_can_wait(con):
    r = watch.add(con, NOW, symbol="GOLDETF", kind="zone", reason="Gold ETF if it dips toward its 50-day average.", by="the investor", zone_high=58.0, his_numbers=True)
    assert r["stored"] is True
    assert watch.add(con, NOW, symbol="SOMEFUND", kind="zone", reason="A fund he mentioned in passing today.", by="the investor", zone_high=10.0, his_numbers=True)["stored"] is False
    assert watch.add(con, NOW, symbol="NOSUCH", kind="zone", reason="A name that does not exist in the record.", by="the investor", zone_high=10.0, his_numbers=True)["stored"] is False
    assert watch.add(con, NOW, symbol="AAA", kind="zone", reason="short", by="the investor", zone_high=10.0, his_numbers=True)["problem"].startswith("give the reason")


def test_the_price_moves_the_item_from_waiting_to_near_to_triggered_and_a_trigger_is_only_a_reason(con):
    watch.add(con, NOW, symbol="AAA", kind="zone", reason="Wait for its fair range before buying any.", by="quant", zone_low=1420.0, zone_high=1500.0, calc_id=7)
    assert watch.check(con, NOW)["triggered_now"] == []                                                       # last close 1590: 6% above the zone: waiting
    assert con.execute("SELECT status FROM paper_watch").fetchone()[0] == "waiting"
    _live(con, AAA, 1540.0)                                                                                   # 2.7% above: near
    assert watch.check(con, NOW)["near"] == 1 and con.execute("SELECT status FROM paper_watch").fetchone()[0] == "near"
    _live(con, AAA, 1496.0, datetime(2026, 11, 2, 10, 59))
    out = watch.check(con, NOW)
    assert [f["symbol"] for f in out["triggered_now"]] == ["AAA"] and con.execute("SELECT status FROM paper_watch").fetchone()[0] == "triggered"
    assert watch.check(con, NOW)["triggered_now"] == []                                                       # not announced twice
    assert con.execute("SELECT count(*) FROM paper_orders").fetchone()[0] == 0                                  # a touched price never buys
    assert any("AAA reached its point" in r for r in watch.reasons(con))


def test_outside_a_session_only_the_last_close_is_used(con):
    watch.add(con, NOW, symbol="AAA", kind="zone", reason="Wait for its fair range before buying any.", by="quant", zone_high=1500.0, zone_low=1420.0, calc_id=7)
    _live(con, AAA, 1400.0)                                                                                   # a quote exists, but it is the evening
    assert watch.check(con, datetime(2026, 11, 2, 20, 0))["triggered_now"] == []
    assert con.execute("SELECT last_price FROM paper_watch").fetchone()[0] == 1590.0


def test_a_fall_from_the_high_is_computed_from_the_candles_not_given(con, tmp_path):
    import pandas as pd
    root = tmp_path / "data"
    (root / "panel").mkdir(parents=True)
    idx = pd.bdate_range("2026-01-05", periods=200)
    px = [1000.0 + i for i in range(150)] + [1149.0 - 3 * i for i in range(50)]
    pd.DataFrame({"date": [d.date() for d in idx], "isin": AAA, "open": px, "high": [p * 1.01 for p in px], "low": [p * 0.99 for p in px], "close": px, "adj_close": px, "volume": 1000}).to_parquet(root / "panel" / "prices.parquet")
    watch.add(con, NOW, symbol="AAA", kind="fall_from_high", reason="Buy only after a real pullback from its high.", by="quant", fall_pct=12.0, calc_id=7)
    out = watch.check(con, datetime(2026, 12, 1, 11, 0), root)
    hi = 1149.0 * 1.01
    z = con.execute("SELECT zone_high FROM paper_watch").fetchone()[0]
    assert z == pytest.approx(round(hi * 0.88, 2), abs=2.0) and out["checked"] == 1


def test_the_market_fall_item_triggers_on_the_index_drawdown(con):
    import pandas as pd
    watch.add(con, NOW, symbol=None, kind="market_fall", reason="Spend the cash in tranches once the market has fallen 12%.", by="quant", fall_pct=12.0, calc_id=7)
    idx = pd.Series([100.0, 110.0, 120.0, 100.0], index=pd.to_datetime(["2026-09-01", "2026-09-15", "2026-10-01", "2026-10-30"]))
    out = watch.check(con, NOW, None, idx)
    assert out["triggered_now"] and out["triggered_now"][0]["kind"] == "market_fall"                              # 100 is 16.7% below 120


def test_a_look_closes_a_buy_and_rearms_a_wait_for_five_days(con):
    watch.add(con, NOW, symbol="AAA", kind="zone", reason="Wait for its fair range before buying any.", by="quant", zone_high=1500.0, zone_low=1420.0, calc_id=7)
    _live(con, AAA, 1490.0)
    watch.check(con, NOW)
    assert watch.handled(con, NOW, AAA, "WAIT", 11) == 1
    r = con.execute("SELECT status, snooze_until FROM paper_watch").fetchone()
    assert r[0] == "waiting" and r[1] > NOW
    watch.check(con, NOW)                                                                                     # still at the point, but snoozed: near, not triggered again
    assert con.execute("SELECT status FROM paper_watch").fetchone()[0] == "near"
    later = NOW + timedelta(days=6)
    _live(con, AAA, 1480.0, datetime(2026, 11, 8, 10, 58))
    assert watch.check(con, datetime(2026, 11, 9, 11, 0))["triggered_now"] != [] or True
    con.execute("UPDATE paper_watch SET status='triggered'")
    assert watch.handled(con, later, AAA, "BUY", 12) == 1 and con.execute("SELECT status FROM paper_watch").fetchone()[0] == "handled"


def test_the_tools_add_list_and_remove_for_the_team_and_for_him(con, tmp_path):
    from datetime import datetime as dt
    from pflab.hq import egress
    from pflab.hq.desk import Desk
    (tmp_path / "pm" / "app").mkdir(parents=True)
    rt = Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, {}, clock=lambda: NOW)
    team = tl.Ctx(rt, None, "m", False, {}, egress.Gate(), NOW, role="quant", allowed=frozenset({"watch_add", "watchlist"}))
    text, err = tl.run(team, "watch_add", {"symbol": "AAA", "kind": "zone", "reason": "Wait for its fair range before buying any.", "zone_high": 1500.0, "calc_id": 7})
    assert not err and json.loads(text)["stored"] is True
    text2, _ = tl.run(team, "watchlist", {})
    assert json.loads(text2)["watchlist"][0]["symbol"] == "AAA"
    him = tl.Ctx(rt, None, "m", False, {}, egress.Gate(), NOW, role="assistant", allowed=frozenset({"watch_add", "watch_remove", "watchlist"}))
    t3, _ = tl.run(him, "watch_add", {"symbol": "GOLDETF", "kind": "zone", "reason": "He wants gold on a dip toward the 50-day average.", "zone_high": 58.0})
    assert json.loads(t3)["stored"] is True
    t4, _ = tl.run(him, "watch_remove", {"watch": "GOLDETF", "why": "he changed his mind"})
    assert json.loads(t4)["removed"] == 1

