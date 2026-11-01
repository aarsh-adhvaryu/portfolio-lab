"""S71: a common kind of question is planned by code, with no cloud call; every playbook plan is as well formed as the one the coordinator wrote in the measurement."""
from __future__ import annotations

import itertools
from types import SimpleNamespace

import pytest

from pflab.eval import roles as R
from pflab.hq import board, missions, playbooks, roster
from tests.test_s68_autonomy import NOW, con, rt  # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(playbooks, "enabled", lambda: True)


def test_every_combination_builds_a_plan_that_passes_all_six_structural_checks():
    for on in itertools.product([False, True], repeat=len(playbooks.FLAGS)):
        fl = dict(zip(playbooks.FLAGS, on))
        if not any(fl.values()):
            continue
        steps, approach = playbooks.build("A sharp sell-off in AI stocks: how exposed am I?", fl)
        for kind in ("strategy", "explain"):
            got = R.plan_scores(kind, steps, approach)
            assert all(got.values()), (playbooks.name_of(fl), kind, [k for k, v in got.items() if not v])


def test_the_words_find_the_kind_of_question():
    f = playbooks.flags_by_words
    assert f("A sharp sell-off in AI-linked stocks could spread. How exposed is my portfolio, and should I change how I put my monthly money to work?")["shock"]
    assert f("A sharp sell-off in AI-linked stocks could spread. How exposed is my portfolio, and should I change how I put my monthly money to work?")["deploy"]
    assert f("My IPO allotment lists next week: sell on listing day or hold?")["ipo"]
    assert f("A material filing on my holding: what does it change?")["filing"]
    assert f("Has anything changed since the earlier conclusion on this?")["review"]
    assert not any(f("What is the weather like in Mumbai?").values())


def test_the_local_model_is_asked_only_when_no_word_decides():
    calls = []

    def chat(model, messages, **kw):
        calls.append(messages[-1]["content"][:30])
        return SimpleNamespace(text='{"shock": false, "deploy": true, "ipo": false, "filing": false, "review": false}')
    fl, how = playbooks.flags_for("Should the bonus go in now or later?", chat)
    assert how == "local model" and fl["deploy"] and len(calls) == 1
    fl, how = playbooks.flags_for("My IPO allotment lists next week", chat)
    assert how == "words" and len(calls) == 1                                      # words decided: no second call
    bad = lambda *a, **k: SimpleNamespace(text='{"shock": "maybe"}')
    fl, how = playbooks.flags_for("Something unusual altogether", bad)
    assert not any(fl.values()) and how == "none"                                   # an invalid reply twice: no flag, the coordinator plans


def test_a_known_question_is_planned_with_no_model_call(rt, con):
    out = missions.create(con, NOW, "My IPO allotment lists next week: should I sell on listing day or hold?", pm_dir=rt.pm_dir)
    rt._hq_client = None                                                           # a model call here would fail: there is no client
    ran = board.run_one(rt, roster.runners())
    assert ran is not None
    m = missions.mission_of(con, out["case_id"])
    assert m["state"] in ("working", "awaiting_approval") and [s["key"] for s in m["plan"]][0] == "premise" and any(s["key"] == "ipo_study" for s in m["plan"])
    tasks = {t["role"] for t in missions._tasks(con, out["case_id"])}
    assert {"coordinator", "research", "quant"} <= tasks
    coord = next(t for t in missions._tasks(con, out["case_id"]) if t["role"] == "coordinator")
    assert coord["status"] == "done"
    assert con.execute("SELECT count(*) FROM api_calls").fetchone()[0] == 0        # nothing was paid
    assert con.execute("SELECT count(*) FROM hq_artifacts WHERE kind='plan' AND task_id=?", [coord["id"]]).fetchone()[0] == 1
    assert any(e == "playbook" for (e,) in con.execute("SELECT event FROM hq_case_log WHERE case_id=?", [out["case_id"]]).fetchall())


def test_only_the_first_plan_is_a_playbook_an_amendment_is_planned_by_the_coordinator(rt, con):
    from pflab.hq import plans
    out = missions.create(con, NOW, "My IPO allotment lists next week: should I sell on listing day or hold?", pm_dir=rt.pm_dir)
    rt._hq_client = None
    board.run_one(rt, roster.runners())                                            # the first plan: a playbook
    n = len(missions._tasks(con, out["case_id"]))
    assert plans.amend(con, NOW, out["case_id"], "Also redo it with a 0.5% charge on every trade", scope_change=True)["amended"]
    assert missions.mission_of(con, out["case_id"])["state"] == "planning"          # the amendment asks for a replan of what changes
    coord = next(t for t in missions._tasks(con, out["case_id"]) if t["role"] == "coordinator" and t["status"] in ("queued", "retry"))
    assert playbooks.try_plan(con, out["case_id"], coord["id"], NOW) is None        # a playbook would plan from the original question and lose the amendment
    assert len(missions._tasks(con, out["case_id"])) >= n


def test_switched_off_the_coordinator_plans_as_before(rt, con, monkeypatch):
    monkeypatch.setattr(playbooks, "enabled", lambda: False)
    out = missions.create(con, NOW, "My IPO allotment lists next week: should I sell on listing day or hold?", pm_dir=rt.pm_dir)
    assert playbooks.enabled() is False and missions.mission_of(con, out["case_id"])["state"] == "planning"


def test_a_question_no_word_or_model_places_goes_to_the_coordinator(rt, con, monkeypatch):
    monkeypatch.setattr(playbooks, "flags_for", lambda goal, chat=None: ({f: False for f in playbooks.FLAGS}, "none"))
    out = missions.create(con, NOW, "Something nobody has asked before, in a field no playbook covers", pm_dir=rt.pm_dir)
    assert playbooks.try_plan(con, out["case_id"], 1, NOW) is None and missions.mission_of(con, out["case_id"])["state"] == "planning"
