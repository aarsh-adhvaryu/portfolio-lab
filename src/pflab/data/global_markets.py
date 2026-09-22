"""World markets, daily, from Yahoo Finance's chart API (collected 2026-09-22).

Groundwork for E2-B's shock graph and for explaining what reached India from
outside (2008 came through US credit, not Indian news). Collected, not used:
no charter reads these yet, and one that does must name its series.

Dates are the exchange's LOCAL trading date (Yahoo stamps each bar at the
local open; the exchange's gmtoffset converts it back). Point-in-time rule
for a charter that uses them: Asian markets close before the NSE (Tokyo,
Hong Kong, Shanghai, Seoul, Taipei, Sydney), so their day-M close is known
at India's day-M close. Europe, the US and Brazil close AFTER the NSE, so a
decision at M may read only their close of M-1.

Yahoo is not an official source. Where FRED carries the same series
(US VIX = VIXCLS, Nasdaq = NASDAQCOM) `pflab.data.macro` holds it too, for
cross-checking.

Output: data/global/{KEY}.parquet -- date, open, high, low, close,
adj_close, volume.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import data_dir

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# key -> Yahoo symbol. First-row dates as probed 2026-09-22.
SERIES = {
    # equity indices (price, not total return)
    "US_SP500": "^GSPC",          # 1970
    "US_NASDAQ": "^IXIC",         # 1971
    "US_DOW": "^DJI",             # 1992
    "UK_FTSE100": "^FTSE",        # 1984
    "DE_DAX": "^GDAXI",           # 1987
    "FR_CAC40": "^FCHI",          # 1990
    "EU_STOXX50": "^STOXX50E",    # 2007
    "JP_NIKKEI225": "^N225",      # 1970
    "HK_HANGSENG": "^HSI",        # 1986
    "CN_SHANGHAI": "000001.SS",   # 1997
    "KR_KOSPI": "^KS11",          # 1996
    "TW_TAIEX": "^TWII",          # 1997
    "AU_ASX200": "^AXJO",         # 1992
    "BR_BOVESPA": "^BVSP",        # 1993
    # volatility
    "US_VIX": "^VIX",             # 1990
    "US_MOVE": "^MOVE",           # 2002, Treasury volatility
    # funds standing in for series FRED no longer serves in full
    "EM_EQUITY_EEM": "EEM",       # 2003
    "US_HIGH_YIELD_HYG": "HYG",   # 2007 (ICE HY spread on FRED: last 3 years only)
    "US_IG_CREDIT_LQD": "LQD",    # 2002
    "US_LONG_TREASURY_TLT": "TLT",  # 2002
    # commodities (front-month futures) and the dollar
    "GOLD": "GC=F", "SILVER": "SI=F", "COPPER": "HG=F",      # 2000
    "WTI": "CL=F", "BRENT_FUT": "BZ=F", "NATGAS": "NG=F",    # 2000 / 2007
    "WHEAT": "ZW=F",                                         # 2000
    "DOLLAR_INDEX": "DX-Y.NYB",   # 1971
    "US_10Y_YIELD": "^TNX",       # 1970, x10 percent
    "BITCOIN": "BTC-USD",         # 2014
}


def fetch(sym: str, timeout: int = 60) -> pd.DataFrame:
    j = requests.get(URL.format(sym=sym),
                     params={"period1": 0, "period2": int(time.time()), "interval": "1d"},
                     headers={"User-Agent": UA}, timeout=timeout).json()
    res = j["chart"]["result"][0]
    off = timedelta(seconds=res["meta"].get("gmtoffset", 0))
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    df = pd.DataFrame({
        "date": [(datetime.fromtimestamp(t, timezone.utc) + off).date() for t in res["timestamp"]],
        "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"],
        "adj_close": adj, "volume": q.get("volume")})
    df = df.dropna(subset=["close"])
    return df[df["close"] > 0].drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def collect(root: Optional[Path] = None, keys: Optional[list] = None, pause: float = 0.5) -> dict:
    """Rewrites each file whole; a series that fails is reported, not fatal."""
    root = root or data_dir()
    out = {}
    for key in keys or SERIES:
        try:
            df = fetch(SERIES[key])
            p = root / "global" / f"{key}.parquet"
            p.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(p, index=False)
            out[key] = (len(df), str(df["date"].min()), str(df["date"].max()))
        except Exception as e:
            out[key] = repr(e)[:200]
        time.sleep(pause)
    return out


def load(key: str, root: Optional[Path] = None) -> pd.DataFrame:
    return pd.read_parquet((root or data_dir()) / "global" / f"{key}.parquet")
