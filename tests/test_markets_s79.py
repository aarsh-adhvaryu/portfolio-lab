"""S79 item 4: markets as a parameter and the clock's mode per market (synthetic dates; the 2026 NSE list is real config)."""
from datetime import date, datetime

from pflab import markets


def test_codes_and_sessions():
    assert set(markets.codes()) >= {"IN", "US"}
    m = markets.get("IN")
    assert m.is_session(date(2026, 11, 5)) and not m.is_session(date(2026, 11, 7))
    assert m.session_after(date(2026, 11, 6), 1) == date(2026, 11, 9)          # Friday + 1 session = Monday
    assert m.previous_session(date(2026, 11, 9)) == date(2026, 11, 6)
    assert m.session_count(date(2026, 11, 6), date(2026, 11, 9)) == 1


def test_horizon_counts_sessions_not_days():
    m = markets.get("IN")
    d5 = m.session_after(date(2026, 11, 2), 5)
    assert d5 > date(2026, 11, 7) and len(m.sessions_between(date(2026, 11, 3), d5)) == 5


def test_modes_in_a_day():
    m = markets.get("IN")
    assert m.mode(datetime(2026, 11, 5, 10, 0)) == "session"
    assert m.mode(datetime(2026, 11, 5, 7, 0)) == "pre_open"
    assert m.mode(datetime(2026, 11, 5, 16, 0)) == "post_close"
    assert m.mode(datetime(2026, 11, 5, 22, 0)) == "deep"
    assert m.mode(datetime(2026, 11, 7, 11, 0)) == "deep"                       # Saturday
    assert m.mode(datetime(2026, 11, 3, 3, 0)) == "deep"


def test_us_session_runs_past_midnight_ist():
    us = markets.get("US")
    assert us.mode(datetime(2026, 11, 5, 23, 30)) == "session"
    assert us.mode(datetime(2026, 11, 6, 0, 30)) == "session"
    assert us.mode(datetime(2026, 11, 6, 12, 0)) == "deep"


def test_primary_prefers_home_then_busy_other():
    assert markets.primary(datetime(2026, 11, 5, 10, 0)) == ("IN", "session")
    assert markets.primary(datetime(2026, 11, 5, 23, 30)) == ("US", "session")
    assert markets.primary(datetime(2026, 11, 7, 11, 0)) == ("IN", "deep")


def test_session_closed_by():
    m = markets.get("IN")
    assert m.session_closed_by(datetime(2026, 11, 5, 16, 0)) == date(2026, 11, 5)
    assert m.session_closed_by(datetime(2026, 11, 5, 10, 0)) == date(2026, 11, 4)
    assert m.session_closed_by(datetime(2026, 11, 9, 8, 0)) == date(2026, 11, 6)


def test_budget_per_mode():
    assert 0 < markets.gpu_duty("deep") <= 1 and markets.rupee_per_hour("post_close") > 0
