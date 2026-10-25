"""E3-R §3-§4: the three regime signals and the gear they select.

    T  Nifty 50 month-end close below its 10-month average (E1 §6, as is)
    V  realised daily volatility over the last 126 sessions of an
       equal-weight basket of the current top 25 by the stack's score,
       above its own trailing 36-month 80th percentile
    B  share of eligible names closing above their own 200-session average
       below 40%

Every series is keyed by the engine's month-end sessions and uses only rows
dated on or before that session.

**Undefined is kept explicit** (E3-R §11 (a), 2026-09-27): a signal that
cannot yet be computed is `None`, never `False`, and `gear_at` counts it as
not firing. That is the investor's decision; recording `None` rather than folding
it into `False` is what lets the manifest list the months it applied to.

Readings declared here, for the lock to confirm (E3-R readiness addendum):

* V's percentile is taken over the **36 previous month-end values**, the
  current one excluded, and needs all 36; `numpy.percentile`'s linear
  interpolation.
* V's basket is rebalanced to equal weight daily (the mean of its names'
  daily returns), with the membership fixed at M, and its volatility is the
  sample standard deviation of those 126 daily returns.
* B's "own 200-session average" is over the name's own last 200 trading
  rows, so a gap in its trading does not shorten the window.

Nothing here picks a parameter; the engine passes the charter's numbers.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Iterable, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

CAUTIOUS, NORMAL, HIGH = "cautious", "normal", "high"


def basket_vol(adj_w: pd.DataFrame, m: date, names: Sequence[str],
               window: int) -> Optional[float]:
    """Sample std of the equal-weight daily return of `names` over the last
    `window` sessions ending at `m`. None if fewer than `window` returns."""
    cols = [n for n in names if n in adj_w.columns]
    if not cols or m not in adj_w.index:
        return None
    pos = adj_w.index.get_loc(m)
    if pos < window:
        return None
    px = adj_w.iloc[pos - window: pos + 1][cols]
    r = (px / px.shift(1) - 1.0).iloc[1:]
    basket = r.mean(axis=1, skipna=True).dropna()
    if len(basket) < window:
        return None
    return float(basket.std(ddof=1))


def own_sma(panel: pd.DataFrame, window: int, field: str = "adj_close") -> pd.DataFrame:
    """Each name's mean of its own last `window` rows, as a wide frame
    (sessions x ISIN), forward-filled across its non-trading sessions."""
    d = panel[["date", "isin", field]].dropna().sort_values(["isin", "date"],
                                                           kind="mergesort")
    g = d.groupby("isin", sort=False)[field]
    cs = g.cumsum()
    lag = cs.groupby(d["isin"], sort=False).shift(window)
    n = d.groupby("isin", sort=False).cumcount() + 1
    sma = ((cs - lag.fillna(0.0)) / window).where(n >= window)
    d = d.assign(_sma=sma)
    return d.pivot_table(index="date", columns="isin", values="_sma",
                         aggfunc="last", dropna=False).sort_index().ffill()


def breadth(close_last: pd.Series, sma_last: pd.Series, names: Iterable[str]) -> Optional[float]:
    """Share of `names` whose last close is above their own average. Names
    without an average yet are left out; None if none has one."""
    names = [n for n in names if n in close_last.index and n in sma_last.index]
    c, s = close_last.reindex(names), sma_last.reindex(names)
    ok = c.notna() & s.notna()
    if not ok.any():
        return None
    return float((c[ok] > s[ok]).mean())


def above_trailing_percentile(values: Mapping[date, Optional[float]], q: float,
                              lookback: int) -> Dict[date, Optional[bool]]:
    """At each date: value > q-th percentile of the previous `lookback`
    values (current excluded). None where the value or any of the previous
    `lookback` is missing."""
    ds = sorted(values)
    out: Dict[date, Optional[bool]] = {}
    for i, d in enumerate(ds):
        v = values[d]
        prev = [values[x] for x in ds[max(0, i - lookback): i]]
        if v is None or len(prev) < lookback or any(p is None for p in prev):
            out[d] = None
            continue
        out[d] = bool(v > np.percentile(np.asarray(prev, dtype=float), q * 100.0))
    return out


def below(values: Mapping[date, Optional[float]], level: float) -> Dict[date, Optional[bool]]:
    return {d: (None if v is None else bool(v < level)) for d, v in values.items()}


def fires(x: Optional[bool]) -> bool:
    """E3-R §11 (a): an undefined signal counts as not firing."""
    return bool(x) if x is not None else False


def cautious_at(t: Optional[bool], v: Optional[bool], b: Optional[bool],
                trigger: str = "V_or_B") -> bool:
    """§4's cautious condition, T and (V or B); S4 is 'V', S5 is 'B'."""
    if trigger == "V_or_B":
        other = fires(v) or fires(b)
    elif trigger == "V":
        other = fires(v)
    elif trigger == "B":
        other = fires(b)
    else:
        raise ValueError(f"unknown gears.trigger {trigger!r}")
    return fires(t) and other


def gear_path(cautious: Sequence[bool], high_gear: bool = True,
              min_cautious_run: int = 2) -> List[str]:
    """One gear per month-end, in order.

    High is the first month-end that is not cautious after at least
    `min_cautious_run` consecutive cautious month-ends (§4); with
    `high_gear=False` (S6) that month is normal.
    """
    out, run = [], 0
    for c in cautious:
        if c:
            out.append(CAUTIOUS)
            run += 1
            continue
        out.append(HIGH if (high_gear and run >= min_cautious_run) else NORMAL)
        run = 0
    return out
