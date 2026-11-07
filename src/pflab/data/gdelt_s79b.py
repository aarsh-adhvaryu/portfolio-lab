"""GDELT 2.0 over plain HTTP, no Google credentials (S79b agent D, written 2026-11-08).

BigQuery needs a Google login the investor may not have configured, so the public 15-minute files are read instead:
`http://data.gdeltproject.org/gdeltv2/{YYYYMMDDHHMMSS}.export.CSV.zip` (events, English) and `.translation.export.CSV.zip`
(events, machine-translated), `.gkg.csv.zip` (Global Knowledge Graph, English). Public, no key, nothing sent out.

Two products:

  1. `world_events_day` -- the daily aggregates the BigQuery queries (tools/gdelt_world_bigquery.sql and
     gdelt_world_types_bigquery.sql) produce, from ALL 192 event files of the UTC day (both feeds, as BigQuery's table
     holds both): one row per (day, ActionGeo country) with n_events, n_articles, mean_tone, mean_goldstein, q1..q4, and
     the 20 CAMEO root-code counts r01..r20. `extend_world` appends the new days to
     data/gdelt/world/daily_by_country.parquet and daily_event_types.parquet (same columns, days after the file's last).
     The bilateral table (daily_bilateral) is NOT extended: it needs actor pairs and was not asked for.
  2. `gkg_theme_day` -- per UTC day, the tone of articles by theme group (finance, energy, tech, regulation, conflict,
     trade) from a SAMPLE of the English GKG files (one file every 30 minutes, 48 a day, about 1/4 of the day's articles): the full
     set is about 1 GB a day and 35 GB for the window. Output data/gdelt_s79b/daily_theme_tone.parquet -- date, theme,
     n_docs, mean_tone, share_negative (tone < -2), n_docs_all (every sampled article), sample_files. Counts are
     sample counts: read shares and tones, not volumes, and compare a day with the days around it.

Point-in-time: a row for UTC day D uses only files stamped on D (GDELT's DATEADDED, the publication time), so it is final
once D ends; never read day D before D+1.
"""
from __future__ import annotations

import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from pflab.data import data_dir

UA = "pflab-research/1.0 (public GDELT files, research)"
BASE = "http://data.gdeltproject.org/gdeltv2/{stamp}.{kind}.zip"
EV_KINDS = ("export.CSV", "translation.export.CSV")
EV_COLS = {1: "sqldate", 28: "root", 29: "quad", 30: "gold", 33: "narts", 34: "tone", 53: "country", 59: "added"}
NUMERIC = ["gold", "narts", "tone"]
THEMES = {   # group -> predicate over a GKG V1 theme code
    "finance": lambda t: t.startswith("ECON_") and not t.startswith("ECON_OIL") or t in ("WB_332_FINANCIAL_SECTOR", "TAX_FNCACT_BANKER", "TAX_FNCACT_INVESTOR"),
    "energy": lambda t: t.startswith(("ENV_OIL", "ENV_NATURALGAS", "ENV_COAL", "ECON_OIL", "ENV_NUCLEAR", "ENV_SOLAR", "ENV_WIND")) or t in ("ENERGY", "WB_507_ENERGY_AND_EXTRACTIVES"),
    "tech": lambda t: t.startswith(("TECH_", "CYBER_")) or t in ("ARTIFICIAL_INTELLIGENCE", "WB_133_INFORMATION_AND_COMMUNICATION_TECHNOLOGIES", "SCIENCE"),
    "regulation": lambda t: t.startswith(("EPU_POLICY", "LEGISLATION", "GOV_REGULATION")) or "REGULATION" in t,
    "conflict": lambda t: t.startswith(("ARMEDCONFLICT", "MILITARY", "TERROR", "WB_2433_CONFLICT_AND_VIOLENCE", "KILL", "CRISISLEX_T03")) or t in ("WAR", "CEASEFIRE"),
    "trade": lambda t: "TRADE" in t or t.startswith(("TARIFF", "SANCTION")) or t in ("ECON_FOREIGNTRADE",),
}
NEG_TONE = -2.0


def _get(url: str, session: requests.Session, tries: int = 3):
    for a in range(tries):
        try:
            r = session.get(url, timeout=90)
            if r.status_code == 200 and r.content[:2] == b"PK":
                return r.content
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(1.5 * (a + 1))
    return None


