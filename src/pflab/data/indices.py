"""NSE index series collector (charter section 10 benchmarks, section 6 trend filter).

The niftyindices.com site caps a download at one year, but that limit is
enforced in the browser only -- `if (diffDays > 365) alert(...)` in
IISLComponet.js. The two endpoints its form posts to accept any range, so the
whole history comes down in a handful of calls.

    POST /BackPage/getHistoricaldatatabletoString   price index (OPEN/HIGH/LOW/CLOSE)
    POST /BackPage/getTotalReturnIndexString        TRI (TotalReturnsIndex, NTR_Value)

Body is {"cinfo": "{'name':..,'startDate':..,'endDate':..,'indexName':..}"},
dates as dd-MMM-yyyy. Verified against the live site 2026-09-16.

Normalised output: data/indices/{KEY}.parquet with columns date, close
(plus open/high/low for the price index).
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import data_dir

BASE = "https://www.niftyindices.com/BackPage/"
PRICE_PATH = "getHistoricaldatatabletoString"
TRI_PATH = "getTotalReturnIndexString"
REFERER = "https://www.niftyindices.com/reports/historical-data"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/json; charset=UTF-8",
    "Referer": REFERER,
    "X-Requested-With": "XMLHttpRequest",
}

# key -> (NSE index name, kind). Names are exactly as the site expects:
# "NIFTY200 MOMENTUM 30" returns rows, "NIFTY 200 MOMENTUM 30" returns [].
SERIES = {
    "NIFTY50_PRICE": ("NIFTY 50", "price"),          # section 6 crash rule (price, not TRI)
    "NIFTY50_TRI": ("NIFTY 50", "tri"),              # B1
    "NIFTY500_TRI": ("NIFTY 500", "tri"),            # B2, primary benchmark
    "NIFTY200_MOMENTUM30_TRI": ("NIFTY200 MOMENTUM 30", "tri"),  # B3
    # B5 (MANDATE §5, 2026-09-21): the one-click alternative for a whole-500
    # momentum investor. Reported only, never in any charter's GATE or
    # C1-C4 arithmetic. Launched in the 2020s; the earlier history is
    # back-computed by NSE, the same caveat as B3. Spelled as the site
    # expects: "NIFTY 500 MOMENTUM 50" returns [].
    "NIFTY500_MOMENTUM50_TRI": ("NIFTY500 MOMENTUM 50", "tri"),  # B5
}

# Valuation series (pe, pb, divYield). NOT an E1 input: charter section 2 ranks
# the universe by traded value precisely to avoid needing fundamentals, and
# section 3 is pure price momentum. Collected for two reasons only -- it
# cross-checks the TRI series against the price series (TRI return minus price
# return should be about the dividend yield, and B2 is the primary benchmark),
# and it is E2 groundwork. Using it in E1 would need a charter change.
VALUATION_PATH = "getpepbHistoricaldataDBtoString"
VALUATION_SERIES = {
    "NIFTY50_VALUATION": "NIFTY 50",
    "NIFTY500_VALUATION": "NIFTY 500",
}
# NIFTY200 MOMENTUM 30 has no valuation history (the endpoint returns []).

# Sector indices (collected 2026-09-22) -- groundwork for E1-S (MANDATE §7
# sector-trend cap) and E2-B's sector nodes. Every NSE sectoral/thematic index
# the endpoint serves, price and TRI both; WHICH sectors, and price or TRI,
# is the charter's to choose, not this collector's. Not in SERIES, so
# collect_all() is unchanged. Names probed against the live site: "NIFTY
# HEALTHCARE INDEX" returns [], "NIFTY HEALTHCARE" returns rows. Several
# start after 2004 (Private Bank, Healthcare, Oil & Gas, Consumer Durables,
# Chemicals in 2005; Realty, India Consumption, CPSE later); Media returns a
# single row before its real history begins.
SECTORS = {
    "BANK": "NIFTY BANK", "AUTO": "NIFTY AUTO", "FMCG": "NIFTY FMCG", "IT": "NIFTY IT",
    "MEDIA": "NIFTY MEDIA", "METAL": "NIFTY METAL", "PHARMA": "NIFTY PHARMA",
    "PSU_BANK": "NIFTY PSU BANK", "PRIVATE_BANK": "NIFTY PRIVATE BANK",
    "REALTY": "NIFTY REALTY", "FIN_SERVICES": "NIFTY FINANCIAL SERVICES",
    "ENERGY": "NIFTY ENERGY", "INFRA": "NIFTY INFRA", "COMMODITIES": "NIFTY COMMODITIES",
    "CONSUMPTION": "NIFTY INDIA CONSUMPTION", "HEALTHCARE": "NIFTY HEALTHCARE",
    "OIL_GAS": "NIFTY OIL & GAS", "CONSUMER_DURABLES": "NIFTY CONSUMER DURABLES",
    "CPSE": "NIFTY CPSE", "PSE": "NIFTY PSE", "MNC": "NIFTY MNC",
    "SERVICES": "NIFTY SERVICES SECTOR", "CHEMICALS": "NIFTY CHEMICALS",
}
SECTOR_SERIES = {f"SECTOR_{k}_{kind.upper()}": (name, kind)
                 for k, name in SECTORS.items() for kind in ("price", "tri")}

START = date(2004, 1, 1)
CHUNK_YEARS = 2


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(REFERER, timeout=40)  # the endpoints want a normal page visit first
    return s


def _fmt(d: date) -> str:
    return d.strftime("%d-%b-%Y")


def fetch_range(s: requests.Session, name: str, kind: str,
                start: date, end: date, timeout: int = 120) -> list:
    cinfo = ("{'name':'%s','startDate':'%s','endDate':'%s','indexName':'%s'}"
             % (name, _fmt(start), _fmt(end), name))
    path = {"price": PRICE_PATH, "tri": TRI_PATH, "valuation": VALUATION_PATH}[kind]
    r = s.post(BASE + path, data=json.dumps({"cinfo": cinfo}), timeout=timeout)
    r.raise_for_status()
    rows = r.json()
    if isinstance(rows, dict):  # {"d": "[...]"} on some responses
        rows = json.loads(rows.get("d", "[]"))
    return rows or []


def normalize(rows: list, kind: str) -> pd.DataFrame:
    """One row per session, oldest first."""
    if not rows:
        return pd.DataFrame(columns=["date", "close"])
    df = pd.DataFrame(rows)
    if kind == "price":
        df = df.rename(columns={"HistoricalDate": "date", "OPEN": "open", "HIGH": "high",
                                "LOW": "low", "CLOSE": "close"})
        keep = ["date", "open", "high", "low", "close"]
    elif kind == "valuation":
        df = df.rename(columns={"DATE": "date", "pe": "pe", "pb": "pb",
                                "divYield": "div_yield"})
        keep = ["date", "pe", "pb", "div_yield"]
    else:
        df = df.rename(columns={"Date": "date", "TotalReturnsIndex": "close"})
        keep = ["date", "close"]
    df["date"] = pd.to_datetime(df["date"], format="%d %b %Y").dt.date
    for c in keep[1:]:
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", "", regex=False),
                              errors="coerce")
    value_col = "close" if kind != "valuation" else "pe"
    df = df[keep].dropna(subset=[value_col])
    if kind != "valuation" and df["close"].le(0).any():
        raise ValueError("index series has a non-positive close")
    return df.drop_duplicates("date").sort_values("date").reset_index(drop=True)


def collect(key: str, start: date = START, end: Optional[date] = None,
            root: Optional[Path] = None, sleep: float = 1.0) -> Path:
    """Download one series in chunks and write data/indices/{key}.parquet."""
    if key in SERIES or key in SECTOR_SERIES:
        name, kind = SERIES.get(key) or SECTOR_SERIES[key]
    elif key in VALUATION_SERIES:
        name, kind = VALUATION_SERIES[key], "valuation"
    else:
        raise KeyError(f"unknown series {key!r}; "
                       f"known: {sorted(SERIES) + sorted(VALUATION_SERIES) + sorted(SECTOR_SERIES)}")
    root = root or data_dir()
    end = end or date.today()
    s = _session()
    frames, lo = [], start
    while lo <= end:
        hi = min(end, date(lo.year + CHUNK_YEARS - 1, 12, 31))
        rows = fetch_range(s, name, kind, lo, hi)
        if rows:
            frames.append(normalize(rows, kind))
        print(f"  {key}: {lo} -> {hi}  {len(rows):5d} rows", flush=True)
        lo = date(hi.year + 1, 1, 1)
        time.sleep(sleep)
    if not frames:
        raise ValueError(f"{key}: no rows returned for {start}..{end}")
    out = (pd.concat(frames, ignore_index=True)
             .drop_duplicates("date").sort_values("date").reset_index(drop=True))
    p = root / "indices" / f"{key}.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(p, index=False)
    return p


def collect_all(start: date = START, end: Optional[date] = None,
                root: Optional[Path] = None, valuation: bool = True) -> dict:
    written = {}
    keys = list(SERIES) + (list(VALUATION_SERIES) if valuation else [])
    for key in keys:
        print(f"{key}:", flush=True)
        p = collect(key, start, end, root)
        df = pd.read_parquet(p)
        written[key] = (len(df), df["date"].min(), df["date"].max())
        print(f"  -> {p.name}: {len(df):,} sessions "
              f"{df['date'].min()} .. {df['date'].max()}", flush=True)
    return written


def collect_sectors(start: date = START, end: Optional[date] = None,
                    root: Optional[Path] = None) -> dict:
    """Every SECTOR_SERIES key; a series that fails is reported, not fatal."""
    written = {}
    for key in SECTOR_SERIES:
        try:
            df = pd.read_parquet(collect(key, start, end, root))
            written[key] = (len(df), df["date"].min(), df["date"].max())
        except Exception as e:
            written[key] = repr(e)
        print(f"  -> {key}: {written[key]}", flush=True)
    return written


def load(key: str, root: Optional[Path] = None) -> pd.DataFrame:
    root = root or data_dir()
    return pd.read_parquet(root / "indices" / f"{key}.parquet")
