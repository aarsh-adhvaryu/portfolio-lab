"""The NSE trading calendar, derived from the bhavcopy (Phase 1 task 1.4).

Sessions are integer positions in this calendar, per CLAUDE.md conventions.
The engine needs three things from it:

  * session offsets   charter section 3: MOM(M) = close(M-21) / close(M-252) - 1
  * month ends        section 6: the last 10 month-end closes of the Nifty 50
  * month starts      section 5: the SIP lands on the first session of a month

The calendar is derived from whatever data the loader has already truncated,
so it is point-in-time by construction: a calendar built for a period never
contains a session after that period's end.

Task 1.4 also requires the bhavcopy calendar to agree with the Nifty 50 price
series. `check_against_index` is that assertion. It caught 27 missing weekend
sessions (Budget days and Diwali Muhurat trading) on the first run.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterable, Optional, Sequence

import pandas as pd

from pflab.data import data_dir


class CalendarMismatch(RuntimeError):
    """The bhavcopy and the index disagree about which days were sessions."""


class TradingCalendar:
    """An ordered, de-duplicated list of trading sessions."""

    def __init__(self, sessions: Iterable[date]):
        self._sessions: list[date] = sorted(set(sessions))
        if not self._sessions:
            raise ValueError("a trading calendar needs at least one session")
        self._pos = {d: i for i, d in enumerate(self._sessions)}

    # -- basics ---------------------------------------------------------
    @property
    def sessions(self) -> list[date]:
        return list(self._sessions)

    def __len__(self) -> int:
        return len(self._sessions)

    def __iter__(self):
        return iter(self._sessions)

    def __getitem__(self, i: int) -> date:
        return self._sessions[i]

    def __contains__(self, d: date) -> bool:
        return d in self._pos

    @property
    def first(self) -> date:
        return self._sessions[0]

    @property
    def last(self) -> date:
        return self._sessions[-1]

    # -- positions ------------------------------------------------------
    def position(self, d: date) -> int:
        """Integer position of an actual session. KeyError if d did not trade."""
        try:
            return self._pos[d]
        except KeyError:
            raise KeyError(f"{d} is not a trading session") from None

    def asof(self, d: date) -> Optional[int]:
        """Position of the last session on or before d, or None if too early.

        This is the point-in-time lookup: a decision dated d may only see
        sessions at or before this position.
        """
        import bisect
        i = bisect.bisect_right(self._sessions, d) - 1
        return i if i >= 0 else None

    def shift(self, d: date, n: int) -> Optional[date]:
        """The session n positions from d (n may be negative).

        Returns None when the shift falls off either end, so callers must
        decide what an incomplete history means rather than silently getting
        the first or last session.
        """
        base = self.position(d) if d in self._pos else self.asof(d)
        if base is None:
            return None
        i = base + n
        return self._sessions[i] if 0 <= i < len(self._sessions) else None

    def next_session(self, d: date) -> Optional[date]:
        """The first session strictly after d -- the section 7 fill date."""
        import bisect
        i = bisect.bisect_right(self._sessions, d)
        return self._sessions[i] if i < len(self._sessions) else None

    def slice(self, start: Optional[date] = None, end: Optional[date] = None) -> list[date]:
        return [d for d in self._sessions
                if (start is None or d >= start) and (end is None or d <= end)]

    # -- calendar-month helpers ----------------------------------------
    def month_ends(self, start: Optional[date] = None,
                   end: Optional[date] = None) -> list[date]:
        """Last session of each calendar month -- the section 4/6 decision dates."""
        out: dict[tuple[int, int], date] = {}
        for d in self.slice(start, end):
            out[(d.year, d.month)] = d          # later sessions overwrite
        return [out[k] for k in sorted(out)]

    def month_starts(self, start: Optional[date] = None,
                     end: Optional[date] = None) -> list[date]:
        """First session of each calendar month -- when the section 5 SIP lands."""
        out: dict[tuple[int, int], date] = {}
        for d in self.slice(start, end):
            out.setdefault((d.year, d.month), d)
        return [out[k] for k in sorted(out)]

    def truncate(self, end: date) -> "TradingCalendar":
        """A calendar with nothing after `end` (charter section 11)."""
        return TradingCalendar(self.slice(end=end))


# -- construction -------------------------------------------------------
def from_sessions(sessions: Sequence[date]) -> TradingCalendar:
    return TradingCalendar(sessions)


def from_bhavcopy(root: Optional[Path] = None, start: Optional[date] = None,
                  end: Optional[date] = None) -> TradingCalendar:
    """Every session with a normalised bhavcopy parquet on disk."""
    root = root or data_dir()
    days = []
    for p in (root / "bhavcopy").glob("*/*.parquet"):
        try:
            d = date.fromisoformat(p.stem)
        except ValueError:
            continue
        if (start is None or d >= start) and (end is None or d <= end):
            days.append(d)
    if not days:
        raise ValueError(f"no bhavcopy sessions under {root / 'bhavcopy'}")
    return TradingCalendar(days)


def from_panel(panel: pd.DataFrame, date_col: str = "date") -> TradingCalendar:
    return TradingCalendar(pd.to_datetime(panel[date_col]).dt.date.unique())


# -- task 1.4 assertion -------------------------------------------------
def check_against_index(cal: TradingCalendar, index_key: str = "NIFTY50_PRICE",
                        root: Optional[Path] = None, raise_on_mismatch: bool = True) -> dict:
    """Assert the bhavcopy calendar and the index agree on sessions.

    Compared only over the window both cover, so a shorter index history is
    not itself a mismatch. Returns the finding; raises CalendarMismatch when
    they disagree and `raise_on_mismatch`.
    """
    from pflab.data import indices
    idx = set(indices.load(index_key, root)["date"])
    if not idx:
        raise ValueError(f"index series {index_key} is empty")
    lo, hi = max(cal.first, min(idx)), min(cal.last, max(idx))
    ours = set(cal.slice(lo, hi))
    theirs = {d for d in idx if lo <= d <= hi}
    only_index, only_bhavcopy = sorted(theirs - ours), sorted(ours - theirs)
    finding = {
        "index": index_key,
        "window": (lo, hi),
        "sessions": len(ours),
        "index_sessions": len(theirs),
        "missing_from_bhavcopy": only_index,
        "missing_from_index": only_bhavcopy,
        "agree": not only_index and not only_bhavcopy,
    }
    if raise_on_mismatch and not finding["agree"]:
        raise CalendarMismatch(
            f"{index_key} and the bhavcopy disagree over {lo}..{hi}: "
            f"{len(only_index)} session(s) only in the index "
            f"(e.g. {only_index[:5]}), "
            f"{len(only_bhavcopy)} only in the bhavcopy (e.g. {only_bhavcopy[:5]})"
        )
    return finding
