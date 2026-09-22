"""NSE daily bhavcopy collector and normaliser (both file formats).

Normalised schema (one parquet per session under data/bhavcopy/YYYY/):
  date, symbol, series, isin, open, high, low, close, prev_close,
  volume, turnover, trades

URL patterns and the format switch date were verified against the live
archive on 2026-09-16 (Phase 1 task 1.1): the last session published in the
old format is 2024-07-05 and the first published only as UDiFF is 2024-07-08.
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import data_dir

OLD_URL = "https://archives.nseindia.com/content/historical/EQUITIES/{yyyy}/{MON}/cm{dd}{MON}{yyyy}bhav.csv.zip"
NEW_URL = "https://archives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{yyyymmdd}_F_0000.csv.zip"
FORMAT_SWITCH = date(2024, 7, 8)  # verified 2026-09-16: first session published only in UDiFF
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
COLUMNS = ["date", "symbol", "series", "isin", "open", "high", "low", "close",
           "prev_close", "volume", "turnover", "trades"]
CASH_SEGMENTS = {"CM", "CASH"}

_OLD_MAP = {"SYMBOL": "symbol", "SERIES": "series", "ISIN": "isin", "OPEN": "open", "HIGH": "high",
            "LOW": "low", "CLOSE": "close", "PREVCLOSE": "prev_close", "TOTTRDQTY": "volume",
            "TOTTRDVAL": "turnover", "TOTALTRADES": "trades", "TIMESTAMP": "date"}
_NEW_MAP = {"TckrSymb": "symbol", "SctySrs": "series", "ISIN": "isin", "OpnPric": "open",
            "HghPric": "high", "LwPric": "low", "ClsPric": "close", "PrvsClsgPric": "prev_close",
            "TtlTradgVol": "volume", "TtlTrfVal": "turnover", "TtlNbOfTxsExctd": "trades",
            "TradDt": "date"}


def urls_for(d: date):
    old = OLD_URL.format(yyyy=d.year, MON=d.strftime("%b").upper(), dd=d.strftime("%d"))
    new = NEW_URL.format(yyyymmdd=d.strftime("%Y%m%d"))
    return (new, old) if d >= FORMAT_SWITCH else (old, new)


def _parse_old_dates(s: pd.Series) -> pd.Series:
    """Parse the old format's TIMESTAMP column.

    Normally "02-JAN-2012" (and "2-JAN-2004" before 2011, unpadded), but NSE
    published at least one session -- 2020-07-13 -- as "13-Jul-20" with a
    two-digit year. The caller's session_date check catches a misread year.
    """
    txt = s.str.strip()
    for fmt in ("%d-%b-%Y", "%d-%b-%y"):
        try:
            return pd.to_datetime(txt, format=fmt).dt.date
        except ValueError:
            continue
    sample = txt.iloc[0] if len(txt) else ""
    raise ValueError(f"unrecognised TIMESTAMP format: {sample!r}")


def normalize(raw: bytes, session_date: Optional[date] = None) -> pd.DataFrame:
    """Parse a bhavcopy CSV (bytes, possibly zipped) of either format."""
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name = [n for n in z.namelist() if n.lower().endswith(".csv")][0]
            raw = z.read(name)
    df = pd.read_csv(io.BytesIO(raw), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    if "TckrSymb" in df.columns:
        df = df.rename(columns=_NEW_MAP)
        if "Sgmt" in df.columns:
            # UDiFF labels the cash market "CM"; keep the older "CASH" spelling too.
            df = df[df["Sgmt"].str.strip().isin(CASH_SEGMENTS)]
        df["date"] = pd.to_datetime(df["date"]).dt.date
    elif "SYMBOL" in df.columns:
        df = df.rename(columns=_OLD_MAP)
        df["date"] = _parse_old_dates(df["date"])
        # TOTALTRADES and ISIN were both added between 2011-06 and 2011-10;
        # files before that carry neither column.
        for c in ("isin", "trades"):
            if c not in df.columns:
                df[c] = None
    else:
        raise ValueError(f"unrecognised bhavcopy header: {list(df.columns)[:8]}")
    for c in ["open", "high", "low", "close", "prev_close", "turnover"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ["volume", "trades"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    df["symbol"] = df["symbol"].str.strip()
    # Debt rows (NCDs, tax-free bonds) carry an empty SERIES in the old format.
    df["series"] = df["series"].fillna("").str.strip()
    df["isin"] = df["isin"].map(lambda s: s.strip() if isinstance(s, str) else None)
    # Pre-2012 sessions have no ISIN at all. Left as a plain object column
    # pyarrow types it "null", and DuckDB then cannot union those files with
    # later ones; pin the dtype so every session shares one schema.
    df["isin"] = df["isin"].astype("string")
    out = df[COLUMNS].reset_index(drop=True)
    if out.empty:
        # A silently empty frame means the parse dropped everything (a renamed
        # column or segment label); never write it out as a good session.
        raise ValueError("bhavcopy parsed to zero rows")
    if session_date is not None and out["date"].iloc[0] != session_date:
        raise ValueError(f"file date {out['date'].iloc[0]} != requested {session_date}")
    return out


def _paths(d: date, root: Path):
    raw = root / "raw" / "bhavcopy" / str(d.year) / f"{d.isoformat()}.zip"
    parq = root / "bhavcopy" / str(d.year) / f"{d.isoformat()}.parquet"
    return raw, parq


def _log(root: Path, rec: dict) -> None:
    p = root / "bhavcopy" / "_log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    rec["ts"] = datetime.utcnow().isoformat()
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def fetch_day(d: date, session: requests.Session, root: Optional[Path] = None,
              timeout: int = 30) -> Optional[Path]:
    """Download and normalise one session. Returns parquet path, or None on
    a 404 from both URL patterns (holiday). Idempotent."""
    root = root or data_dir()
    raw_p, parq_p = _paths(d, root)
    if parq_p.exists():
        return parq_p
    raw = None
    if raw_p.exists():
        raw = raw_p.read_bytes()
    else:
        seen = []
        for url in urls_for(d):
            r = session.get(url, headers=HEADERS, timeout=timeout)
            seen.append(r.status_code)
            if r.status_code == 200 and r.content:
                raw = r.content
                break
            if r.status_code not in (404, 403):
                _log(root, {"date": d, "url": url, "status": r.status_code})
        if raw is None:
            # Record the codes: an all-404 day is a holiday, but a run of 403s
            # is NSE throttling and must not be mistaken for one.
            _log(root, {"date": d, "status": "no-file", "codes": seen})
            return None
        raw_p.parent.mkdir(parents=True, exist_ok=True)
        raw_p.write_bytes(raw)
    df = normalize(raw, d)
    parq_p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parq_p, index=False)
    return parq_p


def collect(start: date, end: date, root: Optional[Path] = None, sleep: float = 0.7,
            weekdays_only: bool = False) -> dict:
    root = root or data_dir()
    s = requests.Session()
    try:  # warm cookies; NSE sometimes wants a landing-page visit first
        s.get("https://www.nseindia.com/", headers=HEADERS, timeout=30)
    except Exception:
        pass
    stats = {"ok": 0, "missing": 0, "error": 0}
    d = start
    while d <= end:
        # NSE trades on some Saturdays and Sundays -- Budget days and Diwali
        # Muhurat sessions. Skipping weekends silently lost 27 real sessions
        # from the 2004-2026 backfill, so attempt every day by default.
        if not weekdays_only or d.weekday() < 5:
            try:
                p = fetch_day(d, s, root)
                stats["ok" if p else "missing"] += 1
            except Exception as e:  # keep going; log it
                stats["error"] += 1
                _log(root, {"date": d, "error": repr(e)})
            time.sleep(sleep)
        d += timedelta(days=1)
    return stats


def load(start: Optional[date] = None, end: Optional[date] = None, root: Optional[Path] = None,
         series=("EQ",)) -> pd.DataFrame:
    """Long panel from the normalised parquet files via DuckDB."""
    import duckdb
    root = root or data_dir()
    glob = str(root / "bhavcopy" / "*" / "*.parquet")
    q = f"select * from read_parquet('{glob}', union_by_name=true)"
    conds = []
    if start:
        conds.append(f"date >= DATE '{start.isoformat()}'")
    if end:
        conds.append(f"date <= DATE '{end.isoformat()}'")
    if series:
        conds.append("series in (" + ",".join(f"'{x}'" for x in series) + ")")
    if conds:
        q += " where " + " and ".join(conds)
    return duckdb.query(q + " order by date, isin").to_df()
