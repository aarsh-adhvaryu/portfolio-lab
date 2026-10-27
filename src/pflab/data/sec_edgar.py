"""SEC EDGAR for the US sleeve (S64 Phase 6 item 3): filings with their ACCEPTANCE time, and XBRL company facts, point in time.

    submissions   the company's filings (8-K, 10-Q, 10-K ...) with the exact time the SEC accepted each: a filing is known to the
                  market from that moment, so that is the point-in-time stamp (the same discipline as the dissemination time of
                  a BSE announcement)
    facts_pit     one XBRL concept (EPS, revenue, net income) as it was known on a date: only facts whose filing was accepted by
                  then; for a period restated later, the value of the latest filing accepted on or before the date
SEC's fair-access rule: a User-Agent that names who is asking, and at most 10 requests a second (this module waits 0.15 s).
Output is cached under data/us/sec/. Public data; nothing of the investor's leaves the PC.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd
import requests

from pflab.data import data_dir

DEFAULT_USER_AGENT = "portfolio-lab portfolio-lab@users.noreply.github.com"      # SEC answered 403 to this one (2026-10-27)
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
PAUSE = 0.15
FORMS = ("8-K", "10-Q", "10-K", "6-K", "20-F", "40-F", "S-1", "424B4")


class SecRefused(RuntimeError):
    pass


def user_agent() -> str:
    """The contact SEC asks every automated client to send: PFLAB_SEC_USER_AGENT, else [sec] user_agent in the secrets file (the
    investor's own contact, which he chooses: it goes to SEC with every request), else the default, which SEC has refused."""
    import os
    if os.environ.get("PFLAB_SEC_USER_AGENT"):
        return os.environ["PFLAB_SEC_USER_AGENT"]
    try:
        from pflab.pm import secrets
        s = secrets.load()
        if s.has("sec", "user_agent"):
            return s.get("sec", "user_agent")
    except Exception:
        pass
    return DEFAULT_USER_AGENT


def get_json(url: str, timeout: int = 60) -> dict:
    time.sleep(PAUSE)
    r = requests.get(url, headers={"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}, timeout=timeout)
    if r.status_code in (403, 429):
        raise SecRefused(f"SEC answered {r.status_code}: it wants a real contact in the User-Agent (fair-access policy). Set "
                         "[sec] user_agent in the secrets file to 'Name contact@address'; nothing else is tried.")
    r.raise_for_status()
    return r.json()


def filings_from(j: dict) -> pd.DataFrame:
    """The recent-filings table of a submissions document, with the accepted time as a timestamp (the SEC publishes it in UTC)."""
    rc = (j.get("filings") or {}).get("recent") or {}
    if not rc.get("accessionNumber"):
        return pd.DataFrame(columns=["accn", "form", "filed", "accepted", "doc", "items"])
    df = pd.DataFrame({"accn": rc["accessionNumber"], "form": rc["form"], "filed": rc["filingDate"],
                       "accepted": rc["acceptanceDateTime"], "doc": rc.get("primaryDocument", [""] * len(rc["form"])),
                       "items": rc.get("items", [""] * len(rc["form"]))})
    df["filed"] = pd.to_datetime(df["filed"]).dt.date
    df["accepted"] = pd.to_datetime(df["accepted"], utc=True, errors="coerce").dt.tz_localize(None)
    return df.sort_values("accepted").reset_index(drop=True)


def submissions(cik: int, root: Optional[Path] = None, get: Callable = get_json, refresh: bool = True) -> pd.DataFrame:
    root = root or data_dir()
    p = root / "us" / "sec" / f"submissions_{cik:010d}.parquet"
    if p.exists() and not refresh:
        return pd.read_parquet(p)
    df = filings_from(get(SUBMISSIONS.format(cik=cik)))
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    return df


def new_filings(df: pd.DataFrame, since: datetime, forms=FORMS) -> pd.DataFrame:
    """Filings accepted after `since` (a naive UTC time) of the wanted forms."""
    return df[(df["accepted"] > pd.Timestamp(since)) & df["form"].isin(forms)].reset_index(drop=True)


def company_facts(cik: int, root: Optional[Path] = None, get: Callable = get_json, refresh: bool = True) -> dict:
    root = root or data_dir()
    p = root / "us" / "sec" / f"facts_{cik:010d}.json"
    if p.exists() and not refresh:
        return json.loads(p.read_text(encoding="utf-8"))
    j = get(FACTS.format(cik=cik))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(j), encoding="utf-8")
    return j


def facts_pit(facts: dict, filings: pd.DataFrame, concept: str, asof: datetime, unit: str = "USD", taxonomy: str = "us-gaap",
              form_prefix: Optional[str] = None) -> pd.DataFrame:
    """The concept's reported values as known at `asof` (naive UTC): each period end (and duration) with the value from the
    latest filing accepted on or before `asof`. Columns: start, end, val, accn, form, filed, accepted."""
    items = ((facts.get("facts") or {}).get(taxonomy) or {}).get(concept, {}).get("units", {}).get(unit, [])
    if not items:
        return pd.DataFrame(columns=["start", "end", "val", "accn", "form", "filed", "accepted"])
    f = pd.DataFrame(items)
    acc = filings.set_index("accn")["accepted"]
    f["accepted"] = f["accn"].map(acc)
    f = f[f["accepted"].notna() & (f["accepted"] <= pd.Timestamp(asof))]
    if form_prefix:
        f = f[f["form"].astype(str).str.startswith(form_prefix)]
    f = f.assign(start=f.get("start"))
    f = f.sort_values("accepted").drop_duplicates(["start", "end"], keep="last")
    return f[["start", "end", "val", "accn", "form", "filed", "accepted"]].sort_values("end").reset_index(drop=True)
