"""NSE structured insider-trading (PIT) disclosures (E2-D §4).

SEBI's Prohibition of Insider Trading Regulations, 2015 created this feed.
Probed live 2026-09-23: it runs **2015-11-19 .. 2026-05-02** and stops.
Nothing is served for June, July, August or September 2026, while March
2026 returns 2,057 rows, so the tail is a real gap in the source and not
a throttle -- the BSE announcement feed is the only current source, and
for 2010-2015 it is the only source at all. Both facts are why E2-D §4
says "structured from ~2015; earlier from BSE".

Point-in-time key is `date`, the broadcast timestamp NSE puts on the
disclosure -- NOT `acqfromDt` (when the insider traded, known only to the
insider) and NOT `intimDt` (when the company was told). A feature at
month-end M may use a row only if its broadcast timestamp is <= M.

VERIFICATION
------------
The endpoint publishes no row count of its own, so there is no ROWCNT to
check a month against the way bse_announcements checks a day. The
analogue used here is **partition additivity**: a window's rows should
equal the union of its two halves. Asking the same question two ways is
the only check the source permits.

It mostly holds -- March 2017 whole = 9,218 = 2,273 + 6,945, and twelve
monthly requests for 2017 reproduce the single whole-year request exactly
(56,841 rows, 56,837 unique). But over 2015-2026 it failed in four
months, where the whole-month answer genuinely omits rows the halves
return: 2023-09 by 7, 2023-12 by 1, 2024-10 by 2 and 2025-03 by 64.
So a month is **written as the union**, not as the whole-window answer,
and the deficit is counted and reported. Trusting the single request
would have dropped 74 real disclosures without any sign that it had.

Schema (data/nse_insider/<year>/<year>-<month>.parquet):
  broadcast_dt, symbol, company, acq_name, person_category, acq_mode,
  transaction_type, securities_type, quantity, value, buy_quantity,
  buy_value, sell_quantity, sell_value, shares_before, pct_before,
  shares_after, pct_after, from_dt, to_dt, intimation_dt, regulation,
  exchange, did, pid, remarks
"""
from __future__ import annotations

import calendar
import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd
import requests

from pflab.data import data_dir
from pflab.data.bhavcopy import HEADERS

API = "https://www.nseindia.com/api/corporates-pit"
REFERER = "https://www.nseindia.com/companies-listing/corporate-filings-insider-trading"

FIRST_DATA_DATE = date(2015, 11, 19)    # probed 2026-09-23
LAST_DATA_DATE = date(2026, 5, 2)       # probed 2026-09-23; feed stops here

_FIELDS = {
    "date": "broadcast_dt", "symbol": "symbol", "company": "company",
    "acqName": "acq_name", "personCategory": "person_category",
    "acqMode": "acq_mode", "tdpTransactionType": "transaction_type",
    "secType": "securities_type", "secAcq": "quantity", "secVal": "value",
    "buyQuantity": "buy_quantity", "buyValue": "buy_value",
    "sellquantity": "sell_quantity", "sellValue": "sell_value",
    "befAcqSharesNo": "shares_before", "befAcqSharesPer": "pct_before",
    "afterAcqSharesNo": "shares_after", "afterAcqSharesPer": "pct_after",
    "acqfromDt": "from_dt", "acqtoDt": "to_dt", "intimDt": "intimation_dt",
    "anex": "regulation", "exchange": "exchange", "did": "did", "pid": "pid",
    "remarks": "remarks",
}
COLUMNS = list(_FIELDS.values())
_NUMERIC = ("quantity", "value", "buy_quantity", "buy_value", "sell_quantity",
            "sell_value", "shares_before", "shares_after", "pct_before", "pct_after")


class SplitCheckFailed(RuntimeError):
    """A window's rows do not equal the union of its halves, so the answer was
    truncated or capped. The month is NOT written."""


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({**HEADERS, "Accept": "*/*", "Referer": REFERER})
    for url in ("https://www.nseindia.com/", REFERER):
        try:
            s.get(url, timeout=40)
        except requests.RequestException:
            pass
        time.sleep(0.5)
    return s


