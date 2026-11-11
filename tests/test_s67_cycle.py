"""S67 the completion cycle: durable board states (interrupted work recovers, held work has a way out, waiting work resumes), the
investigation record (evidence for / against / missing, one request per gap, resume on arrival, reproducible calculations, process
review), and the whole path through the real orchestrator with a scripted model: the system finds a question by itself, opens a case, asks
for a missing report once, and picks the SAME case up when the report arrives. The scripted model checks the wiring, not any reasoning.
Synthetic data; no network."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from pflab.hq import board, cases, egress, governor as gv, service, tools as tl
from pflab.hq.desk import Desk
from pflab.pm import store

AAA, BBB = "INE000A01011", "INE000B01012"
NOW = datetime(2026, 10, 26, 10, 0)          # a Monday
CFG = {"model": "claude-opus-5-5", "cap": 2500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True, "tijori_to_analyst": True}


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    for isin, sym in ((AAA, "AAA"), (BBB, "BBB")):
        c.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                     VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, ?, ?, 'synthetic', now())""", [isin, sym, f"{sym} Limited"])
    return c


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _desk(con, tmp_path, clock, **settings):
    s = {"brain": "economy", "preset": "full", "telegram_send": False, "drop_watch": True, **settings}
    return Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, s, clock=clock)


# --- the scripted model -------------------------------------------------------------------------------------------------------------

def _tool_msg(*calls):
    content = [SimpleNamespace(type="thinking", thinking="", signature="sig")]
    content += [SimpleNamespace(type="tool_use", id=f"tu{k}", name=n, input=i) for k, (n, i) in enumerate(calls)]
    return SimpleNamespace(content=content, stop_reason="tool_use", model=gv.OPUS,
                           usage=SimpleNamespace(input_tokens=800, output_tokens=200, cache_read_input_tokens=0, cache_creation_input_tokens=0))


def _note(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn", model=gv.OPUS,
                           usage=SimpleNamespace(input_tokens=900, output_tokens=150, cache_read_input_tokens=0, cache_creation_input_tokens=0))


class _Msgs:
    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def count_tokens(self, **kw):
        return SimpleNamespace(input_tokens=1000)

    def create(self, **kw):
        self.sent.append(json.loads(json.dumps(kw, default=lambda o: vars(o))))
        return self.replies.pop(0)


class Fake:
    def __init__(self, replies=()):
        self.messages = _Msgs(replies)
        self.beta = SimpleNamespace(messages=self.messages)


# --- the board: durable states ---------------------------------------------------------------------------------------------------------

def test_a_task_the_system_stopped_on_runs_again_within_its_limit_and_is_not_repeated_blindly(con, tmp_path):
    clock = Clock(NOW)
    rt = _desk(con, tmp_path, clock)
    tid = board.post(con, "calc", "a slow question", NOW)
    con.execute("UPDATE hq_tasks SET status='running', attempts=1 WHERE task_id=?", [tid])
    board.once(con, tid, f"told:{tid}", "message", NOW, lambda: None)             # it had already sent its message
    assert board.reap(con, NOW) == 1
    t = board.get(con, tid)
    assert t["status"] == "retry" and "1 effect(s) already done are not repeated" in t["progress"]
    runs = []

    def agent(rt_, task):
        runs.append(task["attempts"])
        sent = board.once(con, task["id"], f"told:{task['id']}", "message", clock(), lambda: None)
        return board.Reply(f"done, message sent again: {sent}")
    out = board.run_one(rt, {"calc": agent})
    assert out["status"] == "done" and runs == [2] and out["result"] == "done, message sent again: False"


def test_attempts_are_bounded_a_failure_backs_off_and_the_last_one_is_final(con, tmp_path):
    clock = Clock(NOW)
    rt = _desk(con, tmp_path, clock)
    tid = board.post(con, "calc", "always fails", NOW)

    def boom(rt_, t):
        raise board.Retryable("the model was unreachable")
    seen = []
    for _ in range(board.MAX_ATTEMPTS + 2):
        t = board.run_one(rt, {"calc": boom})
        if t is None:
            clock.t += timedelta(hours=1)                        # the retry time comes
            continue
        seen.append((t["status"], t["attempts"]))
        clock.t += timedelta(hours=1)
    assert seen == [("retry", 1), ("retry", 2), ("failed", 3)]
    assert board.run_one(rt, {"calc": boom}) is None             # nothing runs forever
    bug = board.post(con, "calc", "has a bug", clock.t)
    assert board.run_one(rt, {"calc": lambda r, t: 1 / 0})["status"] == "failed" and board.get(con, bug)["attempts"] == 1   # a bug is not retried


