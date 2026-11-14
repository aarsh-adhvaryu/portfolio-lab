"""S79b A44: the app checks its own first week and tells him once."""
from datetime import datetime, timedelta

import duckdb
import pytest

from pflab.pm import store
from pflab.service import presence, week_check as wc

ARM = datetime(2026, 11, 16, 9, 0)                  # S86b: the check counts from Monday 16 Nov 2026 (`ARM_FROM`)


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
    wc.note_modes(con, datetime(2026, 11, 16, 10, 0))
    wc.note_modes(con, datetime(2026, 11, 16, 10, 1))
    assert con.execute("SELECT count(*) FROM mode_seen_s79 WHERE market='IN'").fetchone()[0] == 1
    assert con.execute("SELECT mode FROM mode_seen_s79 WHERE market='IN'").fetchone()[0] == "session"


def test_message_is_plain_and_short():
    res = {"overall": "pass", "open_hours": 40.0, "criteria": [{"name": "no_failures", "status": "PASS", "text": "no job run failed"}]}
    t = wc.message(res, ARM, ARM + timedelta(days=8))
    assert "60-day feature freeze" in t and len(t.splitlines()) <= 15


# ------------------------------------------------------------------ S86b (W1): armed from 16 Nov, criteria 6 to 14, an accelerated week that passes and one that fails each

def _row(con, table, **kw):
    """Insert one row, every column not given filled with a neutral default by its type."""
    cols = con.execute(f"DESCRIBE {table}").fetchall()
    vals = {}
    for name, typ, *_ in cols:
        if name in kw:
            vals[name] = kw[name]
        elif typ.startswith(("VARCHAR",)):
            vals[name] = ""
        elif typ.startswith(("DATE",)):
            vals[name] = ARM.date()
        elif typ.startswith("TIMESTAMP"):
            vals[name] = ARM
        elif typ.startswith("BOOLEAN"):
            vals[name] = False
        else:
            vals[name] = 0
    con.execute(f"INSERT INTO {table} ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})", list(vals.values()))


NOW = ARM + timedelta(days=8)


def _green(con):
    wc.arm(con, ARM)
    _open_days(con)
    for m in wc.MODES:
        con.execute("INSERT INTO mode_seen_s79 VALUES (?,?,?,?)", [ARM.date(), "IN", m, ARM])
    con.execute("INSERT INTO catchup_s79 VALUES (1,'IN',?,NULL,NULL,2,'done','done',?,'')", [ARM, NOW])
    _row(con, "forecasts_s79", made_at=ARM + timedelta(hours=1))
    _row(con, "forecast_scores_s79", scored_at=ARM + timedelta(days=3))
    _row(con, "session_log_s81", day=ARM.date(), kind="run", detail_json='{"quotes": 5}')
    _row(con, "us_runs_s81", day=ARM.date(), ran_at=ARM, status="ok")
    _row(con, "us_orders_s81", order_id=1, placed_at=ARM, status="filled")
    for d in range(8):
        _row(con, "desk_sessions_s84", session_id=d + 1, day=(ARM + timedelta(days=d)).date(), status="done")
    _row(con, "pick_scores_s83")
    _row(con, "intake_queue_s85", item_id=1, state="done", created_at=ARM + timedelta(hours=2))
    con.execute("INSERT INTO page_loads_s86 VALUES (?,?,?,0)", [ARM, "/api/today", 200])
    _row(con, "alarm_s86", alarm_id=1, day=ARM.date(), mode="live")
    con.execute("INSERT INTO job_runs VALUES (50,'alarm',?,?,?,'ok','started')", [ARM + timedelta(hours=1)] * 3)
    _row(con, "us_quotes_s86", symbol="SPY", quote_ts=ARM, fetched_at=ARM)
    from pflab import markets
    from pflab.paper import cadence
    for m in ("IN", "US"):
        for d in markets.get(m).sessions_between(ARM.date(), NOW.date()):
            cadence.act(con, ARM, "think_loop", f"watch {m} {d} close: 0 signal(s), 0 case(s) opened", True)


def _status(con):
    r = wc.evaluate(con, ARM, NOW)
    return {c["name"]: c["status"] for c in r["criteria"]}, r["overall"]


def test_before_the_16th_nothing_is_armed(con):
    assert wc.arm(con, datetime(2026, 11, 15, 12, 0)) == 0
    assert wc.run(con, datetime(2026, 11, 15, 12, 0)).get("waiting")


def test_an_earlier_weeks_row_does_not_count_a_new_one_is_armed_on_the_16th(con):
    con.execute("INSERT INTO week_check_s79 (check_id, armed_at, release) VALUES (1, ?, 'old')", [datetime(2026, 11, 8, 9, 0)])
    assert wc.arm(con, ARM) != 1


def test_a_green_week_passes_all_fourteen_criteria(con):
    _green(con)
    st, overall = _status(con)
    assert len(st) == 14 and overall == "pass", st


def test_no_live_session_yet_is_not_tested_not_a_pass(con):
    _green(con)
    con.execute("DELETE FROM session_log_s81")
    st, overall = _status(con)
    assert st["session_loop_with_quotes"] == "NOT TESTED" and overall == "not_yet"


@pytest.mark.parametrize("name, spoil", [
    ("us_morning_and_fills", lambda c: c.execute("UPDATE us_orders_s81 SET status='open'")),
    ("daily_desk_and_picks_scored", lambda c: c.execute("DELETE FROM desk_sessions_s84 WHERE day=?", [(ARM + timedelta(days=2)).date()])),
    ("thinking_loop_every_close", lambda c: _row(c, "think_cases_s84", case_id=1, state="open", opened_at=ARM, market="IN")),
    ("chat_answered_every_message", lambda c: c.execute("UPDATE intake_queue_s85 SET state='failed'")),
    ("pages_without_server_error", lambda c: c.execute("INSERT INTO page_loads_s86 VALUES (?,?,?,0)", [ARM, "/api/world", 500])),
    ("spend_inside_cap_and_priced", lambda c: _row(c, "api_calls", call_id=1, created_at=ARM, status="done", cost_inr=None)),
    ("alarm_lane", lambda c: c.execute("UPDATE alarm_s86 SET slow_cause='the job was late'")),
    ("us_session_loop_and_fast_forward", lambda c: _row(c, "alarm_gap_s86", gap_id=1, off_to=ARM + timedelta(days=1), message="Off from x", red=1)),
])
def test_each_new_criterion_fails_on_its_own(con, name, spoil):
    _green(con)
    spoil(con)
    st, overall = _status(con)
    assert st[name] == "FAIL" and overall == "fail", (name, st)
