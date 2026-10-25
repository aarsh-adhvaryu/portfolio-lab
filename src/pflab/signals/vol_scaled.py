"""Volatility-scaled 6+12 momentum (charter E1c §3).

The Nifty 200 Momentum 30 fund's own score, as close to NSE's published
methodology as this panel allows.

§3 says the two ratios are "then averaged; standardised across the universe
(z-score)", and clipped at ±3 after standardising. NSE standardises each
window's ratio first and averages the two z-scores; averaging raw ratios
first lets whichever window has the larger dispersion dominate. The charter
settled this at the 2026-09-19 amendment: **the charter's order stands and
NSE's order is tested as S12, not adopted.** `order` selects between them; it
is a chartered sweep row, not a free parameter.

**Standardisation happens within the universe, at the decision date.** The
first implementation z-scored across every name in the panel with a score
(1,130 on 2015-12-31) and restricted to the 184-name universe afterwards, so
a name's score measured it against the whole market rather than against the
universe §3 names. That is why the universe only had 48 positive scores
that day, and why the first development sweep halted on a name whose
correctly standardised score was +0.462. The fix, declared in E1c §9
(2026-09-21), splits the work in two:

  * `vol_scaled_ratios` / `momentum_ratios` build the raw ingredients over
    the whole panel -- pure backward shifts and rolling windows, so building
    them once is lookahead-free;
  * `standardise` z-scores and clips one date's ingredients over whatever
    set it is handed, which the engine makes the eligible universe.
"""
from __future__ import annotations

from typing import List, Sequence

import numpy as np
import pandas as pd

from pflab.signals.momentum import momentum_panel

TRADING_DAYS = 252.0
ORDERS = ("average_then_z", "z_then_average")


def vol_scaled_ratios(adj_close: pd.DataFrame, windows=(126, 252),
                      skip: int = 21) -> List[pd.DataFrame]:
    """The raw §3 ingredients, one panel per window.

    For each window w: the return from t-w to t-skip (so the most recent month
    is skipped), divided by the annualised standard deviation of that name's
    daily returns over the SAME span. Nothing is standardised here.
    """
    if skip < 0:
        raise ValueError("skip must be >= 0")
    if any(w <= skip for w in windows):
        raise ValueError("every window must exceed skip")
    daily = adj_close.pct_change()
    out = []
    for w in windows:
        ret = adj_close.shift(skip) / adj_close.shift(w) - 1.0
        # the same span as the return: daily returns from t-w to t-skip
        vol = daily.shift(skip).rolling(w - skip, min_periods=w - skip).std()
        out.append(ret / (vol * np.sqrt(TRADING_DAYS)).where(vol > 0))
    return out


def momentum_ratios(adj_close: pd.DataFrame, lookback: int = 252,
                    skip: int = 21) -> List[pd.DataFrame]:
    """E1c §5 S6 as amended 2026-09-21: E1's raw 12-1 momentum as the single
    ingredient, which then passes through §3's own standardisation and clip,
    so S6 changes the signal and nothing else."""
    return [momentum_panel(adj_close, lookback=lookback, skip=skip)]


def _z(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=0)
    if not (sd > 0):
        return pd.Series(np.nan, index=s.index)
    return (s - s.mean()) / sd


def standardise(parts: Sequence[pd.Series], order: str = "average_then_z",
                clip: float = 3.0) -> pd.Series:
    """One date's score over the names in `parts` -- which is the universe.

    `parts` holds one Series per ingredient, already restricted to the set the
    score is to be standardised across. Only names with every ingredient are
    scored, so both orders see exactly the same names.
    """
    if order not in ORDERS:
        raise ValueError(f"unknown order={order!r}")
    if not parts:
        return pd.Series(dtype=float)
    # Positional keys: every ingredient's row is named after the same date,
    # so concatenating on the names would give two columns with one label.
    frame = pd.concat(list(parts), axis=1, keys=range(len(parts))).dropna()
    if frame.empty:
        return pd.Series(dtype=float)
    if order == "average_then_z":
        z = _z(frame.mean(axis=1))
    else:
        z = pd.concat([_z(frame.iloc[:, k]) for k in range(frame.shape[1])],
                      axis=1).mean(axis=1)
    return z.clip(lower=-clip, upper=clip).dropna()


def vol_scaled_score_panel(adj_close: pd.DataFrame, windows=(126, 252),
                           skip: int = 21, clip: float = 3.0,
                           order: str = "average_then_z") -> pd.DataFrame:
    """Every date's score, standardised across ALL columns of `adj_close`.

    Correct only when `adj_close` already holds just the universe -- which is
    how the tests use it. The engine does not call this: it standardises
    within the eligible universe at each decision date via `standardise`.
    """
    if order not in ORDERS:
        raise ValueError(f"unknown order={order!r}")
    parts = vol_scaled_ratios(adj_close, windows=windows, skip=skip)
    rows = {}
    for d in adj_close.index:
        rows[d] = standardise([p.loc[d] for p in parts], order=order, clip=clip)
    return pd.DataFrame.from_dict(rows, orient="index").reindex(
        index=adj_close.index, columns=adj_close.columns)
