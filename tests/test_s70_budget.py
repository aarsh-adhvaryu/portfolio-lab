"""S70: a mission's money is a class (quick, standard, deep) shown before his yes; work the system chooses itself is quick, starts at most once a day,
only for a holding that matters, and only inside its own share of the month. Synthetic data; the model is scripted."""
from __future__ import annotations

import pytest

from pflab.agents import analyst as an
from pflab.hq import cases, missions, service
from tests.test_s68_autonomy import AAA, CFG, NOW, con, rt, _insert_reading  # noqa: F401  (fixtures)


def _spend_on_system_missions(con, rupees: float) -> None:
    task = con.execute("SELECT t.task_id FROM hq_tasks t JOIN hq_missions m ON m.case_id = t.case_id WHERE m.origin='system' LIMIT 1").fetchone()[0]
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, cost_inr, agent, turn, task_id) "
                "VALUES (9001, ?, 'live', 'claude-sonnet-5-5', 'q', '', '{}', 'done', ?, 'w_research', 1, ?)", [NOW, rupees, task])


def test_what_he_asks_is_standard_and_what_the_system_chooses_is_quick(rt, con):
    asked = missions.create(con, NOW, "Compare phased buying with holding cash", pm_dir=rt.pm_dir)
    assert missions.budget_class(con, asked["case_id"]) == "standard" and missions.cap_of(con, asked["case_id"]) == 80.0
    deep = missions.create(con, NOW, "Study the whole of the technology exposure", pm_dir=rt.pm_dir, budget="deep")
    assert missions.cap_of(con, deep["case_id"]) == 200.0
    _insert_reading(con)
    missions.scan(rt)
    cid = con.execute("SELECT case_id FROM hq_missions WHERE origin='system'").fetchone()[0]
    assert missions.budget_class(con, cid) == "quick" and missions.cap_of(con, cid) == 20.0
    assert missions.card(con, cid)["budget"] == {"spent": 0.0, "cap": 20.0, "class": "quick"}
    assert missions.allow_more(con, NOW, cid, 30.0)["cap_now"] == 50.0           # his word adds to the class cap


def test_a_policy_file_can_set_the_classes_or_one_flat_cap(rt, con, monkeypatch):
    out = missions.create(con, NOW, "Compare phased buying with holding cash", pm_dir=rt.pm_dir)
    monkeypatch.setattr(an, "config", lambda: {**CFG, "policy": {"mission_classes": {"standard": 120}}})
    assert missions.cap_of(con, out["case_id"]) == 120.0
    monkeypatch.setattr(an, "config", lambda: {**CFG, "policy": {"mission_classes": {"standard": 120}, "mission_rupees": 300}})
    assert missions.cap_of(con, out["case_id"]) == 300.0                          # a flat cap, as before S70, still wins


def test_the_system_starts_at_most_one_mission_a_day_for_a_holding_that_matters(rt, con, monkeypatch):
    monkeypatch.setattr(missions, "_weights", lambda c, n: {AAA: 0.01})
    _insert_reading(con)
    r = missions.scan(rt)
    assert r["started"] == [] and r["noted"] == 1                                 # a 1% holding: noted, not a team's work
    assert con.execute("SELECT status FROM hq_cases WHERE subject_key LIKE 'discover:reading:%'").fetchone()[0] == "queued"   # kept, not closed
    monkeypatch.setattr(missions, "_weights", lambda c, n: {AAA: 0.05})
    assert len(missions.scan(rt)["started"]) == 1


def test_the_systems_own_share_of_the_month_holds_new_starts_back(rt, con, monkeypatch):
    monkeypatch.setattr(missions, "DAILY_NEW", 5)                                 # so the share, not the day, is what stops it
    _insert_reading(con, "D1")
    assert len(missions.scan(rt)["started"]) == 1
    assert missions.system_spend_month(con, NOW) == 0.0
    _spend_on_system_missions(con, 800.0)                                         # more than 30% of Rs 2,500
    assert missions.system_spend_month(con, NOW) == pytest.approx(800.0)
    other = "INE000B01012"
    con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                   VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, 'BBB', 'BBB Limited', 'synthetic', now())""", [other])
    monkeypatch.setattr(service, "names", lambda r: ([AAA, other], []))
    _insert_reading(con, "D2", other)
    r = missions.scan(rt)
    assert r["started"] == [] and r["held_back"] >= 1


def test_a_mission_he_asked_for_is_not_counted_against_the_systems_share(rt, con):
    out = missions.create(con, NOW, "Compare phased buying with holding cash", pm_dir=rt.pm_dir)
    tid = con.execute("SELECT task_id FROM hq_tasks WHERE case_id=?", [out["case_id"]]).fetchone()[0]
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, cost_inr, agent, turn, task_id) "
                "VALUES (9002, ?, 'live', 'claude-sonnet-5-5', 'q', '', '{}', 'done', 900.0, 'w_coord', 1, ?)", [NOW, tid])
    assert missions.system_spend_month(con, NOW) == 0.0
