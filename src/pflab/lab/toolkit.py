"""The lab's toolkit: the pure functions a policy may call (S80 phase 2). SELF-CONTAINED on purpose: numpy and pandas only, no pflab imports, so the very same file is copied
into the Docker sandbox next to the harness and runs the same inside and outside it. A policy gets it as `from toolkit import ...`.

Prices are a DataFrame of adjusted closes (rows = dates up to the decision day, columns = security keys). Weights are dicts {key: fraction of the book}; whatever the weights
leave under 1 stays in cash. Every function is point in time: it reads only the rows it is handed.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def returns(prices: pd.DataFrame, window: int = 250) -> pd.DataFrame:
    """Simple daily returns of the last `window` rows (gaps are zero returns)."""
    return prices.pct_change(fill_method=None).iloc[1:].tail(window).fillna(0.0)


def volatility(prices: pd.DataFrame, window: int = 250, floor: float = 0.05, fallback: float = 0.30) -> Dict[str, float]:
    """Annual volatility per column over the last `window` sessions; `fallback` for a name with under 60 returns; never below `floor`."""
    r = prices.pct_change(fill_method=None).iloc[1:].tail(window)
    out = {}
    for k in prices.columns:
        x = r[k].dropna()
        out[k] = max(float(x.std() * math.sqrt(TRADING_DAYS)), floor) if len(x) >= 60 else fallback
    return out


def momentum(prices: pd.DataFrame, lookback: int = 252, skip: int = 21) -> Dict[str, float]:
    """Return over `lookback` sessions ending `skip` sessions ago (the usual 12-1 momentum); names without enough history are left out."""
    if len(prices) <= lookback:
        return {}
    a, b = prices.iloc[-1 - skip], prices.iloc[-1 - lookback]
    m = (a / b - 1.0).replace([np.inf, -np.inf], np.nan).dropna()
    return {k: float(v) for k, v in m.items()}


def reversion(prices: pd.DataFrame, window: int = 21) -> Dict[str, float]:
    """Minus the return of the last `window` sessions (a short-term reversal score: recent losers score high)."""
    if len(prices) <= window:
        return {}
    m = (prices.iloc[-1] / prices.iloc[-1 - window] - 1.0).replace([np.inf, -np.inf], np.nan).dropna()
    return {k: -float(v) for k, v in m.items()}


def rank_top(scores: Dict[str, float], n: int, floor: Optional[float] = None) -> List[str]:
    """The `n` highest-scoring keys (ties by key), optionally only those above `floor`."""
    items = [(k, v) for k, v in scores.items() if v == v and (floor is None or v > floor)]
    items.sort(key=lambda kv: (-kv[1], kv[0]))
    return [k for k, _ in items[:n]]


def inverse_vol(keys: Iterable[str], vol: Dict[str, float], budget: float = 1.0) -> Dict[str, float]:
    """Weights proportional to 1/volatility, summing to `budget`."""
    keys = list(keys)
    if not keys:
        return {}
    inv = {k: 1.0 / max(vol.get(k, 0.30), 0.05) for k in keys}
    s = sum(inv.values())
    return {k: budget * v / s for k, v in inv.items()}


def equal_weight(keys: Iterable[str], budget: float = 1.0) -> Dict[str, float]:
    keys = list(keys)
    return {k: budget / len(keys) for k in keys} if keys else {}


def cap_weights(w: Dict[str, float], caps: Dict[str, float], default_cap: float = 0.10) -> Dict[str, float]:
    """Cut each weight to its cap; the excess is NOT redistributed (it stays in cash). Use `cap_and_fill` to hand it to the names with room."""
    return {k: min(v, caps.get(k, default_cap)) for k, v in w.items() if v > 0}


def cap_and_fill(w: Dict[str, float], caps: Dict[str, float], default_cap: float = 0.10, budget: Optional[float] = None) -> Dict[str, float]:
    """Cut to the caps and hand the excess to the names that still have room (in proportion to their weight), until the budget is placed or no one has room."""
    budget = sum(w.values()) if budget is None else budget
    out = {k: 0.0 for k in w}
    live = {k: v for k, v in w.items() if v > 0}
    left = budget
    while live and left > 1e-12:
        tot = sum(live.values())
        over = {k: caps.get(k, default_cap) - out[k] for k, v in live.items() if out[k] + left * v / tot > caps.get(k, default_cap) + 1e-12}
        if not over:
            for k, v in live.items():
                out[k] += left * v / tot
            left = 0.0
            break
        for k, room in over.items():
            out[k] += room
            left -= room
            live.pop(k)
    return {k: v for k, v in out.items() if v > 1e-12}


def scale(w: Dict[str, float], factor: float) -> Dict[str, float]:
    """Every weight times `factor` (the rest goes to cash)."""
    return {k: v * factor for k, v in w.items()}


def drawdown_from_high(series: pd.Series, window: int = 252) -> float:
    """How far the last value is below the highest of the last `window` values (a negative fraction, 0 at the high)."""
    s = series.dropna().tail(window)
    return float(s.iloc[-1] / s.max() - 1.0) if len(s) else 0.0


def below_average(series: pd.Series, window: int = 200) -> bool:
    """True when the last value is under its `window`-session average."""
    s = series.dropna()
    return bool(len(s) >= window and s.iloc[-1] < s.tail(window).mean())


def fall_gauge(index_prices: pd.Series, drawdown: float = 0.10, window: int = 200) -> bool:
    """The baseline's fall gauge: the index is `drawdown` or more below its 252-session high AND below its `window`-session average."""
    return drawdown_from_high(index_prices) <= -drawdown and below_average(index_prices, window)


def trend_tilt(prices: pd.Series, horizon: int = 20) -> float:
    """A one-number view of one series: the sign-and-size of its trend over `horizon` sessions, scaled by its own volatility, clipped to [-1, 1]."""
    s = prices.dropna()
    if len(s) < max(horizon * 3, 80):
        return 0.0
    r = s.pct_change().dropna()
    sd = float(r.tail(250).std())
    if sd <= 0:
        return 0.0
    z = float(s.iloc[-1] / s.iloc[-1 - horizon] - 1.0) / (sd * math.sqrt(horizon))
    return float(max(-1.0, min(1.0, z / 3.0)))


def tilt_weights(base: Dict[str, float], tilts: Dict[str, float], strength: float = 0.5) -> Dict[str, float]:
    """Multiply each base weight by (1 + strength * tilt) with tilt in [-1, 1], then renormalise to the base's total."""
    raw = {k: max(0.0, v * (1.0 + strength * max(-1.0, min(1.0, tilts.get(k, 0.0))))) for k, v in base.items()}
    s, t = sum(raw.values()), sum(base.values())
    return {k: t * v / s for k, v in raw.items()} if s > 0 else dict(base)


TOOLS = ("returns", "volatility", "momentum", "reversion", "rank_top", "inverse_vol", "equal_weight", "cap_weights", "cap_and_fill", "scale", "drawdown_from_high", "below_average",
         "fall_gauge", "trend_tilt", "tilt_weights")
