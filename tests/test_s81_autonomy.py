"""S81: the autonomy check measures what the loop did on its own and flags a frozen system. Synthetic store."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from pflab.core import autonomy
from pflab.pm import store

NOW = datetime(2026, 11, 16, 16, 0)


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "ledger.duckdb")


def _run(con, day, status):
    con.execute("INSERT INTO core_runs_s80 (day, ran_at, policy_id, status) VALUES (?,?,?,?)", [day, datetime.combine(day, datetime.min.time()), "baseline_v1", status])


def _session(con, sid, reason, status="done", lab_runs=2, ch=1, cost=40.0):
    con.execute("INSERT INTO core_sessions_s80 (session_id, started_at, reason, status, lab_runs, challengers, cost_inr) VALUES (?,?,?,?,?,?,?)",
                [sid, datetime(2026, 11, 14, 10, 0), reason, status, lab_runs, ch, cost])


def test_a_frozen_week_is_flagged_not_autonomous_with_the_reason(con):
    for d in (date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12)):
        _run(con, d, "held")
    rep = autonomy.report(con, NOW)
    assert rep["verdict"]["autonomous"] is False and "NOT AUTONOMOUS" in rep["verdict"]["why"] and "every close was a hold" in rep["verdict"]["why"]
    assert rep["closes"]["run"] == 3 and rep["closes"]["held"] == 3


def test_no_close_at_all_says_the_loop_did_not_run(con):
    assert "no close ran" in autonomy.report(con, NOW)["verdict"]["why"]


def test_a_session_on_its_own_trigger_counts_and_one_he_asked_for_does_not(con):
    _session(con, 1, "the harvesting window opened", lab_runs=3, ch=1, cost=60.0)
    _session(con, 2, "chat: look into the AI bubble", lab_runs=5, ch=2, cost=100.0)
    rep = autonomy.report(con, NOW)
    s = rep["strategist"]
    assert s["sessions"] == 2 and s["own_trigger"] == 1 and s["asked_by_him"] == 1 and s["lab_runs"] == 3 and s["challengers"] == 1
    assert rep["verdict"]["autonomous"] is True
    assert rep["money"]["rupees"] == 160.0 and rep["money"]["per_lab_run"] == 53.33


def test_a_traded_close_is_activity_and_a_part_that_cannot_be_read_is_named(con):
    _run(con, date(2026, 11, 11), "traded")
    rep = autonomy.report(con, NOW)
    assert rep["verdict"]["autonomous"] is True
    assert any(x.startswith("exits") for x in rep["left_out"])                      # the exit tables of S81 do not exist in this store: named, never guessed
    txt = autonomy.text(rep)
    assert "Autonomy check" in txt and "1 traded" in txt and "Could not be read" in txt


def test_allocation_and_promotions_are_counted(con):
    con.execute("INSERT INTO system_allocation_s79 (target_id, market, proposed_at, proposed_by, classes_json, reasons, status, activated_at) VALUES (1,'IN',?,?,?,?,?,?)",
                [datetime(2026, 11, 12, 9, 0), "strategist", "{}", "x" * 60, "active", datetime(2026, 11, 12, 9, 5)])
    con.execute("INSERT INTO core_promotions_s80 (promo_id, happened_at, kind, to_policy) VALUES (1, ?, 'promote', 'p1')", [datetime(2026, 11, 13, 9, 0)])
    rep = autonomy.report(con, NOW)
    assert rep["allocation"] == {"proposed": 1, "adopted": 1, "by_status": {"active": 1}}
    assert rep["strategist"]["promotions"] == {"promote": 1} and rep["verdict"]["autonomous"] is True
