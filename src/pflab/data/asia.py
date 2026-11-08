"""Asian peer indices as one aligned panel (S79b agent D).

The series are collected by `data.global_markets` (Yahoo chart API, files `data/global/{KEY}.parquet`); this module only reads
and aligns them: Kospi (^KS11), Taiex (^TWII), Nikkei 225 (^N225), Hang Seng (^HSI), Shanghai Composite (000001.SS), ASX 200.

Point-in-time: all of these close BEFORE the NSE does (Tokyo 15:30 IST, Seoul 12:00, Taipei 11:00, Hong Kong 13:30,
Shanghai 12:30, Sydney 10:30), so the close dated M is known at India's close of M and a decision at India's day-M close may
read it. Dates are each exchange's LOCAL trading date, which equals the IST date for all of them.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from pflab.data import data_dir

PEERS = {"KR_KOSPI": "Kospi", "TW_TAIEX": "Taiex", "JP_NIKKEI225": "Nikkei 225", "HK_HANGSENG": "Hang Seng",
         "CN_SHANGHAI": "Shanghai Composite", "AU_ASX200": "ASX 200"}


def closes(root: Optional[Path] = None, keys: Optional[list] = None, upto: Optional[date] = None) -> pd.DataFrame:
    """Wide frame (index = date, columns = keys) of closes; a missing file is left out. `upto` truncates (point-in-time)."""
    root = Path(root or data_dir())
    cols = {}
    for k in keys or PEERS:
        p = root / "global" / f"{k}.parquet"
        if p.exists():
            d = pd.read_parquet(p, columns=["date", "close"])
            d["date"] = pd.to_datetime(d["date"])
            cols[k] = d.drop_duplicates("date", keep="last").set_index("date")["close"]
    df = pd.DataFrame(cols).sort_index()
    if upto is not None:
        df = df[df.index <= pd.Timestamp(upto)]
    return df


def returns(root: Optional[Path] = None, keys: Optional[list] = None, upto: Optional[date] = None) -> pd.DataFrame:
    """Daily simple returns on each market's own sessions (a holiday carries nothing: the next session's return spans it)."""
    c = closes(root, keys, upto)
    return pd.DataFrame({k: c[k].dropna().pct_change() for k in c.columns}).sort_index()


def window_change(start: date, end: date, root: Optional[Path] = None) -> dict:
    """Close-to-close change in percent from the last close on or before `start` to the last close on or before `end`."""
    c = closes(root, upto=end)
    out = {}
    for k in c.columns:
        s = c[k].dropna()
        a, b = s[s.index <= pd.Timestamp(start)], s
        if len(a) and len(b):
            out[k] = {"from": str(a.index[-1].date()), "to": str(b.index[-1].date()), "pct": round(float(b.iloc[-1] / a.iloc[-1] - 1) * 100, 2)}
    return out
