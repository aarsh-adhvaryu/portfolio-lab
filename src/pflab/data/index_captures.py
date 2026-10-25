"""Internet Archive captures of NSE's constituent lists (charter E1b §4).

A capture is worth more than any number of change notices: it pins the EXACT
membership of an index on one date, with ISIN. The press releases tell you
what changed; a capture tells you what was. Together they let the walk back
be anchored every couple of years instead of once at the present, which is
the difference between an error that accumulates over twenty years and one
that is bounded inside a single segment.

They also replace the count check with something stronger. Counting members
and comparing to the index's fixed size catches a missing change; comparing
the reconstructed set to the captured set on the same date catches a WRONG
one, which counting never can.

Where the captures are
----------------------
NSE renamed these files when it renamed the indices, so each canonical index
carries every filename it has used:

    Nifty 100        ind_cnx100list.csv      2006-2015
                     ind_nifty100list.csv    2017-2026
    Nifty 500        ind_cnx500list.csv      2006-2015
                     ind_nifty500list.csv    2018-2026
    Nifty Midcap 100 ind_cnxmidcaplist.csv   2006-2015
                     ind_niftymidcap100list.csv  2019-2026
    Nifty 200        ind_nifty200list.csv    2017-2023

Nifty 200 has no capture before 2017 because the index did not exist before
2011 and nobody archived it early. Its pre-2011 membership therefore still
comes from the union of its two parents, but both of those ARE captured from
2006, so the union is anchored even where Nifty 200 itself is not.

Nifty 50 and Nifty Next 50 are collected too, not as universes but as a
cross-check: Nifty 100 is by construction their union.
"""
from __future__ import annotations

import io
import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

from pflab.data import data_dir

CDX_URL = "http://web.archive.org/cdx/search/cdx"
WAYBACK = "http://web.archive.org/web/{ts}id_/{url}"
HEADERS = {"User-Agent": "Mozilla/5.0 (portfolio-lab research)"}

# Every filename each index has used, oldest naming first.
CAPTURE_FILES: Dict[str, List[str]] = {
    "NIFTY100": ["ind_cnx100list.csv", "ind_nifty100list.csv"],
    "NIFTY500": ["ind_cnx500list.csv", "ind_nifty500list.csv"],
    "NIFTY_MIDCAP100": ["ind_cnxmidcaplist.csv", "ind_niftymidcap100list.csv"],
    "NIFTY200": ["ind_nifty200list.csv"],
    # cross-check only: Nifty 100 == Nifty 50 + Nifty Next 50
    "NIFTY50": ["ind_nifty50list.csv", "ind_cnxniftylist.csv"],
    "NIFTY_NEXT50": ["ind_niftynext50list.csv", "ind_cnxniftyjuniorlist.csv"],
}

HOSTS = ["nseindia.com/content/indices/",
         "www.nseindia.com/content/indices/",
         "archives.nseindia.com/content/indices/",
         "niftyindices.com/IndexConstituent/",
         "www.niftyindices.com/IndexConstituent/"]


class CaptureUnreadable(RuntimeError):
    """The capture exists but is not a constituent list."""


def _cdx(params: dict, tries: int = 5):
    for i in range(tries):
        try:
            r = requests.get(CDX_URL, params=params, headers=HEADERS, timeout=120)
            if r.status_code == 200:
                txt = r.text.strip()
                if not txt:
                    return []
                if txt.startswith("["):
                    return r.json()
        except Exception:
            pass
        time.sleep(3 * (i + 1))
    return None


def _file_to_index() -> dict:
    return {f: idx for idx, files in CAPTURE_FILES.items() for f in files}


def capture_index(root: Optional[Path] = None, refresh: bool = False) -> pd.DataFrame:
    """Every archived capture of every constituent list we care about.

    Enumerated by PREFIX, one call per host, rather than one call per
    (host, filename) pair. The per-file form needs sixty calls, most of which
    are for combinations that never existed, and the CDX endpoint rate-limits
    long before they finish. The prefix form is five calls and returns strictly
    more -- including filenames we did not think to ask for.

    `collapse=digest` means consecutive identical captures collapse to the
    first, so each row is a distinct STATE of the list rather than a re-crawl
    of the same bytes.
    """
    root = root or data_dir()
    cache = root / "index_membership" / "raw" / "captures_index.parquet"
    if cache.exists() and not refresh:
        return pd.read_parquet(cache)

    wanted = _file_to_index()
    rows = []
    for host in HOSTS:
        d = _cdx({"url": host + "*", "output": "json",
                  "fl": "timestamp,original,statuscode,digest",
                  "collapse": "digest", "limit": "20000"})
        if not d or len(d) < 2:
            continue
        for ts, orig, status, digest in d[1:]:
            if status != "200":
                continue
            fname = orig.lower().rsplit("/", 1)[-1].split("?")[0]
            idx = wanted.get(fname)
            if not idx:
                continue
            rows.append({"index": idx, "file": fname, "timestamp": ts,
                         "date": datetime.strptime(ts[:8], "%Y%m%d").date(),
                         "url": orig, "digest": digest})
        time.sleep(2)

    df = pd.DataFrame(rows, columns=["index", "file", "timestamp", "date",
                                     "url", "digest"])
    if len(df):
        df = (df.sort_values(["index", "date", "timestamp"])
                .drop_duplicates(["index", "digest"], keep="first")
                .reset_index(drop=True))
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache, index=False)
    return df