def _parse_events(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        try:
            df = pd.read_csv(z.open(z.namelist()[0]), sep="\t", header=None, dtype=str, usecols=list(EV_COLS), on_bad_lines="skip", quoting=3)
        except pd.errors.EmptyDataError:
            return pd.DataFrame(columns=list(EV_COLS.values()))
    df = df.rename(columns=EV_COLS)
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["quad"] = pd.to_numeric(df["quad"], errors="coerce")
    return df


def aggregate_events(df: pd.DataFrame) -> tuple:
    """(by_country, event_types) frames for one batch of events; the day is the UTC date of DATEADDED."""
    df = df.copy()
    df["day"] = pd.to_datetime(df["added"].str[:8], format="%Y%m%d", errors="coerce").dt.date
    df = df.dropna(subset=["day"])
    df["country"] = df["country"].fillna("").replace("", "XX")
    g = df.groupby(["day", "country"])
    by = g.agg(n_events=("tone", "size"), n_articles=("narts", "sum"), mean_tone=("tone", "mean"), mean_goldstein=("gold", "mean")).reset_index()
    for q in (1, 2, 3, 4):
        by[f"q{q}"] = by.set_index(["day", "country"]).index.map(df[df["quad"] == q].groupby(["day", "country"]).size()).fillna(0).astype(int)
    root = pd.to_numeric(df["root"], errors="coerce")
    types = df.assign(rc=root).dropna(subset=["rc"]).groupby(["day", "country", "rc"]).size().unstack(fill_value=0)
    types = types.reindex(columns=range(1, 21), fill_value=0)
    types.columns = [f"r{int(c):02d}" for c in types.columns]
    types = types.reset_index()
    by = by.rename(columns={"day": "date"})
    types = types.rename(columns={"day": "date"})
    by["n_articles"] = by["n_articles"].astype("int64")
    return by, types


def world_events_day(d: date, workers: int = 4, session: Optional[requests.Session] = None) -> dict:
    """All 96 x 2 event files of the UTC day d, fetched with a few threads (a file missing is counted, not fatal)."""
    s = session or requests.Session()
    s.headers["User-Agent"] = UA
    t0 = datetime(d.year, d.month, d.day)
    urls = [BASE.format(stamp=(t0 + timedelta(minutes=15 * i)).strftime("%Y%m%d%H%M%S"), kind=k) for i in range(96) for k in EV_KINDS]

    def one(u):
        raw = _get(u, s)
        time.sleep(0.05)
        return None if raw is None else _parse_events(raw)

    with ThreadPoolExecutor(workers) as ex:
        parts = list(ex.map(one, urls))
    got = [p for p in parts if p is not None and len(p)]
    missing = sum(p is None for p in parts)
    if not got:
        return {"by": pd.DataFrame(), "types": pd.DataFrame(), "missing": missing, "files": len(urls)}
    by, types = aggregate_events(pd.concat(got, ignore_index=True))
    by, types = by[by["date"] == d], types[types["date"] == d]    # DATEADDED of a day's first file can carry the previous day's tail
    return {"by": by, "types": types, "missing": missing, "files": len(urls)}


def extend_world(start: date, end: date, root: Optional[Path] = None, log=print) -> dict:
    """Append days start..end (UTC, complete days only) to the world parquets, after each file's own last date."""
    root = Path(root or data_dir())
    out_dir = root / "gdelt" / "world"
    pb, pt = out_dir / "daily_by_country.parquet", out_dir / "daily_event_types.parquet"
    by_old, ty_old = pd.read_parquet(pb), pd.read_parquet(pt)
    res, d = {}, start
    end = min(end, date.today() - timedelta(days=1))
    raw_dir = root / "gdelt_s79b" / "world_days"
    raw_dir.mkdir(parents=True, exist_ok=True)
    while d <= end:
        cache_b, cache_t = raw_dir / f"by_{d}.parquet", raw_dir / f"types_{d}.parquet"
        if cache_b.exists() and cache_t.exists():
            by, ty, info = pd.read_parquet(cache_b), pd.read_parquet(cache_t), {"cached": True}
        else:
            r = world_events_day(d)
            by, ty, info = r["by"], r["types"], {"missing_files": r["missing"], "files": r["files"]}
            if len(by) and r["missing"] <= 0.1 * r["files"]:
                by.to_parquet(cache_b, index=False)
                ty.to_parquet(cache_t, index=False)
            else:
                info["note"] = "too many files missing: not kept"
                by = ty = pd.DataFrame()
        info["rows"] = len(by)
        res[str(d)] = info
        log(str(d), info)
        d += timedelta(days=1)
    for p, old, key in ((pb, by_old, "by"), (pt, ty_old, "ty")):
        frames = [pd.read_parquet(f) for f in sorted(raw_dir.glob(("by_" if key == "by" else "types_") + "*.parquet"))]
        if not frames:
            continue
        new = pd.concat(frames, ignore_index=True)
        new["date"] = pd.to_datetime(new["date"]).dt.date
        old_last = pd.to_datetime(old["date"]).dt.date.max()
        new = new[(new["date"] > old_last) & (new["date"] <= date.today() - timedelta(days=1))]
        for c in old.columns:
            if c not in new.columns:
                new[c] = 0
        merged = pd.concat([old, new[old.columns]], ignore_index=True).drop_duplicates(["date", "country"], keep="first").sort_values(["date", "country"])
        merged.to_parquet(p, index=False)
        res[f"{p.stem}_last"] = str(merged["date"].max())
    return res


# ---------------------------------------------------------------- GKG theme tone (sampled)

def _parse_gkg(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        try:
            df = pd.read_csv(z.open(z.namelist()[0]), sep="\t", header=None, dtype=str, usecols=[7, 15], on_bad_lines="skip", quoting=3,
                             encoding_errors="replace")
        except pd.errors.EmptyDataError:
            return pd.DataFrame(columns=["themes", "tone"])
    df.columns = ["themes", "tone"]
    df["tone"] = pd.to_numeric(df["tone"].str.split(",").str[0], errors="coerce")
    return df.dropna(subset=["tone"])


def tag_themes(themes: pd.Series) -> dict:
    """group -> boolean mask over the articles, on the V1 theme list (semicolon separated codes)."""
    sets = themes.fillna("").str.split(";")
    return {g: sets.map(lambda ts, f=f: any(f(t) for t in ts if t)) for g, f in THEMES.items()}


def gkg_theme_day(d: date, step: int = 4, workers: int = 4) -> pd.DataFrame:
    """One English GKG file every `step` 15-minute slots (4 = hourly) of the UTC day d, summarised by theme group."""
    s = requests.Session()
    s.headers["User-Agent"] = UA
    t0 = datetime(d.year, d.month, d.day)
    urls = [BASE.format(stamp=(t0 + timedelta(minutes=15 * i)).strftime("%Y%m%d%H%M%S"), kind="gkg.csv") for i in range(0, 96, step)]

    def one(u):
        raw = _get(u, s)
        time.sleep(0.05)
        return None if raw is None else _parse_gkg(raw)

    with ThreadPoolExecutor(workers) as ex:
        parts = [p for p in ex.map(one, urls) if p is not None and len(p)]
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    masks = tag_themes(df["themes"])
    rows = []
    for g, m in masks.items():
        t = df.loc[m, "tone"]
        rows.append({"date": d, "theme": g, "n_docs": int(m.sum()), "mean_tone": float(t.mean()) if len(t) else None,
                     "share_negative": float((t < NEG_TONE).mean()) if len(t) else None, "n_docs_all": len(df), "sample_files": len(parts)})
    rows.append({"date": d, "theme": "all", "n_docs": len(df), "mean_tone": float(df["tone"].mean()), "share_negative": float((df["tone"] < NEG_TONE).mean()),
                 "n_docs_all": len(df), "sample_files": len(parts)})
    return pd.DataFrame(rows)


def extend_themes(start: date, end: date, root: Optional[Path] = None, step: int = 4, log=print) -> dict:
    root = Path(root or data_dir())
    p = root / "gdelt_s79b" / "daily_theme_tone.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    old = pd.read_parquet(p) if p.exists() else pd.DataFrame()
    have = set(pd.to_datetime(old["date"]).dt.date) if len(old) else set()
    frames, d = [old] if len(old) else [], start
    end = min(end, date.today() - timedelta(days=1))
    while d <= end:
        if d not in have:
            t = gkg_theme_day(d, step)
            log(str(d), len(t))
            if len(t):
                frames.append(t)
                pd.concat(frames, ignore_index=True).to_parquet(p, index=False)       # progressive
        d += timedelta(days=1)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(out):
        out["date"] = pd.to_datetime(out["date"]).dt.date
        out = out.drop_duplicates(["date", "theme"], keep="last").sort_values(["date", "theme"])
        out.to_parquet(p, index=False)
    return {"rows": len(out), "first": str(out["date"].min()) if len(out) else None, "last": str(out["date"].max()) if len(out) else None}
