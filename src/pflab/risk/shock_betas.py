"""Company and index betas to macro shock factors (charter E2-B §3).

Everything here is point-in-time: a factor's value at month-end M is its
last observation dated on or before M, and a beta at M uses only the
trailing `window` monthly pairs ending at M. Nothing picks a parameter --
the window, the minimum observations and each factor's transform come from
the charter's config.

Transforms are what "the factor's monthly change" means per series, and are
a reading the charter's lock must confirm (E2-B readiness §3):

    pct    percent change of the month-end level (prices: Brent, USDINR)
    diff   difference of the month-end level (yields in pp, VIX in points)
    sum    sum of the month's daily values (a flow is already a change:
           NSDL net FPI equity investment, ₹ crore)
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Iterable, Mapping, Optional

import numpy as np
import pandas as pd

TRANSFORMS = ("pct", "diff", "sum")


def month_end_values(series: pd.Series, month_ends: Iterable[date],
                     transform: str) -> pd.Series:
    """Factor at each decision month-end, from rows dated <= that month-end.

    `series` is indexed by date. For 'sum' the value is the total of rows in
    (previous month-end, M]; a month with no rows is NaN, not zero.
    """
    if transform not in TRANSFORMS:
        raise ValueError(f"unknown transform {transform!r}; one of {TRANSFORMS}")
    ms = list(month_ends)
    s = series.dropna().sort_index()
    s.index = [pd.Timestamp(d).date() for d in s.index]
    idx = pd.Index(s.index)
    if transform == "sum":
        out, prev = [], None
        for m in ms:
            lo = idx.searchsorted(prev, side="right") if prev else 0
            hi = idx.searchsorted(m, side="right")
            out.append(float(s.iloc[lo:hi].sum()) if hi > lo else np.nan)
            prev = m
        return pd.Series(out, index=ms, dtype=float)
    pos = idx.searchsorted(ms, side="right") - 1
    lvl = pd.Series([s.iloc[p] if p >= 0 else np.nan for p in pos],
                    index=ms, dtype=float)
    return lvl.pct_change(fill_method=None) if transform == "pct" else lvl.diff()


def monthly_returns(close_wide: pd.DataFrame, month_ends: Iterable[date]) -> pd.DataFrame:
    """Month-end to month-end simple returns from an adjusted-close wide frame
    (index dates, columns ISINs). A name without a close at a month-end has no
    return for that month or the next -- no forward fill across a gap."""
    ms = [m for m in month_ends if m in close_wide.index]
    lv = close_wide.loc[ms]
    return lv / lv.shift(1) - 1.0


def rolling_betas(returns: pd.DataFrame, factor: pd.Series, window: int,
                  min_obs: int) -> pd.DataFrame:
    """OLS slope of each column on `factor` over the trailing `window` months,
    pairwise-complete. NaN where fewer than `min_obs` pairs exist."""
    f = factor.reindex(returns.index).astype(float)
    y = returns.astype(float)
    ok = y.notna() & f.notna().to_numpy()[:, None]
    x = pd.DataFrame(np.where(ok, f.to_numpy()[:, None], 0.0),
                     index=y.index, columns=y.columns)
    yv = y.where(ok, 0.0)
    r = lambda d: d.rolling(window, min_periods=1).sum()
    n = r(ok.astype(float))
    sx, sy, sxy, sxx = r(x), r(yv), r(x * yv), r(x * x)
    var = sxx - sx * sx / n.replace(0, np.nan)
    cov = sxy - sx * sy / n.replace(0, np.nan)
    b = cov / var.where(var.abs() > 1e-18)
    return b.where(n >= min_obs)


def portfolio_beta(values: Mapping[str, float], betas: pd.Series,
                   index_beta: float) -> float:
    """Value-weighted beta of a set of holdings. A name with no beta (fewer
    than the minimum observations) counts as index-like (§3)."""
    tot = float(sum(v for v in values.values() if v > 0))
    if tot <= 0:
        return float("nan")
    acc = 0.0
    for isin, v in values.items():
        if v <= 0:
            continue
        b = betas.get(isin, np.nan)
        acc += v * (index_beta if b is None or pd.isna(b) else float(b))
    return acc / tot


def breaches(values: Mapping[str, float], betas_by_factor: Dict[str, pd.Series],
             index_betas: Dict[str, float], multiple: float) -> Dict[str, dict]:
    """Factors on which |beta_portfolio| > multiple * |beta_index| (§4).

    A factor whose index beta is undefined is skipped: with no index edge
    there is no cap to breach (§6: VIX before its first 24 months).
    """
    out = {}
    for f, bi in index_betas.items():
        if bi is None or pd.isna(bi):
            continue
        bp = portfolio_beta(values, betas_by_factor[f], bi)
        cap = multiple * abs(bi)
        if abs(bp) > cap:
            out[f] = {"portfolio": bp, "index": bi, "cap": cap}
    return out
