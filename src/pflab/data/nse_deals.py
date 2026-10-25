"""NSE bulk and block deals, day by day (S48 arm 4; docs/research/s48_who_is_buying_protocol.md).

Endpoint (probed 2026-10-20): `api/historicalOR/bulk-block-short-deals?optionType=bulk_deals|block_deals&from=&to=`
(dates dd-mm-yyyy). It answers at most 70 rows whatever the window, silently, so the collector asks one day at a
time; a day that returns exactly 70 rows may still be cut off and is recorded as `capped`. Bulk deals are reported
after the close, so a study uses a deal only from the next session.

Files: data/nse_deals/{kind}_{yyyy}-{mm}.parquet, one per kind and month, written only when every day of the month
was fetched (a stopped run resumes at the first missing month).
"""
from __future__ import annotations

import time
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, List, Optional

import pandas as pd

from pflab.data import data_dir

API = "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals"
REFERER = "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"
KINDS = {"bulk": "bulk_deals", "block": "block_deals"}
CAP = 70
RETRY_WAITS = (5, 15, 30, 60, 120, 300, 300, 300, 300)   # ~24 min: rides out a mobile-hotspot drop
COLUMNS = ["date", "symbol", "client", "side", "quantity", "price", "kind", "capped"]


def session():
    from pflab.data import nse_insider as ni
    s = ni._session()
    s.headers["Referer"] = REFERER
    return s


def parse(rows: List[dict], kind: str, capped: bool) -> pd.DataFrame:
    out = [{"date": pd.to_datetime(r.get("BD_DT_DATE"), format="%d-%b-%Y", errors="coerce"),
            "symbol": str(r.get("BD_SYMBOL") or "").strip(), "client": str(r.get("BD_CLIENT_NAME") or "").strip(),
            "side": str(r.get("BD_BUY_SELL") or "").strip().upper(),
            "quantity": pd.to_numeric(r.get("BD_QTY_TRD"), errors="coerce"),
            "price": pd.to_numeric(r.get("BD_TP_WATP"), errors="coerce"), "kind": kind, "capped": capped}
           for r in rows]
    return pd.DataFrame(out, columns=COLUMNS)


def fetch_day(get: Callable, kind: str, d: date) -> pd.DataFrame:
    r = get(API, params={"optionType": KINDS[kind], "from": d.strftime("%d-%m-%Y"), "to": d.strftime("%d-%m-%Y")},
            timeout=60)
    r.raise_for_status()
    rows = (r.json() or {}).get("data") or []
    return parse(rows, kind, len(rows) >= CAP)


def month_path(root: Path, kind: str, y: int, m: int) -> Path:
    return root / "nse_deals" / f"{kind}_{y:04d}-{m:02d}.parquet"


def months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def collect(start: date, end: date, kinds=("bulk", "block"), root: Optional[Path] = None, get: Optional[Callable] = None,
            pause: float = 0.6, log: Callable[[str], None] = print) -> dict:
    """Fetch every weekday of every month in [start, end] not already on disk; a month is written whole or not at
    all. Returns counts."""
    root = root or data_dir()
    (root / "nse_deals").mkdir(parents=True, exist_ok=True)
    get_is_live = get is None
    get = get or session().get
    done = {"months": 0, "rows": 0, "capped_days": 0, "skipped": 0}
    for kind in kinds:
        for y, m in months(start, end):
            p = month_path(root, kind, y, m)
            d0 = date(y, m, 1)
            d1 = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
            if p.exists() and d1 < date.today():           # S63: the running month is fetched again (daily job)
                done["skipped"] += 1
                continue
            frames, d = [], max(d0, start)
            while d <= min(d1, end):
                if d.weekday() < 5:
                    waits = RETRY_WAITS if get_is_live else (0, 0, 0)
                    for attempt, w in enumerate(waits):
                        try:
                            frames.append(fetch_day(get, kind, d))
                            break
                        except Exception as e:
                            if attempt == len(waits) - 1:
                                raise                       # the month is not written; a rerun resumes here
                            log(f"{kind} {d}: {type(e).__name__}; waiting {w} s (connection?)")
                            time.sleep(w)
                            if get_is_live and attempt >= 2:
                                get = session().get          # a fresh session after an outage
                    time.sleep(pause)
                d += timedelta(days=1)
            df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)
            df.to_parquet(p, index=False)
            done["months"] += 1
            done["rows"] += len(df)
            done["capped_days"] += int(df.drop_duplicates("date")["capped"].sum()) if len(df) else 0
            log(f"{kind} {y}-{m:02d}: {len(df)} deals")
    return done


def load(root: Optional[Path] = None) -> pd.DataFrame:
    fs = sorted((root or data_dir()).glob("nse_deals/*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True) if fs else pd.DataFrame(columns=COLUMNS)
