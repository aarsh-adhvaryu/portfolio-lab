"""The measurable things a storyline's signals are tied to (S80 phase 3): named series from the collectors' own files, read point in time.

POINT IN TIME. A value for the India close of day D may use only what was known at that close. A series that settles after India's close (the US markets, commodity futures, the foreign
flow figures NSE publishes in the evening) is lagged: its row dated D is not used until D+1. Asian markets that close before India's do not lag. `LAG` is in sessions of the series itself.

Transforms (all computed from rows dated <= the as-of day minus the lag):
    level               the last value
    ret:N               the N-row return (a ratio minus 1)
    sum:N               the sum of the last N rows (for a flow)
    relret:N:OTHER      ret:N of this series minus ret:N of OTHER (how it did against another)
"""
from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Tuple

import pandas as pd

# key -> (folder under the data dir, file stem, value column, lag in rows, what it is)
SERIES: Dict[str, Tuple[str, str, str, int, str]] = {
    "NIFTY500_TRI": ("indices", "NIFTY500_TRI", "close", 0, "the Nifty 500 total-return index (India)"),
    "FII_NET_CR": ("flows", "FII_DII_CASH", "fii_net_cr", 1, "foreign institutions' net cash-market buying, Rs crore a day (published in the evening: lagged a day)"),
    "DII_NET_CR": ("flows", "FII_DII_CASH", "dii_net_cr", 1, "domestic institutions' net cash-market buying, Rs crore a day"),
    "KOSPI": ("global", "KR_KOSPI", "close", 0, "South Korea's KOSPI (AI-chip heavy)"),
    "TAIEX": ("global", "TW_TAIEX", "close", 0, "Taiwan's TAIEX (AI-chip heavy)"),
    "HANGSENG": ("global", "HK_HANGSENG", "close", 0, "Hong Kong's Hang Seng"),
    "NIKKEI": ("global", "JP_NIKKEI225", "close", 0, "Japan's Nikkei 225"),
    "SOX": ("global", "US_SOX", "close", 1, "the US chip index (closes after India: lagged a day)"),
    "NASDAQ": ("global", "US_NASDAQ", "close", 1, "the Nasdaq (lagged a day)"),
    "SP500": ("global", "US_SP500", "close", 1, "the S&P 500 (lagged a day)"),
    "BRENT": ("global", "BRENT_FUT", "close", 1, "Brent crude futures (settle after India's close: lagged a day)"),
    "GOLD": ("global", "GOLD", "close", 1, "gold futures (lagged a day)"),
    "USDINR": ("global", "FX_USDINR", "close", 1, "the rupee per dollar (a higher number is a weaker rupee; lagged a day)"),
    "DOLLAR_INDEX": ("global", "DOLLAR_INDEX", "close", 1, "the dollar index (lagged a day)"),
    "US10Y": ("global", "US_10Y_YIELD", "close", 1, "the US 10-year yield (lagged a day)"),
}


def describe() -> Dict[str, str]:
    return {k: v[4] for k, v in SERIES.items()}


def _root(root: Optional[Path]) -> Path:
    from pflab.data import data_dir
    return Path(root) if root else data_dir()


@lru_cache(maxsize=64)
def _load(path: str, col: str, mtime: float) -> pd.Series:
    df = pd.read_parquet(path)
    s = pd.Series(df[col].astype(float).to_numpy(), index=pd.to_datetime(df["date"]))
    return s[~s.index.duplicated(keep="last")].sort_index().dropna()


def load(key: str, root: Optional[Path] = None) -> Optional[pd.Series]:
    if key not in SERIES:
        return None
    folder, stem, col, _, _ = SERIES[key]
    p = _root(root) / folder / f"{stem}.parquet"
    if not p.exists():
        return None
    return _load(p.as_posix(), col, p.stat().st_mtime)


def known(key: str, asof: date, root: Optional[Path] = None) -> Optional[pd.Series]:
    """The rows of `key` usable for the India close of `asof` (dated <= asof, and `lag` rows fewer where the series settles after India's close)."""
    s = load(key, root)
    if s is None:
        return None
    s = s[s.index <= pd.Timestamp(asof)]
    lag = SERIES[key][3]
    if lag and len(s):
        s = s.iloc[:-lag] if s.index[-1] >= pd.Timestamp(asof) else s            # the row dated `asof` itself is not known yet; an earlier last row already is
    return s


def value(key: str, transform: str, asof: date, root: Optional[Path] = None) -> Optional[float]:
    """One number, or None when the data does not reach (a signal with no value counts for nothing)."""
    s = known(key, asof, root)
    if s is None or not len(s):
        return None
    kind, *args = transform.split(":")
    try:
        if kind == "level":
            return float(s.iloc[-1])
        n = int(args[0]) if args else 1
        if kind == "sum":
            return float(s.tail(n).sum()) if len(s) >= n else None
        if kind == "ret":
            return float(s.iloc[-1] / s.iloc[-1 - n] - 1.0) if len(s) > n else None
        if kind == "relret":
            o = known(args[1], asof, root)
            if o is None or len(s) <= n or len(o) <= n:
                return None
            return float(s.iloc[-1] / s.iloc[-1 - n] - 1.0) - float(o.iloc[-1] / o.iloc[-1 - n] - 1.0)
    except (IndexError, ValueError, ZeroDivisionError):
        return None
    return None


def level_on(key: str, day: date, root: Optional[Path] = None) -> Optional[float]:
    """The series' own value on `day` (or the last row before it), for scoring a prediction AFTER the fact (no lag: the outcome is what happened)."""
    s = load(key, root)
    if s is None:
        return None
    s = s[s.index <= pd.Timestamp(day)]
    return float(s.iloc[-1]) if len(s) else None
