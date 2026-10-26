"""Technicals for one stock (S54c): a description of its price, never a signal (PLAN A9).

Standard definitions: simple moving averages of the close; RSI(14) and ATR(14) with Wilder's smoothing (alpha 1/14);
true range = max(high - low, |high - previous close|, |low - previous close|); the 52-week range over 250 sessions;
volume against its 20-session average.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up, dn = d.clip(lower=0), (-d).clip(lower=0)
    au = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    ad = dn.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(ad != 0, 100.0)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    pc = close.shift(1)
    tr = pd.concat([high - low, (high - pc).abs(), (low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def summary(df: pd.DataFrame) -> dict:
    """`df`: date, open, high, low, close, volume (oldest first). Last values plus the series for a chart."""
    d = df.dropna(subset=["close"]).reset_index(drop=True)
    if d.empty:
        return {"sessions": 0}
    c = d["close"].astype(float)
    ma50, ma200 = c.rolling(50).mean(), c.rolling(200).mean()
    r = rsi(c)
    a = atr(d["high"].astype(float), d["low"].astype(float), c) if {"high", "low"} <= set(d) else pd.Series(np.nan, index=c.index)
    y = c.iloc[-250:]
    v = d["volume"].astype(float) if "volume" in d else pd.Series(np.nan, index=c.index)
    v20 = v.rolling(20).mean()
    last = lambda s: (float(s.iloc[-1]) if len(s) and np.isfinite(s.iloc[-1]) else None)
    tail = d.iloc[-250:]
    return {"sessions": int(len(d)), "close": last(c), "ma50": last(ma50), "ma200": last(ma200), "rsi14": last(r),
            "atr14": last(a), "high52": float(y.max()), "low52": float(y.min()),
            "volume_ratio": (last(v) / last(v20)) if last(v) and last(v20) else None,
            "chart": {"dates": [str(x)[:10] for x in tail["date"]], "close": [float(x) for x in c.iloc[-250:]],
                      "ma50": [None if not np.isfinite(x) else float(x) for x in ma50.iloc[-250:]],
                      "ma200": [None if not np.isfinite(x) else float(x) for x in ma200.iloc[-250:]]}}


def ohlcv(root, isin: str, start, end) -> pd.DataFrame:
    """The stock's NSE bhavcopy rows (EQ, BE, BZ) between two dates."""
    from pflab import _duck
    from pflab.data.bhavcopy import bhav_files
    files = bhav_files(root, start, end)
    if not files:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    rel = f"read_parquet({files!r}, union_by_name=true)"
    return _duck.sql(f'SELECT date, first("open") AS "open", max(high) AS high, min(low) AS low, last("close") AS "close", '
                      f'sum(volume) AS volume FROM {rel} WHERE isin = \'{isin}\' AND series IN (\'EQ\',\'BE\',\'BZ\') '
                      f"AND date BETWEEN DATE '{start}' AND DATE '{end}' GROUP BY date ORDER BY date").df()


def for_isin(root, isin: str, asof, days: int = 420) -> Optional[dict]:
    from datetime import timedelta
    df = ohlcv(root, isin, asof - timedelta(days=days), asof)
    return summary(df) if len(df) else None
