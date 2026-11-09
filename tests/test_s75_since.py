"""S75: "reset the usage" without deleting anything: the month's usage is counted from `[api] counted_since` when that is later than the first of the month."""
from __future__ import annotations

from datetime import datetime

import pytest

from pflab.agents import analyst as an
from pflab.hq import governor as gv
from pflab.pm import store

NOW = datetime(2026, 11, 20, 12, 0)
CFG = {"model": an.MODEL, "cap": 1000.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True}


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


def _call(con, cid, day, rupees, agent="w_research"):
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, cost_inr, agent, turn) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [cid, day, "live", gv.SONNET, "q", "", "{}", "done", rupees, agent, 1])


def test_the_month_starts_on_the_first_unless_a_later_moment_is_given():
    assert an.month_start(NOW, CFG) == datetime(2026, 11, 1)
    assert an.month_start(NOW, {**CFG, "counted_since": datetime(2026, 11, 12, 8, 0)}) == datetime(2026, 11, 12, 8, 0)
    assert an.month_start(NOW, {**CFG, "counted_since": "2026-11-12T08:00:00"}) == datetime(2026, 11, 12, 8, 0)
    assert an.month_start(NOW, {**CFG, "counted_since": datetime(2026, 10, 5)}) == datetime(2026, 11, 1)          # earlier than the month: no effect
    assert an.month_start(NOW, {**CFG, "counted_since": datetime(2026, 12, 5)}) == datetime(2026, 11, 1)          # in the future: ignored
    assert an.month_start(NOW, {**CFG, "counted_since": "not a date"}) == datetime(2026, 11, 1)


def test_spend_before_the_moment_stays_in_the_record_but_stops_counting(con, monkeypatch):
    _call(con, 1, datetime(2026, 11, 3), 300.0)
    _call(con, 2, datetime(2026, 11, 15), 40.0)
    monkeypatch.setattr(an, "config", lambda: CFG)
    assert an.month_spend_inr(con, NOW) == 340.0
    monkeypatch.setattr(an, "config", lambda: {**CFG, "counted_since": datetime(2026, 11, 12)})
    assert an.month_spend_inr(con, NOW) == 40.0
    assert con.execute("SELECT count(*), sum(cost_inr) FROM api_calls").fetchone() == (2, 340.0)                  # nothing was deleted