def test_a_chain_over_the_hop_limit_is_held_and_has_two_explicit_ways_out(con, tmp_path):
    clock = Clock(NOW)
    rt = _desk(con, tmp_path, clock)
    parent = board.post(con, "research", "x", NOW)
    ids = [parent]
    for _ in range(board.MAX_HOPS + 1):
        ids.append(board.post(con, "calc", "next link", NOW, parent=ids[-1]))
    held = board.held(con)
    assert len(held) == 1 and held[0]["meant_for"] == "calc" and "hops" in held[0]["why"]
    tid = held[0]["id"]
    board.release(con, tid, NOW, "the investor")
    assert board.get(con, tid)["status"] == "queued" and board.get(con, tid)["to"] == "calc"
    agents = {"research": lambda r, t: board.Reply("r"),
              "calc": lambda r, t: board.Reply("c", then=[("calc", "again")]) if t["id"] == tid else board.Reply("c")}
    assert board.run_all(rt, agents, max_n=10) >= 1
    assert board.get(con, tid)["status"] == "done" and board.get(con, tid)["body"]["released_by"] == "the investor"
    again = [t for t in board.recent(con, 20) if t["text"] == "again"]
    assert again and again[0]["status"] == "held" and again[0]["parent"] == tid   # a release runs one link; what it hands on is held again
    board.dismiss(con, again[0]["id"], NOW, "keeper", "not wanted")
    assert board.get(con, again[0]["id"])["status"] == "dismissed"
    old = board.post(con, "calc", "z", NOW - timedelta(days=9), parent=ids[-1])
    con.execute("UPDATE hq_tasks SET status='held', hops=9 WHERE task_id=?", [old])
    con.execute("UPDATE hq_tasks SET created_at=? WHERE task_id=?", [NOW - timedelta(days=9), old])
    assert board.expire_held(con, NOW) == 1 and "dismissed by keeper" in board.get(con, old)["result"]
    with pytest.raises(ValueError):
        board.release(con, old, NOW, "x")


def test_waiting_work_resumes_when_its_data_arrives_and_a_duplicate_order_is_one_task(con, tmp_path):
    clock = Clock(NOW)
    rt = _desk(con, tmp_path, clock)
    a = board.post(con, "research", "AAA results", NOW, dedup_key="research:AAA:q2")
    assert board.post(con, "research", "AAA results again", NOW, dedup_key="research:AAA:q2") == a

    def agent(rt_, t):
        if not t["body"].get("have"):
            return board.Reply("waiting for the Q2 results", status="waiting", data={"waiting_on": "result:AAA:q2"})
        return board.Reply("read them")
    assert board.run_one(rt, {"research": agent})["status"] == "waiting"
    assert board.run_one(rt, {"research": agent}) is None
    con.execute("UPDATE hq_tasks SET body_json=? WHERE task_id=?", [json.dumps({"have": True}), a])
    assert board.wake(con, "result:AAA:q2", NOW, "the filing") == 1 and board.wake(con, "result:AAA:q2", NOW) == 0
    assert board.run_one(rt, {"research": agent})["status"] == "done"
    assert board.post(con, "research", "AAA results once more", NOW, dedup_key="research:AAA:q2") != a   # closed: a new order is allowed


# --- the investigation record ------------------------------------------------------------------------------------------------------------

def test_missing_evidence_is_not_evidence_against_and_stale_items_do_not_count(con):
    cid, new = cases.open_case(con, NOW, "Did the order book improve after the Q2 results?", subject="AAA", isin=AAA,
                               assumptions=["management guidance holds"])
    assert new and cases.open_case(con, NOW, "did the order book improve after the q2 results", subject="AAA")[0] == cid
    assert cases.assess(con, cid, NOW)["verdict"] == "open"
    cases.add_evidence(con, cid, NOW, "The Q2 investor presentation was not found.", stance="missing", source_kind="filing")
    a = cases.assess(con, cid, NOW)
    assert a["verdict"] == "insufficient" and a["against"] == 0 and a["missing"] == 1
    cases.add_evidence(con, cid, NOW, "Order book rose in the Q2 results filing.", stance="for", source_id="filing:1", source_kind="filing",
                       published_at=NOW - timedelta(days=3))
    cases.add_evidence(con, cid, NOW, "A news story from last month says orders slipped.", stance="against", source_id="art:9",
                       source_kind="article", published_at=NOW - timedelta(days=40))
    a = cases.assess(con, cid, NOW)
    assert a["stale"] == 1 and a["against"] == 0 and a["verdict"] == "supported"        # the old story is not counted
    cases.add_evidence(con, cid, NOW, "Today's exchange note says orders slipped, guidance cut.", stance="against", source_id="filing:2",
                       source_kind="filing", published_at=NOW - timedelta(hours=2))
    assert cases.assess(con, cid, NOW)["verdict"] == "mixed"
    with pytest.raises(ValueError):
        cases.add_evidence(con, cid, NOW, "x", stance="maybe")


