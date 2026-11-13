"""S85 `rules`: the thinking loop's `act` reads the standing instructions (a case's sale or buy is held back by a rule and the case records the rule as the reason). Synthetic; the world is the S84
case fixture (a scripted gateway, a paper book with WIN held and NEWX not)."""
from __future__ import annotations

import pytest

from pflab.hq import rules
from pflab.think import cases, session
from tests.test_s84_case import CALM, DAY, NEWX, NOW, WIN, _case, _gate, ans, con  # noqa: F401  (the fixture and helpers)


def _orders(con):
    return con.execute("SELECT count(*) FROM paper_orders").fetchone()[0]


def test_a_case_sale_is_held_back_by_hold_name_and_the_case_records_the_rule(con, monkeypatch):
    monkeypatch.setattr(session, "_whole_book", lambda con, day: 1e12)
    r = rules.propose(con, NOW, "hold_name", "hold WIN, do not sell it", {"isin": WIN, "symbol": "WIN"}, source="test")
    cid = _case(con, exposure_inr=1000.0)
    _gate(con, [])
    refs = session.act(con, NOW, cid, {"isin": WIN, "symbol": "WIN", "market": "IN", "option": "trim", "size_inr": 100000.0, "reason": "trim"})
    assert refs == ["no order: not sold: your rule 'hold WIN, do not sell it' holds back WIN (Rs 100,000)"] and _orders(con) == 0
    step = [s for s in cases.steps(con, cid) if s["step"] == "rule_block"]
    assert step and "hold WIN" in step[0]["payload_json"]
    assert con.execute("SELECT rule_id, site, side FROM rules_held_back_s85").fetchone() == (r["rule_id"], "case", "sell")
    rules.undo(con, r["rule_id"])                                                                         # Undo: the same sale goes through
    refs = session.act(con, NOW, cid, {"isin": WIN, "symbol": "WIN", "market": "IN", "option": "trim", "size_inr": 100000.0, "reason": "trim"})
    assert any(x.startswith("paper_order:") for x in refs)


def test_a_thesis_break_sale_is_never_held_by_hold_name(con, monkeypatch):
    monkeypatch.setattr(session, "_whole_book", lambda con, day: 1e12)
    rules.propose(con, NOW, "hold_name", "hold WIN, do not sell it", {"isin": WIN, "symbol": "WIN"}, source="test")
    cid = _case(con, exposure_inr=1000.0)
    con.execute("UPDATE think_cases_s84 SET klass='damage' WHERE case_id=?", [cid])                        # the case calls the news damage to the thesis
    _gate(con, [])
    refs = session.act(con, NOW, cid, {"isin": WIN, "symbol": "WIN", "market": "IN", "option": "sell", "size_inr": 0.0, "reason": "damage"})
    assert any(x.startswith("paper_order:") for x in refs) and con.execute("SELECT count(*) FROM rules_held_back_s85").fetchone()[0] == 0


def test_a_case_buy_is_held_back_by_pause_buys_on_the_name_and_by_no_new_names_and_by_a_cash_floor(con):
    rules.propose(con, NOW, "pause_buys", "pause NEWX buying", {"scope": "name", "isin": NEWX, "symbol": "NEWX"}, source="test")
    cid = _case(con, isin=NEWX, symbol="NEWX", exposure_inr=0.0)
    _gate(con, [], checks=["pass"])
    d = {"isin": NEWX, "symbol": "NEWX", "market": "IN", "option": "buy_in_parts", "size_inr": 30000.0, "parts": 3, "reason": "the dip", "worst_pct_book": -0.008}
    assert session.act(con, NOW, cid, d)[0].startswith("no order: not bought: your rule 'pause NEWX buying'") and _orders(con) == 0
    rules.undo(con, "pause_newx_buying")
    rules.propose(con, NOW, "no_new_names", "no new names", {}, source="test")
    assert session.act(con, NOW, cid, d)[0].startswith("no order: not bought: your rule 'no new names'") and _orders(con) == 0
    rules.undo(con, "no_new_names")
    rules.propose(con, NOW, "cash_floor", "keep 90% in cash", {"share_pct": 90}, source="test")
    refs = session.act(con, NOW, cid, d)
    assert refs[0].startswith("no order: not bought: your rule 'keep 90% in cash'") and "keeps 90% of the book in cash" in refs[0] and _orders(con) == 0
    assert con.execute("SELECT count(*) FROM rules_held_back_s85").fetchone()[0] == 3
    rules.undo(con, "keep_90_in_cash")                                                                       # Undo: the part is bought
    assert session.act(con, NOW, cid, d)[0].startswith("paper_order:")


def test_the_decision_row_of_a_held_back_case_says_which_rule(con):
    """The reason stored with the decision carries the rule (`think_decisions_s84.reason`), through `decide` -> `act`."""
    rules.propose(con, NOW, "pause_buys", "pause NEWX buying", {"scope": "name", "isin": NEWX, "symbol": "NEWX"}, source="test")
    cid = _case(con, isin=NEWX, symbol="NEWX", exposure_inr=0.0)
    refs = session.act(con, NOW, cid, {"isin": NEWX, "symbol": "NEWX", "market": "IN", "option": "buy_in_parts", "size_inr": 30000.0, "parts": 3, "reason": "x", "worst_pct_book": -0.005})
    assert "your rule 'pause NEWX buying'" in refs[0]
    cases.record_decision(con, cid, DAY, isin=NEWX, symbol="NEWX", rule_option="buy_in_parts", model_option="buy_in_parts", acted_option="nothing (" + refs[0][:120] + ")", order_refs=refs,
                          reason="the rule chose a buy | " + refs[0])
    assert "pause NEWX buying" in cases.decisions(con, cid)[-1]["reason"]
