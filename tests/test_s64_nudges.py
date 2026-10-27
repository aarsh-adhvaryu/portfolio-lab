"""S64: Kite-style pre-trade nudges from our own data."""
from datetime import date, timedelta

import pandas as pd
import pytest

from pflab.plan import nudges

ASOF = date(2026, 10, 26)
ISIN = "INE000A01011"


def bhav(root, series="EQ", turnover=5e7, sessions=25, symbol="AAA"):
    d = root / "bhavcopy" / "2026"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for k in range(sessions):
        day = ASOF - timedelta(days=sessions - 1 - k)
        if day.weekday() < 5:
            rows.append(dict(date=day, symbol=symbol, series=series, isin=ISIN, open=100.0, high=101.0, low=99.0, close=100.0,
                             prev_close=100.0, volume=1000.0, turnover=turnover, trades=10))
    pd.DataFrame(rows).to_parquet(d / "2026-all.parquet", index=False)


@pytest.fixture
def root(tmp_path, monkeypatch):
    from pflab.data import bhavcopy, nse_corporate_actions as nca
    monkeypatch.setattr(bhavcopy, "bhav_files", lambda r, s, e: [str(p) for p in (r / "bhavcopy").rglob("*.parquet")])
    monkeypatch.setattr(nca, "events", lambda r=None, raw=None, series=("EQ",): pd.DataFrame(columns=["isin", "ex_date", "kind", "factor", "subject"]))
    return tmp_path


def kinds(root, **kw):
    return [n["kind"] for n in nudges.check(root, ISIN, ASOF, **kw)]


def test_a_liquid_ordinary_stock_has_no_nudges(root):
    bhav(root)
    assert kinds(root, order_rupees=50_000) == []


def test_trade_to_trade_and_rights_entitlement_come_from_the_series(root):
    bhav(root, series="BE")
    n = nudges.check(root, ISIN, ASOF)
    assert [x["kind"] for x in n] == ["t2t"] and "delivery" in n[0]["text"]
    bhav(root, series="RE")
    assert "rights_entitlement" in kinds(root)


def test_thin_trading_and_an_order_that_moves_the_price(root):
    bhav(root, turnover=5e5)                                             # Rs 5 lakh a day
    n = nudges.check(root, ISIN, ASOF)
    assert n[0]["kind"] == "illiquid" and "our limit" in n[0]["text"]
    bhav(root, turnover=5e7)                                             # Rs 5 crore a day: ordinary...
    assert kinds(root, order_rupees=2_000_000) == ["illiquid"]           # ...but Rs 20 lakh is 4% of a day's trading
    assert kinds(root, order_rupees=100_000) == []


def test_surveillance_and_insolvency_flags(root):
    bhav(root)
    s = root / "surveillance"
    s.mkdir()
    pd.DataFrame([dict(date="2026-10-24", list="GSM", symbol="AAA", isin=ISIN, code="GSM - IBC", desc="Insolvency stage",
                       stage=2.0, ibc=True, verdict="block")]).to_parquet(s / "2026-10-24.parquet", index=False)
    n = nudges.check(root, ISIN, ASOF)
    assert [x["kind"] for x in n] == ["surveillance", "irp"] and "Verdict: block" in n[0]["text"]


def test_split_or_bonus_near_its_ex_date(root, monkeypatch):
    from pflab.data import nse_corporate_actions as nca
    bhav(root)
    ev = pd.DataFrame([dict(isin=ISIN, ex_date=ASOF + timedelta(days=3), kind="split", factor=0.1, subject="s"),
                       dict(isin=ISIN, ex_date=ASOF - timedelta(days=30), kind="bonus", factor=0.5, subject="b"),
                       dict(isin="INE999", ex_date=ASOF, kind="split", factor=0.5, subject="o")])
    monkeypatch.setattr(nca, "events", lambda r=None, raw=None, series=("EQ",): ev)
    n = nudges.check(root, ISIN, ASOF)
    assert [x["kind"] for x in n] == ["corporate_action"] and "not a loss" in n[0]["text"]


def test_filings_name_the_insolvency_process_or_a_suspension_but_not_a_voluntary_liquidation(root):
    bhav(root)
    a = root / "bse_announcements" / "2026"
    a.mkdir(parents=True)
    rows = [("500001", "Voluntary Liquidation of a Thai subsidiary", -10), ("500001", "NCLT admits CIRP application against the company", -40),
            ("500001", "Suspension of trading in equity shares", -3), ("500002", "Suspension of trading", -3)]
    pd.DataFrame([dict(scrip_code=s, company="x", headline=h, category="Company Update", subcategory="", news_dt=ASOF + timedelta(days=d),
                       dissem_dt=pd.Timestamp(ASOF + timedelta(days=d)), attachment="", news_sub="") for s, h, d in rows]
                 ).to_parquet(a / "x.parquet", index=False)
    n = nudges.check(root, ISIN, ASOF, scrip="500001")
    assert sorted(x["kind"] for x in n) == ["irp", "suspension"]
    assert "voluntary" not in " ".join(x["text"].lower() for x in n)
    assert nudges.check(root, ISIN, ASOF, scrip="500003") == []


def test_ticket_lines_carry_the_nudges_and_say_what_cannot_be_checked(root):
    from pflab.plan import trader
    bhav(root, series="BE")
    out = trader.tickets("AAA", 10, 100.0, "L1", isin=ISIN, nudge=lambda i, r: nudges.lines(nudges.check(root, i, ASOF, order_rupees=r)))
    assert out[-1].startswith("NUDGE (t2t):") and out[0].startswith("BUY AAA")
    assert nudges.NOT_CHECKED and "tips" in nudges.NOT_CHECKED[0]
