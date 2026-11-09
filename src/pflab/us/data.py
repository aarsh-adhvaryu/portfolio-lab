"""US daily bars from the repo's own collection (`data/us/raw/{SYMBOL}.parquet`, written by tools/backfill_us.py and data/us_prices.py; Yahoo's chart data, not an official source).

Columns: date (the exchange's local date), open, high, low, close (split-adjusted), adj_close (dividends in too), volume, dividend (USD per share on the ex-date). The sub-book fills at the
open and marks at the close; it never reads a bar dated after the day it is processing.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd


def _root(root) -> Path:
    if root is None:
        from pflab.data import data_dir
        root = data_dir()
    return Path(root)


def bars(symbol: str, root=None) -> Optional[pd.DataFrame]:
    p = _root(root) / "us" / "raw" / f"{symbol.upper()}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df = df.assign(date=pd.to_datetime(df["date"]).dt.date)
    for c in ("open", "close", "dividend"):
        if c not in df.columns:
            df[c] = 0.0
    return df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)


def load(symbols: Iterable[str], root=None) -> Dict[str, pd.DataFrame]:
    out = {}
    for s in symbols:
        b = bars(s, root)
        if b is not None and len(b):
            out[s.upper()] = b
    return out


def bar_on(df: Optional[pd.DataFrame], day: date) -> Optional[dict]:
    """The bar dated exactly `day`, or None."""
    if df is None or df.empty:
        return None
    r = df[df["date"] == day]
    if r.empty:
        return None
    x = r.iloc[-1]
    return {"date": day, "open": float(x["open"]) if pd.notna(x["open"]) and x["open"] > 0 else float(x["close"]), "close": float(x["close"]),
            "dividend": float(x["dividend"]) if pd.notna(x["dividend"]) else 0.0}


def last_on_or_before(df: Optional[pd.DataFrame], day: date) -> Optional[dict]:
    """The latest bar on or before `day` (for a mark when a name has no bar that day)."""
    if df is None or df.empty:
        return None
    r = df[df["date"] <= day]
    return None if r.empty else bar_on(df, r.iloc[-1]["date"])
