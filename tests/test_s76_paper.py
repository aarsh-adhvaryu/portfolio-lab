"""S76: the paper portfolio the system runs by itself. Synthetic record: the start copies his lots without FDs or the US sleeve, decisions are sized by code and
held to the rails, only what the review approves is executed at the close, tax by FIFO lots, money in and out on the same days, claims scored, the gate to his
real money, and the loop that opens the team's work by itself."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab.agents import analyst as an
from pflab.paper import book, manager, rails
from pflab.pm import store
from tests.test_s68_autonomy import CFG, rt  # noqa: F401  (the fixture)

AAA, BBB, ETF, USX = "INE000A01011", "INE000B01012", "INF000E01013", "ZZ0000320193"
DAYS = [date(2026, 10, 26) + timedelta(days=k) for k in range(0, 80) if (date(2026, 10, 26) + timedelta(days=k)).weekday() < 5]


@pytest.fixture(autouse=True)
def _v1_paper_team(monkeypatch):
    """These tests are about the v1 mission path; S80 switches it off by default (`configs/core.toml`), so they run with the close loop off."""
    from pflab import core
    real = core.settings
    monkeypatch.setattr(core, "settings", lambda: {**real(), "core": {"on": False, "retire_missions": False}})


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "p.duckdb")
    for isin, cls, tc, sym, sec in ((AAA, "equity", "EQUITY", "AAA", "IT"), (BBB, "equity", "EQUITY", "BBB", "IT"), (ETF, "etf", "LISTED_NONEQUITY", "GOLDETF", None),
                                    (USX, "equity", "FOREIGN", "USX", None)):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, ?, 'synthetic', now())",
                  [isin, cls, tc, sym, sym + " Ltd", sec])
    c.execute("INSERT INTO accounts (account_id, kind) VALUES ('Z', 'demat')")
    c.execute("INSERT INTO accounts (account_id, kind, currency) VALUES ('US', 'demat', 'USD')")
    c.execute("INSERT INTO events (event_id, kind, account_id, trade_date, amount, ingested_at) VALUES (100, 'deposit', 'Z', ?, 100000, now())", [date(2024, 1, 1)])
    c.execute("INSERT INTO events (event_id, kind, account_id, trade_date, amount, ingested_at) VALUES (101, 'deposit', 'US', ?, 1000, now())", [date(2024, 1, 1)])
    ev = [(1, "buy", "Z", date(2024, 1, 10), AAA, 50, 80.0),(2, "buy", "Z", date(2026, 6, 1), AAA, 10, 95.0), (3, "buy", "Z", date(2025, 3, 3), BBB, 100, 40.0),
          (4, "buy", "US", date(2025, 3, 3), USX, 5, 100.0)]
    for eid, kind, acc, d, isin, q, px in ev:
        c.execute("INSERT INTO events (event_id, kind, account_id, trade_date, isin, qty, price, amount, ingested_at) VALUES (?,?,?,?,?,?,?,?, now())", [eid, kind, acc, d, isin, q, px, q * px])
    c.execute("INSERT INTO cash_ledger VALUES ('Z', ?, 100000, 'cash_transfer_in', 'r', 10)", [date(2024, 1, 1)])
    c.execute("INSERT INTO cash_ledger VALUES ('Z', ?, -8950, 'buy', 'r', 11)", [date(2024, 1, 10)])
    for i, d in enumerate(DAYS):
        for isin, px in ((AAA, 100.0), (BBB, 50.0), (ETF, 60.0)):
            c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d, px])
    return c


def _seed(con):
    return book.seed(con, DAYS[4], datetime(2026, 11, 2, 9, 0))


def _review(con, cid, outcome, at=datetime(2026, 11, 2, 11, 0)):
    from pflab.pm.store import next_id
    con.execute("INSERT INTO hq_case_reviews VALUES (?,?,?,?,?,?)", [next_id(con, "hq_case_reviews", "review_id"), cid, at, "{}", outcome, "n"])


def test_the_start_copies_his_lots_with_their_dates_and_costs_and_leaves_out_the_us_sleeve(con):
    out = _seed(con)
    assert out["new"] and out["lots"] == 3 and out["cash"] == pytest.approx(500_000.0)
    assert {x["isin"] for x in out["left_out"]} == {USX}
    lots = con.execute("SELECT isin, acq_date, qty, cost_per_unit FROM paper_lots ORDER BY acq_date").fetchall()
    assert lots[0][:3] == (AAA, date(2024, 1, 10), 50.0) and lots[0][3] == pytest.approx(80.0)
    h = book.holdings(con, DAYS[4])
    assert h["value"] == pytest.approx(500_000 + 60 * 100 + 100 * 50)
    assert _seed(con)["new"] is False                                                            # once


def test_a_sale_takes_the_oldest_lots_first_and_its_tax_is_what_it_adds_to_the_year(con):
    _seed(con)
    oid = book.place(con, datetime(2026, 11, 2, 10, 0), None, AAA, "sell", qty=55)
    book.fill(con, date(2026, 11, 2), datetime(2026, 11, 2, 21, 0))
    t = con.execute("SELECT realised, tax, detail_json FROM paper_trades WHERE order_id=?", [oid]).fetchone()
    g = json.loads(t[2])["gains"]
    assert g["lt_eq"] == pytest.approx(50 * 20, abs=30) and g["st_eq"] == pytest.approx(5 * 5, abs=5)    # 50 old at 80, 5 newer at 95 (less the sale's charges)
    assert t[1] == pytest.approx(0.20 * g["st_eq"], abs=0.5)                                             # the long-term gain is under the Rs 1.25 lakh
    assert book.tax_of({"st_eq": -1000.0, "lt_eq": 200_000.0}) == pytest.approx(0.125 * (199_000 - 125_000))   # a short-term loss reduces long-term gains
    assert book.tax_of({"lt_eq": -5000.0, "st_eq": 10_000.0}) == pytest.approx(2000.0)                   # a long-term loss does not reduce a short-term gain


def test_the_paper_account_is_separate_and_none_of_his_real_money_reaches_it(con):
    _seed(con)
    con.execute("INSERT INTO cash_ledger VALUES ('Z', ?, 25000, 'cash_transfer_in', 'r', 12)", [date(2026, 11, 4)])
    book.catch_up(con, date(2026, 11, 6), datetime(2026, 11, 6, 21, 0))
    assert book.cash(con, date(2026, 11, 4)) == pytest.approx(500_000.0)                          # his deposit did not reach it
    r = book.returns(con)
    assert r["sessions"] == 5 and r["twr"] == pytest.approx(0.0, abs=1e-9)


def test_the_gate_opens_only_after_two_months_of_beating_the_index_with_a_smaller_fall(con):
    _seed(con)
    book.catch_up(con, DAYS[-1], datetime(2026, 12, 31, 21, 0))
    idx = pd.Series([1000.0 * (1 - 0.001 * i) for i in range(len(DAYS))], index=pd.to_datetime(DAYS))
    g = manager.gate(con, None, idx)
    assert book.returns(con)["sessions"] >= manager.GATE_SESSIONS and g["open"] is True                # flat beats a falling index, with no fall
    up = pd.Series([1000.0 * (1 + 0.002 * i) for i in range(len(DAYS))], index=pd.to_datetime(DAYS))
    assert manager.gate(con, None, up)["open"] is False


def test_the_gate_waits_for_enough_sessions(con):
    _seed(con)
    book.catch_up(con, DAYS[8], datetime(2026, 11, 5, 21, 0))
    assert manager.gate(con, None, pd.Series([1.0, 1.0], index=pd.to_datetime(DAYS[:2])))["open"] is False


def test_the_rails_flag_his_own_concentration_without_selling_it(con):
    _seed(con)
    con.execute("UPDATE paper_cash SET amount = 1000 WHERE kind='seed'")
    f = rails.flags(con, DAYS[4])
    assert any("AAA" in x for x in f) and any("IT sector" in x for x in f)
    assert book.positions(con)[AAA] == 60.0


def test_the_paper_settings_are_read_from_his_budget_file(tmp_path, monkeypatch):
    (tmp_path / "api_budget.toml").write_text("[api]\nmonthly_cap_rupees = 1500\n[paper]\nmonthly_rupees = 450\nmission_rupees = 90\non = \"on\"\n", encoding="utf-8")
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    cfg = an.config()
    assert cfg["paper"] == {"monthly_rupees": 450, "mission_rupees": 90, "on": "on"}
    monkeypatch.setattr(an, "config", lambda: cfg)
    assert manager.settings()["monthly_rupees"] == 450.0 and manager.settings()["mission_rupees"] == 90.0


def test_a_share_with_no_sector_in_the_instruments_table_gets_the_sector_maps_industry(con, monkeypatch):
    con.execute("UPDATE instruments SET sector = NULL WHERE isin = ?", [AAA])
    book._SECTORS.clear()
    monkeypatch.setattr(book, "_industry", lambda isin: "COMPUTERS - SOFTWARE" if isin == AAA else None)
    assert book.inst(con, AAA)["sector"] == "COMPUTERS - SOFTWARE" and book.inst(con, ETF)["sector"] is None

