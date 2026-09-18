from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.data.universe import eligible
from pflab.portfolio.construct import buy_list
from pflab.portfolio.crash_rule import month_end_closes, risk_off
from pflab.signals.momentum import momentum_panel, rank_desc


def test_momentum_uses_only_past_rows():
    idx = pd.date_range("2020-01-01", periods=300, freq="B")
    a = pd.Series(np.linspace(100, 200, 300), index=idx)
    df = pd.DataFrame({"A": a, "B": a[::-1].values})
    m = momentum_panel(df, lookback=252, skip=21)
    assert m.iloc[251].isna().all() and m.iloc[252].notna().all()
    assert m["A"].iloc[-1] == pytest.approx(a.iloc[-22] / a.iloc[-253] - 1)
    # perturbing the future does not change the past
    df2 = df.copy()
    df2.iloc[-1] *= 5
    assert momentum_panel(df2).iloc[:-1].equals(m.iloc[:-1])
    r = rank_desc(m.iloc[-1])
    assert r["A"] == 1 and r["B"] == 2


def test_risk_off_sma10():
    idx = pd.date_range("2020-01-01", periods=400, freq="B")
    s = pd.Series(np.r_[np.linspace(100, 200, 300), np.linspace(200, 120, 100)], index=idx)
    me = month_end_closes(s)
    ro = risk_off(me, months=10)
    assert not ro.iloc[:9].any()        # insufficient history -> False
    assert not ro.iloc[9]               # rising market
    assert ro.iloc[-1]                  # after the fall


def test_buy_list_shortfall_and_integer_shares():
    names = ["A", "B", "C"]
    held = {"A": 9000.0, "B": 0.0}
    px = {"A": 100.0, "B": 2500.0, "C": 30.0}
    orders = buy_list(names, held, cash=6000.0, open_price=px, n_hold=3, max_names=2)
    # target per name = (9000 + 6000)/3 = 5000; shortfalls B=5000, C=5000, A=-4000
    assert [o[0] for o in orders] == ["B", "C"]
    assert orders[0][1] == 2           # floor(5000/2500)
    assert orders[1][1] == 33          # floor(min(5000, 1000)/30)
    assert buy_list(names, held, cash=0.0, open_price=px) == []


def _universe_panel(extra=()):
    dates = pd.date_range("2020-01-01", periods=260, freq="B")
    rows = []
    spec = [("I1", 50.0, 1e8, 260, "EQ", "STK"),
            ("I2", 5.0, 1e9, 260, "EQ", "STK"),      # below the Rs 10 floor
            ("I3", 50.0, 1e7, 100, "EQ", "STK")]     # too little history
    spec += list(extra)
    for isin, price, turn, n, series, itype in spec:
        for d in dates[-n:]:
            rows.append({"date": d, "isin": isin, "close": price, "turnover": turn,
                         "series": series, "instrument_type": itype})
    return pd.DataFrame(rows)


def test_eligible_filter():
    panel = _universe_panel()
    assert list(eligible(panel, min_sessions=250, top_n=500, min_price=10.0)) == ["I1"]


def test_eligible_excludes_etfs_trading_under_series_eq():
    """Charter section 2 / section 15 2026-09-16. A gold ETF out-ranks most
    stocks on traded value and would have been top-25 on momentum in 2020 and
    2024-25; the series filter alone does not catch it."""
    panel = _universe_panel(extra=[("INF_GOLD", 60.0, 9e9, 260, "EQ", "ETF")])
    assert list(eligible(panel, min_sessions=250, top_n=500, min_price=10.0)) == ["I1"]
    # without the type filter it would dominate the ranking
    assert "INF_GOLD" in list(eligible(panel, min_sessions=250, top_n=500,
                                       min_price=10.0, types=None))


def test_eligible_excludes_reits_and_invits():
    panel = _universe_panel(extra=[("REIT1", 400.0, 9e9, 260, "RR", "REIT"),
                                   ("IV1", 100.0, 9e9, 260, "IV", "INVIT")])
    assert list(eligible(panel, min_sessions=250, top_n=500, min_price=10.0)) == ["I1"]


def test_eligible_without_instrument_type_refuses_rather_than_leaking():
    panel = _universe_panel().drop(columns=["instrument_type"])
    with pytest.raises(ValueError, match="instrument_type"):
        eligible(panel, min_sessions=250, top_n=500, min_price=10.0)
