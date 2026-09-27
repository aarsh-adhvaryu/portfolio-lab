"""E2-B §3 betas: point-in-time, correct slope, index-like fallback."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.signals import shock_betas as sb


def _months(n, start=2010):
    return [(pd.Timestamp(f"{start}-01-31") + pd.offsets.MonthEnd(i)).date()
            for i in range(n)]


def test_month_end_value_uses_last_row_on_or_before():
    s = pd.Series([1.0, 2.0, 4.0],
                  index=[date(2010, 1, 29), date(2010, 2, 26), date(2010, 3, 1)])
    ms = [date(2010, 1, 31), date(2010, 2, 28), date(2010, 3, 31)]
    assert sb.month_end_values(s, ms, "diff").tolist()[1:] == [1.0, 2.0]
    assert sb.month_end_values(s, ms, "pct").tolist()[1:] == [1.0, 1.0]


def test_sum_covers_only_the_month_and_empty_month_is_nan():
    s = pd.Series([5.0, -2.0, 7.0],
                  index=[date(2010, 1, 5), date(2010, 1, 31), date(2010, 3, 2)])
    ms = [date(2010, 1, 31), date(2010, 2, 28), date(2010, 3, 31)]
    out = sb.month_end_values(s, ms, "sum")
    assert out.iloc[0] == 3.0 and np.isnan(out.iloc[1]) and out.iloc[2] == 7.0


def test_unknown_transform_refused():
    with pytest.raises(ValueError):
        sb.month_end_values(pd.Series(dtype=float), [], "log")


def test_rolling_beta_recovers_slope_and_respects_min_obs():
    ms = _months(40)
    rng = np.random.default_rng(0)
    f = pd.Series(rng.normal(size=40), index=ms)
    r = pd.DataFrame({"A": 2.0 * f + 0.01, "B": -0.5 * f}, index=ms)
    r.loc[ms[:30], "B"] = np.nan                 # B has 10 obs only
    b = sb.rolling_betas(r, f, window=36, min_obs=24)
    assert b["A"].iloc[23] == pytest.approx(2.0)
    assert np.isnan(b["A"].iloc[22])
    assert b["B"].isna().all()


def test_future_rows_cannot_change_a_past_beta():
    ms = _months(60)
    rng = np.random.default_rng(1)
    f = pd.Series(rng.normal(size=60), index=ms)
    r = pd.DataFrame({"A": f + rng.normal(scale=.1, size=60)}, index=ms)
    b1 = sb.rolling_betas(r, f, 36, 24)
    r2, f2 = r.copy(), f.copy()
    r2.iloc[45:] *= 10
    f2.iloc[45:] = -f2.iloc[45:]
    b2 = sb.rolling_betas(r2, f2, 36, 24)
    pd.testing.assert_series_equal(b1["A"].iloc[:45], b2["A"].iloc[:45])


def test_portfolio_beta_treats_missing_edge_as_index_like():
    betas = pd.Series({"A": 2.0, "B": np.nan})
    assert sb.portfolio_beta({"A": 100.0, "B": 100.0}, betas, 1.0) == pytest.approx(1.5)
    assert sb.portfolio_beta({"A": 100.0, "C": 300.0}, betas, 1.0) == pytest.approx(1.25)


def test_breaches_skip_a_factor_with_no_index_edge():
    betas = {"oil": pd.Series({"A": 3.0}), "vix": pd.Series({"A": 3.0})}
    out = sb.breaches({"A": 1.0}, betas, {"oil": 1.0, "vix": np.nan}, 1.5)
    assert list(out) == ["oil"] and out["oil"]["cap"] == 1.5
