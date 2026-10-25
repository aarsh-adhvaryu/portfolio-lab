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
SERIES = {
    "BRENT": "DCOILBRENTEU", "USDINR": "DEXINUS", "US10Y": "DGS10",
    # Added 2026-09-22: world stress that can reach India from outside.
    # Market prints, never revised -- usable point-in-time with the NY-close
    # rule above.
    "US_VIX": "VIXCLS", "WTI": "DCOILWTICO", "USD_BROAD": "DTWEXBGS",
    "US_10Y_2Y": "T10Y2Y", "US_10Y_3M": "T10Y3M", "FED_FUNDS": "DFF",
    "TED_SPREAD": "TEDRATE",            # ends 2022-01-21 (LIBOR retired)
    "US_NASDAQ": "NASDAQCOM", "US_MORTGAGE30": "MORTGAGE30US",
    "USDCNY": "DEXCHUS", "USDJPY": "DEXJPUS", "USDEUR": "DEXUSEU",
}
# REVISED series: FRED serves only the LATEST vintage, so a past value here is
# not what anyone saw at the time (housing starts and claims are revised;
# the stress indices are re-estimated every week over their whole history).
# Fine for explaining the past. A charter that decides on one must use
# ALFRED vintages (free FRED API key) instead.
REVISED = {
    "US_FIN_STRESS_STL": "STLFSI4", "US_FIN_CONDITIONS_NFCI": "NFCI",
    "US_HOME_PRICES_CS": "CSUSHPINSA", "US_HOUSING_STARTS": "HOUST",
    "US_MORTGAGE_DELINQ": "DRSFRMACBS", "US_UNEMPLOYMENT": "UNRATE",
    "US_JOBLESS_CLAIMS": "ICSA", "COPPER_MONTHLY": "PCOPPUSDM",
}
# Not collected: the ICE BofA credit spreads (BAMLH0A0HYM2 etc.) -- FRED now
# serves only their last three years; global_markets carries HYG/LQD instead.


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
    for key, sid in {**SERIES, **REVISED}.items():
        df = fetch(sid)
        p = root / "macro" / f"{key}.parquet"
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(p, index=False)
        out[key] = {"fred_id": sid, "rows": len(df), "first": str(df["date"].min()),
                    "last": str(df["date"].max()), "revised": key in REVISED}
    return out


def load(key: str, root: Optional[Path] = None) -> pd.DataFrame:
    return pd.read_parquet((root or data_dir()) / "macro" / f"{key}.parquet")
