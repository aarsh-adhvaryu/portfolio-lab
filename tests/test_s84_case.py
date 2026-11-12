"""S84 `case`: T3 understand and choose, T6 act and tell, T7 come back, the reserve and the freezes (`think/session.py`, `think/reserve.py`). Synthetic data and a scripted model only (rule 7).

The pieces built beside this one (gateway, recall, odds, rule, score) are scripted fakes put in `session.DEPS`; the book is the synthetic paper book of `tests/test_s81_exits.py`.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab import think
from pflab.core import baseline_v2, exits, picks
from pflab.ledger import events as ev
from pflab.ledger import system
from pflab.paper import book
from pflab.pm import store
from pflab.think import cases, reserve, session
from pflab.us import picks_wire

WIN, CALM, NEWX = "INE000A01011", "INE000D01014", "INE000N01016"
NOW = datetime(2026, 10, 30, 16, 0)
DAYS = [d.date() for d in pd.bdate_range("2025-08-01", "2026-10-30")]
DAY = DAYS[-1]


# --- the scripted pieces -------------------------------------------------------------------------------------------------------------------------------------------------------

class Gate:
    """A scripted gateway: `answers` for the structured calls, a verdict list for the big-trade check, an optional tool script for the first read."""
    MODELS = {"read": ("claude-sonnet-5-5", "medium"), "decide": ("claude-opus-5-5", "high"), "quick": ("claude-sonnet-5-5", "low")}

    def __init__(self, answers, checks=(), tools_first=False):
        self.answers, self.checks, self.calls, self.tools_first, self.seen_messages = list(answers), list(checks), [], tools_first, []

    def call(self, con, role, system, messages, *, tools=None, case_id=None, purpose="", now=None, max_tokens=1500, schema=None, **kw):
        self.calls.append({"role": role, "purpose": purpose, "schema": schema is not None, "tools": tools is not None})
        self.seen_messages.append(messages)
        m, t = self.MODELS[role]
        out = {"text": "", "json": None, "tool_calls": [], "cost_rupees": 0.5, "cached_tokens": 120, "engine": "anthropic", "model": m, "thinking": t}
        if purpose == "big_trade_check":
            v = self.checks.pop(0) if self.checks else "pass"
            out["json"] = {"verdict": v, "reason": "fine" if v == "pass" else "a stale price"}
            return out
        if purpose.startswith("answer"):
            a = self.answers.pop(0)
            if isinstance(a, Exception):
                raise a
            out["json"], out["text"] = a, json.dumps(a)
            return out
        if self.tools_first and purpose == "read1":
            out["tool_calls"] = [{"id": "t1", "name": "recall", "input": {"symbol": "WIN"}}]
            return out
        out["text"] = "A governance report; the board is investigating."
        return out


class Recall:
    def __init__(self):
        self.used, self.written = [], []

    def recall(self, con, now, *, isin=None, symbol=None, topic=None, sector=None, asof=None, limit_chars=6000):
        it = [{"kind": "analyst_note", "id": 7, "day": "2026-10-20", "source": "analyst", "title": "an earlier note", "text": "the thesis was the order book"}]
        return {"items": it, "text": "[analyst 2026-10-20] an earlier note: the thesis was the order book", "n": 1}

    def mark_used(self, con, items, *, by_kind, by_ref, day):
        self.used.append((by_kind, by_ref, len(items)))

    def write_back(self, con, now, *, isin=None, symbol=None, topic=None, title, text, source, cost_rupees=0.0, case_id=None):
        self.written.append((symbol, title, source, case_id))
        return 1

    def same_subject_fresh(self, con, now, *, isin=None, topic=None, since_move=None):
        return None


class Odds:
    def option_table(self, con, case_id, answer, asof):
        c = cases.get_case(con, case_id)
        rows = []
        for o in think.OPTIONS:
            rows.append({"isin": c["isin"], "symbol": c["symbol"], "option": o, "worst_inr": -5000.0, "likely_inr": 1000.0, "best_inr": 9000.0, "expected_inr": 700.0,
                         "worst_pct_book": -0.005, "size_inr": 30000.0 if o == "buy_in_parts" else 0.0, "basis": "own range"})
        return rows

    def base_rates(self, con, kind, *, move=None, isin=None, asof):
        return {5: {"n": 3}, "basis": "own range"}

    def outcomes(self, con, case, option, *, isin, asof, bet_inr=None):
        return {"worst_inr": -1.0, "basis": "own range"}


class Rule:
    nxt = {"rule_option": "hold", "size_inr": 0.0, "parts": 3, "reason": "the rule holds", "guards": [], "refused": False}

    def decide(self, con, case_id, answer, asof):
        return dict(Rule.nxt)


class Score:
    adv = False

    def advisory(self, con, day):
        return Score.adv


def ans(opt="hold", klass="unclear", pending="the board's decision", sym="WIN", **kw):
    a = {"happened": "Reports of a board investigation.", "sources": ["press reports"], "class": klass, "known": "", "pending": pending, "pending_date": "", "other_names": [],
         "choices": [{"symbol": sym, "option": opt, "reason": "the thesis holds"}],
         "likelihood": {"worst": "unlikely", "likely": "likely", "best": "unlikely", "base_rate_set": "20", "reason": "history"}}
    a.update(kw)
    return a


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    c = store.connect(tmp_path / "l.duckdb")
    for isin, cls, tc, sym, name, sec in ((WIN, "equity", "EQUITY", "WIN", "Win Ltd", "Banks"), (CALM, "equity", "EQUITY", "CALM", "Calm Ltd", "Pharma"), (NEWX, "equity", "EQUITY", "NEWX", "Newx Ltd", "Auto")):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, ?, 'synthetic', now())", [isin, cls, tc, sym, name, sec])
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha')")
    log = ev.EventLog()
    log.append(ev.Event(kind="deposit", account_id="ZER", date=date(2023, 1, 1), amount=9_000_000.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2024, 1, 10), isin=WIN, qty=4000, price=50.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2024, 5, 6), isin=CALM, qty=1000, price=95.0))
    ev.save(c, log, NOW)
    for k, d in enumerate(DAYS):
        for isin in (WIN, CALM, NEWX):
            c.execute("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [isin, d, 100.0 * (1.004 if k % 2 else 0.996) if k < len(DAYS) - 1 else 100.0])
    system.switch(c, tmp_path, DAYS[-6], NOW, start_cash=2_000_000.0)
    book.seed(c, DAYS[-6], NOW)
    book.catch_up(c, DAY, datetime.combine(DAY, datetime.min.time()) + timedelta(hours=21))
    g = Gate([])
    session.DEPS.update({"gateway": g, "recall": Recall(), "odds": Odds(), "rule": Rule(), "score": Score()})
    Rule.nxt = {"rule_option": "hold", "size_inr": 0.0, "parts": 3, "reason": "the rule holds", "guards": [], "refused": False}
    Score.adv = False
    yield c
    session.DEPS.clear()


def _case(con, isin=WIN, symbol="WIN", exposure_inr=400000.0, **kw):
    sid = cases.record_signal(con, NOW, market="IN", isin=isin, symbol=symbol, signal="governance", value=1.0, threshold=1.0, surprise=3.0, exposure_inr=exposure_inr, score=3.0)
    return cases.open_case(con, NOW, market="IN", kind="governance", isin=isin, symbol=symbol, title=f"{symbol}: a board investigation", exposure_inr=exposure_inr, score=3.0, signal_ids=[sid], **kw)


def _thought(con, cid, sym="WIN"):
    """The case was thought through two days ago and nothing has joined it since."""
    old = NOW - timedelta(days=2)
    con.execute("UPDATE think_signals_s84 SET ts=? WHERE case_id=?", [old, cid])
    cases.add_step(con, cid, old, "answer_ok", payload={"answer": ans(sym=sym)})


def _gate(con, answers, **kw):
    g = Gate(answers, **kw)
    session.DEPS["gateway"] = g
    return g


# --- the structured answer ---------------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_valid_answer_fits_and_a_number_or_an_unknown_word_does_not():
    assert session.validate_answer(ans()) == []
    assert any("number" in p for p in session.validate_answer({**ans(), "size_inr": 50000}))
    bad = ans()
    bad["likelihood"]["worst"] = 0.3
    assert any("likelihood.worst" in p for p in session.validate_answer(bad))
    bad = ans()
    bad["likelihood"]["likely"] = "probably"
    assert any("likelihood.likely" in p for p in session.validate_answer(bad))
    assert any("class must be" in p for p in session.validate_answer(ans(klass="scary")))
    assert any("option" in p for p in session.validate_answer(ans(opt="short")))
    assert any("figures the sources did not give" in p for p in session.validate_answer(ans(happened="It fell 9.5% on the day."), known_text="a fall was reported"))
    assert session.validate_answer(ans(happened="It fell 9.5% on the day."), known_text="the close was 9.5% under the high") == []


# --- the session -------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_rule_acts_where_the_model_differs_and_both_choices_and_the_steps_are_stored(con):
    cid = _case(con)
    Rule.nxt = {"rule_option": "sell", "size_inr": 0.0, "parts": 3, "reason": "damage is a thesis break", "guards": [], "refused": False}
    g = _gate(con, [ans("hold", "damage")], tools_first=True)
    r = session.think_case(con, NOW, cid)
    assert r["ok"] and r["class"] == "damage" and r["decisions"][0]["rule"] == "sell" and r["decisions"][0]["model"] == "hold"
    c = cases.get_case(con, cid)
    d = c["decisions"][0]
    assert d["differs"] and d["acted_option"] == "sell" and d["rule_option"] == "sell" and d["model_option"] == "hold" and "the rule acts" in d["reason"]
    assert {o["track"] for o in c["options"]} >= {"table", "model", "rule"}
    assert [o["option"] for o in c["options"] if o["track"] == "rule"] == ["sell"] and [o["option"] for o in c["options"] if o["track"] == "model"] == ["hold"]
    model_steps = [s for s in c["steps"] if s["engine"]]
    assert model_steps and all(s["model"] and s["thinking"] and s["cost_rupees"] > 0 and s["cached_tokens"] == 120 for s in model_steps)
    assert any(s["step"] == "tool:recall" for s in c["steps"]) and c["state"] == "acted" and c["klass"] == "damage"
    assert con.execute("SELECT count(*) FROM paper_orders WHERE side='sell' AND isin=? AND status='open'", [WIN]).fetchone()[0] == 1       # the sale is a paper order, the exit manager's own event
    ev_ = con.execute("SELECT kind, reason FROM exit_events_s81 WHERE isin=? AND kind='case'", [WIN]).fetchone()
    assert ev_ and f"Case #{cid}" in ev_[1]
    assert session.DEPS["recall"].used == [("case", str(cid), 1)] and session.DEPS["recall"].written[0][2] == "case"


def test_sonnet_reads_and_opus_decides_only_over_the_line_or_for_a_chance(con):
    small = _case(con, exposure_inr=20000.0)                                       # a small holding: Sonnet alone
    g = _gate(con, [ans("hold")])
    session.think_case(con, NOW, small)
    assert [c["role"] for c in g.calls if c["purpose"].startswith("answer")] == ["read"] and not [c for c in g.calls if c["role"] == "decide"]
    big = _case(con, isin=CALM, symbol="CALM", exposure_inr=400000.0)              # over 2% of the book: Opus decides
    g = _gate(con, [ans("hold", sym="CALM")])
    session.think_case(con, NOW, big)
    assert [c["role"] for c in g.calls if c["purpose"].startswith("answer")] == ["decide"]
    chance = _case(con, isin=NEWX, symbol="NEWX", exposure_inr=0.0)                # not held: could spend the reserve, Opus decides
    g = _gate(con, [ans("nothing", sym="NEWX")])
    session.think_case(con, NOW, chance)
    assert [c["role"] for c in g.calls if c["purpose"].startswith("answer")] == ["decide"]


def test_an_answer_with_a_number_is_asked_once_more_and_then_the_case_stays_open(con):
    cid = _case(con)
    g = _gate(con, [{**ans(), "size_inr": 50000}, ans("hold")])
    r = session.think_case(con, NOW, cid)
    assert r["ok"] and [c["purpose"] for c in g.calls if c["purpose"].startswith("answer")] == ["answer", "answer_retry"]
    assert any(s["step"] == "answer_refused" for s in cases.get_case(con, cid)["steps"])
    cid2 = _case(con, isin=CALM, symbol="CALM")
    g = _gate(con, [{**ans(sym="CALM"), "size_inr": 1}, {**ans(sym="CALM"), "size_inr": 1}])
    r = session.think_case(con, NOW, cid2)
    assert not r["ok"] and "closed lists" in r["failed"] and cases.get_case(con, cid2)["state"] == "open" and cases.get_case(con, cid2)["decisions"] == []


def test_the_model_failing_or_the_cap_reached_leaves_the_case_open_and_nothing_else_changes(con):
    cid = _case(con)
    _gate(con, [RuntimeError("the monthly cap is reached")])
    r = session.think_case(con, NOW, cid)
    c = cases.get_case(con, cid)
    assert not r["ok"] and "cap is reached" in r["failed"] and c["state"] == "open" and c["decisions"] == [] and c["next_look_on"] is not None
    assert con.execute("SELECT count(*) FROM paper_orders").fetchone()[0] == 0 and any(s["step"] == "failed" for s in c["steps"])
    assert "Thinking failed on 1 case" in session.thinking_text(con, DAY)
    del session.DEPS["gateway"]                                                    # a missing module is the same: one case fails, nothing is raised
    session.DEPS["gateway"] = type("Broken", (), {"call": staticmethod(lambda *a, **k: (_ for _ in ()).throw(ImportError("no gateway yet")))})()
    assert session.think_case(con, NOW, cid)["ok"] is False


def test_the_switch_off_stops_the_loop(con, monkeypatch):
    cid = _case(con)
    monkeypatch.setattr(think, "on", lambda: False)
    assert session.think_case(con, NOW, cid) == {"off": True} and session.follow_up(con, NOW, DAY) == {"off": True}


def test_an_advisory_loop_reports_and_only_a_thesis_break_sale_acts(con):
    Score.adv = True
    cid = _case(con)
    Rule.nxt = {"rule_option": "trim", "size_inr": 100000.0, "parts": 3, "reason": "weighs better", "guards": [], "refused": False}
    _gate(con, [ans("hold", "temporary")])
    r = session.think_case(con, NOW, cid)
    d = cases.get_case(con, cid)["decisions"][0]
    assert r["advisory"] and d["advisory"] and d["acted_option"].startswith("advisory") and con.execute("SELECT count(*) FROM paper_orders").fetchone()[0] == 0
    assert cases.get_case(con, cid)["state"] == "advisory"
    cid2 = _case(con, isin=CALM, symbol="CALM")
    Rule.nxt = {"rule_option": "sell", "size_inr": 0.0, "parts": 3, "reason": "a thesis break", "guards": [], "refused": False}
    _gate(con, [ans("sell", "damage", sym="CALM")])
    session.think_case(con, NOW, cid2)
    assert cases.get_case(con, cid2)["decisions"][0]["acted_option"] == "sell"
    assert con.execute("SELECT count(*) FROM paper_orders WHERE isin=? AND side='sell'", [CALM]).fetchone()[0] == 1


# --- act: sales, the check, the reserve and the 1% limit -----------------------------------------------------------------------------------------------------------------------------

def test_a_sale_over_two_percent_passes_the_independent_check_first_and_a_veto_stops_it(con, monkeypatch):
    monkeypatch.setattr(session, "_whole_book", lambda con, day: 10_000_000.0)    # WIN is 400,000: 4% of the book
    cid = _case(con)
    g = _gate(con, [], checks=["veto"])
    refs = session.act(con, NOW, cid, {"isin": WIN, "symbol": "WIN", "market": "IN", "option": "sell", "size_inr": 0.0, "reason": "damage"})
    assert refs and refs[0].startswith("no order: the big-trade check vetoed") and con.execute("SELECT count(*) FROM paper_orders").fetchone()[0] == 0
    assert [c["purpose"] for c in g.calls] == ["big_trade_check"]
    g = _gate(con, [], checks=["pass"])
    refs = session.act(con, NOW, cid, {"isin": WIN, "symbol": "WIN", "market": "IN", "option": "sell", "size_inr": 0.0, "reason": "damage"})
    assert any(r.startswith("paper_order:") for r in refs) and [c["purpose"] for c in g.calls] == ["big_trade_check"]
    assert con.execute("SELECT count(*) FROM core_checks_s80 WHERE kind='case_trade'").fetchone()[0] == 2


def test_a_small_sale_needs_no_check(con, monkeypatch):
    monkeypatch.setattr(session, "_whole_book", lambda con, day: 1e12)
    cid = _case(con, exposure_inr=1000.0)
    g = _gate(con, [])
    refs = session.act(con, NOW, cid, {"isin": WIN, "symbol": "WIN", "market": "IN", "option": "trim", "size_inr": 100000.0, "reason": "trim"})
    assert any(r.startswith("paper_order:") for r in refs) and g.calls == []
    o = con.execute("SELECT qty FROM paper_orders WHERE isin=? AND side='sell'", [WIN]).fetchone()
    assert o and o[0] == 1000                                                      # Rs 100,000 at Rs 100


def test_a_reserve_buy_passes_the_check_and_is_one_part_of_three(con):
    cid = _case(con, isin=NEWX, symbol="NEWX", exposure_inr=0.0)
    g = _gate(con, [], checks=["pass"])
    st = reserve.reserve_status(con, "IN", DAY)
    assert st["reserve_inr"] > 0 and st["free_inr"] == pytest.approx(st["reserve_inr"], rel=1e-6) and "free to spend on a chance" in st["text"]
    d = {"isin": NEWX, "symbol": "NEWX", "market": "IN", "option": "buy_in_parts", "size_inr": 30000.0, "parts": 3, "reason": "the dip", "worst_pct_book": -0.008}
    refs = session.act(con, NOW, cid, d)
    assert refs[0].startswith("paper_order:") and [c["purpose"] for c in g.calls] == ["big_trade_check"]
    o = con.execute("SELECT amount, side, note FROM paper_orders WHERE isin=?", [NEWX]).fetchone()
    assert o[0] == pytest.approx(10000.0) and o[1] == "buy" and f"case #{cid}" in o[2]
    assert reserve.reserve_status(con, "IN", DAY)["free_inr"] == pytest.approx(st["free_inr"], rel=1e-6)       # plenty of cash beside the reserve: the order does not eat into it


def test_a_bet_whose_worst_case_does_not_fit_one_percent_is_refused_and_an_unchecked_buy_waits(con):
    cid = _case(con, isin=NEWX, symbol="NEWX", exposure_inr=0.0)
    g = _gate(con, [], checks=["pass"])
    refs = session.act(con, NOW, cid, {"isin": NEWX, "symbol": "NEWX", "market": "IN", "option": "buy_in_parts", "size_inr": 30000.0, "parts": 3, "reason": "x", "worst_pct_book": -0.02})
    assert refs[0].startswith("no order: the worst case would lose 2.00%") and g.calls == [] and con.execute("SELECT count(*) FROM paper_orders").fetchone()[0] == 0
    session.DEPS["gateway"] = type("Down", (), {"call": staticmethod(lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))})()
    refs = session.act(con, NOW, cid, {"isin": NEWX, "symbol": "NEWX", "market": "IN", "option": "buy_in_parts", "size_inr": 30000.0, "parts": 3, "reason": "x", "worst_pct_book": -0.005})
    assert refs[0].startswith("no order yet: the big-trade check could not run") and con.execute("SELECT count(*) FROM paper_orders").fetchone()[0] == 0


def test_a_buy_needs_room_in_the_reserve(con, monkeypatch):
    cid = _case(con, isin=NEWX, symbol="NEWX", exposure_inr=0.0)
    _gate(con, [], checks=["pass"])
    monkeypatch.setattr(reserve, "reserve_status", lambda con, m, day: {"free_inr": 500.0, "reserve_inr": 1000.0, "text": "", "used_inr": 500.0, "points": 0.1})
    refs = session.act(con, NOW, cid, {"isin": NEWX, "symbol": "NEWX", "market": "IN", "option": "buy_in_parts", "size_inr": 30000.0, "parts": 3, "reason": "x", "worst_pct_book": -0.005})
    assert "the reserve has no room" in refs[0] and con.execute("SELECT count(*) FROM paper_orders").fetchone()[0] == 0


def test_the_us_legs_sell_and_buy_from_the_sub_book(con, monkeypatch):
    from pflab.us import book as usb
    placed = []
    monkeypatch.setattr(usb, "positions", lambda con, day=None, before=False: {"ZZ0001045810": 10.0})
    monkeypatch.setattr(usb, "place", lambda con, now, day, isin, symbol, side, qty=None, amount_usd=None, reason="": placed.append((side, qty, amount_usd, reason)) or len(placed))
    monkeypatch.setattr(reserve, "reserve_status", lambda con, m, day: {"free_inr": 90000.0, "reserve_inr": 100000.0, "fx": 90.0, "text": "", "used_inr": 0, "points": 1})
    cid = _case(con, isin="ZZ0001045810", symbol="NVDA")
    _gate(con, [], checks=["pass"])
    assert session.act(con, NOW, cid, {"isin": "ZZ0001045810", "symbol": "NVDA", "market": "US", "option": "sell", "reason": "damage"}) == ["us_order:1"]
    assert placed[0][0] == "sell" and placed[0][1] == 10.0 and "next US open" in placed[0][3]
    assert session.act(con, NOW, cid, {"isin": "ZZ0001045810", "symbol": "NVDA", "market": "US", "option": "buy_in_parts", "size_inr": 54000.0, "parts": 3, "reason": "dip", "worst_pct_book": -0.004}) == ["us_order:2"]
    assert placed[1][0] == "buy" and placed[1][2] == pytest.approx(200.0)           # Rs 18,000 a part at 90 a dollar


# --- freezes -------------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_freeze_and_wait_make_a_system_rule_and_a_buy_lifts_it(con):
    cid = _case(con)
    refs = session.act(con, NOW, cid, {"isin": WIN, "symbol": "WIN", "market": "IN", "option": "freeze", "reason": "pending"})
    assert refs[0].startswith("freeze:") and cases.is_frozen(con, WIN, DAY) and cases.frozen_isins(con, DAY, "IN") == [WIN]
    cases.set_case(con, cid, pending="the board's decision")
    session.act(con, NOW, cid, {"isin": CALM, "symbol": "CALM", "market": "IN", "option": "wait", "reason": "pending"})
    f = [x for x in cases.active_freezes(con, DAY) if x["isin"] == CALM][0]
    assert f["until_event"] == "the board's decision" and f["until"] is None
    _gate(con, [], checks=["pass"])
    session.act(con, NOW, cid, {"isin": WIN, "symbol": "WIN", "market": "IN", "option": "buy_in_parts", "size_inr": 30000.0, "parts": 3, "reason": "x", "worst_pct_book": -0.005})
    assert not cases.is_frozen(con, WIN, DAY)


def _bstate(frozen=()):
    from pflab import core
    cfg = core.settings()
    rows = [{"isin": "A", "symbol": "AAA", "sector": "x", "asset_class": "equity", "qty": 10.0, "price": 100.0, "value": 5_000.0, "weight": 0.05, "buyable": True, "klass": "equity", "sleeve": "longterm"},
            {"isin": "B", "symbol": "BBB", "sector": "y", "asset_class": "equity", "qty": 10.0, "price": 100.0, "value": 5_000.0, "weight": 0.05, "buyable": True, "klass": "equity", "sleeve": "longterm"}]
    return {"day": DAY, "value": 100_000.0, "cash": 90_000.0, "bank": 0.0, "rows": rows, "sleeve_target": {"source": "t", "core": 0.0, "index": 0.0, "gold": 0.0, "international": 0.0, "longterm": 0.6, "cash": 0.4},
            "vol": {"A": 0.3, "B": 0.3}, "gauge": {"fired": False, "why": ""}, "cfg": cfg, "frozen": list(frozen)}


def test_a_freeze_blocks_new_buying_in_the_baseline_and_the_reserve_stays_cash():
    base = baseline_v2.decide(_bstate())
    assert base["weights"]["A"] > 0.05 and base["weights"]["B"] > 0.05
    fz = baseline_v2.decide(_bstate(frozen=["A"]))
    assert fz["weights"]["A"] == pytest.approx(0.05) and fz["weights"]["B"] > 0.05 and any("AAA is frozen" in n for n in fz["notes"])
    held = baseline_v2.decide({**_bstate(), "reserve_frac": 0.89})                  # the reserve takes nearly all the cash: nothing is left to buy with
    assert held["weights"]["A"] == pytest.approx(0.05, abs=0.02)


def test_a_freeze_blocks_new_buying_in_the_picks_and_the_us_step(con, monkeypatch):
    from pflab import core
    st = _bstate()
    st["vol"] = {"A": 0.3, "B": 0.3}
    pk = [{"isin": "A", "state": "buying", "source": "system", "symbol": "AAA"}, {"isin": "B", "state": "buying", "source": "system", "symbol": "BBB"}]
    monkeypatch.setattr(picks, "managed", lambda con, market="IN": pk)
    monkeypatch.setattr(picks, "share", lambda con, market="IN": {"share": 0.5, "source": "t"})
    monkeypatch.setattr(picks, "on", lambda market="IN": True)
    w = picks.target_weights(con, st, "IN")
    assert w["A"] > 0.05 and w["B"] > 0.05
    cases.add_freeze(con, NOW, isin="A", symbol="AAA", market="IN", case_id=None, until=DAY + timedelta(days=5))
    st["day"] = DAY
    w = picks.target_weights(con, st, "IN")
    assert w["A"] == pytest.approx(0.05) and w["B"] > 0.05
    # the US step: a frozen pick's target is what the sub-book holds
    monkeypatch.setattr(picks_wire.picks, "managed", lambda con, market="IN": [])
    monkeypatch.setattr(picks_wire.pick_share, "settings", lambda m=None: {"us_spy_floor": 0.3})
    ust = {"settings": {"invested_share": 0.9}, "value": 1000.0, "day": DAY, "picks": {"weights": {"U1": 0.2, "U2": 0.2}},
           "rows": [{"isin": "U1", "symbol": "UAA", "buyable": True, "value": 50.0}, {"isin": "U2", "symbol": "UBB", "buyable": True, "value": 50.0}]}
    out = picks_wire.extra_weights(con, ust)
    assert out["extra"]["UAA"] == 0.2
    cases.add_freeze(con, NOW, isin="U1", symbol="UAA", market="US", case_id=None, until=DAY + timedelta(days=5))
    out = picks_wire.extra_weights(con, ust)
    assert out["extra"]["UAA"] == pytest.approx(0.05) and out["extra"]["UBB"] == 0.2 and any("UAA is frozen" in n for n in out["notes"])


# --- the freeze through a case, parts, follow-up ---------------------------------------------------------------------------------------------------------------------------------------

def test_a_wait_decision_freezes_the_name_and_a_later_non_freeze_lifts_it(con):
    cid = _case(con)
    Rule.nxt = {"rule_option": "wait", "size_inr": 0.0, "parts": 3, "reason": "the board decides tonight", "guards": [], "refused": False}
    _gate(con, [ans("wait", "unclear", pending="the board's decision")])
    r = session.think_case(con, NOW, cid)
    c = cases.get_case(con, cid)
    assert r["ok"] and c["state"] == "acted" and c["pending"] == "the board's decision" and cases.is_frozen(con, WIN, DAY)
    assert c["next_look_on"] is not None and c["next_look_on"] > DAY
    later = datetime.combine(c["next_look_on"], datetime.min.time()) + timedelta(hours=16)
    Rule.nxt = {"rule_option": "hold", "size_inr": 0.0, "parts": 3, "reason": "the board kept him", "guards": [], "refused": False}
    cases.signals(con, case_id=cid)
    cases.record_signal(con, later, market="IN", isin=WIN, symbol="WIN", signal="news", value=1, threshold=1, surprise=1, exposure_inr=1, score=1)
    sid = con.execute("SELECT max(signal_id) FROM think_signals_s84").fetchone()[0]
    cases.set_signal(con, sid, case_id=cid, status="joined")
    _gate(con, [ans("hold", "temporary", pending="")])
    out = session.follow_up(con, later, later.date())
    assert out["rethought"] == 1 and not cases.is_frozen(con, WIN, later.date())


def test_three_parts_five_sessions_apart_and_the_later_part_waits_for_its_gap(con):
    cid = _case(con, isin=NEWX, symbol="NEWX", exposure_inr=0.0)
    Rule.nxt = {"rule_option": "buy_in_parts", "size_inr": 30000.0, "parts": 3, "reason": "the dip", "guards": [], "refused": False}
    _gate(con, [ans("buy_in_parts", "market_fear", pending="", sym="NEWX")], checks=["pass", "pass", "pass"])
    r = session.think_case(con, NOW, cid)
    assert r["ok"] and r["state"] == "acted" and len(session._parts_done(con, cid, NEWX)) == 1
    case = cases.get_case(con, cid)
    assert case["next_look_on"] is not None
    d0 = NOW.date()
    early = datetime.combine(d0 + timedelta(days=2), datetime.min.time()) + timedelta(hours=16)
    assert session._continue_parts(con, early, case) == []                          # not 5 sessions yet
    cases.set_case(con, cid, next_look_on=d0)                                       # (the look is due; nothing new happened)
    from pflab import markets
    day2 = markets.get("IN").session_after(d0, 5)
    late = datetime.combine(day2, datetime.min.time()) + timedelta(hours=16)
    out = session.follow_up(con, late, day2)
    assert out["parts"] == 1 and len(session._parts_done(con, cid, NEWX)) == 2
    day3 = markets.get("IN").session_after(day2, 5)
    cases.set_case(con, cid, next_look_on=day2)
    out = session.follow_up(con, datetime.combine(day3, datetime.min.time()) + timedelta(hours=16), day3)
    assert len(session._parts_done(con, cid, NEWX)) == 3
    assert session._continue_parts(con, datetime.combine(day3 + timedelta(days=9), datetime.min.time()), cases.get_case(con, cid)) == []          # three parts, no fourth
    amounts = [p["inr"] for p in session._parts_done(con, cid, NEWX)]
    assert amounts == [10000.0, 10000.0, 10000.0]


def test_a_follow_up_by_date_closes_a_decided_case_and_extends_a_pending_one_without_a_model_call(con):
    done = _case(con)
    cases.set_case(con, done, state="acted", next_look_on=DAY, pending=None)
    _thought(con, done)
    waiting = _case(con, isin=CALM, symbol="CALM")
    cases.set_case(con, waiting, state="waiting", next_look_on=DAY, pending="a result on the 5th")
    _thought(con, waiting, sym="CALM")
    g = _gate(con, [])
    out = session.follow_up(con, NOW, DAY)
    assert out["closed"] == 1 and out["extended"] == 1 and out["rethought"] == 0 and g.calls == []
    assert cases.get_case(con, done)["state"] == "closed" and cases.get_case(con, done)["closed_reason"] == "decided, nothing pending"
    assert cases.get_case(con, waiting)["next_look_on"] > DAY and cases.get_case(con, waiting)["state"] == "waiting"
    assert session.follow_up(con, NOW, DAY)["looked"] == 0                           # a second run the same day does nothing more


def test_a_quiet_case_closes_after_the_quiet_sessions_and_gives_back_its_freeze(con):
    cid = _case(con)
    cases.set_case(con, cid, state="waiting", next_look_on=DAY, pending="something that never came")
    _thought(con, cid)
    cases.add_freeze(con, NOW, isin=WIN, symbol="WIN", market="IN", case_id=cid, until_event="something that never came")
    far = DAY + timedelta(days=120)
    out = session.follow_up(con, datetime.combine(far, datetime.min.time()) + timedelta(hours=16), far)
    assert out["closed"] == 1 and "quiet" in cases.get_case(con, cid)["closed_reason"] and not cases.is_frozen(con, WIN, far)


def test_a_look_by_event_rethinks_when_a_new_signal_joined_the_case(con):
    cid = _case(con)
    _gate(con, [ans("hold")])
    session.think_case(con, NOW, cid)
    later = NOW + timedelta(days=3)
    cases.set_case(con, cid, next_look_on=later.date())
    quiet = session.follow_up(con, later, later.date())
    assert quiet["rethought"] == 0
    cases.set_case(con, cid, next_look_on=(later + timedelta(days=1)).date())
    s2 = cases.record_signal(con, later + timedelta(days=1), market="IN", isin=WIN, symbol="WIN", signal="news", value=2, threshold=1, surprise=2, exposure_inr=1, score=1)
    cases.set_signal(con, s2, case_id=cid, status="joined")
    g = _gate(con, [ans("hold")])
    out = session.follow_up(con, later + timedelta(days=1), (later + timedelta(days=1)).date())
    assert out["rethought"] == 1 and [c["purpose"] for c in g.calls if c["purpose"].startswith("answer")]


# --- telling and the block Today shows --------------------------------------------------------------------------------------------------------------------------------------------

def test_the_telegram_text_is_plain_and_goes_once_when_a_case_acts(con):
    cid = _case(con)
    Rule.nxt = {"rule_option": "freeze", "size_inr": 0.0, "parts": 3, "reason": "pending", "guards": [], "refused": False}
    _gate(con, [ans("freeze", "unclear")])
    r = session.think_case(con, NOW, cid)
    assert r["told"]
    row = con.execute("SELECT kind, text, status FROM outbox ORDER BY msg_id DESC LIMIT 1").fetchone()
    assert row[0] == "watch" and f"Case #{cid}" in row[1] and "If it goes badly" in row[1] and "looks again" in row[1] and "WIN: freeze" in row[1] and len(row[1]) < 1500
    assert "{" not in row[1] and "None" not in row[1]
    assert session.tell(con, NOW, cid) is None or True
    n = con.execute("SELECT count(*) FROM outbox").fetchone()[0]
    session.tell(con, NOW, cid)
    assert con.execute("SELECT count(*) FROM outbox").fetchone()[0] == n              # the same stage is not told twice


def test_a_case_that_only_holds_on_a_small_exposure_is_not_told(con):
    cid = _case(con, exposure_inr=1000.0)
    _gate(con, [ans("hold")])
    r = session.think_case(con, NOW, cid)
    assert r["ok"] and not r["told"]


def test_the_thinking_text_and_the_reserve_lines(con):
    cid = _case(con)
    cases.set_case(con, cid, klass="unclear", pending="the board's decision", next_look_on=date(2026, 11, 3))
    t = session.thinking_text(con, DAY)
    assert "Thinking about: WIN (unclear)" in t and "waiting for: the board's decision" in t and "India reserve:" in t and "free to spend on a chance" in t
    assert reserve.hold_fraction("IN") == pytest.approx(0.10) and reserve.hold_fraction("US") == pytest.approx(0.10)


def test_the_reserve_is_a_share_of_the_part_and_the_exposed_figures_are_plain_dicts(con):
    st = reserve.reserve_status(con, "IN", DAY)
    h = book.holdings(con, DAY)
    assert st["reserve_inr"] == pytest.approx(0.10 * h["value"], rel=1e-6) and st["used_inr"] == 0.0 and st["points"] == pytest.approx(10.0, abs=0.01)
    assert json.dumps(st) and reserve.reserve_status(con, "US", DAY)["free_inr"] == 0.0         # no US account: nothing to keep


# --- through the real door with a scripted vendor client ---------------------------------------------------------------------------------------------------------------------------------

def test_a_case_runs_through_the_real_gateway_and_stores_the_engine_model_thinking_cost_and_cache(con, monkeypatch):
    from types import SimpleNamespace
    from pflab.agents import analyst as an
    from pflab.llm import gateway
    monkeypatch.setattr(an, "config", lambda path=None: {"model": "claude-opus-5-5", "cap": 2500.0, "ask_above": 1000.0, "usd_inr": 90.0, "adopted": True, "policy": {}, "acceptance": {},
                                                          "paper": {}, "tijori_to_analyst": True, "counted_since": None})
    sent = []

    def create(**p):
        sent.append(p)
        usage = SimpleNamespace(input_tokens=2000, output_tokens=400, cache_read_input_tokens=1500, cache_creation_input_tokens=0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(ans("hold", "temporary", pending="")))], stop_reason="end_turn", model=p["model"], usage=usage)

    fake = SimpleNamespace(messages=SimpleNamespace(count_tokens=lambda **k: SimpleNamespace(input_tokens=3000), create=create), beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    gateway.set_client(fake)
    del session.DEPS["gateway"]
    try:
        cid = _case(con)                                                              # 4% of a Rs 10m book is over the Opus line
        monkeypatch.setattr(session, "_whole_book", lambda con, day: 10_000_000.0)
        r = session.think_case(con, NOW, cid)
    finally:
        gateway.set_client(None)
    assert r["ok"], r
    steps = [s for s in cases.get_case(con, cid)["steps"] if s["engine"]]
    assert {s["model"] for s in steps} == {"claude-sonnet-5-5", "claude-opus-5-5"} and all(s["engine"] == "anthropic" and s["thinking"] and s["cost_rupees"] > 0 and s["cached_tokens"] == 1500 for s in steps)
    assert con.execute("SELECT count(*) FROM api_calls WHERE case_id=? AND agent='think'", [cid]).fetchone()[0] == len(steps)
    assert all("output_config" in p and p["output_config"].get("effort") for p in sent) and any("format" in p["output_config"] for p in sent)
