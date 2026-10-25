"""Was a fall the market's or the company's? (PLAN S20)

For a share that fell, split the move with the market model of `event_reaction`:

    expected = alpha + beta * r_market  (+ any macro-shock term the caller supplies)
    residual = r - expected,   z = residual / (sigma * sqrt(k))

and label it from fixed thresholds, set by reasoning before looking at any fall and not tuned:

    fall          the k-session return is at or below FALL (-5%)
    market down   the market's k-session return is at or below MARKET (-2%)
    specific      z at or below Z_SPECIFIC (-3): the part the market does not explain is far outside this
                  name's own usual noise

    not a fall                     return above FALL
    market-wide                    market down and z above Z_SPECIFIC (the market explains it)
    company-specific               market not down and z at or below Z_SPECIFIC
    mixed                          market down and z at or below Z_SPECIFIC (it fell with the market and much more)
    normal volatility              none of the above (a big move for a volatile name, market not down)

A label is a classification of what already happened, with its numbers; it is not a reason. Whether
a filing explains the residual is for the filings monitor and for the investor to read.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from pflab.monitor import event_reaction as er

FALL = -0.05
MARKET = -0.02
Z_SPECIFIC = -3.0


@dataclass(frozen=True)
class FallResult:
    isin: str
    start: date
    sessions: int
    ret: float
    market_ret: float
    beta: float
    expected: float
    residual: float
    z: float
    label: str
    n_fit: int


def _cum(r: pd.Series, start: date, k: int) -> Optional[float]:
    r = r.dropna()
    r.index = pd.to_datetime(r.index)
    pos = r.index.searchsorted(pd.Timestamp(start), side="left")
    w = r.iloc[pos: pos + k]
    if len(w) < k:
        return None
    return float(np.expm1(np.log1p(w).sum()))


def classify(isin: str, ret_i: pd.Series, ret_m: pd.Series, start: date, sessions: int = 1, *,
             extra_expected: float = 0.0, fall: float = FALL, market: float = MARKET,
             z_specific: float = Z_SPECIFIC) -> Optional[FallResult]:
    """Label the `sessions`-day move starting on `start`. None when there is no usable fit (too little
    history) or the series does not cover the window."""
    mm = er.fit(ret_i, ret_m, start)
    if mm is None or mm.sigma <= 0:
        return None
    r, rm = _cum(ret_i, start, sessions), _cum(ret_m, start, sessions)
    if r is None or rm is None:
        return None
    expected = sessions * mm.alpha + mm.beta * rm + extra_expected       # alpha per session, beta on the window
    resid = r - expected
    z = resid / (mm.sigma * np.sqrt(sessions))
    if r > fall:
        label = "not a fall"
    elif rm <= market and z <= z_specific:
        label = "mixed"
    elif rm <= market:
        label = "market-wide"
    elif z <= z_specific:
        label = "company-specific"
    else:
        label = "normal volatility"
    return FallResult(isin, start, sessions, r, rm, mm.beta, expected, resid, float(z), label, mm.n)


def scan(isin: str, ret_i: pd.Series, ret_m: pd.Series, sessions: int = 1, **kw) -> pd.DataFrame:
    """Every window in the series that is a fall, with its label. One row per start session."""
    out = []
    for d in pd.to_datetime(ret_i.dropna().index):
        res = classify(isin, ret_i, ret_m, d.date(), sessions, **kw)
        if res is not None and res.label != "not a fall":
            out.append(res.__dict__)
    return pd.DataFrame(out)
