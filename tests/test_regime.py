"""E3-R §3-§4 signals and gears."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.signals import regime as rg


def test_undefined_is_not_firing_and_is_kept_distinct():
    assert rg.fires(None) is False and rg.fires(True) is True
    # T and B fire, V undefined: cautious on B alone (§11 (a))
    assert rg.cautious_at(True, None, True) is True
    assert rg.cautious_at(True, None, None) is False
    assert rg.cautious_at(False, True, True) is False
    assert rg.cautious_at(True, True, False, trigger="B") is False
    assert rg.cautious_at(True, False, True, trigger="V") is False


def test_high_gear_needs_two_consecutive_cautious_months():
    c = [False, True, False, True, True, False, False, True, True, True, False]
    assert rg.gear_path(c) == ["normal", "cautious", "normal", "cautious", "cautious",
                               "high", "normal", "cautious", "cautious", "cautious",
                               "high"]
    assert "high" not in rg.gear_path(c, high_gear=False)


def test_trailing_percentile_excludes_current_and_needs_full_lookback():
    ds = [date(2000 + i // 12, i % 12 + 1, 28) for i in range(40)]
    vals = {d: float(i) for i, d in enumerate(ds)}
    out = rg.above_trailing_percentile(vals, 0.8, 36)
    assert all(out[d] is None for d in ds[:36])
    assert out[ds[36]] is True            # 36 > 80th pct of 0..35
    vals[ds[36]] = 1.0
    assert rg.above_trailing_percentile(vals, 0.8, 36)[ds[36]] is False
    vals[ds[10]] = None                    # a hole inside the lookback
    assert rg.above_trailing_percentile(vals, 0.8, 36)[ds[36]] is None


def test_basket_vol_uses_only_rows_up_to_m():
    idx = [date(2020, 1, 1) + pd.Timedelta(days=i) for i in range(200)]
    rng = np.random.default_rng(0)
    w = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, .01, (200, 3)), axis=0)),
                     index=idx, columns=["A", "B", "C"])
    m = idx[150]
    v1 = rg.basket_vol(w, m, ["A", "B"], 126)
    w2 = w.copy()
    w2.iloc[151:] *= 3.0
    assert rg.basket_vol(w2, m, ["A", "B"], 126) == v1
    assert rg.basket_vol(w, idx[100], ["A", "B"], 126) is None


def test_own_sma_counts_the_names_rows_not_calendar_sessions():
    rows = [{"date": date(2020, 1, d), "isin": "A", "adj_close": float(d)}
            for d in (1, 2, 5, 6)]
    s = rg.own_sma(pd.DataFrame(rows), 3)
    assert np.isnan(s.loc[date(2020, 1, 2), "A"])
    assert s.loc[date(2020, 1, 5), "A"] == pytest.approx((1 + 2 + 5) / 3)
    assert s.loc[date(2020, 1, 6), "A"] == pytest.approx((2 + 5 + 6) / 3)


def test_breadth_share_above_own_average():
    c = pd.Series({"A": 10.0, "B": 5.0, "C": 7.0, "D": 1.0})
    s = pd.Series({"A": 9.0, "B": 6.0, "C": np.nan, "D": 0.5})
    assert rg.breadth(c, s, ["A", "B", "C", "D"]) == pytest.approx(2 / 3)
    assert rg.breadth(c, s, ["C"]) is None
