"""The engine's precomputed §2 filter must equal `universe.eligible` exactly.

The engine cannot call `universe.eligible` at every month-end (0.9 s on the
development panel, so a sweep would not finish), so it precomputes the same
three statistics once. That optimisation is only legitimate if it changes no
decision, which is what this asserts.
"""
from datetime import date

import pandas as pd
import pytest

from conftest import random_walk_panel
from pflab.backtest import engine
from pflab.data import universe as uni


def _cfg():
    return {"universe": {"series": ["EQ"], "min_sessions": 60,
                         "top_n_by_turnover": 8, "turnover_window": 20,
                         "min_price": 10.0}}


def _month_ends(panel):
    return sorted(engine._month_ends(sorted(panel["date"].unique())))


def test_fast_path_matches_universe_eligible_at_every_month_end():
    sessions, names, panel = random_walk_panel(seed=40, n_names=20,
                                               start="2016-01-01", end="2018-12-31")
    # vary turnover so the top-N ranking is not degenerate
    panel = panel.copy()
    panel["turnover"] = panel["turnover"] * (
        panel["isin"].str.extract(r"(\d+)").astype(int)[0].values + 1)
    cfg = _cfg()
    pre = engine.precompute_universe(panel, cfg)
    for m in _month_ends(panel):
        hist = panel[panel["date"] <= m]
        slow = uni.eligible(hist, series=("EQ",), min_sessions=60, top_n=8,
                            turnover_window=20, min_price=10.0)
        fast = engine.eligible_at(pre, m, min_sessions=60, top_n=8, min_price=10.0)
        assert list(slow) == list(fast), f"month-end {m}"


def test_fast_path_matches_when_a_name_stops_trading():
    """A delisted name keeps its last statistics under both paths, because
    `eligible` groups every row dated <= M."""
    sessions, names, panel = random_walk_panel(seed=41, n_names=12,
                                               start="2016-01-01", end="2018-12-31")
    panel = panel[~((panel["isin"] == names[0]) & (panel["date"] >= date(2017, 6, 1)))]
    cfg = _cfg()
    pre = engine.precompute_universe(panel, cfg)
    for m in _month_ends(panel):
        hist = panel[panel["date"] <= m]
        slow = uni.eligible(hist, series=("EQ",), min_sessions=60, top_n=8,
                            turnover_window=20, min_price=10.0)
        fast = engine.eligible_at(pre, m, min_sessions=60, top_n=8, min_price=10.0)
        assert list(slow) == list(fast), f"month-end {m}"


def test_fast_path_excludes_non_stk_like_the_filter_does():
    sessions, names, panel = random_walk_panel(seed=42, n_names=10,
                                               start="2016-01-01", end="2018-12-31")
    panel = panel.copy()
    panel.loc[panel["isin"] == names[0], "instrument_type"] = "ETF"
    pre = engine.precompute_universe(panel, _cfg())
    m = _month_ends(panel)[-1]
    fast = engine.eligible_at(pre, m, min_sessions=60, top_n=8, min_price=10.0)
    assert names[0] not in fast


def test_momentum_hoisting_is_backward_only():
    """Computing momentum once on the full frame must equal computing it on
    the frame truncated at each date -- it is a pure shift."""
    from pflab.signals.momentum import momentum_panel
    sessions, names, panel = random_walk_panel(seed=43, n_names=6,
                                               start="2015-01-01", end="2018-12-31")
    adj = panel.pivot_table(index="date", columns="isin", values="adj_close",
                            aggfunc="last")
    full = momentum_panel(adj, lookback=252, skip=21)
    for m in [adj.index[300], adj.index[600], adj.index[-1]]:
        partial = momentum_panel(adj.loc[adj.index <= m], lookback=252, skip=21)
        pd.testing.assert_series_equal(full.loc[m], partial.loc[m])
