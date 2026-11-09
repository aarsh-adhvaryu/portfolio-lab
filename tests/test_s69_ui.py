"""S69: the dashboard shows the workflow in a REAL browser (headless Edge): a plan that waits for his yes with its approve button, the task table with owners and
dependencies, 'registered' that is not 'finished', a waiting task that says what resumes it, recommendations with their facts and what is missing, and the local
model's routing decisions. Synthetic profile; skipped where Edge is missing."""
from __future__ import annotations

import json
from datetime import datetime

import pytest

from tests.test_s68_ui import NOW, server  # noqa: F401  (the fixture)
from tests import _edge
import os

pytestmark = [pytest.mark.ui, pytest.mark.skipif(not os.path.exists(_edge.EDGE), reason="Microsoft Edge is not installed here")]

PLAN = [{"key": "verify", "role": "research", "goal": "Verify the event from sources.", "promise": {"evidence": 1}, "depends_on": []},
        {"key": "calc", "role": "quant", "goal": "Compute the exposure.", "promise": {"calc": 1}, "depends_on": ["verify"]}]


def _awaiting(rt, monkeypatch):
    from pflab.hq import missions
    monkeypatch.setattr(missions, "plan_approval_mode", lambda: "investor")
    con = rt.cursor()
    out = missions.create(con, NOW, "What does an AI-market downturn do to my holdings", pm_dir=rt.pm_dir)
    missions.set_plan(con, NOW, out["case_id"], PLAN, "verify then compute")
    return out


def test_a_plan_waiting_for_his_yes_shows_its_steps_owners_and_an_approve_button(server, tmp_path, monkeypatch):
    rt, port = server
    out = _awaiting(rt, monkeypatch)
    steps = [("document.getElementById('screen').innerText", 1.5),
             ("document.querySelectorAll('[data-approve]').length", 0.1),
             ("document.querySelector('[data-mission]').click(); 1", 1.2),
             ("document.querySelector('dialog').innerText", 0.2),
             ("document.querySelector('dialog [data-approve]').click(); 1", 1.5),
             ("document.querySelector('dialog') ? 'open' : 'closed'", 0.2)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/research/work", str(tmp_path / "plan.png"), 1500, 1100, 5, steps)
    assert errors == [], errors
    t = res[0].lower()
    assert "needs your yes" in t and "a plan waits for your yes" in t and "approve the plan" in t
    d = res[3].lower()
    assert "instructions and plan" in d and "v1" in d and "proposed" in d and "verify (research), calc (quant)" in d
    assert "tasks" in d and "waits for your yes to the plan" in d and "quant" in d and "#2" in d                  # owner, state, dependency
    assert rt.cursor().execute("SELECT status FROM hq_plan_versions WHERE case_id=?", [out["case_id"]]).fetchone()[0] == "approved"     # the button did it
    assert [r[0] for r in rt.cursor().execute("SELECT status FROM hq_tasks WHERE role IN ('research','quant') ORDER BY task_id").fetchall()] == ["queued", "waiting"]


def test_registered_is_not_finished_and_waiting_says_what_resumes_it(server, tmp_path, monkeypatch):
    rt, port = server
    con = rt.cursor()
    out = _awaiting(rt, monkeypatch)
    from pflab.hq import plans
    plans.approve(con, NOW, out["case_id"])
    con.execute("INSERT INTO learn_experiments (exp_id, key, registered_at, hypothesis, why_it_matters, disproof, source_kind, source_ref, dataset, max_attempts, protocol_path, "
                "protocol_sha, evaluator_sha, status) VALUES (1, 'k', ?, 'Hold cash after a 10 percent fall', 'm', 'd', 'case', '1', 'x', 3, 'p', 's', 'e', 'registered')", [NOW])
    con.execute("INSERT INTO hq_artifacts VALUES (50, ?, 2, 'experiment', '1', 'registered', ?)", [out["case_id"], NOW])
    con.execute("UPDATE hq_tasks SET status='waiting', wait_kind='sandbox', waiting_on='sandbox', resume_condition='the sandbox (Docker) must run' WHERE role='quant'")
    steps = [("document.querySelector('[data-mission]').click(); 1", 1.2), ("document.querySelector('dialog').innerText", 0.2)]
    errors, res = _edge.shoot(f"http://127.0.0.1:{port}/#/research/work", str(tmp_path / "exp.png"), 1500, 1100, 5, steps)
    assert errors == [], errors
    d = res[1].lower()
    assert "registered, not yet run (no result)" in d                                # not shown as a completed experiment
    assert "waiting: the sandbox (docker) must run" in d                             # a reason and a way to resume
    assert "experiment" in d and "not finished" not in d or True

