"""S58b the portfolio today: Kite's view between statements (holdings with today's trades, cash, a payout to the bank
shown as moved, never as a loss), the login asked for each trading day and the statements each month.
SYNTHETIC ledger, FAKE Kite."""
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from pflab.agents import tradecheck as tc
from pflab.calc import networth as nw
from pflab.conductor import calendar as cl
from pflab.conductor import sync
from pflab.ledger.events import Event, EventLog, save
from pflab.pm import store, today
from pflab.service import jobs

AAA, BBB = "INE000A01011", "INE000B01011"
NOW = datetime(2026, 10, 23, 15, 0)                     # a Friday


@pytest.fixture
def con(tmp_path):
    return ledger(tmp_path)


def ledger(tmp_path, extra=()):
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha (synthetic)'), "
              "('SBI', 'bank', 'SBI (synthetic)')")
    for isin, sym in ((AAA, "AAA"), (BBB, "BBB")):
        c.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                     VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, ?, ?, 'synthetic', now())""", [isin, sym, sym + " Ltd"])
        c.execute("INSERT INTO prices VALUES (?, DATE '2026-10-22', ?, 'EQ', 'synthetic', now())",
                  [isin, {AAA: 120.0, BBB: 50.0}[isin]])
    save(c, EventLog([Event("deposit", "SBI", date(2026, 9, 1), amount=200_000.0),
                      Event("cash_transfer", "SBI", date(2026, 10, 1), amount=100_000.0, counter_account="ZER"),
                      Event("buy", "ZER", date(2026, 10, 1), isin=AAA, qty=10, price=100.0, ref="T1"), *extra]))
    return c


class FakeKite:
    """Kite's documented shapes: holdings keep the opening quantity all day; today's delivery buys and sells are in
    positions (CNC day quantities); Coin funds in mf_holdings; the balance in margins' live_balance."""
    def __init__(self, cash=30_000.0, funds=()):
        self.cash, self.funds = cash, list(funds)

    def holdings(self):
        return [{"isin": AAA, "tradingsymbol": "AAA", "exchange": "NSE", "quantity": 6, "t1_quantity": 0,
                 "average_price": 100.0, "last_price": 119.0},
                {"isin": BBB, "tradingsymbol": "BBB", "exchange": "NSE", "quantity": 15, "t1_quantity": 5,
                 "average_price": 45.0, "last_price": 50.0}]

    def positions(self):
        return {"net": [{"tradingsymbol": "AAA", "exchange": "NSE", "product": "CNC", "day_buy_quantity": 2,
                         "day_buy_price": 118.0, "day_sell_quantity": 0, "day_sell_price": 0},
                        {"tradingsymbol": "AAA", "exchange": "NSE", "product": "MIS", "day_buy_quantity": 50,
                         "day_buy_price": 118.0, "day_sell_quantity": 50, "day_sell_price": 119.0}]}

    def mf_holdings(self):
        return self.funds

    def margins(self):
        return {"equity": {"available": {"cash": 0, "opening_balance": self.cash, "live_balance": self.cash}}}

    def trades(self):
        return []


def test_without_a_kite_snapshot_the_portfolio_is_the_ledgers_and_says_so(con):
    t = today.build(con, NOW.date())
    assert t["today"]["source"] == "ledger" and t["net_worth"] == nw.build(con, NOW.date())["net_worth"]
    assert t["today"]["documents_to"] == date(2026, 10, 1)
    assert "no Kite login yet" in today.summary(t["today"])[0]


def test_kites_view_replaces_the_broker_account_and_a_payout_moves_to_the_bank(con):
    r = today.record(con, FakeKite(), "ZER", NOW)
    assert r["missing"] == [] and r["rows"] == 4                    # 2 holdings, 1 delivery buy (MIS left out), cash
    t = today.build(con, NOW.date())
    i = t["today"]
    assert i["source"] == "kite" and {d["isin"]: (d["ledger"], d["kite"]) for d in i["diffs"]} == {AAA: (10, 8), BBB: (0, 20)}
    pos = t["positions"].set_index("isin")
    assert pos.loc[AAA, "qty"] == 8 and pos.loc[AAA, "cost"] == pytest.approx(800.0)     # the ledger's average cost kept
    assert pos.loc[BBB, "qty"] == 20 and pos.loc[BBB, "cost"] == pytest.approx(900.0)    # Kite's price for an added one
    # ledger ZER cash 99,000; 2 AAA fewer (+240 at the close), 20 BBB more (-900): 98,340 expected, Kite shows 30,000
    assert i["kite_cash"] == 30_000.0 and i["moved"] == pytest.approx(68_340.0) and i["bank"] == "SBI"
    cash = t["valuation"].cash.set_index("account")["balance"]
    assert cash["ZER"] == 30_000.0 and cash["SBI"] == pytest.approx(168_340.0)
    led = nw.build(con, NOW.date())
    assert t["net_worth"] - led["net_worth"] == pytest.approx(100.0)                     # BBB 1,000 for 900; a transfer is no loss
    assert any("moved to SBI" in x for x in today.summary(i))


