"""The US session on the investor's clock. The calendar is `conductor/us_calendar.py` (NYSE's holidays and early closes, daylight saving from the zone); the market's own object is
`markets.get("US")`. All IST values are naive IST wall-clock times, as everywhere else in the system.

    Winter (EST, UTC-5): open 20:00 IST, close 02:30 IST on the NEXT calendar day.   Summer (EDT, UTC-4): open 19:00 IST, close 01:30 IST on the next day.
    So the US close of New York date D is handled in the IST morning of D+1 (`handling_day`), and a Friday session closes early on Saturday morning IST.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional, Tuple

from pflab import markets


def market(code: str = "US"):
    """The market object (`markets.get`). Every function below takes `market="US"` as its last argument; "IN" answers from the Indian calendar and changes nothing there."""
    return markets.get(code)


def is_session(d: date, market: str = "US") -> bool:
    return markets.get(market).is_session(d)


def window_ist(d: date, market: str = "US") -> Optional[Tuple[datetime, datetime]]:
    """(open, close) of the market's date `d` as naive IST times; None when the market is shut. For the US: New York's date and session."""
    return markets.get(market).window_ist(d)


def close_ist(d: date, market: str = "US") -> Optional[datetime]:
    w = window_ist(d, market)
    return None if w is None else w[1]


def handling_day(d: date, market: str = "US") -> Optional[date]:
    """The IST calendar day on which the close of the market's date `d` happens (and is handled)."""
    c = close_ist(d, market)
    return None if c is None else c.date()


def session_closed_by(now_ist: datetime, settle_minutes: int = 30, market: str = "US") -> date:
    """The latest session whose close passed at least `settle_minutes` before `now_ist` (the daily bar is final by then)."""
    return markets.get(market).session_closed_by(now_ist - timedelta(minutes=int(settle_minutes)))


def mode(now_ist: datetime, market: str = "US") -> str:
    return markets.get(market).mode(now_ist)


def previous_session(d: date, market: str = "US") -> date:
    return markets.get(market).previous_session(d)


def next_session(d: date, market: str = "US") -> date:
    return markets.get(market).next_session(d)
