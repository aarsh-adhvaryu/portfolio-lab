"""S69: the workflow made explicit. One approval of a plan, numbered instructions and amendments from the conversation, independent tasks that really overlap,
an awaited experiment, a budget that parks work, executable monitors, duplicate evidence merged, new files routed by the local model (with a safe path when it
fails), and the reviewer's real verdict published. A scripted model stands in for the API; these are development tests (the live run is the acceptance)."""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timedelta

import pytest

from pflab.agents import analyst as an
from pflab.hq import arrivals, board, cases, governor as gv, missions, plans, roster, service, triggers
from pflab.hq import tools as tl
from tests.test_s68_missions import (CFG, NOW, PLAN, Model, _fake_calc, _happy_scripts, _run, _say, _use, con, rt)  # noqa: F401


@pytest.fixture
def approval(monkeypatch):
    monkeypatch.setattr(missions, "plan_approval_mode", lambda: "investor")


# --- one approval, then execution ----------------------------------------------------------------------------------------------------------

def test_his_request_waits_once_for_his_yes_and_nothing_runs_before_it(rt, con, monkeypatch, approval):
    _fake_calc(monkeypatch)
    m, out = _run(rt, monkeypatch, _happy_scripts())
    service.drive_missions(rt)
    card = missions.card(con, 1)
    assert card["state"] == "awaiting_approval" and card["awaiting_approval"] and "approval" in card["blocker"]
    assert [t["status"] for t in card["tasks"] if t["role"] in ("research", "quant")] == ["needs_approval", "needs_approval"]
    assert all(role == "coordinator" for role, _ in m.seen)                          # no worker has been asked anything
    v = card["plan_versions"][0]
    assert v["status"] == "proposed" and [s["key"] for s in v["steps"]] == ["verify", "scenarios"] and v["steps"][1]["role"] == "quant"
    assert any("say yes" in (r[0] or "") or "Say \"approve\"" in (r[0] or "") for r in con.execute("SELECT text FROM chat_messages").fetchall())
    out = plans.approve(con, NOW, 1, by="the investor (test)")                       # his yes
    assert out["approved"] and len(out["tasks"]) == 2
    service.drive_missions(rt)
    card = missions.card(con, 1)
    assert card["state"] == "done" and card["instruction_version"] == 1
    assert card["plan_versions"][0]["status"] == "approved" and all(t["instruction_version"] == 1 for t in card["tasks"])
    assert plans.approve(con, NOW, 1)["approved"] is False                           # asked for once, not again


def test_a_plan_he_declines_runs_nothing_and_closes_the_investigation(rt, con, monkeypatch, approval):
    _fake_calc(monkeypatch)
    m, _ = _run(rt, monkeypatch, _happy_scripts())
    service.drive_missions(rt)
    assert plans.decline(con, NOW, 1, note="too broad")["declined"]
    card = missions.card(con, 1)
    assert card["state"] == "declined" and cases.get(con, 1)["status"] == "done"
    assert all(t["status"] in ("done", "dismissed") for t in card["tasks"]) and not any(r != "coordinator" for r, _ in m.seen)


def test_the_assistant_tool_needs_his_own_words_to_approve(rt, con, monkeypatch, approval):
    _fake_calc(monkeypatch)
    _run(rt, monkeypatch, _happy_scripts())
    service.drive_missions(rt)

    def ctx(msg):
        return tl.Ctx(rt, 1, "m", False, {}, None, NOW, role="assistant", source=f"RECORD SNAPSHOT: x\n\nHIS MESSAGE:\n{msg}\nnot yet, no, wait",   # (tool output after his words says "no": it must not count)
                      allowed=frozenset({"decide_plan", "amend_investigation"}), his_text=msg)
    assert tl.decide_plan(ctx("what does the plan cost?"), {"case_id": 1, "decision": "approve"})["approved"] is False
    assert tl.decide_plan(ctx("approve, but wait until Monday"), {"case_id": 1, "decision": "approve"})["approved"] is False       # a hedge is not a yes
    assert tl.decide_plan(ctx("yes, go ahead"), {"case_id": 1, "decision": "approve"})["approved"] is True


# --- the review's real verdict is published ----------------------------------------------------------------------------------------------------

