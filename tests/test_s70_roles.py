"""S70: the measured-seats harness (src/pflab/eval/roles.py) is itself tested before any paid call: the planted faults are really in the dossiers, the
grader has positive and negative controls, the decision rules do what the protocol says. No model is called."""
from __future__ import annotations

import re

import pytest

from pflab.eval import roles as R


def _words_that_name(item: R.Item) -> str:
    """Words a careful reviewer would write: quote the planted thing as it stands on the page."""
    for a in item.anchors:
        m = re.search(a, item.dossier, re.I)
        if m:
            return f"The dossier says '{m.group(0)}', which is wrong."
    return ""


def test_the_set_is_balanced_and_its_prefixes_too():
    items = R.reviewer_set(24, 4)
    faulty, clean = [i for i in items if i.fault != "clean"], [i for i in items if i.fault == "clean"]
    assert len(faulty) == 24 and len(clean) == 4
    assert {f: sum(1 for i in faulty if i.fault == f) for f in R.FAULTS} == {f: 4 for f in R.FAULTS}
    pre = R.reviewer_set(12, 2)
    assert {f: sum(1 for i in pre if i.fault == f) for f in R.FAULTS} == {f: 2 for f in R.FAULTS} and len(pre) == 14
    assert len({i.id for i in items}) == 28


def test_every_planted_fault_is_really_in_its_dossier_and_a_reviewer_could_name_it():
    for i in R.reviewer_set(24, 0):
        assert i.anchors, i.id
        assert any(re.search(a, i.dossier, re.I) for a in i.anchors), (i.id, i.anchors)       # the thing to be named is on the page


def test_each_fault_is_present_only_in_its_own_kind_and_never_in_the_clean_controls():
    items = R.reviewer_set(24, 4)
    for i in items:
        has = {"untraced_number": bool(re.search(r"since August", i.dossier)),
               "no_baseline": bool(re.search(r"earned 14\.2% a year", i.dossier)),
               "stale_as_cause": "STALE" in i.dossier,
               "assumption_as_estimate": "estimated from ten years" in i.dossier,
               "size_on_open_gaps": bool(re.search(r"\| tax Rs", i.dossier)),
               "outruns_evidence": "1 for, 0 against" in i.dossier}
        assert [k for k, v in has.items() if v] == ([i.fault] if i.fault != "clean" else []), i.id
    for i in items:
        assert ("baseline" in i.dossier) == (i.fault != "no_baseline"), i.id                 # the test has its baseline everywhere except where that is the planted fault
    clean =[i for i in items if i.fault == "clean"]
    assert all("LEDGER: complete" in c.dossier and "not estimated" in c.dossier and "baseline" in c.dossier for c in clean)


def test_a_careful_reviewer_scores_full_marks_and_a_blind_approver_none():
    items = R.reviewer_set(24, 4)
    careful = [R.graded(i, "revise" if i.fault != "clean" else "approve", _words_that_name(i)) for i in items]
    s = R.summarize(careful)
    assert s["caught"] == 24 and s["false_alarms"] == 0 and s["no_verdict"] == 0 and all(v == [4, 4] for v in s["by_fault"].values())
    blind = R.summarize([R.graded(i, "approve", "looks fine") for i in items])
    assert blind["caught"] == 0 and blind["false_alarms"] == 0
    silent = R.summarize([R.graded(i, None, "") for i in items])
    assert silent["caught"] == 0 and silent["no_verdict"] == 28


def test_rejecting_everything_does_not_count_as_finding_the_fault():
    items = R.reviewer_set(24, 4)
    s = R.summarize([R.graded(i, "reject", "this work is not good enough in general") for i in items])
    assert s["caught"] == 0 and s["false_alarms"] == 4
    g = R.graded(items[0], "revise", "something is wrong somewhere")
    assert g["caught"] is False and g["flagged_but_not_named"] is True


def test_naming_the_thing_without_objecting_is_not_a_catch():
    i = R.reviewer_set(1, 0)[0]
    assert R.graded(i, "approve", _words_that_name(i))["caught"] is False


