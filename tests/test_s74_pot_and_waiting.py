"""S74: the opportunity pot's ideas become proposals in the one ledger, and what waits for his yes (limits, theme baskets, the pot) reaches him in the conversation with a number he
can answer: his yes counts only in his own words and only for a question he was just shown. Synthetic data only."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from pflab.agents import questions as qs
from pflab.app import assistant, chat
from pflab.hq import daily, egress, proposals, rules, tools as tl
from pflab.risk import themes
from tests.test_s68_autonomy import AAA, NOW, con, rt  # noqa: F401  (fixtures)


def _idea(con, iid=1, status="open"):
    con.execute("INSERT INTO pot_ideas (idea_id, made_at, isin, symbol, reason, ref_close, buy_below, exit_above, stop_below, amount, horizon_days, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [iid, NOW, AAA, "AAA", "A new listing with a fall to its first-month low", 100.0, 92.0, 120.0, 85.0, 25000.0, 180, status])


def _fake_create(monkeypatch, store_it=True):
    """proposals.create without the whole ledger: it records the call and stores a row like the real one."""
    calls = []

    def create(con, now, inputs, *, pm_dir=None, case_id=None, by="the system"):
        calls.append((inputs, by))
        banned = rules.violation(con, inputs["action"], inputs["isin"])
        if banned:
            return {"stored": False, "problem": banned}
        pid = 100 + len(calls)
        con.execute("INSERT INTO hq_proposals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [pid, now, now, None, inputs["action"], inputs["isin"], inputs["symbol"], "proposed", "unreviewed", 1, "snap", "v1", json.dumps({"action": inputs["action"]}), "[]", None, None])
        return {"stored": True, "proposal_id": pid}
    monkeypatch.setattr(proposals, "create", create)
    return calls


# --- the pot ---------------------------------------------------------------------------------------------------------------------

def test_an_open_pot_idea_becomes_a_proposal_once_with_the_prices_code_worked_out(rt, con, monkeypatch):
    _idea(con)
    calls = _fake_create(monkeypatch)
    L = daily.pot_to_proposals(rt, NOW)
    assert len(L) == 1 and "became proposal #101" in L[0] and "nothing is bought" in L[0]
    inputs, by = calls[0]
    assert inputs["action"] == "BUY" and inputs["amount_rupees"] == 25000.0 and "buy at or below 92.0, exit above 120.0, stop below 85.0" in inputs["reason"] and by == "the opportunity pot"
    pay = json.loads(con.execute("SELECT payload_json FROM hq_proposals WHERE proposal_id = 101").fetchone()[0])
    assert pay["pot_idea"] == 1 and pay["pot"] == {"buy_below": 92.0, "exit_above": 120.0, "stop_below": 85.0}
    assert daily.pot_to_proposals(rt, NOW) == [] and len(calls) == 1                                          # the same idea is not proposed twice


def test_a_closed_idea_is_left_alone_and_a_house_rule_still_applies_to_the_pot(rt, con, monkeypatch):
    _idea(con, 1, status="closed")
    calls = _fake_create(monkeypatch)
    assert daily.pot_to_proposals(rt, NOW) == [] and calls == []
    _idea(con, 2)
    con.execute("UPDATE instruments SET sector = 'IT - Software' WHERE isin = ?", [AAA])
    rules.propose(con, NOW, "sector_exclusion", "No new tech until I say", {"terms": ["software"]}, name="no_new_tech")
    L = daily.pot_to_proposals(rt, NOW)
    assert len(L) == 1 and "was not proposed" in L[0] and "no_new_tech" in L[0]


# --- what waits for his yes ------------------------------------------------------------------------------------------------------

def _ask(con, q="Limit for 'AI and IT': at most 6.0% of the portfolio. Answer yes to apply it, no to decline.", agent="limits", key="limit:theme_limit:ai_it:1"):
    return qs.ask(con, agent, key, q, NOW)


def _ctx(rt, said):
    return tl.Ctx(rt, 1, "local", False, {}, egress.Gate(), NOW, mode="normal", source=said, role="assistant", allowed=frozenset(assistant.TOOLS), his_text=said)


def _shown(con, text):
    chat._add(con, assistant.thread(con, NOW), "ai", "assistant", text, "done", NOW)


def _call(rt, said, qid, answer):
    return json.loads(tl.run(_ctx(rt, said), "answer_question", {"q_id": qid, "answer": answer}, 1)[0])


def test_the_review_puts_each_waiting_request_to_him_with_a_number(rt, con, tmp_path):
    qid = _ask(con)
    rt.data_root = tmp_path
    daily.review(rt, NOW)
    msg = con.execute("SELECT text FROM chat_messages WHERE mode LIKE 'note:review:%'").fetchone()[0]
    assert f"[Q#{qid}]" in msg and "at most 6.0% of the portfolio" in msg and "say yes or no here" in msg


def test_the_waiting_tool_lists_them(rt, con):
    qid = _ask(con)
    _ask(con, "Something from another agent", agent="bank", key="bank:1")
    out = json.loads(tl.run(_ctx(rt, "what is waiting"), "waiting", {}, 1)[0])
    assert [w["q"] for w in out["waiting_for_his_yes"]] == [f"Q#{qid}"]                                       # only the limit and pot questions


def test_his_yes_applies_a_limit_he_was_just_shown(rt, con, monkeypatch):
    applied = []
    monkeypatch.setattr(themes, "resolve", lambda c, n: applied.append(1) or {"applied": 1})
    qid = _ask(con)
    _shown(con, f"Waiting for your yes [Q#{qid}]: Limit for 'AI and IT': at most 6.0% of the portfolio.")
    out = _call(rt, "yes, apply it", qid, "yes")
    assert out["answered"] is True and out["q"] == f"Q#{qid}" and applied == [1]
    assert con.execute("SELECT status, answer FROM questions WHERE q_id = ?", [qid]).fetchone() == ("answered", "yes")


def test_his_no_declines_it(rt, con, monkeypatch):
    monkeypatch.setattr(themes, "resolve", lambda c, n: {})
    qid = _ask(con)
    _shown(con, f"[Q#{qid}] The pot limit")
    assert _call(rt, "no, leave it", qid, "no")["answered"] is True and con.execute("SELECT answer FROM questions WHERE q_id = ?", [qid]).fetchone()[0] == "no"


def test_the_refusals(rt, con, monkeypatch):
    monkeypatch.setattr(themes, "resolve", lambda c, n: {})
    qid = _ask(con)
    assert "was not put to him" in _call(rt, "yes", qid, "yes")["why"]                                       # never shown: a stray yes cannot answer it
    _shown(con, f"[Q#{qid}] The limit")
    assert "does not clearly say yes" in _call(rt, "hmm, not sure", qid, "yes")["why"]                       # his words, not the model's
    assert "does not clearly say no" in _call(rt, "yes", qid, "no")["why"]
    other = _ask(con, "A bank label question", agent="bank", key="bank:2")
    _shown(con, f"[Q#{other}] bank")
    assert "no open limit or pot question" in _call(rt, "yes", other, "yes")["why"]                          # only limits, theme baskets and the pot
    assert "no open limit or pot question" in _call(rt, "yes", 9999, "yes")["why"]
    assert con.execute("SELECT status FROM questions WHERE q_id = ?", [qid]).fetchone()[0] == "open"        # nothing above changed it


def test_a_question_shown_long_ago_is_not_the_one_he_is_answering(rt, con, monkeypatch):
    monkeypatch.setattr(themes, "resolve", lambda c, n: {})
    qid = _ask(con)
    _shown(con, f"[Q#{qid}] The limit")
    for i in range(5):                                                                                       # five newer messages push it out of the window
        _shown(con, f"A later message {i}")
    assert _call(rt, "yes", qid, "yes")["answered"] is False
