"""S86b (W1): the Problems list: collected from where problems are written, deduplicated with first and last time, copyable, one line a week; the page-load record of the app's server."""
from __future__ import annotations

from datetime import datetime, timedelta

import duckdb
import pytest

from pflab.pm import store
from pflab.service import problems

NOW = datetime(2026, 11, 20, 12, 0)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


def test_a_clean_week_has_no_line_and_a_plain_none(con):
    assert problems.weekly_line(con, NOW) is None and problems.copy_text(con) == "Problems: none."


def test_failed_jobs_are_deduplicated_with_first_and_last_time(con):
    for k, t in enumerate((NOW - timedelta(days=3), NOW - timedelta(days=1))):
        con.execute("INSERT INTO job_runs VALUES (?,?,?,?,?,?,?)", [k + 1, "nav", t, t, t, "failed", "KeyError: x"])
    con.execute("INSERT INTO job_runs VALUES (9,'collect',?,?,?, 'failed','abandoned: the process stopped')", [NOW] * 3)
    problems.collect(con, NOW)
    problems.collect(con, NOW)                                                       # idempotent
    rows = problems.listing(con)
    assert len(rows) == 1 and rows[0]["key"] == "nav" and rows[0]["times"] == 2 and rows[0]["first_seen"] < rows[0]["last_seen"]
    assert "the job nav failed 2 time(s)" in problems.copy_text(con) and "first" in problems.copy_text(con)


def test_blind_spots_and_late_alarms_are_listed_and_the_weekly_line_counts_kinds(con):
    con.execute("INSERT INTO eyes_s86 (source, label, blind_since) VALUES ('yahoo','news (Yahoo Finance)',?)", [NOW - timedelta(hours=3)])
    con.execute("INSERT INTO alarm_s86 (alarm_id, isin, symbol, headline, first_seen_at, slow_cause, day) VALUES (1,'X','ABC','h',?, 'the source was late', ?)", [NOW - timedelta(days=1), NOW.date()])
    problems.collect(con, NOW)
    kinds = {r["kind"] for r in problems.listing(con)}
    assert kinds == {"blind_spot", "late_alarm"}
    assert "Problems this week: 2" in problems.weekly_line(con, NOW)


def test_page_loads_table_exists_for_the_server_middleware(con):
    con.execute("INSERT INTO page_loads_s86 VALUES (?,?,?,?)", [NOW, "/api/today", 200, 12.0])
    assert con.execute("SELECT count(*) FROM page_loads_s86").fetchone()[0] == 1
