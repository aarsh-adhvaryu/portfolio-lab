"""BSE corporate announcements collector (E2-A).

Backs the announcements page on bseindia.com. Point-in-time key is the
dissemination timestamp. A day is written only when its rows match the
API's own count (Table1.ROWCNT); see IncompleteDay.

Schema (one parquet per day under data/bse_announcements/YYYY/):
  scrip_code, company, headline, category, subcategory, news_dt,
  dissem_dt, attachment, news_sub
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd
import requests

from pflab.data import data_dir

URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}
_FIELDS = {"SCRIP_CD": "scrip_code", "SLONGNAME": "company", "HEADLINE": "headline",
           "CATEGORYNAME": "category", "SUBCATNAME": "subcategory", "NEWS_DT": "news_dt",
           "DissemDT": "dissem_dt", "ATTACHMENTNAME": "attachment", "NEWSSUB": "news_sub"}
COLUMNS = list(_FIELDS.values())


class IncompleteDay(RuntimeError):
    """A day's response does not add up, so the day is NOT written.

    Found 2026-09-22 during the 2010-onward backfill: under sustained load
    the API sometimes answers with a single all-null row, or stops paging
    early, instead of refusing. The first version wrote those answers as if
    they were the day -- 523 blank day files -- and, because `collect` skips
    any day whose file exists, they would never have been retried. Every
    response now carries the day's total in Table1.ROWCNT, which equals the
    number of unique announcements over all pages (checked on 2025-07-15:
    1,239 of 1,239); a day is kept only if it matches.
    """


def _page(d: date, page: int, session: requests.Session, timeout: int) -> dict:
    ds = d.strftime("%Y%m%d")
    params = {"pageno": page, "strCat": "-1", "strPrevDate": ds, "strScrip": "",
              "strSearch": "P", "strToDate": ds, "strType": "C", "subcategory": "-1"}
    r = session.get(URL, params=params, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()


def expected_count(j: dict) -> int:
    """The day's announcement count from Table1.ROWCNT. A response without it
    is not trusted -- a genuinely empty day still reports ROWCNT 0."""
    t1 = j.get("Table1") or []
    if not t1 or "ROWCNT" not in t1[0]:
        raise IncompleteDay("response has no Table1.ROWCNT")
    return int(t1[0]["ROWCNT"])


def fetch_day(d: date, session: requests.Session, max_pages: int = 400,
              timeout: int = 30, page_sleep: float = 0.4) -> List[dict]:
    """Every announcement disseminated on `d`, or IncompleteDay."""
    rows: List[dict] = []
    seen = set()
    expected = None
    for page in range(1, max_pages + 1):
        j = _page(d, page, session, timeout)
        if expected is None:
            expected = expected_count(j)
            if expected == 0:
                return []
        table = j.get("Table") or []
        if any(not x.get("NEWSID") for x in table):
            raise IncompleteDay(f"{d}: page {page} returned a row with no NEWSID "
                                f"(a throttled or malformed answer)")
        for x in table:
            # An announcement re-disseminated later the same day repeats its
            # NEWSID with a new DissemDT, and BSE's ROWCNT counts both. Keying
            # on NEWSID alone dropped the second copy and left the day one
            # short of its own count for ever (2015-08-29: Andhra Cements
            # results at 14:58:51 and again at 15:10:13). Found 2026-09-23.
            key = (x["NEWSID"], x.get("DissemDT"))
            if key not in seen:
                seen.add(key)
                rows.append(x)
        if len(rows) >= expected or len(table) < 50:
            break
        time.sleep(page_sleep)
    if len(rows) != expected:
        raise IncompleteDay(f"{d}: collected {len(rows)} of {expected} announcements")
    return rows


def verify_file(d: date, path: Path, session: requests.Session, timeout: int = 30) -> bool:
    """True if the saved day has exactly the day's count and no blank rows.
    One request (page 1) per day."""
    df = pd.read_parquet(path)
    if len(df) and df["scrip_code"].isna().any():
        return False
    return len(df) == expected_count(_page(d, 1, session, timeout))


def normalize(rows: List[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    df = pd.DataFrame(rows)
    keep = {k: v for k, v in _FIELDS.items() if k in df.columns}
    df = df.rename(columns=keep)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = None
    for c in ("news_dt", "dissem_dt"):
        df[c] = pd.to_datetime(df[c], errors="coerce")
    df["scrip_code"] = df["scrip_code"].astype(str)
    return df[COLUMNS].reset_index(drop=True)


LEDGER = "_verified.txt"


def verified_days(root: Optional[Path] = None) -> set:
    """Days whose file is known good: written by the count-checked collector,
    or re-checked against the API's count. One ISO date per line."""
    p = (root or data_dir()) / "bse_announcements" / LEDGER
    return set(p.read_text(encoding="utf-8").split()) if p.exists() else set()


def _mark_verified(root: Path, d: date) -> None:
    p = root / "bse_announcements" / LEDGER
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(d.isoformat() + "\n")


def collect(start: date, end: date, root: Optional[Path] = None, sleep: float = 0.8,
            verify: bool = False) -> dict:
    """Fetch every day in [start, end] that has no file yet. Idempotent.

    With `verify`, a day that already has a file is checked against the API's
    count first and re-fetched if it does not match -- the way to repair a
    backfill written before IncompleteDay existed.
    """
    root = root or data_dir()
    s = requests.Session()
    stats = {"ok": 0, "empty": 0, "error": 0, "verified": 0, "repaired": 0,
             "unverified": 0}
    done = verified_days(root)
    d = start
    while d <= end:
        out = root / "bse_announcements" / str(d.year) / f"{d.isoformat()}.parquet"
        if out.exists() and verify and d.isoformat() not in done:
            try:
                if verify_file(d, out, s):
                    stats["verified"] += 1
                    _mark_verified(root, d)
                else:
                    out.unlink()
                    stats["repaired"] += 1
            except Exception:
                # a throttled answer to the CHECK: the file stays, still
                # unverified, and the next pass checks it again
                stats["unverified"] += 1
            time.sleep(sleep)
        if not out.exists():
            try:
                df = normalize(fetch_day(d, s))
                out.parent.mkdir(parents=True, exist_ok=True)
                df.to_parquet(out, index=False)
                _mark_verified(root, d)          # checked against ROWCNT on the way in
                stats["ok" if len(df) else "empty"] += 1
            except Exception as e:
                stats["error"] += 1
                lp = root / "bse_announcements" / "_log.jsonl"
                lp.parent.mkdir(parents=True, exist_ok=True)
                with open(lp, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"date": d.isoformat(), "error": repr(e),
                                        "ts": datetime.utcnow().isoformat()}) + "\n")
            time.sleep(sleep)
        d += timedelta(days=1)
    return stats