def _d(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _raw(s: requests.Session, start: date, end: date, timeout: int = 120) -> List[dict]:
    r = s.get(API, params={"index": "equities", "from_date": _d(start),
                           "to_date": _d(end)}, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    if not isinstance(j, dict) or "data" not in j:
        raise SplitCheckFailed(f"{start}..{end}: answer has no data key")
    return j["data"] or []


def row_key(x: dict) -> tuple:
    """Identity of a disclosure, for de-duplication and the split check."""
    return (x.get("did"), x.get("pid"), x.get("symbol"), x.get("date"),
            x.get("secAcq"), x.get("acqName"))


def fetch_window(s: requests.Session, start: date, end: date,
                 sleep: float = 0.7, timeout: int = 120) -> tuple:
    """(rows, deficit) for [start, end] -- the UNION of the whole window and
    its two halves, and how many rows the whole-window answer was missing.

    The source reports no count, so a truncated answer is otherwise
    indistinguishable from a quiet month, and asking the same question two
    ways is the only check available. Run over 2015-2026 on 2026-09-23 it
    found four months where NSE's whole-month answer genuinely drops rows
    the halves return: 2023-09 by 7, 2023-12 by 1, 2024-10 by 2 and
    2025-03 by 64. The deficit is real and reproducible, so the union is
    the better record and the whole-window answer alone would have lost
    those disclosures silently.

    The union only ever ADDS rows the source itself served for a sub-window
    of the same period, so nothing here invents a disclosure.
    """
    whole = _raw(s, start, end, timeout)
    if start == end:
        return whole, 0
    mid = start + (end - start) / 2
    time.sleep(sleep)
    h1 = _raw(s, start, mid, timeout)
    time.sleep(sleep)
    h2 = _raw(s, mid + pd.Timedelta(days=1), end, timeout)
    seen, out = set(), []
    for r in list(whole) + list(h1) + list(h2):
        k = row_key(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
    deficit = len(seen) - len(set(map(row_key, whole)))
    return out, deficit


def normalize(rows: List[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(rows)
    df = df.rename(columns={k: v for k, v in _FIELDS.items() if k in df.columns})
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    df["broadcast_dt"] = pd.to_datetime(df["broadcast_dt"], format="%d-%b-%Y %H:%M",
                                        errors="coerce")
    for c in ("from_dt", "to_dt", "intimation_dt"):
        df[c] = pd.to_datetime(df[c], format="%d-%b-%Y", errors="coerce")
    for c in _NUMERIC:
        df[c] = pd.to_numeric(df[c].replace({"-": None, "": None}), errors="coerce")
    df = df[COLUMNS]
    return df.drop_duplicates().reset_index(drop=True)


def month_path(root: Path, year: int, month: int) -> Path:
    return root / "nse_insider" / str(year) / f"{year}-{month:02d}.parquet"


LEDGER = "_verified.txt"


def verified_months(root: Optional[Path] = None) -> set:
    p = (root or data_dir()) / "nse_insider" / LEDGER
    return set(p.read_text(encoding="utf-8").split()) if p.exists() else set()


def _mark(root: Path, year: int, month: int) -> None:
    p = root / "nse_insider" / LEDGER
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{year}-{month:02d}\n")


def collect(start: date = FIRST_DATA_DATE, end: date = LAST_DATA_DATE,
            root: Optional[Path] = None, sleep: float = 0.7) -> dict:
    """Backfill by month, idempotent, split-checked. One worker."""
    root = root or data_dir()
    s = _session()
    done = verified_months(root)
    stats = {"months": 0, "rows": 0, "empty": 0, "skipped": 0, "failed": 0,
             "whole_window_deficit_rows": 0, "months_with_deficit": 0}
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        tag = f"{y}-{m:02d}"
        if tag in done:
            stats["skipped"] += 1
        else:
            a = max(start, date(y, m, 1))
            b = min(end, date(y, m, calendar.monthrange(y, m)[1]))
            try:
                raw, deficit = fetch_window(s, a, b, sleep)
                df = normalize(raw)
                if deficit:
                    stats["whole_window_deficit_rows"] += deficit
                    stats["months_with_deficit"] += 1
                p = month_path(root, y, m)
                p.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(p, index=False)
                _mark(root, y, m)
                stats["months"] += 1
                stats["rows"] += len(df)
                if not len(df):
                    stats["empty"] += 1
            except Exception as e:
                stats["failed"] += 1
                lp = root / "nse_insider" / "_log.jsonl"
                lp.parent.mkdir(parents=True, exist_ok=True)
                with open(lp, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"month": tag, "error": repr(e),
                                        "ts": datetime.utcnow().isoformat()}) + "\n")
            time.sleep(sleep)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return stats


def load(root: Optional[Path] = None) -> pd.DataFrame:
    root = root or data_dir()
    files = sorted((root / "nse_insider").glob("*/*.parquet"))
    if not files:
        raise FileNotFoundError("nse_insider not collected")
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
