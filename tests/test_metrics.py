from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.eval.metrics import (cagr, max_drawdown, sharpe, stationary_bootstrap_ci,
                                unitized_nav, xirr)


def test_unitized_nav_ignores_flows_when_returns_are_flat():
    idx = pd.date_range("2024-01-01", periods=4, freq="D")
    values = pd.Series([100.0, 200.0, 200.0, 300.0], index=idx)
    flows = pd.Series([100.0, 100.0, 0.0, 100.0], index=idx)
    nav = unitized_nav(values, flows)
    assert np.allclose(nav.values, 100.0)


def test_unitized_nav_tracks_returns():
    idx = pd.date_range("2024-01-01", periods=3, freq="D")
    values = pd.Series([100.0, 110.0, 210.0], index=idx)   # +10%, then deposit 100 and flat
    flows = pd.Series([100.0, 0.0, 100.0], index=idx)
    nav = unitized_nav(values, flows)
    assert nav.iloc[1] == pytest.approx(110.0)
    assert nav.iloc[2] == pytest.approx(110.0)


def test_cagr_and_drawdown():
    idx = pd.to_datetime([date(2020, 1, 1), date(2021, 1, 1), date(2022, 1, 1)])
    nav = pd.Series([100.0, 50.0, 200.0], index=idx)
    assert cagr(nav) == pytest.approx(2 ** (365.25 * 0 + 1 / ((idx[-1] - idx[0]).days / 365.25)) - 1)
    assert max_drawdown(nav) == pytest.approx(0.5)


def test_xirr_simple():
    r = xirr([date(2020, 1, 1), date(2021, 1, 1)], [-100.0, 110.0])
    assert r == pytest.approx(0.10, abs=1e-3)


def test_sharpe_zero_for_flat():
    idx = pd.date_range("2020-01-31", periods=13, freq="ME")
    assert sharpe(pd.Series(100.0, index=idx)) == 0.0


def test_bootstrap_ci_contains_true_mean():
    rng = np.random.default_rng(1)
    x = rng.normal(0.01, 0.05, size=120)
    lo, hi = stationary_bootstrap_ci(x, block=6, n=500)
    assert lo < x.mean() < hi
