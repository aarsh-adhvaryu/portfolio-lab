"""GDELT 2.0 events, India-filtered, daily aggregate (E2-B, E2-C).

Backfill from BigQuery (tools/gdelt_bigquery.sql, Phase 1 task 1.6).
Daily job: the 96 fifteen-minute export files for a date, English and
translingual feeds both (see FEEDS). Column
positions follow the GDELT 2.0 events codebook; VERIFY once against a
real file.

Schema (data/gdelt/daily/YYYY-MM-DD.parquet): one row per event with the
kept columns; plus data/gdelt/agg/YYYY-MM-DD.parquet with daily
aggregates (n_events, n_articles, mean_tone, mean_goldstein, share by
QuadClass).
"""
from __future__ import annotations

import io
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import data_dir

BASE = "http://data.gdeltproject.org/gdeltv2/{stamp}.export.CSV.zip"
# GDELT 2.0 publishes TWO event feeds per fifteen minutes: English and
# translingual (65 languages, machine-translated). BigQuery's gdeltv2.events
# holds both, so the backfill (tools/gdelt_bigquery.sql) counts both, and the
# live job must too. Found 2026-09-22: English alone gave 6,424 India events
# for 2026-09-14; English + translation gave 7,547, BigQuery's count exactly.
FEEDS = (BASE, "http://data.gdeltproject.org/gdeltv2/{stamp}.translation.export.CSV.zip")
# Verified against a live export 2026-09-16 (the docstring's "VERIFY once").
# Column 51 is ActionGeo_Type, a 0-5 enum, NOT the country code: it matched no
# India rows at all. ActionGeo_CountryCode is column 53.
KEEP = {0: "event_id", 1: "sqldate", 7: "a1_country", 17: "a2_country", 26: "event_code",
        28: "root_code", 29: "quad_class", 30: "goldstein", 31: "n_mentions", 32: "n_sources",
        33: "n_articles", 34: "avg_tone", 53: "action_country", 59: "date_added", 60: "source_url"}
INDIA_ACTOR = "IND"   # ISO-3 in actor country codes
INDIA_GEO = "IN"      # FIPS in ActionGeo_CountryCode


def _filter(df: pd.DataFrame) -> pd.DataFrame:
    m = (df["a1_country"].eq(INDIA_ACTOR) | df["a2_country"].eq(INDIA_ACTOR)
         | df["action_country"].eq(INDIA_GEO))
    return df[m]


def parse_export(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = z.namelist()[0]
        try:
            df = pd.read_csv(z.open(name), sep="\t", header=None, dtype=str, usecols=list(KEEP),
                             on_bad_lines="skip", quoting=3)
        except pd.errors.EmptyDataError:     # GDELT sometimes publishes an empty 15-minute file (seen 2026-10-15)
            return pd.DataFrame(columns=list(KEEP.values()))
    df = df.rename(columns=KEEP)
    for c in ("goldstein", "avg_tone"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in ("n_mentions", "n_sources", "n_articles", "quad_class"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    return _filter(df)


def aggregate(df: pd.DataFrame, d: date) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame([{"date": d, "n_events": 0, "n_articles": 0, "mean_tone": None,
                              "mean_goldstein": None, "q1": 0, "q2": 0, "q3": 0, "q4": 0}])
    qc = df["quad_class"].value_counts()
    return pd.DataFrame([{"date": d, "n_events": len(df), "n_articles": int(df["n_articles"].fillna(0).sum()),
                          "mean_tone": float(df["avg_tone"].mean()),
                          "mean_goldstein": float(df["goldstein"].mean()),
                          **{f"q{i}": int(qc.get(i, 0)) for i in (1, 2, 3, 4)}}])


def collect_day(d: date, root: Optional[Path] = None, sleep: float = 0.2) -> dict:
    root = root or data_dir()
    out_ev = root / "gdelt" / "daily" / f"{d.isoformat()}.parquet"
    out_ag = root / "gdelt" / "agg" / f"{d.isoformat()}.parquet"
    if out_ev.exists() and out_ag.exists():
        return {"skipped": True}
    s = requests.Session()
    frames = []
    missing = 0
    for slot in range(96):
        t = datetime(d.year, d.month, d.day) + timedelta(minutes=15 * slot)
        for feed in FEEDS:
            r = s.get(feed.format(stamp=t.strftime("%Y%m%d%H%M%S")), timeout=60)
            if r.status_code == 200 and r.content[:2] == b"PK":
                frames.append(parse_export(r.content))
            else:
                missing += 1
            time.sleep(sleep)
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=list(KEEP.values()))
    out_ev.parent.mkdir(parents=True, exist_ok=True)
    out_ag.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_ev, index=False)
    aggregate(df, d).to_parquet(out_ag, index=False)
    return {"events": len(df), "missing_slots": missing}


def collect(start: date, end: date, root: Optional[Path] = None) -> dict:
    stats = {"days": 0, "events": 0}
    d = start
    while d <= end:
        r = collect_day(d, root)
        stats["days"] += 1
        stats["events"] += r.get("events", 0)
        d += timedelta(days=1)
    return stats
