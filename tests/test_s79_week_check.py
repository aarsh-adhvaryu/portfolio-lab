"""S79b A44: the app checks its own first week and tells him once."""
from datetime import datetime, timedelta

import duckdb
import pytest

from pflab.pm import store
from pflab.service import presence, week_check as wc

ARM = datetime(2026, 11, 9, 9, 0)


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    store.migrate(c)
    return c


def _open_days(con, days=8, hours_each=3):
    for d in range(days):
        t = ARM + timedelta(days=d)
        presence.start(con, t)
        presence.beat(con, t + timedelta(hours=hours_each))


def test_waits_until_the_week_is_over_and_enough_open_time(con):
    wc.arm(con, ARM)
    r = wc.run(con, ARM + timedelta(days=3))
    assert r.get("waiting") and "of 7 days" in r["skipped"]
    _open_days(con, days=2, hours_each=1)
    assert wc.run(con, ARM + timedelta(days=8)).get("waiting")                       # 8 days but under 12 h open


def test_pass_sends_once_and_starts_the_freeze(con):
    wc.arm(con, ARM)
    _open_days(con)
    for m in wc.MODES:
        con.execute("INSERT INTO mode_seen_s79 VALUES (?,?,?,?)", [ARM.date(), "IN", m, ARM])
    res = wc.evaluate(con, ARM, ARM + timedelta(days=8))
    names = {c["name"]: c["status"] for c in res["criteria"]}
    assert names["modes_reached"] == "PASS" and names["no_failures"] == "PASS"
    assert names["catch_up_after_gaps"] == "FAIL"                                    # the nights off missed sessions and no catch-up row exists in this synthetic store
    assert res["overall"] == "fail"


def test_a_failed_job_fails_the_check_and_an_offline_one_does_not(con):
    wc.arm(con, ARM)
    _open_days(con)
    con.execute("INSERT INTO job_runs VALUES (1,'collect',?,?,?,'offline','offline: x')", [ARM + timedelta(days=2)] * 3)
    assert {c["name"]: c["status"] for c in wc.evaluate(con, ARM, ARM + timedelta(days=8))["criteria"]}["no_failures"] == "PASS"
    con.execute("INSERT INTO job_runs VALUES (2,'nav',?,?,?,'failed','KeyError: x')", [ARM + timedelta(days=3)] * 3)
    r = wc.evaluate(con, ARM, ARM + timedelta(days=8))
    assert r["overall"] == "fail" and "nav x1" in [c for c in r["criteria"] if c["name"] == "no_failures"][0]["text"]
    out = wc.run(con, ARM + timedelta(days=8))
    assert out["overall"] == "fail" and out["final"]
    assert con.execute("SELECT count(*) FROM outbox WHERE dedup_key LIKE 'week_check:%'").fetchone()[0] == 1
    assert wc.run(con, ARM + timedelta(days=9)).get("skipped", "").startswith("verdict already given")


def test_a_gap_with_a_missed_session_needs_a_catch_up(con):
    wc.arm(con, ARM)
    presence.start(con, ARM)
    presence.beat(con, ARM + timedelta(hours=4))
    presence.start(con, ARM + timedelta(days=2))                                     # off Mon 13:00 to Wed 09:00: Mon and Tue closed while off
    r = wc.evaluate(con, ARM, ARM + timedelta(days=8))
    assert [c for c in r["criteria"] if c["name"] == "catch_up_after_gaps"][0]["status"] == "FAIL"
    con.execute("INSERT INTO catchup_s79 VALUES (1,'IN',?,NULL,NULL,2,'done','done',?,'')", [ARM + timedelta(days=2), ARM + timedelta(days=2, minutes=5)])
    r = wc.evaluate(con, ARM, ARM + timedelta(days=8))
    assert [c for c in r["criteria"] if c["name"] == "catch_up_after_gaps"][0]["status"] == "PASS"


def test_modes_are_noted_once_a_day(con):
    wc.note_modes(con, datetime(2026, 11, 9, 10, 0))
    wc.note_modes(con, datetime(2026, 11, 9, 10, 1))
    assert con.execute("SELECT count(*) FROM mode_seen_s79 WHERE market='IN'").fetchone()[0] == 1
    assert con.execute("SELECT mode FROM mode_seen_s79 WHERE market='IN'").fetchone()[0] == "session"


def test_message_is_plain_and_short():
    res = {"overall": "pass", "open_hours": 40.0, "criteria": [{"name": "no_failures", "status": "PASS", "text": "no job run failed"}]}
    t = wc.message(res, ARM, ARM + timedelta(days=8))
    assert "60-day feature freeze" in t and len(t.splitlines()) <= 15
