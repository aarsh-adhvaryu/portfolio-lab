"""S81 B9: tests re-written for behaviour that still exists and lost its tests when the committee code was cut (S80 phase 4): the circuit breaker, the daily look, the budget reset.
Synthetic stores only."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from pflab.hq import governor as gv
from pflab.paper import cadence
from pflab.pm import store

NOW = datetime(2026, 11, 20, 20, 0)


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "ledger.duckdb")


def _days(con, values, flows=None):
    d0 = date(2026, 10, 30)
    for i, v in enumerate(values):
        f = (flows or {}).get(i, 0.0)
        con.execute("INSERT INTO paper_days VALUES (?, ?, ?, 0, ?, '{}')", [d0 + timedelta(days=i), v, v, f])


def test_the_circuit_breaker_turns_on_at_a_twelve_percent_fall_from_the_high_and_off_above_it(con):
    _days(con, [100.0, 110.0, 106.0])
    assert cadence.breaker(con)["on"] is False                                           # 3.6% below the high
    con.execute("DELETE FROM paper_days")
    _days(con, [100.0, 110.0, 96.0])                                                    # 12.7% below the high
    b = cadence.breaker(con)
    assert b["on"] is True and b["drawdown"] < -0.12 and b["limit"] == -cadence.BREAKER_DRAWDOWN


def test_a_top_up_is_not_a_gain_so_it_cannot_hide_a_fall_from_the_breaker(con):
    # the account falls 13% on its own while 20 of outside money comes in: the level path takes the 20 out, so the breaker is still on
    _days(con, [100.0, 110.0, 110.0 * 0.87 + 20.0], flows={2: 20.0})
    assert cadence.breaker(con)["on"] is True
    path = dict(cadence.level_path(con))
    assert abs(path[date(2026, 11, 1)] - (110.0 * 0.87) / 110.0 * 1.1) < 1e-9


def test_the_breaker_needs_two_marked_days_before_it_says_anything(con):
    _days(con, [100.0])
    assert cadence.breaker(con) == {"on": False, "drawdown": 0.0}


def test_the_daily_look_always_leaves_an_act_even_when_nothing_needs_a_look(con):
    from pflab.paper import book
    con.execute("INSERT INTO paper_cash VALUES (1, ?, 500000, 'seed', 'fake starting cash', now())", [date(2026, 10, 30)])
    _days(con, [500000.0, 501000.0])
    out = cadence.daily_look(con, NOW)
    assert "daily look" in out["look"] and "nothing needs a look today" in out["look"] and out["reasons"] == []
    acts = cadence.last_acts(con)
    assert acts and acts[0]["loop"] == "daily_look"
    assert book.started(con)


def test_the_daily_look_before_the_book_starts_says_so_and_does_not_fail(con):
    assert cadence.daily_look(con, NOW) == {"waiting": "not started"}


def test_a_reset_of_the_budget_also_resets_the_day_limit(con):
    """S78 (live 2026-11-02): he reset the budget at 19:00 but the day limit still counted the morning's spend and refused every call until midnight."""
    cfg = {"model": "m", "cap": 2500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True}
    now = datetime(2026, 11, 2, 19, 30)
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, cost_inr, agent, turn, his_order) "
                "VALUES (1,?,?,?,?,?,?,?,?,?,?,?)", [datetime(2026, 11, 2, 9, 0), "live", gv.OPUS, "q", "", "{}", "done", 112.6, "brain", 1, False])
    with pytest.raises(gv.BudgetRefused, match="a day"):
        gv.check(con, "brain", 17.2, 5000, 4000, now, "normal", cfg)                    # without the reset the day is spent
    gv.check(con, "brain", 17.2, 5000, 4000, now, "normal", {**cfg, "counted_since": datetime(2026, 11, 2, 19, 0)})   # counted from the reset: it may begin
