"""S64 Phase 6 item 4: the NYSE calendar, around the daylight-saving switch."""
from datetime import date, datetime

import pytest

from pflab.conductor import us_calendar as uc

CAL = uc.load()


def test_holidays_early_closes_and_weekends():
    assert CAL.has_year(2026) and CAL.has_year(2027) and not CAL.has_year(2028)
    assert not CAL.is_trading_day(date(2026, 11, 26)) and not CAL.is_trading_day(date(2026, 7, 3))        # Thanksgiving, July 4 observed
    assert not CAL.is_trading_day(date(2027, 12, 24)) and not CAL.is_trading_day(date(2026, 10, 31))      # Christmas observed; a Saturday
    assert CAL.is_trading_day(date(2026, 10, 27)) and CAL.is_trading_day(date(2026, 11, 27))
    assert CAL.next_trading_day(date(2026, 11, 25)) == date(2026, 11, 27)


def test_the_open_moves_an_hour_in_ist_when_the_us_changes_its_clocks():
    before = CAL.session_ist(date(2026, 10, 30))        # US still on summer time (clocks go back on 1 Nov 2026)
    after = CAL.session_ist(date(2026, 11, 2))
    assert before[0] == datetime(2026, 10, 30, 19, 0) and before[1] == datetime(2026, 10, 31, 1, 30)
    assert after[0] == datetime(2026, 11, 2, 20, 0) and after[1] == datetime(2026, 11, 3, 2, 30)
    spring_before, spring_after = CAL.session_ist(date(2027, 3, 12)), CAL.session_ist(date(2027, 3, 15))
    assert spring_before[0].hour == 20 and spring_after[0].hour == 19                                     # and back in March 2027


def test_an_early_close_ends_at_one_new_york_time():
    s = CAL.session_ist(date(2026, 11, 27))
    assert s[0] == datetime(2026, 11, 27, 20, 0) and s[1] == datetime(2026, 11, 27, 23, 30)
    assert CAL.session_ist(date(2026, 11, 26)) is None


def test_mode_through_a_session_that_crosses_midnight_in_ist():
    m = CAL.mode
    assert m(datetime(2026, 10, 27, 18, 0)) == "pre_open" and m(datetime(2026, 10, 27, 19, 0)) == "open"
    assert m(datetime(2026, 10, 28, 0, 30)) == "open"                      # after midnight IST, still the 27th's session in New York
    assert m(datetime(2026, 10, 28, 1, 45)) == "after_close"
    assert m(datetime(2026, 10, 31, 12, 0)) == "closed"                    # Saturday in New York
    assert m(datetime(2026, 11, 26, 21, 0)) == "closed"                    # Thanksgiving
    assert CAL.pass_time_ist(date(2026, 10, 27)) == datetime(2026, 10, 27, 19, 20) and CAL.pass_time_ist(date(2026, 11, 26)) is None
    assert uc.us_session(datetime(2026, 10, 27, 19, 5), CAL) == "open"

