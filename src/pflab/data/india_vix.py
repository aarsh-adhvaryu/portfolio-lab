"""India VIX daily history, 2008-03-03 onward (E3-R S8, E2-B, E2-C).

Two sources, stitched and cross-checked:

  * NSE, `api/historicalOR/vixhistory` -- the official series, but it serves
    only from 2010-07-19, needs the cookies a normal page visit sets, accepts
    at most 365 days per request and silently CAPS each answer at 70 rows, so
    it is fetched a calendar month at a time.
  * Yahoo Finance `^INDIAVIX` chart API -- from 2008-03-03 (VIX's launch).

On the 3,971 days both carried at build time (2026-09-22) the closes agreed
to a median 0.0025 points and a 99th percentile of 0.005 -- Yahoo's rounding
of the same series -- so Yahoo is used ONLY for the days before NSE's series
begins, and every row records its `source`. `collect` refuses to write if the
overlap ever stops agreeing.

Output: data/indices/INDIA_VIX.parquet -- date, open, high, low, close, source.
Point-in-time: a month-end decision uses only rows dated <= M, as for every
index series (runner truncates at the period end).
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import data_dir

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
NSE_PAGE = "https://www.nseindia.com/reports-indices-historical-vix"
NSE_API = "https://www.nseindia.com/api/historicalOR/vixhistory"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/%5EINDIAVIX"
START = date(2008, 3, 1)
NSE_CAP = 70                       # rows per answer; a full answer means truncated
AGREE_MEDIAN, AGREE_P99 = 0.01, 0.05


def _nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*"})
    s.get("https://www.nseindia.com/", timeout=30)
    time.sleep(1)
    s.get(NSE_PAGE, timeout=30)
    time.sleep(1)
    s.headers["Referer"] = NSE_PAGE
    return s


def fetch_nse(start: date = START, end: Optional[date] = None, pause: float = 1.0) -> pd.DataFrame:
    """Month by month, retrying a month with a fresh session. Raises if a
    month still fails or ever returns the capped 70 rows."""
    end = end or date.today()
    s, rows, m = _nse_session(), [], date(start.year, start.month, 1)
    while m <= end:
        nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        hi = min(nxt - timedelta(days=1), end)
        for attempt in range(3):
            try:
                r = s.get(NSE_API, params={"from": m.strftime("%d-%m-%Y"),
                                           "to": hi.strftime("%d-%m-%Y")}, timeout=60)
                d = r.json()["data"]
                if len(d) >= NSE_CAP:
                    raise ValueError(f"{m}: answer hit the {NSE_CAP}-row cap")
                rows += d
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(5)
                s = _nse_session()
        m = nxt
        time.sleep(pause)
    if not rows:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close"])
    df = pd.DataFrame(rows)
    return (pd.DataFrame({
        "date": pd.to_datetime(df["EOD_TIMESTAMP"], format="%d-%b-%Y").dt.date,
        "open": df["EOD_OPEN_INDEX_VAL"].astype(float),
        "high": df["EOD_HIGH_INDEX_VAL"].astype(float),
        "low": df["EOD_LOW_INDEX_VAL"].astype(float),
        "close": df["EOD_CLOSE_INDEX_VAL"].astype(float)})
        .drop_duplicates("date").sort_values("date").reset_index(drop=True))


def fetch_yahoo(start: date = START, end: Optional[date] = None) -> pd.DataFrame:
    end = end or date.today()
    to_ts = lambda d: int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
    j = requests.get(YAHOO, params={"period1": to_ts(start), "period2": to_ts(end + timedelta(days=1)),
                                    "interval": "1d"}, headers={"User-Agent": UA}, timeout=60).json()
    res = j["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    ist = timedelta(hours=5, minutes=30)
    df = pd.DataFrame({
        "date": [(datetime.fromtimestamp(t, timezone.utc) + ist).date() for t in res["timestamp"]],
        "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"]})
    df = df.dropna(subset=["close"])
    return df[df["close"] > 0].drop_duplicates("date").sort_values("date").reset_index(drop=True)


def stitch(nse: pd.DataFrame, yahoo: pd.DataFrame) -> tuple:
    """(series, check). NSE wherever it has the day; Yahoo only before NSE's
    first day. Raises if the overlap disagrees -- a changed or broken source
    must stop the build, not blend in."""
    if nse.empty:
        raise ValueError("NSE returned nothing")
    m = nse[["date", "close"]].merge(yahoo[["date", "close"]], on="date", suffixes=("_n", "_y"))
    diff = (m["close_n"] - m["close_y"]).abs()
    check = {"overlap_days": int(len(m)), "median_abs_diff": float(diff.median()),
             "p99_abs_diff": float(diff.quantile(0.99)), "max_abs_diff": float(diff.max())}
    if len(m) < 250 or check["median_abs_diff"] > AGREE_MEDIAN or check["p99_abs_diff"] > AGREE_P99:
        raise ValueError(f"NSE and Yahoo India VIX disagree: {check}")
    early = yahoo[yahoo["date"] < nse["date"].min()].assign(source="yahoo")
    out = pd.concat([early, nse.assign(source="nse")], ignore_index=True)
    return out.sort_values("date").reset_index(drop=True), check


def update(root: Optional[Path] = None, end: Optional[date] = None, overlap_days: int = 10,
           fetch=None) -> dict:
    """Daily top-up: re-fetch only the last `overlap_days` before the stored end (NSE, the official series) and
    merge; the full stitched rebuild (`collect`) runs only when nothing is stored yet."""
    root = root or data_dir()
    p = root / "indices" / "INDIA_VIX.parquet"
    if not p.exists():
        return collect(root, end)
    old = pd.read_parquet(p)
    old["date"] = pd.to_datetime(old["date"]).dt.date
    start = old["date"].max() - timedelta(days=overlap_days)
    new = (fetch or fetch_nse)(start=start, end=end).assign(source="nse")
    out = (pd.concat([old[old["date"] < start], new], ignore_index=True)
           .drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True))
    out.to_parquet(p, index=False)
    return {"rows": len(out), "added": int(len(out) - len(old)), "last": str(out["date"].max())}


def collect(root: Optional[Path] = None, end: Optional[date] = None) -> dict:
    root = root or data_dir()
    series, check = stitch(fetch_nse(end=end), fetch_yahoo(end=end))
    p = root / "indices" / "INDIA_VIX.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    series.to_parquet(p, index=False)
    return {"path": str(p), "rows": len(series),
            "first": str(series["date"].min()), "last": str(series["date"].max()),
            "yahoo_rows": int((series["source"] == "yahoo").sum()), **check}
