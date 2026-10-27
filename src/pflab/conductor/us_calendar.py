"""The US market's clock (S64 Phase 6 item 4): NYSE sessions in New York time, and when they fall on the investor's clock (IST).

The open moves between 19:00 and 20:00 IST with US daylight saving; it is computed from the zone each time. Holidays and early
closes are from configs/us_market_holidays.toml (NYSE's page, read 2026-10-27). The times are the laptop's wall clock, as in
`calendar.py`: `now` is naive IST.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from pflab import _toml

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "us_market_holidays.toml"
NY, IST = ZoneInfo("America/New_York"), ZoneInfo("Asia/Kolkata")
OPEN, CLOSE, EARLY_CLOSE = time(9, 30), time(16, 0), time(13, 0)
PASS_AFTER_OPEN = timedelta(minutes=20)           # the brain's US pass runs 20 minutes into the session


@dataclass(frozen=True)
class UsCalendar:
    holidays: Dict[date, str] = field(default_factory=dict)
    early: Dict[date, str] = field(default_factory=dict)
    years: Tuple[int, ...] = ()

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def hours(self, d: date) -> Optional[Tuple[datetime, datetime]]:
        """(open, close) as aware New York times, or None on a day the market is shut."""
        if not self.is_trading_day(d):
            return None
        return (datetime.combine(d, OPEN, NY), datetime.combine(d, EARLY_CLOSE if d in self.early else CLOSE, NY))

    def session_ist(self, d: date) -> Optional[Tuple[datetime, datetime]]:
        """The same session as naive IST wall-clock times (it can end after midnight)."""
        h = self.hours(d)
        return None if h is None else tuple(t.astimezone(IST).replace(tzinfo=None) for t in h)    # type: ignore[return-value]

    def mode(self, now_ist: datetime) -> str:
        """'closed', 'pre_open', 'open' or 'after_close' for a naive IST moment. A session that began on the previous New York
        day but is still running past midnight IST counts as open."""
        t = now_ist.replace(tzinfo=IST).astimezone(NY)
        d = t.date()
        h = self.hours(d)
        if h is None:
            return "closed"
        if t < h[0]:
            return "pre_open"
        return "open" if t < h[1] else "after_close"

    def next_trading_day(self, d: date) -> date:
        n = d + timedelta(days=1)
        while not self.is_trading_day(n):
            n += timedelta(days=1)
        return n

    def pass_time_ist(self, d: date) -> Optional[datetime]:
        s = self.session_ist(d)
        return None if s is None else s[0] + PASS_AFTER_OPEN

    def has_year(self, y: int) -> bool:
        return y in self.years


def load(path: Optional[Path] = None) -> UsCalendar:
    cfg = _toml.load(path or CONFIG)
    return UsCalendar({h["date"]: h["name"] for h in cfg.get("holiday", [])}, {e["date"]: e["name"] for e in cfg.get("early_close", [])},
                      tuple(cfg.get("meta", {}).get("years", ())))


def us_session(now_ist: datetime, cal: Optional[UsCalendar] = None) -> str:
    """The US market's mode at an IST moment (used by calendar.py's callers)."""
    return (cal or load()).mode(now_ist)
