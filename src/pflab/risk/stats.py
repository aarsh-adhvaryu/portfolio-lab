"""Portfolio risk statistics: volatility, drawdown, beta, correlation, concentration (PLAN S15).

All inputs are pandas Series/DataFrames indexed by date. Nothing here fetches data. Where
there are too few observations the answer is NaN, not a number from two points.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

from pflab.eval import metrics

TRADING_DAYS = 252


def daily_returns(nav: pd.Series) -> pd.Series:
    s = nav.dropna().astype(float)
    s.index = pd.to_datetime(s.index)
    return s.pct_change().dropna()


def volatility(returns: pd.Series, periods: int = TRADING_DAYS, min_obs: int = 20) -> float:
    r = returns.dropna()
    return float(r.std(ddof=1) * np.sqrt(periods)) if len(r) >= min_obs else float("nan")


def drawdown_series(nav: pd.Series) -> pd.Series:
    n = nav.dropna().astype(float)
    return 1.0 - n / n.cummax()


def max_drawdown(nav: pd.Series) -> float:
    return metrics.max_drawdown(nav)


def beta(returns: pd.Series, bench: pd.Series, min_obs: int = 20) -> float:
    """OLS slope of `returns` on `bench` over the dates both have."""
    a, b = returns.align(bench, join="inner")
    ok = a.notna() & b.notna()
    a, b = a[ok], b[ok]
    if len(a) < min_obs or float(b.var(ddof=1)) <= 0:
        return float("nan")
    return float(np.cov(a, b, ddof=1)[0, 1] / b.var(ddof=1))


def correlation(returns: pd.DataFrame, min_obs: int = 20) -> pd.DataFrame:
    """Pairwise correlation of columns, NaN where fewer than `min_obs` shared observations."""
    return returns.corr(min_periods=min_obs)


def concentration(weights: pd.Series, top_ns=(1, 3, 5, 10)) -> Dict[str, float]:
    """HHI (sum of squared weights of the HOLDINGS, renormalised to sum 1), effective number of
    holdings (1/HHI) and the share held in the top N."""
    w = weights.dropna()
    w = w[w > 0]
    if w.empty:
        return {"hhi": float("nan"), "effective_n": float("nan"), "n": 0, **{f"top{n}": float("nan") for n in top_ns}}
    w = w / w.sum()
    hhi = float((w ** 2).sum())
    s = w.sort_values(ascending=False)
    return {"hhi": hhi, "effective_n": 1.0 / hhi, "n": int(len(w)),
            **{f"top{n}": float(s.iloc[:n].sum()) for n in top_ns}}


def summary(nav: pd.Series, bench_close: Optional[pd.Series] = None) -> Dict[str, float]:
    """Volatility, max drawdown and beta (if a benchmark close series is given) of a NAV."""
    r = daily_returns(nav)
    out = {"vol_annual": volatility(r), "max_drawdown": max_drawdown(nav) if len(nav.dropna()) > 1 else float("nan"),
           "obs": int(len(r))}
    if bench_close is not None:
        out["beta"] = beta(r, daily_returns(bench_close))
    return out
