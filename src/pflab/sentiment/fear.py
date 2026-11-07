"""Priced fear (S79b item 15b, spec (b)): the volatility index of the market (India VIX; US VIX), the Nifty put-call ratio, the option skew (implied volatility at 90% of
spot minus at 110%) and, per theme, the realised volatility of the theme's primary price proxy. Every series is the market's own published number; code only aligns
and z-scores them (point in time, the day never in its own history)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from pflab.sentiment import read_series, stale_align


def vix(root, market: str) -> Optional[pd.Series]:
    root = Path(root)
    cands = {"IN": [("indices/INDIA_VIX.parquet", ("close",))],
             "US": [("global/US_VIX.parquet", ("close", "value")), ("macro/US_VIX.parquet", ("value", "close"))]}.get(market, [])
    for f, cols in cands:
        if (root / f).exists():
            s = read_series(root / f, cols)
            if s is not None:
                return s
    return None


def _derived(root, name: str, col: str, symbol: Optional[str] = "NIFTY") -> Optional[pd.Series]:
    p = Path(root) / "derived" / name
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
    except Exception:
        return None
    if symbol and "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    if col not in df.columns or df.empty:
        return None
    s = pd.Series(pd.to_numeric(df[col], errors="coerce").to_numpy(float), index=pd.to_datetime(df["date"])).dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s if len(s) else None


def pcr(root, market: str) -> Optional[pd.Series]:
    """Open-interest put-call ratio of the Nifty options (derived/fo_index.parquet, from the NSE F&O bhavcopy; 2024 onward). IN only."""
    return _derived(root, "fo_index.parquet", "pcr") if market == "IN" else None


def skew(root, market: str) -> Optional[pd.Series]:
    """Option skew of the nearest usable Nifty expiry (derived/implied_probs.parquet `skew_90_110`; 2024 onward). IN only."""
    return _derived(root, "implied_probs.parquet", "skew_90_110", symbol=None) if market == "IN" else None


def realised_vol(level: pd.Series, window: int = 20) -> pd.Series:
    """Annualised standard deviation of the proxy's daily log changes over `window` sessions ending on each date (uses only rows <= the date)."""
    lv = level.astype(float)
    r = np.log(lv.where(lv > 0)).diff()
    return (r.rolling(window, min_periods=max(5, window // 2)).std() * np.sqrt(252.0)).dropna()


def fear_frame(root, market: str, index: pd.DatetimeIndex, max_age_days: int = 4) -> pd.DataFrame:
    """Columns fear_vix, fear_pcr, fear_skew on `index` (each NaN where the market has no such series or the last print is older than max_age_days)."""
    out = pd.DataFrame(index=pd.DatetimeIndex(index))
    for col, s in (("fear_vix", vix(root, market)), ("fear_pcr", pcr(root, market)), ("fear_skew", skew(root, market))):
        out[col] = stale_align(s, out.index, max_age_days) if s is not None else np.nan
    return out


def native(root, market: str) -> dict:
    """{component: native series} for the fear components that exist on this PC."""
    out = {"fear_vix": vix(root, market), "fear_pcr": pcr(root, market), "fear_skew": skew(root, market)}
    return {k: v for k, v in out.items() if v is not None and len(v)}
