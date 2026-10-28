"""Red-flag events, keyed to the session they become usable (E2-A §3, §4).

One row per (security, flag, announcement). The point of this module is the
`usable_from` column: the first trading session on which a decision may act
on the flag. Everything downstream -- the universe exclusion, the
intra-month exit, the §8a event study -- reads that column and nothing else,
so the point-in-time rule is implemented in exactly one place.

§3's key, as amended 2026-09-24
-------------------------------
    DissemDT where present, NEWS_DT otherwise, declared per row.

BSE returns `DissemDT` as null for every announcement before 2016 -- the
source, not the collector -- which is why the fallback exists. Over 222,419
announcements in the 2016-2022 overlap where both exist, the two differ by a
median of 5.1 seconds and only 0.009% cross a session boundary, so the
substitution misdates about one announcement in 11,000 by one session
(`docs/BUILT.md` §3). E2-A §6's window now starts in 2017, so
on that window the fallback never fires; it stays because the table is built
over the whole feed and because E2-A's §8a reports 2010-2016.

THE AFTER-15:30 RULE
--------------------
An announcement whose key timestamp falls after 15:30 is usable from the
NEXT session, because the market it would have moved had already closed.
One at or before 15:30 is usable from the session it landed in, if that day
traded, and otherwise from the next session. A flag that arrives on a
Saturday is usable on Monday whatever the clock says.

This is the whole of the lookahead guard for E2-A. Getting it wrong in the
lenient direction would let the engine sell on news the market had not seen.

Schema (data/red_flag_events/events.parquet):
  isin, scrip_code, company, flag, key_dt, key_source, usable_from,
  headline, category, subcategory
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from pflab.data import data_dir, red_flags

CUTOFF = time(15, 30)
COLUMNS = ["isin", "scrip_code", "company", "flag", "key_dt", "key_source",
           "usable_from", "headline", "category", "subcategory"]


def usable_from(key_dt: pd.Timestamp, calendar) -> Optional[date]:
    """The first session a decision may act on an announcement stamped `key_dt`.

    After 15:30 -> the next session. At or before -> that session if it
    traded, else the next one.
    """
    if pd.isna(key_dt):
        return None
    d = key_dt.date()
    if key_dt.time() > CUTOFF:
        return calendar.next_session(d)
    return d if d in calendar else calendar.next_session(d)


def _resolve_isin(scrip: str, when: pd.Timestamp, by_scrip: dict) -> Optional[str]:
    """The ISIN this scrip code carried at `when`.

    The map is date-ranged because a face-value split issues a new ISIN
    (CLAUDE.md rule 8). Joining on the current ISIN alone would attach a
    2012 flag to a security identifier that did not exist until 2024.
    """
    rows = by_scrip.get(scrip)
    if not rows:
        return None
    for isin, lo, hi in rows:
        if lo <= when <= hi:
            return isin
    return None


def build(root: Optional[Path] = None, start_year: int = 2010,
          calendar=None) -> pd.DataFrame:
    """Classify the whole announcement feed and key every flag to a session."""
    from pflab.data import bse_scrip_isin, calendar as cal_mod

    root = root or data_dir()
    if calendar is None:
        panel = pd.read_parquet(root / "panel" / "prices.parquet", columns=["date"])
        calendar = cal_mod.from_sessions(pd.to_datetime(panel["date"]).dt.date.unique())

    m = bse_scrip_isin.load(root)
    m = m[m["isin"] != ""]
    by_scrip: dict = {}
    for r in m.itertuples(index=False):
        by_scrip.setdefault(str(r.scrip_code), []).append(
            (r.isin, pd.Timestamp(r.valid_from), pd.Timestamp(r.valid_to)))

    base = root / "bse_announcements"
    out = []
    for year_dir in sorted(base.glob("*")):
        if not year_dir.is_dir():
            continue
        try:
            if int(year_dir.name) < start_year:
                continue
        except ValueError:
            continue
        for f in sorted(year_dir.glob("*.parquet")):
            d = pd.read_parquet(f, columns=["scrip_code", "company", "headline",
                                            "category", "subcategory",
                                            "news_dt", "dissem_dt"])
            if not len(d):
                continue
            d["scrip_code"] = d["scrip_code"].astype(str).str.strip()
            d["dissem_dt"] = pd.to_datetime(d["dissem_dt"], errors="coerce")
            d["news_dt"] = pd.to_datetime(d["news_dt"], errors="coerce")
            for r in d.itertuples(index=False):
                flags = red_flags.classify(r.headline or "", r.category or "",
                                           r.subcategory or "")
                if not flags:
                    continue
                # §3 as amended 2026-09-24: DissemDT where present, else NEWS_DT
                if pd.notna(r.dissem_dt):
                    key_dt, src = r.dissem_dt, "DissemDT"
                elif pd.notna(r.news_dt):
                    key_dt, src = r.news_dt, "NEWS_DT"
                else:
                    key_dt, src = pd.NaT, "unresolved"
                isin = _resolve_isin(r.scrip_code, key_dt, by_scrip) \
                    if pd.notna(key_dt) else None
                u = usable_from(key_dt, calendar)
                for fl in flags:
                    out.append({"isin": isin, "scrip_code": r.scrip_code,
                                "company": r.company, "flag": fl,
                                "key_dt": key_dt, "key_source": src,
                                "usable_from": u, "headline": r.headline,
                                "category": r.category, "subcategory": r.subcategory})
    df = pd.DataFrame(out, columns=COLUMNS) if out else pd.DataFrame(columns=COLUMNS)
    d = root / "red_flag_events"
    d.mkdir(parents=True, exist_ok=True)
    df.to_parquet(d / "events.parquet", index=False)
    (d / "_build.json").write_text(json.dumps({
        "built": datetime.utcnow().isoformat(),
        "events": int(len(df)),
        "with_isin": int(df["isin"].notna().sum()) if len(df) else 0,
        "by_key_source": (df["key_source"].value_counts().to_dict() if len(df) else {}),
        "flags_frozen_at": red_flags_commit(),
    }, indent=2, default=str), encoding="utf-8")
    return df


def red_flags_commit() -> str:
    """The commit that froze pflab/data/red_flags.py (E2-A §4)."""
    import subprocess
    try:
        return subprocess.check_output(
            ["git", "log", "-1", "--format=%H", "--", "src/pflab/data/red_flags.py"],
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return "unknown"


def load(root: Optional[Path] = None) -> pd.DataFrame:
    p = (root or data_dir()) / "red_flag_events" / "events.parquet"
    if not p.exists():
        raise FileNotFoundError(f"{p} not built; run red_flag_events.build()")
    return pd.read_parquet(p)


def flagged_at(events: pd.DataFrame, when: date, months: int = 12) -> set:
    """ISINs carrying any flag usable in the trailing `months` at `when`.

    E2-A §3's eligibility test. Strictly `usable_from <= when`, so a flag
    disseminated after 15:30 on the decision date is not visible -- that is
    the whole point of `usable_from`.
    """
    if not len(events):
        return set()
    lo = when - timedelta(days=int(round(months * 30.44)))
    u = pd.to_datetime(events["usable_from"]).dt.date
    m = (u <= when) & (u > lo) & events["isin"].notna()
    return set(events.loc[m, "isin"])


def new_flags_on(events: pd.DataFrame, session: date) -> set:
    """ISINs whose flag becomes usable exactly on `session` (§3's exit trigger)."""
    if not len(events):
        return set()
    u = pd.to_datetime(events["usable_from"]).dt.date
    return set(events.loc[(u == session) & events["isin"].notna(), "isin"])