def test_the_reviewer_rule():
    base = {"faulty": 20, "caught": 18, "clean": 4, "false_alarms": 0}
    assert R.decide(base, {**base, "caught": 17})["seat"] == "sonnet"                       # 17 >= 0.9 x 18 = 16.2, >= 70%, no extra false alarm
    assert R.decide(base, {**base, "caught": 16})["seat"] == "opus" and not R.decide(base, {**base, "caught": 16})["relative_ok"]
    low = {"faulty": 20, "caught": 12, "clean": 4, "false_alarms": 0}
    assert R.decide(low, {**low, "caught": 12})["seat"] == "opus" and not R.decide(low, {**low, "caught": 12})["absolute_ok"]   # equal, but below the floor: stays
    assert R.decide(base, {**base, "false_alarms": 2})["seat"] == "opus"                       # two more false alarms than Opus
    assert R.decide(base, {**base, "false_alarms": 1})["seat"] == "sonnet"


def test_the_interval_is_the_wilson_interval():
    lo, hi = R.wilson(18, 20)
    assert 0.69 < lo < 0.71 and 0.97 < hi < 0.99
    assert R.wilson(0, 0) == (0.0, 1.0)


GOOD = [{"key": "premise", "role": "research", "goal": "Verify what happened, its dates and size, from sources", "promise": {"evidence": 2}},
        {"key": "exposure", "role": "quant", "goal": "Compute his exposure and a stated-shock scenario against a baseline of buying monthly", "promise": {"scenario": 1}, "depends_on": ["premise"]},
        {"key": "view", "role": "research", "goal": "Look for evidence against, and competing explanations; say what would change the view", "promise": {"evidence": 2}, "depends_on": ["premise"]}]


def test_plan_checks_pass_a_sound_plan_and_fail_each_break():
    assert all(R.plan_scores("strategy", GOOD).values())
    assert all(R.plan_scores("explain", GOOD).values())
    one = R.plan_scores("strategy", GOOD[:1])
    assert not one["steps_2_to_6"] and not one["has_quant"]
    no_premise = R.plan_scores("strategy", [GOOD[1], GOOD[0]])
    assert not no_premise["premise_first"]
    cyc = [dict(GOOD[0], depends_on=["exposure"]), dict(GOOD[1], depends_on=["premise"])]
    assert not R.plan_scores("strategy", cyc)["valid_structure"]
    ghost = [GOOD[0], dict(GOOD[1], depends_on=["nope"])]
    assert not R.plan_scores("strategy", ghost)["valid_structure"]
    bad_role = [GOOD[0], dict(GOOD[1], role="boss")]
    assert not R.plan_scores("strategy", bad_role)["valid_structure"]
    assert not R.plan_scores("strategy", [GOOD[0], dict(GOOD[1], goal="Compute his exposure")], "")["baseline_or_competing"]
    assert not R.plan_scores("strategy", [GOOD[0], GOOD[1]], "")["what_would_invalidate"]
    assert not any(R.plan_scores("strategy", None).values())                                  # no plan, no marks


def test_the_planner_rule():
    full = {"tasks": 6, "per_check": {c: 6 for c in R.PLAN_CHECKS}, "mean": 1.0}
    ok = {"tasks": 6, "per_check": {c: 6 for c in R.PLAN_CHECKS}, "mean": 0.95}
    assert R.decide_planner(full, ok)["planner"] == "sonnet"
    weak = {"tasks": 6, "per_check": {**{c: 6 for c in R.PLAN_CHECKS}, "premise_first": 3}, "mean": 0.92}
    d = R.decide_planner(full, weak)
    assert d["planner"] == "opus" and not d["floor_ok"] and d["relative_ok"]                  # one check passed on half the tasks: the floor holds it back
    assert R.decide_planner(full, {**ok, "mean": 0.85})["planner"] == "opus"


def test_plan_tasks_and_summary():
    assert len(R.PLANNER_TASKS) == 6 and all(R.plan_task_text(i).startswith("TASK #1 (coordinator)") for i in range(6))
    rows = [R.plan_scores(R.PLANNER_TASKS[i][0], GOOD) for i in range(6)]
    assert R.plan_summary(rows)["mean"] == 1.0
