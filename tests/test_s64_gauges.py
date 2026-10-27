"""S64: IPO froth, breadth and correction-length gauges."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.quant import gauges

ASOF = date(2026, 10, 26)


def test_episodes_measure_the_fall_down_and_the_way_back():
    # 100 -> 120 (peak at 2) -> 90 (trough at 5, a 25% fall) -> back above 120 at index 9
    v = [100, 110, 120, 110, 100, 90, 95, 105, 115, 125, 130, 120, 100]
    ep = gauges.episodes(pd.Series(v, index=pd.bdate_range("2020-01-01", periods=len(v))))
    done = [e for e in ep if not e["open"]]
    assert len(done) == 1 and done[0]["to_trough"] == 3 and done[0]["to_recover"] == 4 and done[0]["total"] == 7
    assert done[0]["depth"] == pytest.approx(-0.25)
    assert ep[-1]["open"] and ep[-1]["to_recover"] is None and ep[-1]["depth"] == pytest.approx(100 / 130 - 1)     # now in a 23% fall
    assert gauges.episodes(pd.Series([100, 105, 95, 104, 110])) == []                                              # a 9% dip is not counted


def test_corrections_report_how_far_into_a_fall_the_index_is(tmp_path):
    idx = pd.bdate_range("2015-01-01", periods=1000)
    px = 100 + 20 * np.sin(np.arange(1000) / 60.0)
    load = lambda k: pd.DataFrame({"date": idx, "close": px})              # noqa: E731
    out = gauges.corrections(tmp_path, ASOF, keys=["NIFTY500_TRI", "SECTOR_IT_TRI"], loader=lambda k: load(k).assign(date=idx))
    row = out["indices"]["Nifty500"]
    assert row["past_falls_of_10pct_or_more"] >= 1 and row["median_sessions_peak_to_trough"] > 0
    assert "It" in out["indices"] and "not a forecast" in out["note"]


def make_closes(n_up, n_down, sessions=520, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-10-01", periods=sessions)
    cols = {}
    for k in range(n_up):
        cols[f"U{k}"] = 100 * np.cumprod(1 + rng.normal(0.0015, 0.004, sessions))        # steadily up: above its averages
    for k in range(n_down):
        cols[f"D{k}"] = 100 * np.cumprod(1 + rng.normal(-0.0015, 0.004, sessions))       # steadily down: below them
    return pd.DataFrame(cols, index=idx)


def test_breadth_counts_names_above_their_averages_and_where_that_sits_in_the_year():
    b = gauges.breadth(None, ASOF, closes=make_closes(30, 70))
    assert b["names"] == 100 and 20 <= b["above_200d_pct"] <= 40 and b["read"] == "most names are in a downtrend"
    up = gauges.breadth(None, ASOF, closes=make_closes(80, 20))
    assert up["above_200d_pct"] > 65 and up["read"] == "most names are in an uptrend"
    thin = make_closes(5, 5).iloc[:100]
    assert "not_built" in gauges.breadth(None, ASOF, closes=thin)                             # too little history: said, not guessed


def test_ipo_froth_compares_the_last_year_with_the_five_before(tmp_path):
    rows, ld = [], {}
    q_starts = pd.date_range("2020-01-02", "2026-09-01", freq="QS") + pd.Timedelta(days=3)
    for qi, q0 in enumerate(q_starts):
        n = 4 if q0 < pd.Timestamp("2025-07-01") else 12                       # 4 large listings a quarter, then 12
        for k in range(n):
            isin = f"INE{qi:04d}{k:05d}"
            d = pd.bdate_range(q0, periods=1 + k)[-1]
            ld[isin] = d
            rows.append(dict(date=d, isin=isin, series="EQ", close=110.0, prev_close=100.0, turnover=5e9))
    p = tmp_path / "panel"
    p.mkdir()
    pd.DataFrame(rows).to_parquet(p / "prices.parquet", index=False)
    pd.DataFrame({"first_trade": pd.Series(ld)}).to_parquet(p / "listing_dates.parquet")
    f = gauges.ipo_froth(tmp_path, ASOF)
    assert f["per_quarter_now"] == 12.0 and f["per_quarter_prior_5_years"] == 4.0 and f["ratio"] == 3.0     # whole quarters only
    assert f["read"] == "busier than its 5-year norm" and f["median_listing_gain_now_pct"] == 10.0
