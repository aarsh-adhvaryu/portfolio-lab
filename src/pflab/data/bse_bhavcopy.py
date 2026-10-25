"""BSE daily bhavcopy (UDiFF CSV): closing prices for securities that do not trade on NSE.

Why: a few holdings list only on BSE (e.g. NSE's own shares, scrip 544937). The NSE panel stays the price
source for everything it covers; BSE closes are loaded into the PM store only for ISINs with no NSE price in
the window (`pm.prices.refresh`), so each security has one price source.

URL pattern verified against the live site on 2026-10-15 (BhavCopy_BSE_CM_0_0_0_<yyyymmdd>_F_0000.CSV, the
same UDiFF columns as NSE's, so `bhavcopy.normalize` reads it). Files are kept under data/bse_bhavcopy/YYYY/,
never under data/bhavcopy/ (the NSE research panel).
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import bhavcopy, data_dir

URL = "https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{yyyymmdd}_F_0000.CSV"
HEADERS = {**bhavcopy.HEADERS, "Referer": "https://www.bseindia.com/"}
DIR = "bse_bhavcopy"


def _parq(d: date, root: Path) -> Path:
    return root / DIR / str(d.year) / f"{d.isoformat()}.parquet"


def _log(root: Path, rec: dict) -> None:
    p = root / DIR / "_log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    rec["ts"] = datetime.now().isoformat()
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def fetch_day(d: date, session: requests.Session, root: Optional[Path] = None, timeout: int = 30) -> Optional[Path]:
    """Download and normalise one session; None when BSE has no file (holiday). Idempotent."""
    root = root or data_dir()
    p = _parq(d, root)
    if p.exists():
        return p
    r = session.get(URL.format(yyyymmdd=d.strftime("%Y%m%d")), headers=HEADERS, timeout=timeout)
    if r.status_code != 200 or not r.content or r.content.lstrip()[:1] == b"<":     # an HTML error page
        _log(root, {"date": d, "status": "no-file", "code": r.status_code})
        return None
    df = bhavcopy.normalize(r.content, d)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    return p


def collect(start: date, end: date, root: Optional[Path] = None, sleep: float = 0.7, session=None) -> dict:
    root = root or data_dir()
    s = session or requests.Session()
    stats = {"ok": 0, "missing": 0, "error": 0}
    d = start
    while d <= end:
        try:
            stats["ok" if fetch_day(d, s, root) else "missing"] += 1
        except Exception as e:
            stats["error"] += 1
            _log(root, {"date": d, "error": repr(e)})
        time.sleep(sleep)
        d += timedelta(days=1)
    return stats


def load(start: Optional[date] = None, end: Optional[date] = None, root: Optional[Path] = None) -> pd.DataFrame:
    from pflab import _duck
    root = root or data_dir()
    files = list((root / DIR).glob("*/*.parquet"))
    if not files:
        return pd.DataFrame(columns=["date", "symbol", "series", "isin", "close"])
    q = f"select * from read_parquet('{root / DIR}/*/*.parquet', union_by_name=true)"
    conds = ([f"date >= DATE '{start.isoformat()}'"] if start else []) + ([f"date <= DATE '{end.isoformat()}'"] if end else [])
    if conds:
        q += " where " + " and ".join(conds)
    return _duck.sql(q).df()