def test_a_missing_report_is_one_dependency_and_one_request_and_the_same_case_resumes(con):
    cid, _ = cases.open_case(con, NOW, "What did AAA's Q2 results say about margins?", subject="AAA", isin=AAA)
    did, fresh = cases.request(con, cid, NOW, "q2_result", "AAA's Q2 results filing", match={"doc_kind": "result", "isin": AAA})
    assert fresh and cases.request(con, cid, NOW, "q2_result", "AAA's Q2 results filing", match={"doc_kind": "result", "isin": AAA}) == (did, False)
    assert cases.get(con, cid)["status"] == "waiting_data"
    qs = con.execute("SELECT agent, subject_key, status FROM questions").fetchall()
    assert qs == [("investigator", f"case:{cid}:q2_result", "open")]                  # one question, however often it is asked
    assert cases.sweep(con, NOW + timedelta(hours=1)) == []                           # nothing has arrived
    assert cases.due(con, NOW + timedelta(hours=1)) == []                             # a waiting case is not worked on
    con.execute("INSERT INTO kg_docs (doc_id, kind, title, published_at, ingested_at) VALUES ('result:AAA:q2', 'result', 'AAA Q2', ?, ?)",
                [NOW + timedelta(hours=2), NOW + timedelta(hours=2)])
    con.execute("INSERT INTO kg_edges VALUES ('result:AAA:q2', 'about', ?, ?, NULL, 'test', NULL, NULL, ?)",
                [f"company:{AAA}", NOW, NOW])
    assert cases.sweep(con, NOW + timedelta(hours=3)) == [(cid, "q2_result")]
    assert cases.get(con, cid)["status"] == "queued" and cases.due(con, NOW + timedelta(hours=3)) == [cid]
    log = [e for e, in con.execute("SELECT event FROM hq_case_log WHERE case_id=? ORDER BY log_id", [cid]).fetchall()]
    assert log[0] == "opened" and "waiting_data" in log and "queued" in log


def test_a_case_passes_through_a_restart_and_a_reopened_conclusion_keeps_why_it_changed(con):
    cid, _ = cases.open_case(con, NOW, "Is the thesis on BBB intact?", subject="BBB", isin=BBB)
    cases.start_pass(con, [cid], 5, NOW)
    cases._LIVE.clear()                                                               # the process died: a new one owns nothing
    assert cases.reap(con, NOW + timedelta(minutes=1)) == 1                           # the process died mid-pass
    c = cases.get(con, cid)
    assert c["status"] == "retry" and c["attempts"] == 1 and "interrupted" in c["error"]
    for k in range(5):
        cases.start_pass(con, [cid], 5 + k, NOW)
        cases._LIVE.clear()                                                       # each time the process died again
        cases.reap(con, NOW)
    assert cases.get(con, cid)["status"] == "failed"                                  # out of attempts: visible, not looping
    cid2, _ = cases.open_case(con, NOW, "Is the thesis on AAA intact?", subject="AAA", isin=AAA)
    cases.add_evidence(con, cid2, NOW, "Margins held in the latest filing.", stance="for", source_id="f:1", source_kind="filing",
                       published_at=NOW - timedelta(days=2))
    r = cases.conclude(con, cid2, NOW, "watch", "one supporting filing", uncertainty="one source",
                       next_review_at=NOW + timedelta(days=3))
    assert not r["changed"]
    assert cases.due(con, NOW + timedelta(days=2)) == []
    assert cases.due(con, NOW + timedelta(days=3, hours=1)) == [cid2] and cases.get(con, cid2)["status"] == "queued"
    cases.add_evidence(con, cid2, NOW + timedelta(days=3), "Guidance was cut in today's filing.", stance="against", source_id="f:2",
                       source_kind="filing", published_at=NOW + timedelta(days=3))
    r = cases.conclude(con, cid2, NOW + timedelta(days=3), "tell", "guidance cut contradicts the thesis")
    assert r["changed"]
    why = con.execute("SELECT detail FROM hq_case_log WHERE case_id=? AND event='conclusion changed'", [cid2]).fetchone()[0]
    assert "was watch" in why and "now tell" in why
    cid3, _ = cases.open_case(con, NOW, "Should the BBB position be added to?", subject="BBB", isin=BBB)
    cases.add_evidence(con, cid3, NOW, "One article is bullish.", stance="for", source_id="art:1", source_kind="article", published_at=NOW)
    cases.conclude(con, cid3, NOW, "suggest", "an article is bullish")
    flags = json.loads(con.execute("SELECT process_json FROM hq_case_reviews WHERE case_id=? ORDER BY review_id DESC LIMIT 1", [cid3]).fetchone()[0])["flags"]
    assert any("confidence not supported" in f for f in flags)                      # 'suggest' on one source: the process is flagged
    cases.outcome_note(con, cid2, NOW + timedelta(days=30), "price fell 8% after")
    assert "does not show the reasoning was sound" in con.execute("SELECT note FROM hq_case_reviews WHERE case_id=? ORDER BY review_id DESC LIMIT 1",
                                                                  [cid2]).fetchone()[0]


