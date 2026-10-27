"""S64 Phase 6 item 3: US prices in the panel layout, the universe, SEC filings and facts point in time."""
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from pflab.data import sec_edgar as sec, us_prices as up


def bars(n=30, start="2026-01-02", dividend_at=None):
    idx = pd.bdate_range(start, periods=n)
    close = pd.Series(100 + np.arange(n, dtype=float), index=idx)
    df = pd.DataFrame({"date": [d.date() for d in idx], "open": close.to_numpy() - 0.5, "high": close.to_numpy() + 1, "low": close.to_numpy() - 1,
                       "close": close.to_numpy(), "adj_close": close.to_numpy() * 0.98, "volume": 1e6, "dividend": 0.0})
    if dividend_at is not None:
        df.loc[dividend_at, "dividend"] = 0.5
    return df


def test_collect_writes_one_file_each_refuses_a_shorter_download_and_reports_failures(tmp_path):
    out = up.collect(["SPY", "BAD"], tmp_path, pause=0, get=lambda s, **k: bars(40) if s == "SPY" else (_ for _ in ()).throw(RuntimeError("no data")))
    assert out["SPY"][0] == 40 and "no data" in out["BAD"] and not (tmp_path / "us" / "raw" / "BAD.parquet").exists()
    out2 = up.collect(["SPY"], tmp_path, pause=0, get=lambda s, **k: bars(10))                  # a cut history must not replace a longer file
    assert "kept the file" in out2["SPY"] and len(pd.read_parquet(tmp_path / "us" / "raw" / "SPY.parquet")) == 40


def test_recent_days_appends_and_replaces_overlapping_days_only(tmp_path):
    up.collect(["SPY"], tmp_path, pause=0, get=lambda s, **k: bars(40))
    new = bars(5, start="2026-02-20")                                       # overlaps the file's last days, one new day beyond it
    new["close"] = 999.0
    up.collect(["SPY"], tmp_path, pause=0, get=lambda s, **k: new, recent_days=10)
    df = pd.read_parquet(tmp_path / "us" / "raw" / "SPY.parquet").sort_values("date")
    assert df["date"].is_unique and df["date"].max() == new["date"].max() and (df[df["date"].isin(set(new["date"]))]["close"] == 999.0).all()


def test_panel_has_the_indian_layout_keys_stocks_by_pseudo_isin_and_funds_by_symbol(tmp_path):
    up.collect(["SPY", "AAPL"], tmp_path, pause=0, get=lambda s, **k: bars(30, dividend_at=3))
    panel = up.build_panel(tmp_path, {"AAPL": 320193})
    assert list(panel.columns) == up.PANEL_COLUMNS
    assert set(panel.loc[panel.symbol == "AAPL", "isin"]) == {"ZZ0000320193"} and set(panel.loc[panel.symbol == "SPY", "isin"]) == {"US:SPY"}
    a = panel[panel.symbol == "AAPL"]
    assert set(a["series"]) == {"US"} and a["adj_factor"].iloc[0] == pytest.approx(0.98) and a["dividend"].sum() == 0.5
    assert a["prev_close"].iloc[1] == a["close"].iloc[0] and (tmp_path / "us" / "prices.parquet").exists()


def test_universe_is_the_etfs_plus_his_names_and_optionally_the_index(tmp_path):
    (tmp_path / "us_list.toml").write_text('symbols = ["nvda", "AAPL"]\n')
    u = up.universe(tmp_path)
    assert u[:3] == ["SPY", "QQQ", "XLC"] and u[-2:] == ["NVDA", "AAPL"] and len(u) == len(up.ETFS) + 2
    html = "<table><tr><th>Symbol</th><th>Security</th></tr><tr><td>MSFT</td><td>x</td></tr><tr><td>BRK.B</td><td>y</td></tr></table>"
    assert up.sp500_symbols(lambda u_: html) == ["BRK-B", "MSFT"]
    assert "MSFT" in up.universe(tmp_path, with_sp500=True, get_html=lambda u_: html)


SUB = {"filings": {"recent": {"accessionNumber": ["a1", "a2", "a3"], "form": ["10-Q", "8-K", "10-Q"],
                              "filingDate": ["2026-05-01", "2026-06-10", "2026-08-01"],
                              "acceptanceDateTime": ["2026-05-01T20:15:30.000Z", "2026-06-10T13:00:00.000Z", "2026-08-01T20:30:00.000Z"],
                              "primaryDocument": ["q.htm", "e.htm", "q2.htm"], "items": ["", "2.02", ""]}}}


def test_filings_carry_their_acceptance_time_and_new_ones_are_found_by_it(tmp_path):
    f = sec.submissions(320193, tmp_path, get=lambda url: SUB)
    assert list(f["accn"]) == ["a1", "a2", "a3"] and f["accepted"].iloc[0] == pd.Timestamp("2026-05-01 20:15:30")
    new = sec.new_filings(f, datetime(2026, 6, 1))
    assert list(new["accn"]) == ["a2", "a3"] and sec.new_filings(f, datetime(2026, 6, 1), forms=("10-Q",))["accn"].tolist() == ["a3"]
    assert "320193" in str(next((tmp_path / "us" / "sec").glob("submissions_*")).name).lstrip("submissions_0")


def test_facts_are_known_only_from_the_acceptance_of_the_filing_and_a_restatement_replaces_only_after_its_own_filing():
    f = sec.filings_from(SUB)
    facts = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        {"start": "2026-01-01", "end": "2026-03-31", "val": 1.50, "accn": "a1", "form": "10-Q", "filed": "2026-05-01"},
        {"start": "2026-01-01", "end": "2026-03-31", "val": 1.55, "accn": "a3", "form": "10-Q", "filed": "2026-08-01"},     # restated
        {"start": "2026-04-01", "end": "2026-06-30", "val": 1.70, "accn": "a3", "form": "10-Q", "filed": "2026-08-01"}]}}}}}
    before = sec.facts_pit(facts, f, "EarningsPerShareDiluted", datetime(2026, 6, 15), unit="USD/shares")
    assert list(before["val"]) == [1.50]                                           # Q2 and the restatement are not known yet
    after = sec.facts_pit(facts, f, "EarningsPerShareDiluted", datetime(2026, 8, 2), unit="USD/shares")
    assert list(after["val"]) == [1.55, 1.70]
    assert sec.facts_pit(facts, f, "NoSuchConcept", datetime(2026, 8, 2)).empty


def test_a_refusal_from_sec_is_said_not_worked_around(monkeypatch):
    class R:
        status_code = 403
    monkeypatch.setattr(sec.requests, "get", lambda *a, **k: R())
    monkeypatch.setattr(sec.time, "sleep", lambda s: None)
    with pytest.raises(sec.SecRefused, match="real contact"):
        sec.get_json("https://data.sec.gov/x")
    monkeypatch.setenv("PFLAB_SEC_USER_AGENT", "Someone someone@example.org")
    assert sec.user_agent() == "Someone someone@example.org"