def fetch_capture(timestamp: str, url: str, root: Optional[Path] = None,
                  refresh: bool = False) -> bytes:
    root = root or data_dir()
    name = f"{timestamp}_{url.rsplit('/', 1)[-1]}"
    p = root / "index_membership" / "raw" / "captures" / name
    if refresh or not p.exists() or p.stat().st_size == 0:
        # The Wayback replay host returns a transient 502 "Connection refused"
        # often enough that a single attempt loses about half the captures.
        last = None
        for i in range(5):
            try:
                r = requests.get(WAYBACK.format(ts=timestamp, url=url),
                                 headers=HEADERS, timeout=180)
                r.raise_for_status()
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(r.content)
                last = None
                break
            except Exception as e:
                last = e
                time.sleep(4 * (i + 1))
        if last is not None:
            raise last
    return p.read_bytes()


def parse_capture(content: bytes) -> pd.DataFrame:
    """One capture -> symbol, isin, company.

    The old files carry a title line above the header ("Constituents list of
    CNX 100,,,,"), so the header row has to be found rather than assumed.
    """
    text = content.decode("utf-8", errors="replace")
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines[:10]):
        low = ln.lower()
        if "symbol" in low and ("isin" in low or "company" in low):
            start = i
            break
    if start is None:
        raise CaptureUnreadable("no header row with Symbol and ISIN/Company")
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    df.columns = [c.strip() for c in df.columns]
    ren = {"Symbol": "symbol", "ISIN Code": "isin", "Company Name": "company"}
    df = df.rename(columns=ren)
    for c in ("symbol", "isin"):
        if c not in df.columns:
            raise CaptureUnreadable(f"capture has no {c} column")
        df[c] = df[c].astype(str).str.strip()
    df = df[df["isin"].str.match(r"^IN[EF0-9]")]
    if df.empty:
        raise CaptureUnreadable("no rows with a usable ISIN")
    keep = [c for c in ("symbol", "isin", "company") if c in df.columns]
    return df[keep].reset_index(drop=True)


def collect(root: Optional[Path] = None, refresh: bool = False) -> tuple:
    """Download and parse every capture. (dict index -> {date: DataFrame}, report)."""
    idx = capture_index(root, refresh)
    out: Dict[str, Dict[date, pd.DataFrame]] = {}
    report = {"captures_listed": int(len(idx)), "parsed": 0, "failed": [],
              "by_index": {}}
    for r in idx.itertuples(index=False):
        try:
            df = parse_capture(fetch_capture(r.timestamp, r.url, root))
        except Exception as e:
            report["failed"].append({"index": r.index, "date": str(r.date),
                                     "file": r.file,
                                     "error": f"{type(e).__name__}: {e}"})
            continue
        out.setdefault(r.index, {})[r.date] = df
        report["parsed"] += 1
    for k, v in out.items():
        ds = sorted(v)
        report["by_index"][k] = {
            "captures": len(ds), "first": str(ds[0]), "last": str(ds[-1]),
            "dates": [str(d) for d in ds],
            "sizes": {str(d): int(len(v[d])) for d in ds},
        }
    return out, report


def write(captures: dict, root: Optional[Path] = None) -> Path:
    root = root or data_dir()
    d = root / "index_membership" / "captures"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, by_date in captures.items():
        for dt, df in by_date.items():
            x = df.copy()
            x["index"] = index
            x["capture_date"] = dt
            rows.append(x)
    out = (pd.concat(rows, ignore_index=True) if rows
           else pd.DataFrame(columns=["symbol", "isin", "company", "index",
                                      "capture_date"]))
    p = root / "index_membership" / "captures.parquet"
    out.to_parquet(p, index=False)
    return p


def load(root: Optional[Path] = None) -> dict:
    root = root or data_dir()
    df = pd.read_parquet(root / "index_membership" / "captures.parquet")
    df["capture_date"] = pd.to_datetime(df["capture_date"]).dt.date
    out: Dict[str, Dict[date, pd.DataFrame]] = {}
    for (index, dt), g in df.groupby(["index", "capture_date"]):
        out.setdefault(index, {})[dt] = g[["symbol", "isin"]].reset_index(drop=True)
    return out


