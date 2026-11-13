"""When a filing may be used (S82, A58: replaces the S81 rule "a filing with no release time is left out").

A filing WITH a release (dissemination) time is usable from that time. A filing with a date but NO release time is usable from the NEXT TRADING DAY's open (09:15 IST on
the Indian calendar in `markets.py`): it was public during its own day, we do not know when, so it counts from the next session's open. A filing dated on a day the market
was shut goes to the next trading open after it. The derived time is stored on the event with its rule (`ts_rule`), so nothing is silent.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from typing import Optional, Tuple

import pandas as pd

RULE_RELEASE = "release_time"
RULE_DERIVED = "next_open_no_release_time"
RULE_NEWS = "article_day_next_day"
RULE_PUBLISHED = "published_time"
RULES = (RULE_RELEASE, RULE_DERIVED, RULE_NEWS, RULE_PUBLISHED)
IST_OFFSET = timedelta(hours=5, minutes=30)      # GDELT's clock is UTC; the system's is IST wall time
RULE_RECEIVED = "received_time"                  # S85: a document or checked fact he sent (source "you"): usable from the moment the intake received it
RULES = RULES + (RULE_RECEIVED,)


@lru_cache(maxsize=4096)
def next_open(day: date, market: str = "IN") -> datetime:
    """The open of the first trading session strictly after `day` (naive IST)."""
    from pflab import markets
    m = markets.get(market)
    d = m.next_session(day)
    w = m.window_ist(d)
    return w[0] if w else datetime.combine(d, m.open)


def _day(x) -> Optional[date]:
    if x is None or x is pd.NaT:
        return None
    t = pd.to_datetime(x, errors="coerce")
    return None if pd.isna(t) else t.date()


def filing_time(dissem_dt, news_dt, file_day, market: str = "IN") -> Tuple[Optional[datetime], Optional[str], Optional[date]]:
    """(ts, rule, own_date) of one filing row. `file_day` is the day the announcement file belongs to (the exchange's query day, which is the filing's own day);
    when the row also carries a news date that is later, the later is the filing's date (the conservative one). No usable date at all gives (None, None, None)."""
    dt = pd.to_datetime(dissem_dt, errors="coerce") if dissem_dt is not None else pd.NaT
    if not pd.isna(dt):
        return dt.to_pydatetime(), RULE_RELEASE, dt.date()
    days = [d for d in (_day(file_day), _day(news_dt)) if d is not None]
    if not days:
        return None, None, None
    own = max(days)
    return next_open(own, market), RULE_DERIVED, own


def news_time(published, file_day=None) -> Tuple[Optional[datetime], Optional[str]]:
    """(ts, rule) of one live news item (the 15-minute GDELT GKG files, `data/gkg`). An item with a publication time (GDELT's `DATE`, UTC) is stored at that time in IST wall
    time (+5:30): stored as UTC it would look 5.5 hours earlier than it was, a look-ahead. An item with NO time but a collection day is usable from the next day (00:00),
    the rule older stored news already follows. Nothing usable: (None, None)."""
    t = pd.to_datetime(published, errors="coerce") if published is not None else pd.NaT
    if not pd.isna(t):
        return (t + IST_OFFSET).to_pydatetime(), RULE_PUBLISHED
    d = _day(file_day)
    if d is None:
        return None, None
    return datetime.combine(d + timedelta(days=1), time(0, 0)), RULE_NEWS


_FILE_DAY = None


def file_day_of(name) -> Optional[date]:
    """The day in an announcement file's name (`.../2026/2026-10-23.parquet`), or None."""
    import re
    global _FILE_DAY
    if _FILE_DAY is None:
        _FILE_DAY = re.compile(r"(\d{4}-\d{2}-\d{2})\.parquet$")
    m = _FILE_DAY.search(str(name).replace("\\", "/"))
    return date.fromisoformat(m.group(1)) if m else None


def stamp_missing(df: pd.DataFrame, tcol: str = "t", fcol: str = "filename") -> pd.DataFrame:
    """For the study readers that read the announcement files through DuckDB (`filename=true`): a row whose time `tcol` is null gets the next trading open after the day in its
    file's name (A58); rows that have a time are untouched; a row with no file day stays null. The frame is returned with `tcol` filled in and `fcol` dropped."""
    out = df.copy()
    miss = out[tcol].isna()
    if miss.any():
        days = out.loc[miss, fcol].map(file_day_of)
        out.loc[miss, tcol] = [next_open(d) if d is not None else pd.NaT for d in days]
        out[tcol] = pd.to_datetime(out[tcol])
    return out.drop(columns=[fcol])
