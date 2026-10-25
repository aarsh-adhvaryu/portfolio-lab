"""S63 wiring (the investor's yes, 2026-10-25): the TimesFM refresh check, the collectors' daily mode (history kept, the
running month refetched), holders and market context for the brain, deals and holdings in the graph. Synthetic data."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab.pm import store


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


def test_refresh_due_when_weights_are_missing_or_timesfm_lost(con, tmp_path):
    from pflab.quant import tfm2_live as fl
    asof = date(2026, 11, 2)
    assert [k for k, _ in fl.refresh_due(con, tmp_path, asof)] == ["missing"]          # a fresh install
    for f in ("A", "B"):
        p = tmp_path / "research" / "timesfm2" / "ft" / f"q6_ln_revenue_{f}"
        p.mkdir(parents=True)
        (p / "model.safetensors").write_bytes(b"x")
    assert fl.refresh_due(con, tmp_path, asof) == []
    for k in range(31):
        con.execute("INSERT INTO tfm_scoreboard VALUES (?,?,?,?,?,?,?,?)",
                    ["revenue", asof - timedelta(days=30 - k), 10, 12, 1.2, "baseline", False, datetime(2026, 11, 2)])
    keys = [k for k, _ in fl.refresh_due(con, tmp_path, asof)]
    assert keys == ["lost:revenue"]


def test_latest_quarter_waits_for_the_filing_deadline():
    from pflab.data import bse_shareholding as bs
    assert bs.quarter_end(bs.latest_qtrid(date(2026, 10, 25))) == date(2026, 9, 30)
    assert bs.quarter_end(bs.latest_qtrid(date(2026, 10, 15))) == date(2026, 6, 30)       # September not due yet


def test_fpi_daily_merge_keeps_history(tmp_path, monkeypatch):
    from pflab.data import fpi_flows
    old = pd.DataFrame({"report_date": [date(2020, 1, 2)], "asset": ["Equity"], "route": ["Sub-total"],
                        "gross_purchase_cr": [1.0], "gross_sale_cr": [2.0], "net_cr": [-1.0], "net_usd_mn": [0.0],
                        "usd_inr": [70.0]})
    (tmp_path / "macro").mkdir()
    old.to_parquet(tmp_path / "macro" / "FPI_DAILY.parquet")
    new = old.assign(report_date=[date(2026, 10, 23)], net_cr=[155.0])
    monkeypatch.setattr(fpi_flows, "fetch_month", lambda s, me: new)
    monkeypatch.setattr(fpi_flows.time, "sleep", lambda s: None)
    fpi_flows.collect(date(2026, 10, 1), date(2026, 10, 25), tmp_path, pause=0, merge=True)
    got = fpi_flows.load(tmp_path)
    assert sorted(got["report_date"].astype(str)) == ["2020-01-02", "2026-10-23"]


def test_market_context_is_point_in_time(tmp_path):
    from pflab.hq import context
    (tmp_path / "macro").mkdir()
    (tmp_path / "indices").mkdir()
    days = pd.date_range("2026-08-01", "2026-10-30", freq="D")
    pd.DataFrame({"date": days.date, "value": range(len(days))}).to_parquet(tmp_path / "macro" / "BRENT.parquet")
    out = context.market(tmp_path, date(2026, 10, 1))
    assert out["brent_usd"]["on"] == "2026-10-01" and out["india_vix"].startswith("not available")


def test_deals_and_holdings_reach_the_graph(con, tmp_path):
    from pflab.kg import build as kb
    (tmp_path / "nse_deals").mkdir()
    pd.DataFrame({"date": [pd.Timestamp("2026-10-23")], "symbol": ["AAA"], "client": ["A FUND"], "side": ["BUY"],
                  "quantity": [1000], "price": [10.5], "kind": ["bulk"], "capped": [False]}
                 ).to_parquet(tmp_path / "nse_deals" / "bulk_2026-10.parquet")
    (tmp_path / "bse_shareholding").mkdir()
    pd.DataFrame({"scrip_code": ["500001"], "quarter_end": [date(2026, 9, 30)], "status": ["ok"], "promoter_pct": [55.0],
                  "pledged_pct_of_promoter": [0.0]}).to_parquet(tmp_path / "bse_shareholding" / "summary.parquet")
    pd.DataFrame({"scrip_code": ["500001"], "qtrid": [131], "quarter_end": [date(2026, 9, 30)], "inst_pct": [20.0],
                  "mf_pct": [8.0], "fpi_pct": [12.0], "status": ["ok"]}).to_parquet(tmp_path / "bse_shareholding" / "institutions.parquet")
    u = pd.DataFrame({"isin": ["INE000A01011"], "symbol": ["AAA"], "scrip": ["500001"], "name": ["Aaa Ltd"]})
    assert kb.deals(con, u, date(2026, 1, 1), tmp_path) == 1
    assert kb.holdings(con, u, tmp_path) == 1
    assert kb.deals(con, u, date(2026, 1, 1), tmp_path) == 0                             # idempotent
    t = con.execute("SELECT title FROM kg_docs WHERE kind='holding'").fetchone()[0]
    assert "promoters 55.00%" in t and "FPIs 12.00%" in t
