"""Markets as a parameter, and the clock's MODE per market (S79 items 3-4, A42).

`configs/markets.toml` names each market (calendar, session times, currency, benchmark, sector map, sources). Everything new stores a `market`
column and asks this module for sessions, horizons and the mode:

    m = markets.get("IN");  m.is_session(d);  m.previous_session(d);  m.session_after(d, 5)   # horizons are SESSIONS on this market's calendar
    markets.modes(now_ist)            -> {"IN": "post_close", "US": "deep"}
    markets.primary(now_ist)          -> ("IN", "post_close")

Modes (all in the laptop's IST wall clock, no timezone guessing beyond the US calendar's own):
    session     the market is trading (live watch, unexplained moves)
    pre_open    a session day, within `pre_open_hours_before_open` of the open (what the other side's close means here today)
    post_close  within `post_close_hours` after the close of a session (explain the day, score, update weights, forecast)
    deep        everything else: evenings, nights, weekends, holidays (agenda, learner, replay)
Modes set the GPU duty cycle and the rupee budget per hour, never a job time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pflab import _toml

CONFIG = Path(__file__).resolve().parents[2] / "configs" / "markets.toml"
CONFIGS = CONFIG.parent
MODES = ("pre_open", "session", "post_close", "deep")
PRIMARY = "IN"
_PRIORITY = {"session": 0, "pre_open": 1, "post_close": 2, "deep": 3}


def _hm(s: str) -> time:
    h, m = str(s).split(":")
    return time(int(h), int(m))


@dataclass(frozen=True)
class Market:
    code: str
    name: str
    tz: str
    currency: str
    open: time
    close: time
    benchmark: str
    index: str
    sector_map: str
    sources: Tuple[str, ...]
    calendar: object = field(repr=False, compare=False, default=None)          # has is_trading_day(d)
    pre_open_hours: float = 3.0
    post_close_hours: float = 2.0

    # --- sessions on this market's own calendar -------------------------------------------------------------------------
    def is_session(self, d: date) -> bool:
        return bool(self.calendar.is_trading_day(d))

    def previous_session(self, d: date) -> date:
        """The last session strictly before `d`."""
        n = d - timedelta(days=1)
        while not self.is_session(n):
            n -= timedelta(days=1)
        return n

    def next_session(self, d: date) -> date:
        """The first session strictly after `d`."""
        n = d + timedelta(days=1)
        while not self.is_session(n):
            n += timedelta(days=1)
        return n

    def last_session_on_or_before(self, d: date) -> date:
        return d if self.is_session(d) else self.previous_session(d)

    def session_after(self, d: date, n: int) -> date:
        """The date `n` sessions after `d` (n may be negative). Horizons of 1, 5 and 20 sessions are counted here, never in calendar days."""
        cur = d
        step = 1 if n >= 0 else -1
        for _ in range(abs(int(n))):
            cur = self.next_session(cur) if step > 0 else self.previous_session(cur)
        return cur

    def sessions_between(self, start: date, end: date) -> List[date]:
        """Sessions in the closed range [start, end]."""
        out, d = [], start
        while d <= end:
            if self.is_session(d):
                out.append(d)
            d += timedelta(days=1)
        return out

    def session_count(self, start: date, end: date) -> int:
        """Sessions after `start` up to and including `end` (the number of steps from start to end)."""
        return len([d for d in self.sessions_between(start + timedelta(days=1), end)])

    # --- the clock (IST wall clock, naive) ------------------------------------------------------------------------------
    def window_ist(self, d: date) -> Optional[Tuple[datetime, datetime]]:
        """The session of date `d` as naive IST times; None when shut. A US session can end after midnight IST."""
        if not self.is_session(d):
            return None
        fn = getattr(self.calendar, "session_ist", None)
        if fn is not None:
            return fn(d)
        return datetime.combine(d, self.open), datetime.combine(d, self.close)

    def mode(self, now: datetime) -> str:
        """The mode of this market at a naive IST moment."""
        pre, post = timedelta(hours=self.pre_open_hours), timedelta(hours=self.post_close_hours)
        best = "deep"
        for off in (-2, -1, 0, 1):                              # a session that began the day before may still run; the next may start soon
            w = self.window_ist(now.date() + timedelta(days=off))
            if w is None:
                continue
            o, c = w
            if o <= now < c:
                return "session"
            if o - pre <= now < o:
                best = "pre_open"
            elif c <= now < c + post and best == "deep":
                best = "post_close"
        return best

    def session_closed_by(self, now: datetime) -> date:
        """The latest session whose close has passed at `now` (the one to score and explain)."""
        d = now.date() + timedelta(days=1)
        for _ in range(12):
            d = d - timedelta(days=1)
            w = self.window_ist(d)
            if w is not None and w[1] <= now:
                return d
        return self.previous_session(now.date())


@lru_cache(maxsize=1)
def _config(path: str = str(CONFIG)) -> dict:
    return _toml.load(path)


def _calendar(name: str):
    from pflab.conductor import calendar as cal, us_calendar as ucal
    if name.startswith("us_"):
        return ucal.load(CONFIGS / name)
    return cal.load(CONFIGS / name)


@lru_cache(maxsize=8)
def get(code: str = PRIMARY) -> Market:
    cfg = _config()
    m = cfg["markets"][code]
    modes = cfg.get("modes", {})
    return Market(code=code, name=m["name"], tz=m["tz"], currency=m["currency"], open=_hm(m["open"]), close=_hm(m["close"]),
                  benchmark=m["benchmark"], index=m.get("index", m["benchmark"]), sector_map=m.get("sector_map", ""),
                  sources=tuple(m.get("sources", ())), calendar=_calendar(m["holidays"]),
                  pre_open_hours=float(modes.get("pre_open_hours_before_open", 3.0)), post_close_hours=float(modes.get("post_close_hours", 2.0)))


def codes() -> List[str]:
    return list(_config()["markets"].keys())


def modes(now: datetime) -> Dict[str, str]:
    return {c: get(c).mode(now) for c in codes()}


def primary(now: datetime) -> Tuple[str, str]:
    """The market and mode the system works by now: the home market's mode, unless it is deep and another market is busier."""
    ms = modes(now)
    home = ms.get(PRIMARY, "deep")
    if home != "deep":
        return PRIMARY, home
    others = [(c, m) for c, m in ms.items() if c != PRIMARY and m != "deep"]
    return min(others, key=lambda kv: _PRIORITY[kv[1]]) if others else (PRIMARY, "deep")


def gpu_duty(mode: str) -> float:
    return float(_config().get("modes", {}).get("gpu_duty", {}).get(mode, 0.5))


def rupee_per_hour(mode: str) -> float:
    return float(_config().get("modes", {}).get("rupee_per_hour", {}).get(mode, 3.0))


def pace_spend() -> bool:
    return bool(_config().get("modes", {}).get("pace_spend", False))