def exact_list_check(table: pd.DataFrame, index: str, captures: dict) -> dict:
    """Reconstructed membership against the captured list, on capture dates.

    This is strictly stronger than the count check: counting catches a missing
    change, comparing sets catches a wrong one too. `missing` is a name the
    capture has and we do not; `extra` is one we invented.
    """
    from pflab.data.index_membership import members_at
    by_date = (captures or {}).get(index) or {}
    per = {}
    for d in sorted(by_date):
        truth = set(by_date[d]["isin"])
        got = members_at(table, index, d)
        per[str(d)] = {
            "captured": len(truth), "reconstructed": len(got),
            "agree": len(truth & got),
            "missing": sorted(truth - got)[:20],
            "n_missing": len(truth - got),
            "extra": sorted(got - truth)[:20],
            "n_extra": len(got - truth),
            "exact": truth == got,
        }
    n = len(per)
    return {"index": index, "dates": n,
            "exact": sum(1 for v in per.values() if v["exact"]),
            "worst": max((v["n_missing"] + v["n_extra"] for v in per.values()),
                         default=0),
            "per_date": per}


def union_identity_check(captures: dict) -> dict:
    """Is Nifty 200 really Nifty 100 + Nifty Midcap 100 on a given date?

    NSE's methodology (September 2026 edition) says it is, and E1b §4 leans on
    that to derive the pre-2011 years. The captures say it became true only at
    the 2016 restructure. On dates where both parents were captured:

        2010-01-02   Nifty 100 = 100, Midcap = 100, OVERLAP 27, union 173
        2014-01-22   Nifty 100 = 100, Midcap = 100, OVERLAP 32, union 168
        2026-08-27   Nifty 100 = 100, Midcap = 100, overlap  0, union 200

    Before April 2016 the old CNX Midcap was an independently selected index
    that shared names with CNX 100; only the restructure made the two a
    partition. So the union derivation is valid from the restructure onward
    and is NOT evidence about 2007. This function is what says so, from data
    rather than from the methodology PDF's present tense.
    """
    n100 = (captures or {}).get("NIFTY100") or {}
    mid = (captures or {}).get("NIFTY_MIDCAP100") or {}
    rows = []
    for d in sorted(set(n100) & set(mid)):
        a, b = set(n100[d]["isin"]), set(mid[d]["isin"])
        rows.append({"date": str(d), "nifty100": len(a), "midcap100": len(b),
                     "overlap": len(a & b), "union": len(a | b),
                     "disjoint": not (a & b)})
    first_disjoint = next((r["date"] for r in rows if r["disjoint"]), None)
    last_overlap = next((r["date"] for r in reversed(rows)
                         if not r["disjoint"]), None)
    return {"comparisons": len(rows), "detail": rows,
            # both parents are captured on only a handful of the same days, so
            # the transition is BRACKETED, not pinned: it happened after the
            # last date they overlapped and by the first date they did not.
            "last_seen_overlapping": last_overlap,
            "first_seen_disjoint": first_disjoint,
            "documented_cause": ("NSE's 2016-02-22 restructure, effective "
                                 "2016-04-01, which redefined the mid-cap "
                                 "segment as ranks 101-250 of Nifty 500"),
            "note": ("the union derivation is valid only where the two parents "
                     "are disjoint; before that they share names and the union "
                     "is SMALLER than Nifty 200, so it is not evidence about "
                     "the pre-2016 years")}


def cross_check_nifty100(captures: dict) -> dict:
    """Nifty 100 is by construction Nifty 50 + Nifty Next 50.

    Checked wherever all three were captured within a week of each other. A
    disagreement means one of the three captures is not what it claims to be,
    which no amount of parsing care would otherwise reveal.
    """
    n100 = (captures or {}).get("NIFTY100") or {}
    n50 = (captures or {}).get("NIFTY50") or {}
    nn50 = (captures or {}).get("NIFTY_NEXT50") or {}
    out = []
    for d in sorted(n100):
        near50 = min(n50, key=lambda x: abs((x - d).days), default=None)
        nearn = min(nn50, key=lambda x: abs((x - d).days), default=None)
        if near50 is None or nearn is None:
            continue
        if abs((near50 - d).days) > 7 or abs((nearn - d).days) > 7:
            continue
        a = set(n100[d]["isin"])
        b = set(n50[near50]["isin"]) | set(nn50[nearn]["isin"])
        out.append({"date": str(d), "nifty100": len(a), "union_50_next50": len(b),
                    "agree": len(a & b), "exact": a == b,
                    "only_in_100": len(a - b), "only_in_union": len(b - a)})
    return {"comparisons": len(out),
            "exact": sum(1 for x in out if x["exact"]), "detail": out}
