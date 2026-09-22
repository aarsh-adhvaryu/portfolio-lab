"""Macro shock factors for E2-B (shock-exposure graph), from FRED.

E2-B's shock factors are Brent, USDINR, the US 10-year yield, FII flows,
India VIX and GDELT intensity. The first three are daily market prices on
FRED's public CSV endpoint (no API key):

    BRENT       DCOILBRENTEU   Brent crude, USD per barrel
    USDINR      DEXINUS        Indian rupees per US dollar (noon NY buying rate)
    US10Y       DGS10          US 10-year Treasury constant-maturity yield, %

These are market observations, not revised statistics, so the value dated D
is what was knowable at D's close (NY time, which is after the Indian close:
a month-end decision should read the PREVIOUS day's print to stay strictly
point-in-time -- the charter that uses them must say so).

FRED stalls requests that present a browser user-agent; a plain client
answers instantly (found 2026-09-22).

Output: data/macro/{KEY}.parquet -- date, value.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import data_dir

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
SERIES = {"BRENT": "DCOILBRENTEU", "USDINR": "DEXINUS", "US10Y": "DGS10"}


def fetch(series_id: str, timeout: int = 60) -> pd.DataFrame:
    r = requests.get(URL, params={"id": series_id},
                     headers={"User-Agent": "curl/8.0"}, timeout=timeout)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    date_col = df.columns[0]
    out = pd.DataFrame({"date": pd.to_datetime(df[date_col]).dt.date,
                        "value": pd.to_numeric(df[series_id], errors="coerce")})
    return out.dropna().sort_values("date").reset_index(drop=True)   # "." = no print


def collect(root: Optional[Path] = None) -> dict:
    root = root or data_dir()
    out = {}
    for key, sid in SERIES.items():
        df = fetch(sid)
        p = root / "macro" / f"{key}.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(p, index=False)
        out[key] = {"fred_id": sid, "rows": len(df), "first": str(df["date"].min()),
                    "last": str(df["date"].max())}
    return out


def load(key: str, root: Optional[Path] = None) -> pd.DataFrame:
    return pd.read_parquet((root or data_dir()) / "macro" / f"{key}.parquet")
