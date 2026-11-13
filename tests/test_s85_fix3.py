"""S85 fix3: (1) a held name's refused buy keeps its guard in the stored reason, (2) a case is re-looked off its calendar (a new thesis-break event; the first look after a timing guard cleared),
(3) names with digits (ICICIB22, BHARAT22, NIFTY50) are names, not figures. Synthetic store, scripted model through the one door, no paid call."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from pflab import think
from pflab.think import cases, rule, session, watch

from tests.test_s80_core import GLD
from tests.test_s84_integration import (CLOSE_AT, DAY, Client, _world, answer, con, extend, orders, script)  # noqa: F401  (fixtures and helpers of the S84 integration file)

GUARD = "it made a new low 2 sessions ago: wait for 5 sessions above it (test)"


def _held_case(con, tmp_path, monkeypatch, guard=True):
    """GLDBEES (an ETF) is held by the synthetic book; the model says 'buy in parts, temporary'; the rule's new-low guard is switched on (or off) by the test."""
    state = {"on": guard}
    monkeypatch.setattr(rule, "new_low_guard", lambda s, sessions, clear_days: GUARD if state["on"] else None)
    script(Client(answer("GLDBEES", "buy_in_parts", "temporary", pending="", worst="very unlikely", likely="even", best="likely"), check="pass"))
    sid = cases.record_signal(con, CLOSE_AT, market="IN", isin=GLD, symbol="GLDBEES", signal="move_1d", value=-0.04, threshold=0.03, surprise=2.0, exposure_inr=100000.0, score=200000.0)
    cid = cases.open_case(con, CLOSE_AT, market="IN", kind="market", isin=GLD, symbol="GLDBEES", title="GLDBEES moved -4% in a day", exposure_inr=100000.0, score=200000.0, signal_ids=[sid],
                          opened_by="watch", state="open")
    r = session.think_case(con, CLOSE_AT + timedelta(minutes=40), cid, root=tmp_path / "data")
    assert r["ok"], r
    return cid, state


def _not_due(con, cid):
    cases.set_case(con, cid, next_look_on=DAY + timedelta(days=60))


def _n_answers(con, cid):
    return len([s for s in cases.steps(con, cid) if s["step"] == "answer_ok"])


# --- (1) the guard stays in the reason of a hold ---------------------------------------------------------------------------------------------------------------------------

def test_a_held_names_refused_buy_keeps_the_guard_that_made_it_wait_in_the_stored_reason(con, tmp_path, monkeypatch):
    cid, _ = _held_case(con, tmp_path, monkeypatch)
    d = cases.get_case(con, cid)["decisions"][0]
    assert d["model_option"] == "buy_in_parts" and d["rule_option"] == "hold", d
    assert d["reason"].count("Hold: no sale beats holding") == 1                                   # the sale did not beat holding: said as before
    assert rule.BUY_WAITS in d["reason"] and GUARD in d["reason"], d["reason"]                    # and the guard that made the buy wait is said too
    assert not [o for o in orders(con, "buy") if o[0] == GLD]


def test_the_rule_alone_returns_the_guard_in_the_hold_and_no_text_when_the_buy_is_not_refused(con, tmp_path, monkeypatch):
    cid, state = _held_case(con, tmp_path, monkeypatch)
    case = cases.get_case(con, cid)
    ans = session._normal(session._last_answer(con, cid), {"GLDBEES": GLD})
    r = rule.decide(con, cid, ans, DAY)
    rr = (r.get("all") or [r])[0]
    assert rr["rule_option"] == "hold" and rr["guards"] == [GUARD] and rr["refused"] is False and GUARD in rr["reason"]      # refused stays False: the session reads a refused flag as "nothing"
    state["on"] = False
    rr2 = (rule.decide(con, cid, ans, DAY).get("all") or [None])[0]
    assert rr2["rule_option"] == "buy_in_parts" and GUARD not in rr2["reason"] and case["decisions"]


# --- (2a) a new thesis-break event re-looks the case at once ---------------------------------------------------------------------------------------------------------------

def _rec(con, cid, when, kind, severity):
    sid = cases.record_signal(con, when, market="IN", isin=GLD, symbol="GLDBEES", signal="thesis_event", value=3.0, threshold=1.0, surprise=3.0, exposure_inr=100000.0, score=300000.0,
                              detail={"ref": f"t:{when.isoformat()}", "kind": kind, "severity": severity, "text": "an inquiry", "event_ts": str(when)})
    cases.set_signal(con, sid, case_id=cid, status="joined")
    return sid


