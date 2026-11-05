"""S79 item 3: run on open. Off is normal; a job is due when its input is newer; the one away digest; silence counts open time only."""
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from pflab.pm import store
from pflab.service import away, jobs, ondemand, presence
from pflab.service.jobs import Ctx, Job
from pflab.service.schedule import Daily


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


def _ctx(con, now):
    return Ctx(con, now, Path("."), Path("."), Path("."))


def _run(con, job, start, end, status="ok"):
    rid = store.next_id(con, "job_runs", "run_id")
    con.execute("INSERT INTO job_runs VALUES (?,?,?,?,?,?,?)", [rid, job, start, start, end, status, "{}"])


def test_gap_is_recorded_as_off_from_to(con):
    t0 = datetime(2026, 11, 6, 16, 0)
    presence.start(con, t0)
    presence.beat(con, t0 + timedelta(minutes=30))
    seg = presence.start(con, datetime(2026, 11, 9, 9, 0))
    assert seg["off_from"] == t0 + timedelta(minutes=30) and seg["off_to"] == datetime(2026, 11, 9, 9, 0)
    assert "off from Fri 06 Nov 16:30 to Mon 09 Nov 09:00" in presence.describe(seg["off_from"], seg["off_to"])
    assert presence.open_time(con, t0, datetime(2026, 11, 9, 9, 0)) == timedelta(minutes=30)       # the weekend does not count


def test_a_short_pause_is_not_a_gap(con):
    presence.start(con, datetime(2026, 11, 5, 10, 0))
    assert presence.start(con, datetime(2026, 11, 5, 10, 3))["off_from"] is None


def test_silence_counts_open_time_only(con):
    from pflab.paper import cadence
    presence.start(con, datetime(2026, 11, 2, 9, 0))
    presence.beat(con, datetime(2026, 11, 2, 10, 0))
    presence.start(con, datetime(2026, 11, 9, 9, 0))
    # 7 days wall clock since the last act, but only ~1 hour open: not silent for a 30 h limit
    assert presence.open_time(con, datetime(2026, 11, 2, 9, 0), datetime(2026, 11, 9, 9, 0)) < timedelta(hours=30)


def test_job_is_due_when_its_input_is_newer_not_at_its_slot(con):
    job = Job("forecast", Daily(21, 0), lambda c: {})
    now = datetime(2026, 11, 9, 11, 0)                          # Monday morning, long before 21:00
    _run(con, "forecast", datetime(2026, 11, 6, 21, 0), datetime(2026, 11, 6, 21, 1))
    assert jobs.is_due(_ctx(con, now), job)[0] is False
    _run(con, "prices", datetime(2026, 11, 9, 10, 50), datetime(2026, 11, 9, 10, 55))
    due, why = jobs.is_due(_ctx(con, now), job)
    assert due and "prices finished" in why
    _run(con, "forecast", datetime(2026, 11, 9, 10, 56), datetime(2026, 11, 9, 10, 57))
    assert jobs.is_due(_ctx(con, now), job)[0] is False


def test_a_failed_attempt_cools_down(con):
    job = Job("forecast", Daily(21, 0), lambda c: {}, cooldown_minutes=30)
    now = datetime(2026, 11, 9, 11, 0)
    _run(con, "forecast", datetime(2026, 11, 6, 21, 0), datetime(2026, 11, 6, 21, 1))
    _run(con, "prices", datetime(2026, 11, 9, 10, 50), datetime(2026, 11, 9, 10, 55))
    _run(con, "forecast", datetime(2026, 11, 9, 10, 58), datetime(2026, 11, 9, 10, 59), "failed")
    assert jobs.is_due(_ctx(con, now), job)[0] is False
    assert jobs.is_due(_ctx(con, now + timedelta(minutes=40)), job)[0] is True


def test_max_age_runs_on_open(con):
    job = Job("selfcheck", Daily(2, 10, weekdays_only=False), lambda c: {})
    _run(con, "selfcheck", datetime(2026, 11, 7, 2, 10), datetime(2026, 11, 7, 2, 11))
    due, why = jobs.is_due(_ctx(con, datetime(2026, 11, 9, 11, 0)), job)
    assert due
    _run(con, "selfcheck", datetime(2026, 11, 9, 10, 0), datetime(2026, 11, 9, 10, 1))
    assert jobs.is_due(_ctx(con, datetime(2026, 11, 9, 11, 0)), job)[0] is False


def test_a_summary_is_not_sent_hours_late(con):
    job = Job("summary_morning", Daily(9, 0), lambda c: {})
    assert jobs.is_due(_ctx(con, datetime(2026, 11, 9, 9, 30)), job)[0] is True
    due, why = jobs.is_due(_ctx(con, datetime(2026, 11, 9, 18, 0)), job)
    assert not due and "stale" in why


def test_unlisted_jobs_keep_the_old_rule(con):
    job = Job("somejob", Daily(21, 0), lambda c: {})
    assert jobs.is_due(_ctx(con, datetime(2026, 11, 9, 11, 0)), job)[0] is True            # latest slot Fri 21:00, no run
    assert ondemand.reason(_ctx(con, datetime(2026, 11, 9, 11, 0)), job) is None


def test_sessions_missed_over_a_weekend_and_digest_once(con):
    off_from, off_to = datetime(2026, 11, 6, 16, 0), datetime(2026, 11, 9, 9, 0)
    assert away.sessions_missed("IN", off_from, off_to) == []                      # Friday closed at 15:30 before it went off
    off_from = datetime(2026, 11, 6, 12, 0)
    assert away.sessions_missed("IN", off_from, off_to) == [date(2026, 11, 6)]
    presence.start(con, off_from)
    presence.start(con, off_to)
    did = away.maybe_send(con, off_to)
    assert did and away.maybe_send(con, off_to) is None                            # once per gap
    assert "While you were away: off from Fri 06 Nov 12:00" in away.latest(con)["text"]
    assert con.execute("SELECT kind FROM outbox WHERE dedup_key LIKE 'away:%'").fetchone()[0] == "summary"