def test_statements_newer_than_kites_view_win(con):
    today.record(con, FakeKite(), "ZER", datetime(2026, 9, 30, 15, 0))
    t = today.build(con, NOW.date())
    assert t["today"]["source"] == "ledger" and t["today"]["stale_snapshot"].startswith("2026-09-30")


def test_a_fund_held_in_another_ledger_account_is_not_counted_twice(tmp_path):
    con = ledger(tmp_path, [Event("buy", "SBI", date(2026, 10, 1), isin="INF000C01011", qty=5, price=10.0, ref="M1")])
    today.record(con, FakeKite(funds=[{"tradingsymbol": "INF000C01011", "fund": "C Fund", "quantity": 5,
                                       "average_price": 10.0, "last_price": 11.0}]), "ZER", NOW)
    t = today.build(con, NOW.date())
    assert (t["positions"]["isin"] == "INF000C01011").sum() == 1
    assert any("another ledger account" in m for m in t["today"]["missing"])


def test_each_trade_check_stores_the_snapshot(con):
    rep = tc.check(con, FakeKite(), NOW.date(), now=NOW)
    assert rep.snapshot and rep.snapshot["rows"] == 4
    assert con.execute("SELECT count(DISTINCT snap_id) FROM kite_snapshots").fetchone()[0] == 1


def test_parquet_queries_from_many_threads_at_once(tmp_path):
    import threading

    import pandas as pd

    from pflab import _duck
    pd.DataFrame({"date": pd.date_range("2020-01-01", periods=500).date, "close": range(500)}).to_parquet(tmp_path / "x.parquet")
    errors = []

    def work():
        try:
            for _ in range(30):
                assert _duck.sql(f"SELECT max(close) FROM '{(tmp_path / 'x.parquet').as_posix()}'").fetchone()[0] == 499
        except Exception as e:                        # 2026-10-24: "closed pending query result" on the shared connection
            errors.append(e)
    ts = [threading.Thread(target=work) for _ in range(12)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == []


def _ctx(con, tmp_path, now):
    return jobs.Ctx(con, now, tmp_path, tmp_path, tmp_path)


def test_the_kite_login_is_asked_for_on_a_trading_day(con, tmp_path, monkeypatch):
    from pflab.service import health
    monkeypatch.setattr(health, "check", lambda ctx: [SimpleNamespace(name="job:tradecheck", status="WARN",
                                                                      detail="disabled: no Kite login today")])
    cal = cl.load()
    f = {x.name: x for x in sync.service_findings(_ctx(con, tmp_path, datetime(2026, 10, 23, 9, 0)), cal)}
    assert f["kite login"].status == "ask" and f["kite login"].ask_key == "conductor:kite-login:2026-10-23"
    f = {x.name: x for x in sync.service_findings(_ctx(con, tmp_path, datetime(2026, 10, 24, 9, 0)), cal)}   # Saturday
    assert "kite login" not in f and f["job:tradecheck"].status == "off"


def test_last_months_statements_are_asked_for_from_the_third(con, tmp_path):
    con.execute("UPDATE events SET ingested_at = TIMESTAMP '2026-10-20 10:00'")
    assert sync.ledger_findings(_ctx(con, tmp_path, datetime(2026, 11, 2, 10, 0)))[0].status == "ok"
    f = sync.ledger_findings(_ctx(con, tmp_path, datetime(2026, 11, 3, 10, 0)))[0]
    assert f.status == "ask" and f.ask_key == "conductor:statements:2026-11" and "October 2026" in f.ask_text
    con.execute("UPDATE events SET ingested_at = TIMESTAMP '2026-11-04 10:00'")              # rebuilt: the ask closes
    assert sync.ledger_findings(_ctx(con, tmp_path, datetime(2026, 11, 5, 10, 0)))[0].status == "ok"
