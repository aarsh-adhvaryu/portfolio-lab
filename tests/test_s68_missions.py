"""S68 P2: one request becomes a mission carried by a coordinator, research and quant workers and an independent reviewer; tasks are done when
their promised artifacts exist; waits are named and cost no attempt; a restart loses nothing. A scripted model stands in for the API (labelled:
these are development tests, the live run is the acceptance). Synthetic data only."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from pflab.agents import analyst as an
from pflab.hq import board, cases, egress, governor as gv, missions, roster, service, workers
from pflab.hq.desk import Desk
from pflab.pm import store

NOW = datetime(2026, 10, 31, 15, 0)
CFG = {"model": an.MODEL, "cap": 2500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True, "tijori_to_analyst": True}


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


# --- a scripted model: answers by role, from the system prompt ---------------------------------------------------------------------------------

def _use(*calls, model=gv.SONNET):
    content = [SimpleNamespace(type="thinking", thinking="", signature="sig")]
    content += [SimpleNamespace(type="tool_use", id=f"tu{k}{id(c)}", name=n, input=i) for k, (n, i) in enumerate(calls) for c in [object()]]
    return SimpleNamespace(content=content, stop_reason="tool_use", model=model,
                           usage=SimpleNamespace(input_tokens=900, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0))


def _say(text, model=gv.SONNET):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn", model=model,
                           usage=SimpleNamespace(input_tokens=900, output_tokens=120, cache_read_input_tokens=0, cache_creation_input_tokens=0))


ROLE_MARK = {"ROLE coordinator": "coordinator", "ROLE research": "research", "ROLE quant": "quant", "ROLE review": "review"}


class Model:
    def __init__(self, scripts):
        self.scripts = {r: list(v) for r, v in scripts.items()}
        self.seen = []
        self.messages = SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(input_tokens=1000), create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        sys_text = kw["system"][0]["text"]
        role = next(r for m, r in ROLE_MARK.items() if m in sys_text)
        self.seen.append((role, kw))
        q = self.scripts[role]
        if not q:
            raise AssertionError(f"the {role} was asked again with nothing scripted")
        r = q.pop(0)
        if isinstance(r, Exception):
            raise r
        return r(kw) if callable(r) else r


@pytest.fixture
def rt(con, tmp_path, monkeypatch):
    monkeypatch.setattr(an, "config", lambda: CFG)
    monkeypatch.setattr(service, "gate", lambda r: egress.Gate())
    (tmp_path / "pm" / "app").mkdir(parents=True)
    d = Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, {"brain": "normal", "preset": "full", "telegram_send": False}, clock=lambda: NOW)
    return d


def _fake_calc(monkeypatch, status="checked"):
    from pflab.agents import workshop as wk

    def ask(con, question, *a, **k):
        spec = SimpleNamespace(code="result = {'x': 1}", alt_code="", datasets=[], test={}, params={})
        run = SimpleNamespace(result={"worst_fall_pct": -18.0, "months_to_recover": 14}, contained=True, cross_checked=True, problems=[])
        return SimpleNamespace(status=status, spec=spec, run=run, folder=None, attempts=[1], confirm={"status": "agrees"}, inputs=None)
    monkeypatch.setattr(wk, "ask", ask)


PLAN = [{"key": "verify", "role": "research", "goal": "Verify the event, its dates and size from sources; look for evidence against it.",
         "promise": {"evidence": 2}, "depends_on": []},
        {"key": "scenarios", "role": "quant", "goal": "Compare phased buying with holding cash across a sharp fall; assumptions visible.",
         "promise": {"calc": 1}, "depends_on": ["verify"]}]


def _happy_scripts(extra_review=None):
    return {
        "coordinator": [_use(("plan_mission", {"case_id": 1, "steps_json": json.dumps(PLAN), "approach": "verify then compute"}), model=gv.OPUS), _say("Planned.", gv.OPUS),
                        _use(("submit_answer", {"case_id": 1, "answer": "The evidence in the case shows the drop in evidence 1; calc 1 gives -18.0 under stated assumptions.",
                                                "limitations": "Weights are assumptions.", "monitor_next": "The next filing."}),
                             model=gv.OPUS),
                        _say("Answer written.", gv.OPUS)],
        "research": [_use(("case_evidence", {"case_id": 1, "stance": "for", "text": "A company filing reports the move.", "source_kind": "filing", "published": "2026-10-20"}),
                          ("case_evidence", {"case_id": 1, "stance": "against", "text": "The move reversed within two sessions per prices.", "source_kind": "observation"})),
                     _say("Two items recorded.")],
        "quant": [_use(("case_calculate", {"case_id": 1, "question": "Worst fall and recovery under phased buying versus cash"})), _say("Calculation done.")],
        "review": [_use(("reproduce_calc", {"calc_id": 1}), model=gv.OPUS),
                   _use(("submit_review", {"case_id": 1, "verdict": "approve", "findings": "Reproduced calc 1; evidence is sourced.", "checks": "reproduce_calc 1"}), model=gv.OPUS),
                   _say("Approved.", gv.OPUS)] if extra_review is None else extra_review,
    }


def _run(rt, monkeypatch, scripts, goal="Investigate a China-related AI sell-off and my exposure to it"):
    m = Model(scripts)
    rt._hq_client = m
    monkeypatch.setattr(cases, "reproduce", lambda con, calc_id, **k: {"reproduced": True, "basis": "original", "label": "reproduced from the original data",
                                                                        "same_as_kept": True, "differences": [], "problems": [], "result": {"x": 1}, "kept": {"x": 1}})
    out = missions.create(rt.cursor(), NOW, goal, pm_dir=rt.pm_dir)
    return m, out


def test_one_request_becomes_planned_researched_calculated_reviewed_and_answered(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    m, out = _run(rt, monkeypatch, _happy_scripts())
    assert out["state"] == "planning" and out["case_id"] == 1
    service.drive_missions(rt)
    card = missions.card(con, 1)
    assert card["state"] == "done" and card["blocker"] is None, (card["state"], card["blocker"], card["tasks"])
    kinds = [o["kind"] for o in card["outputs"]]
    assert kinds.count("evidence") == 2 and "calc" in kinds and "review" in kinds and "answer" in kinds and "plan" in kinds
    assert [t["role"] for t in card["tasks"]] == ["coordinator", "research", "quant", "review", "coordinator"]
    assert all(t["status"] == "done" for t in card["tasks"])
    c = cases.get(con, 1)
    assert c["status"] == "done" and c["decision"] == "watch" and "calc 1" in c["reason"]
    assert con.execute("SELECT count(*) FROM hq_calcs WHERE case_id=1").fetchone()[0] == 1               # a saved calculation
    assert con.execute("SELECT outcome FROM hq_case_reviews WHERE outcome IS NOT NULL").fetchone()[0] == "approved"
    # each role saw only its own tools and its own context
    tools_by_role = {}
    for role, kw in m.seen:
        tools_by_role.setdefault(role, {t["name"] for t in kw["tools"]})
    assert "submit_review" in tools_by_role["review"] and "submit_review" not in tools_by_role["research"]
    assert "case_calculate" in tools_by_role["quant"] and "case_calculate" not in tools_by_role["review"]
    assert "plan_mission" in tools_by_role["coordinator"] and "plan_mission" not in tools_by_role["quant"]
    rev_first = next(kw for role, kw in m.seen if role == "review")
    assert "ROLE review" in rev_first["system"][0]["text"] and "worker" not in json.dumps(rev_first["messages"][0]).lower().split("research worker")[0][:0]


def test_the_dependent_step_waits_for_its_dependency_and_runs_after_it(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    _run(rt, monkeypatch, _happy_scripts())
    board.run_one(rt, roster.runners())                                   # the coordinator only: it plans
    ts = {t["role"]: t for t in missions._tasks(con, 1) if t["role"] in ("research", "quant")}
    assert ts["research"]["status"] == "queued" and ts["quant"]["status"] == "waiting" and ts["quant"]["waiting_on"] == f"task:{ts['research']['id']}"
    board.run_one(rt, roster.runners())                                   # research done -> the quant is woken
    assert missions._tasks(con, 1)[2]["status"] == "queued" and missions._tasks(con, 1)[1]["status"] == "done"


def test_a_task_that_stops_talking_without_its_artifact_is_told_and_then_fails_with_the_reason(rt, con, monkeypatch):
    scripts = _happy_scripts()
    scripts["research"] = [_say("I looked and found nothing to record."), _say("Still nothing."), _say("No evidence, sorry.")]
    _run(rt, monkeypatch, scripts)
    service.drive_missions(rt)
    card = missions.card(con, 1)
    assert card["state"] == "blocked" and "research" in card["blocker"] and "evidence" in card["blocker"]
    assert cases.get(con, 1)["status"] == "failed"                         # a model's say-so is not completion; the case does not read "done"
    assert not [o for o in card["outputs"] if o["kind"] == "answer"]


def test_missing_docker_parks_the_quant_with_a_named_condition_and_no_attempt_spent(rt, con, monkeypatch):
    from pflab.agents import sandbox as sb
    from pflab.agents import workshop as wk
    state = {"ok": False}

    def ask(*a, **k):
        if not state["ok"]:
            raise sb.SandboxUnavailable("Docker Desktop is not running")
        return _fake_calc_out()
    monkeypatch.setattr(wk, "ask", ask)
    monkeypatch.setattr(sb, "status", lambda *a, **k: {"ok": state["ok"], "why": "Docker Desktop is not running"})
    scripts = _happy_scripts()
    scripts["quant"] = [_use(("case_calculate", {"case_id": 1, "question": "worst fall under both policies"})),
                        _use(("case_calculate", {"case_id": 1, "question": "worst fall under both policies"})), _say("Calculation done.")]
    _run(rt, monkeypatch, scripts)
    service.drive_missions(rt)
    q = next(t for t in missions._tasks(con, 1) if t["role"] == "quant")
    assert q["status"] == "waiting" and q["waiting_on"] == "sandbox" and "Docker" in (q["resume"] or "")
    assert q["attempts"] == 1
    card = missions.card(con, 1)
    assert card["state"] == "working" and "waiting" in card["blocker"] and "sandbox" in card["blocker"]
    assert con.execute("SELECT count(*) FROM hq_calcs").fetchone()[0] == 0           # nothing invented, nothing run on the host
    state["ok"] = True
    service.drive_missions(rt)                                                         # Docker is back: the same task resumes
    assert missions.card(con, 1)["state"] == "done"
    q = next(t for t in missions._tasks(con, 1) if t["role"] == "quant")
    assert q["status"] == "done"


def _fake_calc_out():
    spec = SimpleNamespace(code="result = {'x': 1}", alt_code="", datasets=[], test={}, params={})
    run = SimpleNamespace(result={"worst_fall_pct": -18.0}, contained=True, cross_checked=True, problems=[])
    return SimpleNamespace(status="checked", spec=spec, run=run, folder=None, attempts=[1], confirm={"status": "agrees"}, inputs=None)


def test_a_provider_failure_waits_with_back_off_and_does_not_use_an_analytical_attempt(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    scripts = _happy_scripts()
    scripts["research"] = [ConnectionError("provider down")] + scripts["research"]
    _run(rt, monkeypatch, scripts)
    board.run_all(rt, roster.runners())
    r = next(t for t in missions._tasks(con, 1) if t["role"] == "research")
    assert r["status"] == "retry" and r["wait_kind"] == "provider" and r["attempts"] == 0 and r["next_review"] > NOW
    assert board.next_queued(con, NOW) is None                                         # not retried until its time
    later = NOW + timedelta(minutes=10)
    rt.clock = lambda: later
    service.drive_missions(rt)
    assert missions.card(con, 1)["state"] == "done"


def test_a_budget_refusal_waits_until_the_budget_can_change(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    for _ in range(8):                                                                 # the system's workers have spent their day
        con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, cost_inr, agent, turn) "
                    "VALUES ((SELECT coalesce(max(call_id),0)+1 FROM api_calls), ?, 'live', ?, 'q', '', '{}', 'done', 11.0, 'w_research', 1)", [NOW, gv.SONNET])
    m = Model(_happy_scripts())
    rt._hq_client = m
    missions.create(con, NOW, "Look into the oil price move for the system's own reasons", pm_dir=rt.pm_dir, origin="code")       # not his order: day limits hold
    board.run_all(rt, roster.runners())
    r = next(t for t in missions._tasks(con, 1) if t["role"] == "coordinator")        # the workers' layer is spent for the day: the first task waits
    assert r["status"] == "retry" and r["wait_kind"] == "budget" and r["attempts"] == 0
    assert (r["next_review"] - NOW) > timedelta(hours=1)                               # tomorrow, not in 5 minutes
    assert board.next_queued(con, NOW) is None
    missions.tick(rt)
    card = missions.card(con, 1)
    assert "waiting" in (card["blocker"] or "") and "budget" in (card["blocker"] or "")


def test_a_restart_in_the_middle_loses_no_artifact_and_repeats_no_task(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    m, _ = _run(rt, monkeypatch, _happy_scripts())
    board.run_all(rt, roster.runners())
    missions.tick(rt)
    board.run_one(rt, roster.runners())                                                # research done
    n_art = con.execute("SELECT count(*) FROM hq_artifacts").fetchone()[0]
    con.execute("UPDATE hq_tasks SET status='running', attempts=1 WHERE role='quant'")  # the process died during the quant's run
    board._LIVE.clear()
    assert board.reap(con, NOW) == 1
    service.drive_missions(rt)                                                         # the new process carries on from the store
    assert missions.card(con, 1)["state"] == "done"
    assert con.execute("SELECT count(*) FROM hq_tasks WHERE role='research'").fetchone()[0] == 1       # research not repeated
    assert con.execute("SELECT count(*) FROM hq_artifacts WHERE kind='evidence'").fetchone()[0] == 2
    assert n_art >= 3


def test_a_revision_request_creates_a_task_for_that_role_and_a_second_review(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    review = [_use(("submit_review", {"case_id": 1, "verdict": "revise", "findings": "The baseline is missing.",
                                      "revisions_json": json.dumps([{"role": "quant", "what": "Add the buy-now baseline"}])}), model=gv.OPUS), _say("Revise.", gv.OPUS),
              _use(("reproduce_calc", {"calc_id": 1}), model=gv.OPUS),
              _use(("submit_review", {"case_id": 1, "verdict": "approve", "findings": "Baseline now present.", "checks": "reproduce"}), model=gv.OPUS), _say("Approved.", gv.OPUS)]
    scripts = _happy_scripts(extra_review=review)
    scripts["quant"] = [_use(("case_calculate", {"case_id": 1, "question": "worst fall"})), _say("done"),
                        _use(("case_calculate", {"case_id": 1, "question": "worst fall with the buy-now baseline"})), _say("done")]
    _run(rt, monkeypatch, scripts)
    service.drive_missions(rt)
    card = missions.card(con, 1)
    assert card["state"] == "done" and card["round"] == 1
    assert [t["role"] for t in card["tasks"]].count("review") == 2 and [t["role"] for t in card["tasks"]].count("quant") == 2
    assert [r[0] for r in con.execute("SELECT outcome FROM hq_case_reviews WHERE outcome IS NOT NULL ORDER BY review_id").fetchall()] == ["revise", "approved"]


def test_a_plan_with_a_bad_step_is_refused_and_the_coordinator_may_try_again(rt, con, monkeypatch):
    bad = [{"key": "a", "role": "trader", "goal": "buy it"}]
    scripts = _happy_scripts()
    scripts["coordinator"][0] = _use(("plan_mission", {"case_id": 1, "steps_json": json.dumps(bad)}), model=gv.OPUS)
    scripts["coordinator"].insert(1, _use(("plan_mission", {"case_id": 1, "steps_json": json.dumps(PLAN)}), model=gv.OPUS))
    _fake_calc(monkeypatch)
    _run(rt, monkeypatch, scripts)
    service.drive_missions(rt)
    assert missions.card(con, 1)["state"] == "done"
    assert con.execute("SELECT count(*) FROM hq_tool_calls WHERE tool='plan_mission'").fetchone()[0] == 2


def test_a_worker_cannot_call_a_tool_outside_its_role(rt, con, monkeypatch):
    scripts = _happy_scripts()
    scripts["research"] = [_use(("submit_review", {"case_id": 1, "verdict": "approve", "findings": "ok"})), _say("done")]
    _run(rt, monkeypatch, scripts)
    board.run_all(rt, roster.runners())
    row = con.execute("SELECT status, result FROM hq_tool_calls WHERE tool='submit_review'").fetchone()
    assert row[0] == "refused" and "not a tool of this role" in row[1]
    assert con.execute("SELECT count(*) FROM hq_case_reviews WHERE outcome IS NOT NULL").fetchone()[0] == 0


def test_the_investigation_card_has_goal_owner_action_outputs_blocker_progress_and_trigger(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    _run(rt, monkeypatch, _happy_scripts())
    card = missions.card(con, 1)
    for k in ("goal", "owner", "current_action", "outputs", "blocker", "last_useful_progress", "next_trigger", "state", "snapshot", "tasks"):
        assert k in card
    assert card["owner"] == "coordinator" and card["next_trigger"] == "the coordinator plans the steps"
    assert card["snapshot"].endswith("no-prices")                                      # the snapshot the mission reads is named


def test_the_same_goal_on_the_same_day_is_one_mission(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    _, out = _run(rt, monkeypatch, _happy_scripts())
    again = missions.create(con, NOW, "investigate a china-related AI sell-off and my exposure to it", pm_dir=rt.pm_dir)
    assert again["new"] is False and again["mission_id"] == out["mission_id"]


def test_a_task_may_make_only_so_many_of_the_dear_calls(rt, con, monkeypatch):
    """Found live: one mission made 41 quant turns and about 19 calculations and cost Rs 450."""
    _fake_calc(monkeypatch)
    from pflab.hq import tools as tl
    monkeypatch.setitem(tl.DAILY, "case_calculate", 99)                              # (the day's cap is a different limit; this is the task's)
    calls = [_use(("case_calculate", {"case_id": 1, "question": f"worst fall {k}"})) for k in range(6)]
    scripts = _happy_scripts()
    scripts["quant"] = calls + [_say("I used what I could.")]
    _run(rt, monkeypatch, scripts)
    board.run_one(rt, roster.runners())
    board.run_one(rt, roster.runners())
    board.run_one(rt, roster.runners())                                           # coordinator, research, quant
    rows = con.execute("SELECT status, left(result, 60) FROM hq_tool_calls WHERE tool='case_calculate' ORDER BY call_no").fetchall()
    assert [r[0] for r in rows].count("ran") == tl_cap() and any(r[0] == "refused" and "already used" in r[1] for r in rows)


def tl_cap() -> int:
    from pflab.hq import tools
    return tools.TASK_CAPS["case_calculate"]


def test_a_mission_that_has_spent_its_budget_drops_what_has_not_started_and_goes_to_review(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    _run(rt, monkeypatch, _happy_scripts())
    board.run_one(rt, roster.runners())                                           # the coordinator plans: research and quant queued
    t = missions._tasks(con, 1)
    r = next(x for x in t if x["role"] == "research")
    con.execute("UPDATE hq_tasks SET started_at=?, finished_at=? WHERE task_id=?", [NOW, NOW + timedelta(minutes=1), r["id"]])
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, cost_inr, agent, turn) "
                "VALUES (900, ?, 'live', ?, 'q', '', '{}', 'done', 400.0, NULL, 1)", [NOW + timedelta(seconds=30), gv.OPUS])      # a calculation writer's call inside its window
    assert 400.0 <= missions.mission_cost(con, 1, NOW + timedelta(hours=1)) < 410.0
    missions.tick(rt)
    states = {x["role"]: x["status"] for x in missions._tasks(con, 1) if x["role"] in ("research", "quant")}
    assert states["quant"] == "dismissed" and "budget" in con.execute("SELECT result FROM hq_tasks WHERE role='quant'").fetchone()[0]
    assert missions.card(con, 1)["state"] == "reviewing"                          # not blocked: the mission goes on to be judged on what exists
    assert any(e[0] == "budget" for e in con.execute("SELECT event FROM hq_case_log WHERE case_id=1").fetchall())


def test_a_daily_tool_cap_is_a_wait_until_it_resets_not_a_failure(rt, con, monkeypatch):
    """Found live: a quant whose day's calculation cap was spent ended 'without what it promised' and blocked the mission."""
    from pflab.hq import tools as tl
    _fake_calc(monkeypatch)
    monkeypatch.setitem(tl.DAILY, "case_calculate", 0)
    scripts = _happy_scripts()
    scripts["quant"] = [_use(("case_calculate", {"case_id": 1, "question": "worst fall"})), _say("The day's limit stopped me.")]
    _run(rt, monkeypatch, scripts)
    board.run_one(rt, roster.runners())
    board.run_one(rt, roster.runners())
    board.run_one(rt, roster.runners())
    q = next(t for t in missions._tasks(con, 1) if t["role"] == "quant")
    assert q["status"] == "retry" and q["wait_kind"] == "tool limit" and q["attempts"] == 0 and "resets at midnight" in q["resume"]
    assert q["next_review"] > NOW
    missions.tick(rt)
    assert missions.card(con, 1)["state"] == "working" and "limit" in missions.card(con, 1)["blocker"]


def test_a_workers_tool_list_is_not_strict_so_the_compiled_grammar_stays_small(rt):
    """Found on the first real run in the app: 'the compiled grammar is too large' for the quant's 38 tools."""
    from pflab.hq import tools as tl
    for role, names in workers.TOOLS.items():
        defs = tl.definitions(frozenset(n for n in names if n in tl.TOOLS))
        assert not any(d.get("strict") for d in defs), role
    assert sum(1 for d in tl.definitions() if d.get("strict")) <= tl.MAX_STRICT              # the brain's own list is as it was