# --- the whole path: nobody asks, the system investigates ----------------------------------------------------------------------------------

def test_a_calculation_is_kept_with_its_script_data_and_result_and_can_be_reproduced(con, tmp_path):
    import pandas as pd
    from pflab.agents import workshop as wk
    spec = wk.Spec(["d"], "def compute(data):\n    return {'total': float(data['d']['x'].sum())}\n",
                   {"data": {"d": [{"x": 1.0}, {"x": 2.0}]}, "expected": {"total": 3.0}, "tol": 1e-9}, explain="sum of x")
    frames = {"d": pd.DataFrame({"x": [1.0, 2.0, 3.0]})}
    run = wk.run(spec, dict(frames))
    out = wk.Outcome("checked", run, spec, "test writer", ["ok"])
    out.confirm = {"status": "agrees"}
    cid, _ = cases.open_case(con, NOW, "Total of x?", subject="AAA")
    kid = cases.record_calc(con, cid, NOW, "Total of x?", out)
    row = con.execute("SELECT code_sha, datasets_json, result_json, status FROM hq_calcs WHERE calc_id=?", [kid]).fetchone()
    assert json.loads(row[1]) == ["d"] and json.loads(row[2]) == {"total": 6.0} and row[3] == "checked" and len(row[0]) == 64
    again = cases.reproduce(con, kid, lambda names: dict(frames))
    assert again["ok"] and again["same_as_kept"]
    changed = cases.reproduce(con, kid, lambda names: {"d": pd.DataFrame({"x": [5.0, 5.0]})})
    assert changed["ok"] and not changed["same_as_kept"]
    ev = cases.evidence(con, cid)[-1]
    assert ev["kind"] == "calculation" and ev["calc_id"] == kid and ev["data"]["confirmed"] == "agrees"


# --- after a sleep: catch up before thinking, and say what is not current -------------------------------------------------------------------

# --- review, learning and limits ------------------------------------------------------------------------------------------------------------------

def test_a_case_that_never_settles_is_closed_as_inconclusive_after_its_passes_and_reviewed_later(con):
    cid, _ = cases.open_case(con, NOW, "Is there an edge in AAA's order book?", subject="AAA")
    t = NOW
    for k in range(cases.MAX_STEPS):
        cases.start_pass(con, [cid], 100 + k, t)
        cases.end_pass(con, [cid], 100 + k, t, True)
        t += timedelta(hours=2)
    c = cases.get(con, cid)
    assert c["status"] == "done" and c["decision"] == "inconclusive" and c["next_review"] > t - timedelta(hours=2)
    assert c["verdict"] == "open" and "could not settle" in (c["uncertainty"] or "")
    # no pass of a case ever turns into a live rule or a promoted strategy: the learner's registers are untouched
    for table in ("learn_claims", "learn_tests", "learned", "limit_proposals"):
        assert con.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_the_ipo_strategy_weighs_holding_as_much_as_selling_from_the_numbers(con):
    """(S82: `cases.discover`, which opened a case for an allotment, had no caller and was deleted; the strategy's own wording is what stays tested.)"""
    from pflab.plan import ipo
    import pandas as pd
    base = {"n": 40, "listing_gain_at_close": {"median": 0.05, "p10": -0.1, "p90": 0.3, "share_up": 0.62},
            "after_listing_day_20_sessions": {"median": -0.02, "p10": -0.2, "p90": 0.2, "share_up": 0.45}}
    import pflab.plan.ipo as ipo_mod
    orig = ipo_mod.base_rates
    ipo_mod.base_rates = lambda root, *a, **k: base
    try:
        out = ipo.strategy(con, "x", NOW.date(), "ALPHACO", 20, 1000.0, 50000.0, with_plan=False, stcg=0.2)
    finally:
        ipo_mod.base_rates = orig
    text = " ".join(out["choices_for_the_allotment"])
    assert "62% of large IPOs closed their first day above" in text and "as legitimate as selling" in text and "does not guarantee returns" in text
    assert "7 of 10" not in text                                                       # the claim comes from the numbers, not from a typed sentence


@pytest.fixture(autouse=True)
def _v1_advisor_layers(monkeypatch):
    """S80 switches the v1 advisor layers off by default (`configs/core.toml`); these tests are about the v1 hq round, so they run with the close loop off."""
    from pflab import core
    real = core.settings
    monkeypatch.setattr(core, "settings", lambda: {**real(), "core": {**real()["core"], "on": False, "advisors_off": False, "retire_missions": False}})
