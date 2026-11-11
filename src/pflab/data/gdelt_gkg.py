"""GDELT Global Knowledge Graph 2.1, filtered to named companies (PLAN S38).

Every 15 minutes GDELT publishes a GKG file (English, plus a translingual file): one row per article with its
URL, source, themes, locations, persons, organisations, tone and quotations. There is no article text (only
the link). Files: http://data.gdeltproject.org/gdeltv2/YYYYMMDDHHMMSS.gkg.csv.zip and .translation.gkg.csv.zip
(about 5 MB each, verified 2026-10-15). Only rows whose organisations or names match an alias are kept, so a
day of ~190 files (~1 GB downloaded) leaves a small parquet: data/gkg/YYYY-MM-DD.parquet.

GKG 2.1 columns used (codebook): 1 DATE (publish/crawl time, UTC), 3 SourceCommonName, 4 DocumentIdentifier
(URL), 7 Themes, 9 Locations, 11 Persons, 13 Organizations, 15 V2Tone (first value = tone), 22 Quotations,
23 AllNames.
"""
from __future__ import annotations

import io
import re
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

from pflab.data import data_dir

FEEDS = ("http://data.gdeltproject.org/gdeltv2/{stamp}.gkg.csv.zip",
         "http://data.gdeltproject.org/gdeltv2/{stamp}.translation.gkg.csv.zip")
COLS = {1: "date", 3: "source", 4: "url", 7: "themes", 9: "locations", 11: "persons", 13: "orgs", 15: "tone",
        22: "quotes", 23: "names"}
KEEP = ["date", "source", "url", "isins", "themes", "persons", "orgs", "tone", "quotes", "india"]


def compile_aliases(aliases: Dict[str, List[str]]) -> List[tuple]:
    """{isin: [alias, ...]} -> [(isin, regex)]; aliases match whole words, case-insensitive."""
    return [(isin, re.compile(r"\b(?:" + "|".join(re.escape(a.lower()) for a in al) + r")\b"))
            for isin, al in aliases.items() if al]


def parse(raw: bytes, rx: List[tuple]) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        try:
            df = pd.read_csv(z.open(z.namelist()[0]), sep="\t", header=None, dtype=str, quoting=3,
                             on_bad_lines="skip", encoding="latin-1", usecols=list(COLS))
        except pd.errors.EmptyDataError:
            return pd.DataFrame(columns=KEEP)
    df = df.rename(columns=COLS).fillna("")
    hay = (df["orgs"] + " ; " + df["names"]).str.lower()
    hits = [[isin for isin, r in rx if r.search(h)] for h in hay]
    df["isins"] = [";".join(h) for h in hits]
    df = df[df["isins"] != ""].copy()
    if df.empty:
        return pd.DataFrame(columns=KEEP)
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d%H%M%S", errors="coerce")
    df["tone"] = pd.to_numeric(df["tone"].str.split(",").str[0], errors="coerce")
    df["india"] = df["locations"].str.contains("#IN#|#India#", regex=True)
    trim = lambda s, n: ";".join(dict.fromkeys(x.split(",")[0] for x in s.split(";") if x)) if s else ""
    df["themes"] = df["themes"].map(lambda s: ";".join(list(dict.fromkeys(t for t in s.split(";") if t))[:15]))
    df["persons"] = df["persons"].map(lambda s: trim(s, 10))
    df["orgs"] = df["orgs"].map(lambda s: trim(s, 10))
    df["quotes"] = df["quotes"].str.slice(0, 2000)
    return df[KEEP]


def collect_day(d: date, aliases: Dict[str, List[str]], root: Optional[Path] = None, session=None,
                sleep: float = 0.2) -> dict:
    root = root or data_dir()
    out = root / "gkg" / f"{d.isoformat()}.parquet"
    if out.exists():
        return {"skipped": True}
    rx = compile_aliases(aliases)
    s = session or requests.Session()
    frames, missing = [], 0
    for slot in range(96):
        t = datetime(d.year, d.month, d.day) + timedelta(minutes=15 * slot)
        for feed in FEEDS:
            try:
                r = s.get(feed.format(stamp=t.strftime("%Y%m%d%H%M%S")), timeout=120)
            except requests.RequestException:
                missing += 1
                continue
            if r.status_code == 200 and r.content[:2] == b"PK":
                frames.append(parse(r.content, rx))
            else:
                missing += 1
            time.sleep(sleep)
    df = pd.concat(frames, ignore_index=True).drop_duplicates("url") if frames else pd.DataFrame(columns=KEEP)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return {"articles": int(len(df)), "missing_files": missing}


def load(since: date, root: Optional[Path] = None) -> pd.DataFrame:
    root = root or data_dir()
    files = sorted(p for p in (root / "gkg").glob("*.parquet") if p.stem >= since.isoformat())
    # `file_day` (S82, A58): the collection day of the file, so an item with no time of its own can be used from the next day
    return pd.concat([pd.read_parquet(p).assign(file_day=date.fromisoformat(p.stem)) for p in files], ignore_index=True) if files else pd.DataFrame(columns=KEEP + ["file_day"])
