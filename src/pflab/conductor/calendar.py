"""The market's clock: trading days, the mode at a moment, the closed stretch ahead (S53).

Times are the laptop's wall clock (IST on the investor's machine), as in `service.schedule`. Holidays come from
`configs/market_holidays.toml` (sourced and dated there). A year with no list is treated as weekdays-only and the
sync check says so; a guessed holiday is never added.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pflab import _toml

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "market_holidays.toml"
OPEN, CLOSE = time(9, 15), time(15, 30)
EVENING_READY = time(21, 0)         # the evening jobs (collect 19:30, prices 20:15, guards 20:45) have run by now
SWITCH_ON_AT = time(18, 0)          # asked-for switch-on time before a session that follows a closed stretch

MODES = ("closed", "pre_open", "market", "after_close")


@dataclass(frozen=True)
class Calendar:
    holidays: Dict[date, str] = field(default_factory=dict)
    special: Dict[date, str] = field(default_factory=dict)
    years: Tuple[int, ...] = ()

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self.holidays

    def why_closed(self, d: date) -> Optional[str]:
        if d in self.holidays:
            return self.holidays[d]
        return ("Saturday", "Sunday")[d.weekday() - 5] if d.weekday() >= 5 else None

    def mode(self, now: datetime) -> str:
        if not self.is_trading_day(now.date()):
            return "closed"
        t = now.time()
        return "pre_open" if t < OPEN else "market" if t < CLOSE else "after_close"

    def next_trading_day(self, d: date) -> date:
        """The first trading day strictly after `d`."""
        n = d + timedelta(days=1)
        while not self.is_trading_day(n):
            n += timedelta(days=1)
        return n

    def previous_trading_day(self, d: date) -> date:
        """The last trading day strictly before `d`."""
        n = d - timedelta(days=1)
        while not self.is_trading_day(n):
            n -= timedelta(days=1)
        return n

    def last_closed_session(self, now: datetime) -> date:
        """The latest session whose closing data should exist by `now`: today once the evening jobs ran, else the one
        before."""
        d = now.date()
        if self.is_trading_day(d) and now.time() >= EVENING_READY:
            return d
        return self.previous_trading_day(d)

    def closed_after(self, d: date) -> List[date]:
        """The closed days between `d` and the next trading day (empty when tomorrow trades)."""
        out, n = [], d + timedelta(days=1)
        while not self.is_trading_day(n):
            out.append(n)
            n += timedelta(days=1)
        return out

    def has_year(self, y: int) -> bool:
        return y in self.years


def load(path: Optional[Path] = None) -> Calendar:
    cfg = _toml.load(path or CONFIG)
    hol = {h["date"]: h["name"] for h in cfg.get("holiday", [])}
    spc = {s["date"]: s["name"] for s in cfg.get("special", [])}
    return Calendar(hol, spc, tuple(cfg.get("meta", {}).get("years", ())))


def describe_closed(cal: Calendar, days: List[date]) -> str:
    """'Sat 24 Oct, Sun 25 Oct' with holiday names: 'Tue 10 Nov (Diwali Balipratipada)'."""
    parts = []
    for d in days:
        why = cal.holidays.get(d)
        parts.append(f"{d:%a %d %b}" + (f" ({why})" if why else ""))
    return ", ".join(parts)
