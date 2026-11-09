"""The US session on the investor's clock. The calendar is `conductor/us_calendar.py` (NYSE's holidays and early closes, daylight saving from the zone); the market's own object is
`markets.get("US")`. All IST values are naive IST wall-clock times, as everywhere else in the system.

    Winter (EST, UTC-5): open 20:00 IST, close 02:30 IST on the NEXT calendar day.   Summer (EDT, UTC-4): open 19:00 IST, close 01:30 IST on the next day.
    So the US close of New York date D is handled in the IST morning of D+1 (`handling_day`), and a Friday session closes early on Saturday morning IST.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional, Tuple

from pflab import markets


def market():
    return markets.get("US")


def is_session(d: date) -> bool:
    return market().is_session(d)


def window_ist(d: date) -> Optional[Tuple[datetime, datetime]]:
    """(open, close) of New York date `d` as naive IST times; None when the market is shut."""
    return market().window_ist(d)


def close_ist(d: date) -> Optional[datetime]:
    w = window_ist(d)
    return None if w is None else w[1]


def handling_day(d: date) -> Optional[date]:
    """The IST calendar day on which the close of New York date `d` happens (and is handled)."""
    c = close_ist(d)
    return None if c is None else c.date()


def session_closed_by(now_ist: datetime, settle_minutes: int = 30) -> date:
    """The latest New York session whose close passed at least `settle_minutes` before `now_ist` (the daily bar is final by then)."""
    return market().session_closed_by(now_ist - timedelta(minutes=int(settle_minutes)))


def mode(now_ist: datetime) -> str:
    return market().mode(now_ist)


def previous_session(d: date) -> date:
    return market().previous_session(d)


def next_session(d: date) -> date:
    return market().next_session(d)
