"""Trading calendar (Phase 1 task 1.4).

Synthetic sessions, so these stay fast and need no data directory.
"""
from datetime import date

import pytest

from pflab.data import calendar as cal_mod
from pflab.data.calendar import CalendarMismatch, TradingCalendar

# Jan-Mar 2024 weekdays, minus 2024-01-26 (Republic Day) and 2024-03-08
# (Mahashivratri), plus 2024-03-02 -- a real Saturday session.
def _days():
    out = []
    d = date(2024, 1, 1)
    while d <= date(2024, 3, 29):
        if d.weekday() < 5 and d not in (date(2024, 1, 26), date(2024, 3, 8)):
            out.append(d)
        d += __import__("datetime").timedelta(days=1)
    out.append(date(2024, 3, 2))          # Saturday special session
    return out


CAL = TradingCalendar(_days())


def test_sorted_deduplicated_and_membership():
    c = TradingCalendar([date(2024, 1, 3), date(2024, 1, 2), date(2024, 1, 3)])
    assert c.sessions == [date(2024, 1, 2), date(2024, 1, 3)]
    assert len(c) == 2 and date(2024, 1, 2) in c and date(2024, 1, 5) not in c


def test_empty_calendar_rejected():
    with pytest.raises(ValueError, match="at least one session"):
        TradingCalendar([])


def test_position_requires_a_real_session():
    assert CAL.position(CAL[0]) == 0
    with pytest.raises(KeyError, match="not a trading session"):
        CAL.position(date(2024, 1, 26))          # a holiday


def test_asof_is_the_point_in_time_lookup():
    """A decision dated on a holiday sees the previous session, never a later one."""
    i = CAL.asof(date(2024, 1, 26))
    assert CAL[i] == date(2024, 1, 25)
    assert CAL.asof(date(2023, 12, 1)) is None   # before any session


def test_shift_by_sessions():
    d = date(2024, 2, 15)
    assert CAL.shift(d, 0) == d
    assert CAL.shift(d, 1) == date(2024, 2, 16)
    assert CAL.shift(d, -1) == date(2024, 2, 14)


def test_shift_past_either_end_returns_none():
    """An incomplete history must not silently clamp to the first session --
    that would fabricate a 12-1 momentum for a name without 252 sessions."""
    assert CAL.shift(CAL.first, -1) is None
    assert CAL.shift(CAL.last, 1) is None
    assert CAL.shift(CAL.first, -252) is None


def test_next_session_is_the_fill_date():
    """Charter section 7: decide on the close of M, fill at the open of M+1."""
    assert CAL.next_session(date(2024, 1, 25)) == date(2024, 1, 29)   # 26th is a holiday
    assert CAL.next_session(CAL.last) is None


def test_month_ends_are_last_sessions_not_month_end_dates():
    me = CAL.month_ends()
    assert me[0] == date(2024, 1, 31)
    assert me[1] == date(2024, 2, 29)     # leap year
    assert me[2] == date(2024, 3, 29)


def test_month_starts_are_first_sessions():
    ms = CAL.month_starts()
    assert ms[0] == date(2024, 1, 1)
    assert ms[1] == date(2024, 2, 1)
    assert ms[2] == date(2024, 3, 1)


def test_weekend_session_is_kept():
    """NSE trades some Saturdays; dropping them lost 27 real sessions."""
    assert date(2024, 3, 2) in CAL
    assert CAL.next_session(date(2024, 3, 1)) == date(2024, 3, 2)


def test_truncate_drops_everything_after_the_period_end():
    t = CAL.truncate(date(2024, 2, 15))
    assert t.last == date(2024, 2, 15)
    assert t.month_ends()[-1] == date(2024, 2, 15)   # not 2024-02-29
    assert len(t) < len(CAL)


def test_from_panel_reads_distinct_dates():
    import pandas as pd
    p = pd.DataFrame({"date": [date(2024, 1, 2), date(2024, 1, 2), date(2024, 1, 3)],
                      "close": [1.0, 2.0, 3.0]})
    assert cal_mod.from_panel(p).sessions == [date(2024, 1, 2), date(2024, 1, 3)]


# -- the task 1.4 assertion itself --------------------------------------
def _check(monkeypatch, index_days, **kw):
    """Patch indices.load itself: `from pflab.data import indices` resolves to
    the package attribute once the real module is imported, so patching
    sys.modules alone works only when this file runs on its own."""
    import pandas as pd
    from pflab.data import indices as real

    def fake_load(key, root=None):
        return pd.DataFrame({"date": list(index_days),
                             "close": [1.0] * len(index_days)})

    monkeypatch.setattr(real, "load", fake_load)
    return cal_mod.check_against_index(CAL, "NIFTY50_PRICE", **kw)


def test_agreement_passes_when_calendars_match(monkeypatch):
    f = _check(monkeypatch, CAL.sessions)
    assert f["agree"] and not f["missing_from_bhavcopy"]


def test_mismatch_raises_and_names_the_missing_session(monkeypatch):
    """The real failure: the index had a Saturday the bhavcopy skipped."""
    extra = CAL.sessions + [date(2024, 2, 3)]
    with pytest.raises(CalendarMismatch, match="2024, 2, 3"):
        _check(monkeypatch, extra)
    f = _check(monkeypatch, extra, raise_on_mismatch=False)
    assert f["missing_from_bhavcopy"] == [date(2024, 2, 3)] and not f["agree"]


def test_shorter_index_history_is_not_a_mismatch(monkeypatch):
    """Momentum 30 starts in 2005; that is not a disagreement."""
    f = _check(monkeypatch, CAL.slice(date(2024, 2, 1), date(2024, 3, 29)))
    assert f["agree"] and f["window"][0] == date(2024, 2, 1)