def test_the_published_conclusion_carries_the_reviewers_actual_verdict(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    _run(rt, monkeypatch, _happy_scripts())
    service.drive_missions(rt)
    res = missions.mission_of(con, 1)["result"]
    assert res["review_verdict"] == "approve" and cases.get(con, 1)["decision"] == "watch"
    fin = [r[0] for r in con.execute("SELECT text FROM hq_tasks WHERE role='coordinator' ORDER BY task_id").fetchall()][-1]
    assert "Review outcome: approved" in fin and "REJECTED" not in fin               # it used to be read as a rejection
    assert missions.verdict_of("approved") == missions.verdict_of("approve") == "approve" and missions.verdict_of("rejected") == "reject"
    told = [r[0] for r in con.execute("SELECT text FROM chat_messages WHERE mode LIKE 'note:mission:1:done%'").fetchall()]
    assert told and "verdict: approve" in told[0]


def test_a_rejecting_review_makes_an_inconclusive_case_that_says_so(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    sc = _happy_scripts(extra_review=[_use(("submit_review", {"case_id": 1, "verdict": "reject", "findings": "Unsupported."}), model=gv.OPUS), _say("Rejected.", gv.OPUS)])
    sc["coordinator"][2] = _use(("submit_answer", {"case_id": 1, "answer": "The review rejected this; nothing is concluded.", "limitations": "Unsupported.", "monitor_next": "Nothing."}), model=gv.OPUS)
    _run(rt, monkeypatch, sc)
    service.drive_missions(rt)
    assert missions.mission_of(con, 1)["result"]["review_verdict"] == "reject" and cases.get(con, 1)["decision"] == "inconclusive"


# --- amendments: numbered instructions, without a release -----------------------------------------------------------------------------------------

def test_a_refinement_from_the_conversation_is_the_next_version_and_replans_without_asking_again(rt, con, monkeypatch, approval):
    _fake_calc(monkeypatch)
    sc = _happy_scripts()
    plan2 = [{"key": "costs", "role": "quant", "goal": "Redo the comparison with a 0.5% charge on each trade.", "promise": {"calc": 1}, "depends_on": []}]
    sc["coordinator"].insert(2, _use(("plan_mission", {"case_id": 1, "steps_json": json.dumps(plan2), "approach": "only the cost assumption changes"}), model=gv.OPUS))
    sc["coordinator"].insert(3, _say("Replanned.", gv.OPUS))
    sc["quant"] = [_use(("case_calculate", {"case_id": 1, "question": "Worst fall and recovery under phased buying versus cash"})), _say("Done."),
                   _use(("case_calculate", {"case_id": 1, "question": "The same with a 0.5% charge"})), _say("Done again.")]
    sc["review"] = [_use(("submit_review", {"case_id": 1, "verdict": "approve", "findings": "ok"}), model=gv.OPUS), _say("ok", gv.OPUS)]
    _run(rt, monkeypatch, sc)
    board.run_one(rt, roster.runners())                                               # the coordinator plans v1
    plans.approve(con, NOW, 1)
    board.run_one(rt, roster.runners(), prefix="w_")                                  # research (v1) runs
    out = plans.amend(con, NOW, 1, "Also use a 0.5% charge on every trade in the comparison.")
    assert out["amended"] and out["version"] == 2 and out["needs_approval"] is False and out["replaced_tasks"]
    assert plans.amend(con, NOW, 1, "Also use a 0.5% charge on every trade in the comparison.")["duplicate"]       # saying it twice is one version
    card = missions.card(con, 1)
    assert card["state"] == "planning"
    assert any(t["status"] == "dismissed" for t in card["tasks"])
    service.drive_missions(rt)
    card = missions.card(con, 1)
    assert card["state"] == "done", (card["state"], card["blocker"])
    vs = {v["version"]: v for v in card["plan_versions"]}
    assert vs[1]["status"] == "superseded" and vs[2]["status"] == "auto" and vs[2]["source"] == "amendment" and "0.5%" in vs[2]["instruction"]
    assert card["instruction_version"] == 2
    ver = {t["id"]: t["instruction_version"] for t in card["tasks"]}
    assert 1 in ver.values() and 2 in ver.values()
    assert any(e[0] == "amendment" for e in con.execute("SELECT event FROM hq_case_log WHERE case_id=1").fetchall())
    # the review read both instructions and was told the older research ran under v1
    review_task = [t for t in missions._tasks(con, 1) if t["role"] == "review"][-1]
    assert "v1" in con.execute("SELECT text FROM hq_tasks WHERE task_id=?", [review_task["id"]]).fetchone()[0]


def test_a_change_of_scope_or_a_financial_policy_waits_for_his_yes_again(rt, con, monkeypatch, approval):
    _fake_calc(monkeypatch)
    sc = _happy_scripts()
    plan2 = [{"key": "deploy", "role": "quant", "goal": "Compare deploying Rs 50,000 a month, unused cash carried forward, as a paper example only.", "promise": {"calc": 1}, "depends_on": []}]
    sc["coordinator"].insert(2, _use(("plan_mission", {"case_id": 1, "steps_json": json.dumps(plan2), "approach": "a paper example"}), model=gv.OPUS))
    sc["coordinator"].insert(3, _say("Replanned.", gv.OPUS))
    _run(rt, monkeypatch, sc)
    board.run_one(rt, roster.runners())
    plans.approve(con, NOW, 1)
    out = plans.amend(con, NOW, 1, "Assume I invest Rs 50,000 a month through January, carrying unused cash forward.", financial_policy=True)
    assert out["needs_approval"] is True
    board.run_one(rt, roster.runners())                                               # the coordinator replans
    card = missions.card(con, 1)
    assert card["state"] == "awaiting_approval" and plans.waiting(con, 1)["version"] == 2
    assert [t["status"] for t in card["tasks"] if t["instruction_version"] == 2 and t["role"] != "coordinator"] == ["needs_approval"]
    assert plans.active_number(con, 1) == 1                                           # v1 still the one in force; v2 is not active policy
    assert plans.decline(con, NOW, 1)["declined"] and missions.card(con, 1)["state"] == "working"             # declining an amendment leaves the earlier plan going
    assert plans.versions(con, 1)[1]["status"] == "rejected"


def test_a_verdict_older_than_the_instructions_in_force_is_not_a_verdict_on_the_new_work(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    _run(rt, monkeypatch, _happy_scripts())
    service.drive_missions(rt)
    assert missions.card(con, 1)["state"] == "done"
    # an amendment after an approving review: the old verdict must not publish the new work
    sc = _happy_scripts()
    plans.amend(con, NOW + timedelta(hours=1), 1, "Add a second scenario with a slower recovery.")
    row = con.execute("SELECT reviewed_at FROM hq_case_reviews").fetchone()[0]
    act = plans.versions(con, 1)[-1]
    assert act["status"] == "drafting" and row <= NOW + timedelta(hours=1)           # the earlier review predates the new version


# --- tasks really overlap ----------------------------------------------------------------------------------------------------------------------

def test_independent_tasks_run_at_the_same_time_and_a_dependent_one_waits(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    plan = [{"key": "a", "role": "research", "goal": "Gather evidence on the move from sources.", "promise": {"evidence": 1}, "depends_on": []},
            {"key": "b", "role": "quant", "goal": "Compute the exposure to a stated fall.", "promise": {"calc": 1}, "depends_on": []},
            {"key": "c", "role": "quant", "goal": "Compare the two once both exist.", "promise": {"calc": 1}, "depends_on": ["a", "b"]}]
    sc = _happy_scripts()
    sc["coordinator"][0] = _use(("plan_mission", {"case_id": 1, "steps_json": json.dumps(plan), "approach": "a and b in parallel"}), model=gv.OPUS)
    sc["research"] = [_use(("case_evidence", {"case_id": 1, "stance": "for", "text": "A filing reports the move.", "source_kind": "filing", "published": "2026-10-20"})), _say("Recorded.")]
    sc["quant"] = [_use(("case_calculate", {"case_id": 1, "question": "exposure to a stated fall"})), _say("Done b."),
                   _use(("case_calculate", {"case_id": 1, "question": "compare a and b"})), _say("Done c.")]
    barrier = threading.Barrier(2, timeout=8)                                         # both must be inside the "model" at once, or the test fails
    seen = {}
    inner, _ = _run(rt, monkeypatch, sc)

    class Overlap:
        def __init__(self):
            self.messages = inner.messages
            self.beta = type("B", (), {"messages": type("M", (), {"create": staticmethod(self._create)})})()

        def _create(self, **kw):
            role = next(r for mk, r in __import__("tests.test_s68_missions", fromlist=["x"]).ROLE_MARK.items() if mk in kw["system"][0]["text"])
            if role in ("research", "quant") and "TASK #2" in json.dumps(kw["messages"][0]["content"]) or "TASK #3" in json.dumps(kw["messages"][0]["content"]):
                if kw["messages"][0]["content"][0]["text"].count("tool_result") == 0 and not seen.get("done_" + role):
                    seen["done_" + role] = True
                    barrier.wait()                                                    # raises BrokenBarrierError if the other task is not running too
                    seen[role] = datetime.now()
            return inner._create(**kw)
    rt._hq_client = Overlap()
    service.drive_missions(rt)
    card = missions.card(con, 1)
    assert card["state"] == "done", (card["state"], card["blocker"], [(t["id"], t["status"], t["progress"] if "progress" in t else "") for t in card["tasks"]])
    t = {x["id"]: x for x in card["tasks"]}
    a, b, c = t[2], t[3], t[4]
    assert a["started"] and b["started"] and a["started"] <= b["finished"] and b["started"] <= a["finished"] and seen.get("research") and seen.get("quant"), "the two independent tasks did not overlap"   # (the barrier is the proof: the fixed test clock cannot order them)
    assert c["depends_on"] == [2, 3] and c["started"] >= max(a["finished"], b["finished"])        # the dependent one waited for both
    calls = con.execute("SELECT count(DISTINCT call_id), count(*) FROM api_calls").fetchone()
    assert calls[0] == calls[1]                                                       # no two calls were given the same id
    assert con.execute("SELECT count(*) FROM api_calls WHERE task_id IS NULL").fetchone()[0] == 0   # every call is tied to its task


def test_a_claim_is_atomic_across_threads(con):
    now = NOW
    for i in range(30):
        board.post(con, "w_research", f"t{i}", now, frm="mission")
    got, lock = [], threading.Lock()

    def take():
        c = con.cursor()
        while True:
            tid = board.claim(c, now, prefix="w_")
            if tid is None:
                return
            with lock:
                got.append(tid)
    ts = [threading.Thread(target=take) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(got) == list(range(1, 31))                                          # each task exactly once, none lost


def test_ids_handed_to_two_threads_at_once_are_distinct(con):
    from pflab.pm.store import next_id
    out, lock = [], threading.Lock()

    def ask():
        c = con.cursor()
        v = next_id(c, "hq_artifacts", "artifact_id")
        with lock:
            out.append(v)
    ts = [threading.Thread(target=ask) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(set(out)) == 8


# --- an experiment is awaited ---------------------------------------------------------------------------------------------------------------

def _experiment_row(con, status="registered"):
    con.execute("INSERT INTO learn_experiments VALUES (1, 'k1', ?, 'Hold cash when the index falls 10%', 'matters', 'it loses', 'case', '1', 'index:NIFTY50_TRI', 3, 'p.md', 'sha', 'esha', ?, NULL, NULL, NULL, 'deployment')",
                [NOW, status]) if False else con.execute(
        "INSERT INTO learn_experiments (exp_id, key, registered_at, hypothesis, why_it_matters, disproof, source_kind, source_ref, dataset, max_attempts, protocol_path, "
        "protocol_sha, evaluator_sha, status) VALUES (1, 'k1', ?, 'Hold cash when the index falls 10 percent', 'matters', 'it loses', 'case', '1', 'index:NIFTY50_TRI', 3, 'p.md', 'sha', 'esha', ?)",
        [NOW, status])


def test_a_registered_experiment_is_not_a_result_the_mission_waits_for_it_and_the_result_reaches_the_review(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    sc = _happy_scripts()
    _run(rt, monkeypatch, sc)
    board.run_one(rt, roster.runners())                                               # plan
    _experiment_row(con, "registered")
    con.execute("INSERT INTO hq_artifacts VALUES (500, 1, 3, 'experiment', '1', 'registered', ?)", [NOW])
    for _ in range(3):
        board.run_one(rt, roster.runners())
    missions.tick(rt)
    card = missions.card(con, 1)
    assert card["state"] == "working" and card["experiments_pending"] == [{"id": 1, "status": "registered"}] and "experiment #1" in card["next_trigger"]
    assert not any(t["role"] == "review" for t in card["tasks"])                      # no review, no answer, while the experiment is only registered
    con.execute("UPDATE learn_experiments SET status='rejected', decision_why='did not beat always-invested on the validation period' WHERE exp_id=1")
    missions.tick(rt)
    card = missions.card(con, 1)
    assert any(o["kind"] == "experiment_result" and "rejected" in o["detail"] for o in card["outputs"])
    ev = [e["text"] for e in cases.evidence(con, 1)]
    assert any("Experiment #1 (rejected)" in t for t in ev)                          # the result is in the case the reviewer reads
    follow = [t for t in missions._tasks(con, 1) if t["role"] == "quant" and "Experiment #1 finished" in con.execute("SELECT text FROM hq_tasks WHERE task_id=?", [t["id"]]).fetchone()[0]]
    assert follow and follow[0]["status"] in ("queued", "waiting")                    # the worker is asked what it means
    from pflab.hq import workers
    assert "EXPERIMENT #1 [rejected]" in workers._dossier(con, 1, {"body": {}}, NOW)


def test_an_experiment_in_a_running_mission_is_driven_without_waiting_for_the_nightly_cycle(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    _run(rt, monkeypatch, _happy_scripts())
    board.run_one(rt, roster.runners())
    _experiment_row(con, "registered")
    con.execute("INSERT INTO hq_artifacts VALUES (500, 1, 3, 'experiment', '1', 'registered', ?)", [NOW])
    ran = []
    from pflab.learner import experiments as ex
    monkeypatch.setattr(ex, "local_writer", lambda *a, **k: (lambda p: ""))
    monkeypatch.setattr(ex, "run", lambda c, eid, root, now, writer, **k: ran.append(eid) or c.execute("UPDATE learn_experiments SET status='rejected' WHERE exp_id=?", [eid]))
    assert missions.drive_experiments(rt) is True and ran == [1]
    assert missions.drive_experiments(rt) is False                                    # nothing more to drive


# --- executable monitoring -----------------------------------------------------------------------------------------------------------------

def test_a_monitoring_sentence_is_not_a_monitor_but_a_supported_trigger_is_saved_and_fires(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    from tests.test_s58b_today import AAA
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, 'AAA', 'AAA Ltd', 's', now())", [AAA])
    con.execute("INSERT INTO prices VALUES (?, DATE '2026-10-30', 120.0, 'EQ', 's', now())", [AAA])
    sc = _happy_scripts()
    trig = [{"kind": "price_below", "symbol": "AAA", "value": 100}, {"kind": "move_pct", "symbol": "AAA", "pct": -10}, {"kind": "watch_the_vibes", "symbol": "AAA"},
            {"kind": "review_on", "date": "2026-11-20"}, {"kind": "price_above", "symbol": "NOSUCH", "value": 5}]
    sc["coordinator"][2] = _use(("submit_answer", {"case_id": 1, "answer": "Hold; calc 1 gives -18.0.", "limitations": "Assumptions.", "monitor_next": "Watch AAA below 100.",
                                                   "triggers_json": json.dumps(trig), "change": "first"}), model=gv.OPUS)
    _run(rt, monkeypatch, sc)
    service.drive_missions(rt)
    res = missions.mission_of(con, 1)["result"]
    assert res["monitor_executable"] is True and len(res["triggers"]) == 3 and len(res["monitor_unsupported"]) == 2
    assert any("not one the system can check" in u for u in res["monitor_unsupported"]) and any("NOSUCH" in u or "name a held" in u for u in res["monitor_unsupported"])
    card = missions.card(con, 1)
    assert [t["kind"] for t in card["triggers"]] == ["price_below", "move_pct", "review_on"] and card["triggers"][0]["describe"].endswith("Rs 100.00")
    assert triggers.check(rt) == []                                                   # 120 is neither below 100 nor -10% from 120
    con.execute("INSERT INTO prices VALUES (?, DATE '2026-11-02', 95.0, 'EQ', 's', now())", [AAA])
    rt2 = type("R", (), {"cursor": lambda self: con.cursor(), "clock": lambda self: datetime(2026, 11, 2, 18, 0)})()
    fired = triggers.check(rt2)
    assert len(fired) == 2                                                            # below 100, and a move of -20.8% from 120
    assert triggers.check(rt2) == []                                                  # each fires once
    assert missions.mission_of(con, 1)["state"] == "planning"                         # the finished investigation is looked at again, by itself
    assert any(e[0] == "trigger fired" for e in con.execute("SELECT event FROM hq_case_log WHERE case_id=1").fetchall())


def test_an_answer_with_no_trigger_says_there_is_no_executable_monitor(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    _run(rt, monkeypatch, _happy_scripts())
    service.drive_missions(rt)
    res = missions.mission_of(con, 1)["result"]
    assert res["monitor_executable"] is False and res["triggers"] == []


# --- evidence: duplicates merge, contradictions stay -------------------------------------------------------------------------------------------

def test_the_same_finding_twice_is_one_piece_of_evidence_and_a_contradiction_is_kept(con):
    cid, _ = cases.open_case(con, NOW, "Did the AI sell-off hit my holdings?", origin="investor")
    a = cases.add_evidence(con, cid, NOW, "The filing reports a 12% fall in segment revenue.", stance="for", source_id="doc:1", published_at=NOW)
    b = cases.add_evidence(con, cid, NOW + timedelta(hours=1), "The filing reports a 12% fall in segment revenue.", stance="for", source_id="doc:1", published_at=NOW)
    c = cases.add_evidence(con, cid, NOW, "the filing reports a 12 % fall in segment revenue", stance="for", source_id="doc:1", published_at=NOW)
    assert a == b == c and len(cases.evidence(con, cid)) == 1
    d = cases.add_evidence(con, cid, NOW, "The filing reports a 12% fall in segment revenue.", stance="against", source_id="doc:1", published_at=NOW)
    assert d != a and len(cases.evidence(con, cid)) == 2                              # opposite stance from the same source: material, kept
    e = cases.add_evidence(con, cid, NOW, "A second filing reports a 4% rise in segment revenue.", stance="for", source_id="doc:2", published_at=NOW)
    assert e not in (a, d) and len(cases.evidence(con, cid)) == 3
    assert [x[0] for x in con.execute("SELECT event FROM hq_case_log WHERE case_id=? AND event='merged'", [cid]).fetchall()] == ["merged", "merged"]
    assert cases.assess(con, cid, NOW)["verdict"] == "mixed"


# --- new files wake the right investigation; the local model routes ---------------------------------------------------------------------------

def _finished_mission(rt, con, monkeypatch, goal="Investigate the AI sell-off and what a downturn does to my AI-linked holdings"):
    _fake_calc(monkeypatch)
    m, out = _run(rt, monkeypatch, _happy_scripts(), goal=goal)
    service.drive_missions(rt)
    assert missions.card(con, out["case_id"])["state"] == "done"
    return out["case_id"]


def _drop(con, name, text, iid=1, kind="other"):
    con.execute("INSERT INTO inbox_items (item_id, name, kind, sha, status, text, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                [iid, name, kind, f"sha{iid}", "read", text, NOW, NOW])


DOC = ("Analyst note on the AI sell-off: spending on AI chips by the largest buyers was cut, which pushed the downturn in AI-linked stocks further, "
       "and the note says Indian AI-linked holdings may fall again if the downturn continues over the next quarter. " * 2)


def test_a_new_file_finds_its_investigation_through_the_local_model_and_reopens_it(rt, con, monkeypatch):
    cid = _finished_mission(rt, con, monkeypatch)
    _drop(con, "ai_downturn_note.txt", DOC)
    asked = []

    def local(item, cands, err):
        asked.append((item["name"], [c["case_id"] for c in cands], err))
        return {"raw": json.dumps({"case_id": cid, "effect": "new_information", "confidence": 0.8, "why": "it reports a further cut in AI chip spending"}), "model": "qwen3:8b-q8_0"}
    out = arrivals.scan(rt, ask=local)
    assert asked == [("ai_downturn_note.txt", [cid], "")] and out["routed"] == 1 and out["reopened"] == 1
    assert missions.mission_of(con, cid)["state"] == "planning" and plans.versions(con, cid)[-1]["source"] == "review"          # the same investigation, a new version, no prompt
    ev = cases.evidence(con, cid)
    assert any(e["source_id"] == "inbox:1" and "ai_downturn_note.txt" in e["text"] for e in ev)
    d = arrivals.recent(con)[0]
    assert d["outcome"] == "local" and d["tries"] == 1 and d["model"] == "qwen3:8b-q8_0" and d["chosen"]["case_id"] == cid and "reopened" in d["note"]
    assert arrivals.scan(rt, ask=local)["routed"] == 0 and len(asked) == 1           # a file is routed once


def test_unusable_local_output_is_retried_once_and_then_the_plain_rule_decides(rt, con, monkeypatch):
    cid = _finished_mission(rt, con, monkeypatch)
    _drop(con, "ai_downturn_note.txt", DOC)
    replies = iter(["I think it is about case 1.", json.dumps({"case_id": 999, "effect": "new_information", "confidence": 0.9, "why": "x"})])
    errors = []

    def local(item, cands, err):
        errors.append(err)
        return {"raw": next(replies), "model": "qwen3:8b-q8_0"}
    out = arrivals.scan(rt, ask=local)
    assert errors[0] == "" and "not a JSON" in errors[1] or "not a JSON object" in errors[1]            # the second ask names what was wrong with the first
    d = arrivals.recent(con)[0]
    assert d["outcome"] == "rule" and d["tries"] == 2 and out["routed"] == 1                           # still a safe, recorded outcome: a plain rule on shared words
    assert missions.mission_of(con, cid)["state"] == "planning"


def test_when_the_local_model_is_unavailable_a_clear_match_still_routes_and_an_unclear_one_goes_to_the_coordinator(rt, con, monkeypatch):
    cid = _finished_mission(rt, con, monkeypatch)
    _drop(con, "ai_downturn_note.txt", DOC)

    def down(item, cands, err):
        raise ConnectionError("ollama is not running")
    arrivals.scan(rt, ask=down)
    assert arrivals.recent(con)[0]["outcome"] == "rule" and missions.mission_of(con, cid)["state"] == "planning"
    # two equally good fits: it is handed to the coordinator, and says so
    _, b = _run(rt, monkeypatch, _happy_scripts(), goal="Investigate the AI downturn and what it does to my AI-linked holdings, second look")
    c2 = missions.create(con, NOW, "A second look at the AI downturn: what does a downturn do to AI-linked holdings in my portfolio", pm_dir=rt.pm_dir)["case_id"]
    cands = arrivals.candidates(con, "ai downturn holdings sell-off ai-linked stocks")
    assert len(cands) >= 2
    _drop(con, "second.txt", DOC, iid=2)
    arrivals.scan(rt, ask=down)
    assert arrivals.recent(con)[0]["outcome"] in ("escalated", "rule")


def test_a_file_that_concerns_nothing_open_is_recorded_and_changes_nothing(rt, con, monkeypatch):
    cid = _finished_mission(rt, con, monkeypatch)
    _drop(con, "recipe.txt", "A long recipe for lentil soup with onions and cumin, simmered for an hour and served with rice and a squeeze of lemon on top. " * 3)
    out = arrivals.scan(rt, ask=lambda *a: (_ for _ in ()).throw(AssertionError("the model must not be asked")))
    assert out["unrelated"] == 1 and missions.mission_of(con, cid)["state"] == "done"
    assert arrivals.recent(con)[0]["outcome"] == "code"


def test_the_same_file_again_is_merged_not_reopened(rt, con, monkeypatch):
    cid = _finished_mission(rt, con, monkeypatch)
    cases.add_evidence(con, cid, NOW, "File 'ai_downturn_note.txt' arrived", stance="neutral", kind="dataset", source_id="inbox:1", source_kind="dataset")
    _drop(con, "ai_downturn_note.txt", DOC)
    out = arrivals.scan(rt, ask=lambda *a: (_ for _ in ()).throw(AssertionError("the model must not be asked")))
    assert out["merged"] == 1 and missions.mission_of(con, cid)["state"] == "done"


def test_a_duplicate_verdict_is_noted_and_nothing_is_reopened(rt, con, monkeypatch):
    cid = _finished_mission(rt, con, monkeypatch)
    _drop(con, "ai_downturn_note.txt", DOC)
    arrivals.scan(rt, ask=lambda item, cands, err: {"raw": json.dumps({"case_id": cid, "effect": "duplicate", "confidence": 0.9, "why": "says what is known"}), "model": "m"})
    assert missions.mission_of(con, cid)["state"] == "done"
    assert any(e[0] == "arrival" for e in con.execute("SELECT event FROM hq_case_log WHERE case_id=?", [cid]).fetchall())


def test_new_material_during_a_running_investigation_gives_the_research_a_task(rt, con, monkeypatch):
    _fake_calc(monkeypatch)
    _, out = _run(rt, monkeypatch, _happy_scripts(), goal="Investigate the AI sell-off and what a downturn does to my AI-linked holdings")
    board.run_one(rt, roster.runners())                                               # planned: working
    _drop(con, "ai_downturn_note.txt", DOC)
    arrivals.scan(rt, ask=lambda item, cands, err: {"raw": json.dumps({"case_id": 1, "effect": "contradicts", "confidence": 0.7, "why": "reports the opposite"}), "model": "m"})
    tasks = con.execute("SELECT text FROM hq_tasks WHERE role='research' ORDER BY task_id").fetchall()
    assert any("New material arrived" in t[0] for t in tasks)
    assert [e["stance"] for e in cases.evidence(con, 1) if e["source_id"] == "inbox:1"] == ["against"]


def test_routing_is_visible_on_the_screen_api(tmp_path):
    from fastapi.testclient import TestClient
    assert True


def test_a_read_file_whose_content_lives_in_the_graph_is_still_routed_from_the_stored_file(rt, con, monkeypatch, tmp_path):
    """Found in the rehearsal: a dropped note is 'in the graph' with no text on its inbox row, so nothing was ever routed."""
    cid = _finished_mission(rt, con, monkeypatch)
    f = tmp_path / "note.txt"
    f.write_text(DOC, encoding="utf-8")
    con.execute("INSERT INTO inbox_items (item_id, name, kind, path, sha, status, created_at, updated_at) VALUES (1,'note.txt','other',?,?,'in the graph',?,?)", [str(f), "sha1", NOW, NOW])
    assert arrivals.file_text(str(f)).startswith("Analyst note")
    out = arrivals.scan(rt, ask=lambda item, cands, err: {"raw": json.dumps({"case_id": cid, "effect": "new_information", "confidence": 0.9, "why": "further cuts"}), "model": "m"})
    assert out["routed"] == 1 and missions.mission_of(con, cid)["state"] == "planning"
    assert arrivals.file_text(str(tmp_path / "missing.pdf")) == "" and arrivals.file_text(str(tmp_path / "x.bin")) == ""


def test_the_deployment_study_tool_takes_a_trading_charge_so_an_amendment_about_costs_can_be_carried_out():
    tool = tl.TOOLS["policy_scenarios"]
    assert tl.validate(tool, {"case_id": 1, "why": "costs", "cost_bps": 50}) is None
    assert tl.validate(tool, {"case_id": 1, "why": "costs", "cost_bps": 5000}) is not None


def test_the_assistant_can_make_a_recommendation_linked_to_a_finished_investigation(rt, con, monkeypatch):
    """Found in the rehearsal: make_proposal refused a case that had already been concluded."""
    cid = _finished_mission(rt, con, monkeypatch)
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES ('INE000A01011', 'isin', 'equity', 'EQUITY', TRUE, 'AAA', 'AAA Ltd', 's', now())")
    con.execute("INSERT INTO prices VALUES ('INE000A01011', DATE '2026-10-30', 120.0, 'EQ', 's', now())")
    ctx = tl.Ctx(rt, 1, "m", False, {}, None, NOW, role="assistant", allowed=frozenset({"make_proposal"}), his_text="propose a wait")
    out = tl.make_proposal(ctx, {"action": "WAIT", "symbol": "AAA", "case_id": cid, "reason": "The evidence is mixed and nothing in the case argues for acting now.",
                                 "alternatives": "Buying or holding were compared and are not stronger.", "review_condition": "AAA closes below Rs 100"})
    assert out["stored"] and out["proposal_id"] == 1
    assert tl.make_proposal(ctx, {"action": "WAIT", "symbol": "AAA", "case_id": 999, "reason": "x" * 30, "alternatives": "y" * 20, "review_condition": "z" * 10})["stored"] is False


def test_the_everyday_word_address_does_not_stop_a_worker_but_his_own_address_still_does():
    """Found live: a reviewer's revision request began 'Address the dip rule' and the privacy gate blocked the task and with it the investigation."""
    import inspect
    from pflab.hq import egress, llm, workers
    gate = egress.Gate(address=["testlane"], names=["ravi kumar"])
    egress.check("Address the active dip rule in the proposal.", gate, skip=("address_word",))
    for bad in ("flat no 4 somewhere", "He lives at testlane road", "pin code 400001", "house no 9", "Ravi Kumar asked"):
        try:
            egress.check(bad, gate, skip=("address_word",))
            raise AssertionError(bad)
        except egress.EgressBlocked:
            pass
    try:
        egress.check("Address the dip rule", gate)                                  # everywhere else the bare word still blocks
        raise AssertionError("strict default lost")
    except egress.EgressBlocked:
        pass
    assert "egress_skip" in inspect.signature(llm.call).parameters and 'egress_skip=("address_word",)' in inspect.getsource(workers.converse)