def test_a_new_thesis_break_event_joining_an_open_case_re_looks_it_once_off_its_calendar(con, tmp_path, monkeypatch):
    cid, _ = _held_case(con, tmp_path, monkeypatch)
    _not_due(con, cid)
    n0 = _n_answers(con, cid)
    now = CLOSE_AT + timedelta(hours=2)
    out = session.follow_up(con, now, DAY, root=tmp_path / "data")
    assert out["failed"] == [] and _n_answers(con, cid) == n0 and not out.get("relooked")        # nothing new: the model is not called
    _rec(con, cid, now + timedelta(minutes=5), "fraud_investigation", "high")
    out = session.follow_up(con, now + timedelta(minutes=10), DAY, root=tmp_path / "data")
    assert out["failed"] == [] and out.get("relooked") == 1 and _n_answers(con, cid) == n0 + 1, out
    out = session.follow_up(con, now + timedelta(minutes=20), DAY, root=tmp_path / "data")      # once per trigger
    assert out.get("relooked") is None and _n_answers(con, cid) == n0 + 1


def test_an_ordinary_new_event_or_a_medium_one_of_no_break_kind_does_not_re_look_off_the_calendar(con, tmp_path, monkeypatch):
    cid, _ = _held_case(con, tmp_path, monkeypatch)
    _not_due(con, cid)
    n0 = _n_answers(con, cid)
    now = CLOSE_AT + timedelta(hours=2)
    _rec(con, cid, now, "results", "medium")
    out = session.follow_up(con, now + timedelta(minutes=10), DAY, root=tmp_path / "data")
    assert out.get("relooked") is None and _n_answers(con, cid) == n0


def test_the_off_calendar_re_look_stays_inside_the_days_cap_of_cases(con, tmp_path, monkeypatch):
    cid, _ = _held_case(con, tmp_path, monkeypatch)
    _not_due(con, cid)
    n0 = _n_answers(con, cid)
    real = think.settings()
    monkeypatch.setattr(think, "settings", lambda: {**real, "max_cases_per_day": 1})              # this case already used the day's one slot when it was opened
    now = CLOSE_AT + timedelta(hours=2)
    _rec(con, cid, now, "fraud_investigation", "high")
    out = session.follow_up(con, now + timedelta(minutes=10), DAY, root=tmp_path / "data")
    assert out.get("relooked") is None and _n_answers(con, cid) == n0, out


# --- (2b) the first look after the timing guard cleared ----------------------------------------------------------------------------------------------------------------------

def test_the_first_look_after_a_timing_guard_cleared_buys_by_the_rule_alone_without_the_model(con, tmp_path, monkeypatch):
    cid, state = _held_case(con, tmp_path, monkeypatch)
    _not_due(con, cid)                                                                           # off its calendar
    n0, now = _n_answers(con, cid), CLOSE_AT + timedelta(hours=2)
    out = session.follow_up(con, now, DAY, root=tmp_path / "data")                               # the guard still holds: nothing bought, the check is made once a day
    assert out["failed"] == [] and not [o for o in orders(con, "buy") if o[0] == GLD]
    checks = [s for s in cases.steps(con, cid) if s["step"] == "guard_checked"]
    session.follow_up(con, now + timedelta(minutes=5), DAY, root=tmp_path / "data")
    assert len([s for s in cases.steps(con, cid) if s["step"] == "guard_checked"]) == len(checks) == 1
    state["on"] = False                                                                          # the guard's own condition clears
    days = extend(con, 1)
    out = session.follow_up(con, datetime.combine(days[-1], datetime.min.time()) + timedelta(hours=16, minutes=30), days[-1], root=tmp_path / "data")
    assert out["failed"] == [], out
    assert len([o for o in orders(con, "buy") if o[0] == GLD]) == 1, out                         # the first part, decided by the rule on the stored answer
    assert _n_answers(con, cid) == n0                                                            # no model call
    assert [d["rule_option"] for d in cases.get_case(con, cid)["decisions"]] == ["hold", "buy_in_parts"]


# --- (3) names with digits ------------------------------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("sym", ["NIFTYBEES", "ICICIB22", "BHARAT22", "NIFTY50BEES", "GOLDBEES2"])
def test_names_with_digits_are_accepted_as_option_targets_and_in_the_prose(sym):
    a = answer(sym, "buy_in_parts", "market_fear", pending="", happened=f"{sym} fell with the market; ICICIB22 and BHARAT22 too.")
    a["choices"][0]["reason"] = f"{sym} is the broad fund the book already holds; BHARAT22 is similar."
    assert session.validate_answer(a, "a rate scare") == []
    assert session._normal(a, {sym.upper(): "INF000N01017"})["choices"][0]["symbol"] == sym


def test_a_real_figure_next_to_a_name_with_digits_still_needs_a_source():
    a = answer("ICICIB22", "hold", "unclear", pending="", happened="ICICIB22 fell 3.5% on a rate scare.")
    assert any("3.5" in p for p in session.validate_answer(a, "a rate scare"))
    assert session._numbers("buy INR500 of USD50 and Rs 1,500, FY26") >= {"500", "50", "1500", "26"}
