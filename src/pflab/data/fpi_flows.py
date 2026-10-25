"""Daily FPI (FII) net investment, from NSDL's archive (E2-B shock factor).

NSDL's "Daily Trends in FPI Investments" archive
(https://www.fpi.nsdl.co.in/web/Reports/Archive.aspx) is an ASP.NET form:
posting a date returns every reporting date of that month up to it, one
block per date --

    Reporting Date | Debt/Equity | Investment Route | Gross Purchases |
    Gross Sales | Net Investment (Rs Crore) | Net (US$ mn) | 1 USD to INR

-- so one post per month (its last day) fetches the month. Negative values
are printed in parentheses. NSE's `api/fiidiiTradeReact` serves only the
latest day, so NSDL is the only free history.

Point-in-time: NSDL says a reporting date's data "is compiled on the basis
of reports submitted to depositories by Custodians on" that date and covers
trades "on and up to the previous trading day(s)". So the row dated D is
knowable at the end of D, and describes trading before D. Key on
`report_date`, never on the trade date.

The site drops TLS connections that do not look like a browser, so the
session sends full browser headers (found 2026-09-22).

Output: data/macro/FPI_DAILY.parquet -- report_date, asset, route,
gross_purchase_cr, gross_sale_cr, net_cr, net_usd_mn, usd_inr.
`asset` is the table's own label (Equity, Debt, and whatever classes later
years add); `route` is Stock Exchange / Primary market & others / Sub-total
/ Total, as printed.
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import data_dir

URL = "https://www.fpi.nsdl.co.in/web/Reports/Archive.aspx"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
           "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9"}
ROUTES = ("Stock Exchange", "Primary market & others", "Sub-total", "Total")
COLS = ["report_date", "asset", "route", "gross_purchase_cr", "gross_sale_cr",
        "net_cr", "net_usd_mn", "usd_inr"]
_DATE = re.compile(r"^\d{2}-[A-Z][a-z]{2}-\d{4}$")
_NUM = re.compile(r"^\(?-?[\d,]*\.?\d+\)?$")


def _num(s: str) -> float:
    neg = s.startswith("(") and s.endswith(")")
    v = float(s.strip("()").replace(",", ""))
    return -v if neg else v


def _cells(html: str) -> list:
    html = re.sub(r"&nbsp;?", " ", html.replace("&amp;", "&"))
    parts = (re.sub(r"\s+", " ", p).strip() for p in re.split(r"<[^>]+>", html))
    return [p for p in parts if p]


def parse(html: str) -> pd.DataFrame:
    """The cash (equity/debt) table only. Raises if the table is missing."""
    cells = _cells(html)
    try:
        i = next(k for k, c in enumerate(cells) if c.startswith("Daily Trends in FPI Investments"))
    except StopIteration:
        raise ValueError("NSDL answer has no 'Daily Trends in FPI Investments' table")
    end = next((k for k in range(i + 1, len(cells))
                if cells[k].startswith("Daily Trends") or cells[k].startswith("The data presented")),
               len(cells))
    rows, day, asset, fx = [], None, None, None
    k = i + 1
    while k < end:
        c = cells[k]
        if _DATE.match(c):
            day, asset, fx = datetime.strptime(c, "%d-%b-%Y").date(), None, None
        elif c in ROUTES and day is not None:
            nums = []
            while k + 1 < end and len(nums) < 4 and _NUM.match(cells[k + 1]):
                k += 1
                nums.append(_num(cells[k]))
            if len(nums) != 4:
                raise ValueError(f"{day} {asset} {c}: expected 4 numbers, got {nums}")
            if k + 1 < end and cells[k + 1].startswith("Rs."):
                k += 1
                fx = float(cells[k][3:].replace(",", ""))
            rows.append([day, asset if c != "Total" else "Total", c, *nums, fx])
        elif day is not None and not _NUM.match(c) and not c.startswith("Rs."):
            asset = c                                  # Equity, Debt, ... as printed
        k += 1
    df = pd.DataFrame(rows, columns=COLS)
    if not df.empty and df["usd_inr"].isna().all():
        raise ValueError("no conversion rate parsed: the table layout changed")
    return df


def _form(s: requests.Session) -> dict:
    t = s.get(URL, timeout=60).text
    return dict(re.findall(r'<input[^>]*name="([^"]+)"[^>]*value="([^"]*)"', t))


def fetch_month(s: requests.Session, month_end: date) -> pd.DataFrame:
    d = month_end.strftime("%d-%b-%Y")
    f = _form(s)
    f.update({"__EVENTTARGET": "btnSubmit1", "__EVENTARGUMENT": "",
              "hdnDate": d, "txtDate": d, "hdnFlag": ""})
    r = s.post(URL, data=f, headers={"Referer": URL}, timeout=120)
    r.raise_for_status()
    df = parse(r.text)
    return df[(df["report_date"] >= month_end.replace(day=1)) & (df["report_date"] <= month_end)]


def collect(start: date = date(2009, 1, 1), end: Optional[date] = None,
            root: Optional[Path] = None, pause: float = 1.5, merge: bool = False) -> dict:
    """Month by month; a month that fails three times is recorded, not fatal.
    Rewrites the whole file each run (the history is small); S63: `merge` keeps the rows outside the months fetched
    (the daily job fetches the last two months only)."""
    end = end or date.today()
    s = requests.Session()
    s.headers.update(HEADERS)
    frames, failed = [], []
    m = date(start.year, start.month, 1)
    while m <= end:
        nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
        me = min(nxt - timedelta(days=1), end)
        for attempt in range(3):
            try:
                frames.append(fetch_month(s, me))
                break
            except Exception as e:
                if attempt == 2:
                    failed.append((str(m), repr(e)[:200]))
                time.sleep(5 * (attempt + 1))
                s = requests.Session()
                s.headers.update(HEADERS)
        m = nxt
        time.sleep(pause)
    df = (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLS))
    old_p = (root or data_dir()) / "macro" / "FPI_DAILY.parquet"
    if merge and old_p.exists():
        old = pd.read_parquet(old_p)
        got = set(pd.to_datetime(df["report_date"]).dt.to_period("M")) if len(df) else set()
        keep = old[~pd.to_datetime(old["report_date"]).dt.to_period("M").isin(got)]
        df = pd.concat([keep, df], ignore_index=True)
    df = df.drop_duplicates(["report_date", "asset", "route"]).sort_values(
        ["report_date", "asset", "route"]).reset_index(drop=True)
    p = (root or data_dir()) / "macro" / "FPI_DAILY.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    return {"path": str(p), "rows": len(df), "days": int(df["report_date"].nunique()),
            "first": str(df["report_date"].min()), "last": str(df["report_date"].max()),
            "assets": sorted(df["asset"].dropna().unique().tolist()), "failed": failed}


def load(root: Optional[Path] = None) -> pd.DataFrame:
    return pd.read_parquet((root or data_dir()) / "macro" / "FPI_DAILY.parquet")
