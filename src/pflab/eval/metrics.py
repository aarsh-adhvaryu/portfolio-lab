"""Performance metrics for SIP portfolios.

With monthly cash flows the NAV of the account is not a return series.
`unitized_nav` converts (value, external flows) into a unit price so that
CAGR/drawdown/Sharpe are time-weighted and comparable across strategy and
benchmark. `xirr` gives the investor's money-weighted return.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Sequence, Tuple

import numpy as np
import pandas as pd


def unitized_nav(values: pd.Series, flows: pd.Series, base: float = 100.0) -> pd.Series:
    """values: end-of-day total portfolio value (equity + cash), indexed by date.
    flows: external cash flow on each date (deposit +, withdrawal −), assumed
    to arrive at the START of that day, i.e. before that day's return.
    Days before the first non-zero value are dropped."""
    values = values.astype(float)
    flows = flows.reindex(values.index).fillna(0.0).astype(float)
    nz = values.ne(0) | flows.ne(0)
    if not nz.any():
        raise ValueError("no capital")
    first = nz.idxmax()
    values, flows = values.loc[first:], flows.loc[first:]
    nav = pd.Series(index=values.index, dtype=float)
    units = values.iloc[0] / base
    if units <= 0:
        raise ValueError("first value must be positive")
    nav.iloc[0] = base
    for i in range(1, len(values)):
        f = flows.iloc[i]
        if f != 0:
            units += f / nav.iloc[i - 1]
        nav.iloc[i] = values.iloc[i] / units if units > 0 else np.nan
    return nav


def cagr(nav: pd.Series) -> float:
    nav = nav.dropna()
    d0, d1 = pd.Timestamp(nav.index[0]), pd.Timestamp(nav.index[-1])
    years = (d1 - d0).days / 365.25
    if years <= 0:
        raise ValueError("need more than one day")
    return float((nav.iloc[-1] / nav.iloc[0]) ** (1.0 / years) - 1.0)


def max_drawdown(nav: pd.Series) -> float:
    """Positive magnitude, e.g. 0.35 for a 35% peak-to-trough fall."""
    nav = nav.dropna()
    peak = nav.cummax()
    return float((1.0 - nav / peak).max())


def monthly_returns(nav: pd.Series) -> pd.Series:
    s = nav.dropna().copy()
    s.index = pd.to_datetime(s.index)
    return s.resample("ME").last().pct_change().dropna()


def sharpe(nav: pd.Series, rf_annual: float = 0.0) -> float:
    r = monthly_returns(nav) - rf_annual / 12.0
    if r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * np.sqrt(12))


def xirr(dates: Sequence[date], amounts: Sequence[float], lo: float = -0.99, hi: float = 10.0) -> float:
    """Money-weighted annual return. Negative amounts = money in, positive = out."""
    t0 = pd.Timestamp(dates[0])
    t = np.array([(pd.Timestamp(d) - t0).days / 365.0 for d in dates])
    a = np.array(amounts, dtype=float)
    if not (a < 0).any() or not (a > 0).any():
        raise ValueError("need both inflows and outflows")

    def npv(r):
        return float(np.sum(a / (1.0 + r) ** t))

    flo, fhi = npv(lo), npv(hi)
    if flo * fhi > 0:
        raise ValueError("xirr bracket failed")
    for _ in range(200):
        mid = (lo + hi) / 2
        fm = npv(mid)
        if abs(fm) < 1e-9:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def stationary_bootstrap_ci(x: Iterable[float], block: int = 6, n: int = 2000,
                            alpha: float = 0.10, seed: int = 0) -> Tuple[float, float]:
    """Politis–Romano stationary block bootstrap CI for the mean of `x`.
    Expected block length = `block`. Returns (lo, hi) at 1-alpha."""
    x = np.asarray(list(x), dtype=float)
    T = len(x)
    if T < 2:
        raise ValueError("need at least 2 observations")
    rng = np.random.default_rng(seed)
    p = 1.0 / block
    means = np.empty(n)
    for b in range(n):
        idx = np.empty(T, dtype=int)
        idx[0] = rng.integers(T)
        for i in range(1, T):
            idx[i] = rng.integers(T) if rng.random() < p else (idx[i - 1] + 1) % T
        means[b] = x[idx].mean()
    return float(np.quantile(means, alpha / 2)), float(np.quantile(means, 1 - alpha / 2))
