"""S60 the brain with tools (PLAN A18): the tool registry, per-stock drift / odds / edge, the governed tool loop with
its context hand-off, the suggestion ledger, memory corrections and outcomes, redaction, the cited-page fetch.
Synthetic data, a fake API client."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from pflab.agents import analyst as an, memory as mem
from pflab.hq import brain, egress, fetch, governor as gv, keeper, redact, stocks, suggestions as sg, tools as tl
from pflab.hq.desk import Desk
from pflab.pm import store

AAA, BBB, CCC = "INE000A01011", "INE000B01012", "INE000C01013"
NOW = datetime(2026, 10, 26, 10, 0)          # a Monday
CFG = {"model": an.MODEL, "cap": 2500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True, "tijori_to_analyst": True}


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "l.duckdb")
    for isin, sym in ((AAA, "AAA"), (BBB, "BBB"), (CCC, "CCC")):
        c.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                     VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, ?, ?, 'synthetic', now())""", [isin, sym, f"{sym} Limited"])
    c.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES ('ZERODHA', 'demat', 'Zerodha', '12081600')")
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('SB12345678', 'bank', 'SBI')")
    return c


def _prices(con, isin, closes, end: date = date(2026, 10, 23)):
    days = pd.bdate_range(end=end, periods=len(closes))
    for d, x in zip(days, closes):
        con.execute("INSERT INTO prices VALUES (?,?,?,?,?,?)", [isin, d.date(), float(x), "EQ", "nse_bhavcopy", NOW])
    return pd.Series(np.asarray(closes, float), index=days)


def _walk(n, seed, drift=0.0, vol=0.015, start=100.0):
    r = np.random.default_rng(seed).normal(drift, vol, n)
    return start * np.exp(np.cumsum(r))


def _desk(con, tmp_path, **settings):
    s = {"brain": "economy", "preset": "full", "telegram_send": False, "drop_watch": True, **settings}
    return Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, s, clock=lambda: NOW)


def _book(**kw):
    base = dict(asof=NOW.date(), investable=1_000_000.0, values={AAA: 90_000.0, CCC: 20_000.0},
                symbols={AAA: "AAA", BBB: "BBB", CCC: "CCC"}, on_list={AAA, BBB},
                guards={AAA: ("ok", []), BBB: ("ok", [])}, zones={}, results={}, buckets={"equity": 110_000.0},
                bands={"equity": (0.40, 0.05, 0.10)}, max_weight=0.08, gains={AAA: (90_000.0, 60_000.0)},
                qtys={AAA: 900.0, CCC: 200.0})
    base.update(kw)
    return stocks.Book(**base)


# --- a fake API client that calls tools ---------------------------------------------------------------------------------

def _tool_msg(*calls, usage=(800, 200)):
    content = [SimpleNamespace(type="thinking", thinking="", signature="sig")]
    content += [SimpleNamespace(type="tool_use", id=f"tu{k}", name=n, input=i) for k, (n, i) in enumerate(calls)]
    return SimpleNamespace(content=content, stop_reason="tool_use", model=gv.OPUS,
                           usage=SimpleNamespace(input_tokens=usage[0], output_tokens=usage[1], cache_read_input_tokens=0,
                                                 cache_creation_input_tokens=0))


def _note_msg(text):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn", model=gv.OPUS,
                           usage=SimpleNamespace(input_tokens=900, output_tokens=150, cache_read_input_tokens=0,
                                                 cache_creation_input_tokens=0))


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


@pytest.fixture
def quiet_input(monkeypatch):
    monkeypatch.setattr(brain, "portfolio_view", lambda con, asof: ("PORTFOLIO: AAA | equity | 9.0 | Rs 90,000 | +50.0",
                                                                    {"AAA": AAA}))
    monkeypatch.setattr(brain, "watch_view", lambda con: ("WATCH LIST: BBB", {"BBB": BBB}))
    monkeypatch.setattr(tl.Ctx, "book", lambda self: _book())


# --- the registry -------------------------------------------------------------------------------------------------------

def test_every_tool_has_a_strict_schema_and_bounds_are_checked_here():
    defs = tl.definitions()
    assert len(defs) == len(tl.TOOLS) and all(d["input_schema"]["additionalProperties"] is False for d in defs)
    strict = [d["name"] for d in defs if d.get("strict")]
    assert len(strict) <= 20 and "record_suggestion" in strict and "portfolio" not in strict   # the API's limit: 20
    assert not any(k in p for d in defs for p in d["input_schema"]["properties"].values()
                   for k in ("minimum", "maximum", "maxLength"))                  # moved into descriptions for the API
    assert {t.kind for t in tl.TOOLS.values()} == set(tl.KINDS)
    rp = tl.TOOLS["record_prediction"]
    good = {"symbol": "AAA", "kind": "return_above", "level": 5, "due": "2026-11-30", "confidence": 0.6, "claim": "c"}
    assert tl.validate(rp, good) is None
    assert "unknown" in tl.validate(rp, {**good, "extra": 1})
    assert "missing" in tl.validate(rp, {k: v for k, v in good.items() if k != "due"})
    assert "one of" in tl.validate(rp, {**good, "kind": "up"})
    assert "between" in tl.validate(rp, {**good, "confidence": 1.5})
    assert "must be number" in tl.validate(rp, {**good, "level": True})
    rs = tl.TOOLS["record_suggestion"]
    assert "stocks_overview" in rs.params["rested_on"]["items"]["enum"] and "ask_investor" not in rs.params["rested_on"]["items"]["enum"]


def test_tool_results_are_redacted_logged_and_identity_withheld(con, tmp_path):
    rt = _desk(con, tmp_path)
    gate = egress.Gate(ids={"SB12345678"}, names=["testname"])
    ctx = tl.Ctx(rt, 7, gv.OPUS, True, {"AAA": AAA}, gate, NOW)
    mem.remember(con, "note", "cash parked in SB12345678 for now", subject="cash", now=NOW)
    text, err = tl.run(ctx, "memory_recall", {"words": "parked"}, 1)
    assert not err and "SB12345678" not in text and "[ACCOUNT-1]" in text
    mem.remember(con, "note", "write to me at a.b@example.com", subject="contact", now=NOW)
    text, err = tl.run(ctx, "memory_recall", {"subject": "contact"}, 1)
    assert "a.b@example.com" not in text and "[EMAIL]" in text
    assert tl.run(ctx, "nope", {}, 2) == ("unknown tool 'nope'", True)
    text, err = tl.run(ctx, "notes", {}, 2)
    assert err and "missing" in text
    rows = con.execute("SELECT pass_id, turn, tool, status FROM hq_tool_calls ORDER BY call_no").fetchall()
    assert [r[2:] for r in rows] == [("memory_recall", "ran"), ("memory_recall", "ran"), ("nope", "refused"), ("notes", "refused")]
    assert rows[0][:2] == (7, 1)


# --- per-stock facts ----------------------------------------------------------------------------------------------------

def test_drift_states_the_share_rule_cap_and_bands():
    bk = _book()
    c = pd.Series(np.linspace(100, 120, 300), index=pd.bdate_range(end="2026-10-23", periods=300))
    d = stocks.drift(bk, AAA, c)                     # 2 candidates: 40% / 2 = 20%, capped at 8%
    assert d["share_pct"] == 8.0 and d["weight_pct"] == 9.0 and d["gap_pct"] == 1.0 and d["over_cap"]
    assert d["gain_pct"] == 50.0 and d["bucket"]["state"] == "outside its hard band"      # 11% against 40% +-10
    assert d["trend"]["return_1y_pct"] == pytest.approx((120 / c.iloc[-251] - 1) * 100, abs=0.05)
    off = stocks.drift(bk, CCC, c)
    assert off["share_pct"] is None and "not on the stock list" in off["share_rule"]
    failing = stocks.drift(_book(guards={AAA: ("fail", ["debt"]), BBB: ("ok", [])}), AAA, c)
    assert failing["share_pct"] is None and "guard fail" in failing["share_rule"]
    none_checked = stocks.drift(_book(guards={}), BBB, c)
    assert none_checked["share_pct"] is None


def test_odds_count_moves_and_bootstrap_touches_with_their_n():
    c = pd.Series(_walk(800, 3, vol=0.02), index=pd.bdate_range(end="2026-10-23", periods=800))
    o = stocks.odds(_book(), AAA, c, paths=4000)
    m = o["moves_end_to_end"]["21_sessions"]
    r = (c.iloc[-750:].shift(-21) / c.iloc[-750:] - 1).dropna()
    assert m["up_share"] == pytest.approx(float((r >= 0.10).mean()), abs=1e-3) and m["independent"] == len(r) // 21
    assert "%" in m["up_10pct"]                                                    # 34 independent windows: a rate
    assert " of " in o["moves_end_to_end"]["63_sessions"]["up_10pct"]             # 10: a count only
    f21, f63 = o["falls_touch"]["21_sessions"], o["falls_touch"]["63_sessions"]
    assert set(f21) == {"touch_minus_5pct", "touch_minus_10pct", "touch_minus_20pct"}
    assert o["zone"]["verdict"] in ("IN ZONE", "ABOVE ZONE") and "computed_here" in o["zone"]
    from pflab.plan import buyzone as bz
    fallen = pd.Series(np.r_[np.linspace(100, 120, 300), [80.0]], index=pd.bdate_range(end="2026-10-23", periods=301))
    z = bz.zone(fallen, NOW.date(), paths=1000)
    assert z["verdict"] == "IN ZONE" and z["headline"].startswith("below its zone")    # under the bottom, said so
    short = stocks.odds(_book(), AAA, c.iloc[-100:], paths=1000)
    assert "too little history" in short["note"]


def test_edge_is_excess_over_the_index_after_costs_with_independent_n():
    idx = pd.Series(_walk(2100, 5, drift=0.0003), index=pd.bdate_range(end="2026-10-23", periods=2100))
    ahead = idx * np.exp(np.arange(2100) * 0.001)                                 # beats the index by ~0.1% a session
    e = stocks.edge(_book(), AAA, ahead, idx, order=50_000)
    q = e["63_sessions"]
    assert q["excess_mean_pct"] == pytest.approx((np.exp(0.063) * 1.0 - 1) * 100, abs=0.6)
    assert q["independent_windows"] >= 20 and q["worth_a_study"]
    assert q["excess_after_costs_pct"] == pytest.approx(q["excess_mean_pct"] - e["round_trip_cost_pct"], abs=0.02)
    assert 0.1 < e["round_trip_cost_pct"] < 0.5 and "not a forecast" in e["label"]
    assert not e["250_sessions"]["worth_a_study"]                                 # ~8 independent years: too few
    same = stocks.edge(_book(), AAA, idx * np.exp(np.random.default_rng(9).normal(0, 0.004, 2100).cumsum() * 0), idx)
    assert not same["63_sessions"]["worth_a_study"] and "no edge shown" in same["63_sessions"]["reading"]


# --- the loop -------------------------------------------------------------------------------------------------------------

def test_a_pass_looks_with_tools_records_in_shadow_and_checks_the_note(con, tmp_path, quiet_input, monkeypatch):
    monkeypatch.setattr(brain, "SHADOW", True)
    rt = _desk(con, tmp_path)
    _prices(con, AAA, _walk(900, 1))
    replies = [_tool_msg(("memory_recall", {"words": "anything"}), ("research_flags", {"days": 7})),
               _tool_msg(("order_research", {"symbol": "AAA", "question": "What did the results say?"}),
                         ("record_prediction", {"symbol": "AAA", "kind": "return_above", "level": 3, "due": "2026-11-25",
                                                "confidence": 0.55, "claim": "AAA up 3% by 25 Nov"}),
                         ("record_suggestion", {"kind": "hold", "symbol": "AAA", "text": "Keep AAA.",
                                                "reasoning": "Nothing against holding.", "horizon_days": 30,
                                                "rested_on": ["research_flags"]})),
               _note_msg("AAA is 9.0% of the portfolio. It will rise 37% soon. Research ordered.")]
    c = Fake(replies)
    pid = brain.think(rt, "asked", [], c, egress.Gate(), cfg=CFG)
    j = brain.journal(con)[0]
    assert j["id"] == pid and j["status"] == "done" and "9.0%" in j["note"] and "37%" not in j["note"]
    assert [d["action"] for d in j["decisions"]] == ["investigate"] and j["decisions"][0]["shadow"]
    assert con.execute("SELECT count(*) FROM hq_tasks").fetchone()[0] == 0           # shadow: nothing carried out
    assert [t["tool"] for t in j["tools"]] == ["memory_recall", "research_flags", "order_research", "record_prediction",
                                              "record_suggestion"]
    assert [t["status"] for t in j["tools"]][2] == "shadow"
    assert con.execute("SELECT pass_id, model FROM hq_predictions").fetchall() == [(pid, gv.OPUS)]
    s = sg.recent(con)[0]
    assert s["pass"] == pid and s["kind"] == "hold" and s["quality"] == "sound" and s["shadow"]
    calls = con.execute("SELECT agent, turn, status FROM api_calls ORDER BY call_id").fetchall()
    assert calls == [("brain", 1, "done"), ("brain", 2, "done"), ("brain", 3, "done")]
    assert gv.calls_today(con, "brain", NOW) == 1                                  # one pass, three turns
    sent = c.messages.sent
    assert all(m["tools"] and m["system"][0]["cache_control"] for m in sent)
    assert sent[0]["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert sent[1]["messages"][1]["content"][0]["type"] == "thinking"             # thinking blocks passed back
    assert [b["type"] for b in sent[1]["messages"][2]["content"]] == ["tool_result", "tool_result"]   # one message


def test_actions_are_carried_out_once_the_shadow_ends(con, tmp_path, quiet_input, monkeypatch):
    monkeypatch.setattr(brain, "SHADOW", False)
    rt = _desk(con, tmp_path)
    c = Fake([_tool_msg(("order_calculation", {"question": "Largest fall of AAA in 2024?"})), _note_msg("Ordered.")])
    brain.think(rt, "asked", [], c, egress.Gate(), cfg=CFG)
    assert con.execute("SELECT to_agent, from_agent, text FROM hq_tasks").fetchall() == [
        ("calc", "brain", "Largest fall of AAA in 2024?")]
    # the cheaper rival journals only: nothing happens twice
    r = Fake([_tool_msg(("order_calculation", {"question": "Largest fall of AAA in 2023?"})), _note_msg("Ordered.")])
    brain.think(rt, "asked", [], r, egress.Gate(), model=gv.SONNET, role="rival", cfg=CFG)
    assert con.execute("SELECT count(*) FROM hq_tasks").fetchone()[0] == 1
    assert brain.journal(con)[0]["tools"][0]["status"] == "shadow"


def test_actions_are_capped_a_day_and_the_rest_kept_in_the_journal(con, tmp_path, quiet_input, monkeypatch):
    monkeypatch.setattr(brain, "SHADOW", False)
    rt = _desk(con, tmp_path)
    ctx = tl.Ctx(rt, 1, gv.OPUS, False, {"AAA": AAA}, egress.Gate(), NOW, source="AAA")
    for k in range(tl.DAILY["order_research"] + 1):
        text, err = tl.run(ctx, "order_research", {"symbol": "AAA", "question": f"What changed, take {k}?"})
    assert not err and "limit" in text
    assert con.execute("SELECT count(*) FROM hq_tasks").fetchone()[0] == tl.DAILY["order_research"]
    st = [s for (s,) in con.execute("SELECT status FROM hq_tool_calls ORDER BY call_no").fetchall()]
    assert st == ["ran"] * tl.DAILY["order_research"] + ["held"] and "held" in ctx.decisions[-1]


def test_the_last_turn_has_no_tools_and_a_refused_turn_stops_the_pass(con, tmp_path, quiet_input):
    rt = _desk(con, tmp_path)
    loop = [_tool_msg(("journal", {})) for _ in range(brain.MAX_TURNS - 1)] + [_note_msg("Done looking.")]
    c = Fake(loop)
    brain.think(rt, "asked", [], c, egress.Gate(), cfg=CFG)
    sent = c.messages.sent
    assert len(sent) == brain.MAX_TURNS and sent[-1]["tool_choice"] == {"type": "none"}
    assert "last turn" in sent[-1]["messages"][-1]["content"][-1]["text"]
    assert brain.journal(con)[0]["note"] == "Done looking."
    con.execute("DELETE FROM api_calls")
    con.execute("UPDATE hq_passes SET passed_at = passed_at - INTERVAL 2 DAY")
    big = Fake([_tool_msg(("journal", {}))] * 3)
    cfg = {**CFG, "cap": 1.0}                                         # the layer's share refuses the second turn
    with pytest.MonkeyPatch.context() as m:
        m.setattr(gv, "cost_inr", lambda *a, **k: 0.3)
        pid = brain.think(rt, "asked", [], big, egress.Gate(), cfg=cfg)
    j = next(p for p in brain.journal(con) if p["id"] == pid)
    assert j["status"] == "done" and "stopped before turn 2" in j["error"]


def test_near_its_limit_the_brain_hands_off_to_a_fresh_context_and_the_next_pass_reads_it(con, tmp_path, quiet_input,
                                                                                          monkeypatch):
    monkeypatch.setitem(gv.LIMITS, "brain", gv.Limits("brain", 3000, 6000, {"off": 0, "economy": 4, "normal": 8}))
    rt = _desk(con, tmp_path)
    c = Fake([_tool_msg(("journal", {}), usage=(2000, 200)),
              _tool_msg(("save_state", {"state": "Looked at AAA; next: BBB's results."})),
              _tool_msg(("research_flags", {})), _note_msg("Carried on from the state.")])
    brain.think(rt, "asked", [], c, egress.Gate(), cfg=CFG)
    sent = c.messages.sent
    assert "near its limit" in sent[1]["messages"][-1]["content"][-1]["text"]
    assert len(sent[2]["messages"]) == 1 and "YOUR WORKING STATE" in sent[2]["messages"][0]["content"][1]["text"]
    assert brain.journal(con)[0]["note"] == "Carried on from the state."
    st = mem.recall(con, kinds=["state"], asof=NOW.date())
    assert len(st) == 1 and st[0].subject == f"brain:{gv.OPUS}"
    _, change, _ = brain.build_input(con, NOW.date(), "morning", [], gv.OPUS)
    assert "YOUR LAST WORKING STATE" in change and "BBB's results" in change
    # without a save, code writes the state itself; the new one supersedes the last
    c2 = Fake([_tool_msg(("journal", {}), usage=(2000, 200)), _tool_msg(("research_flags", {})), _note_msg("ok")])
    brain.think(rt, "asked", [], c2, egress.Gate(), cfg=CFG)
    st = mem.recall(con, kinds=["state"], asof=NOW.date(), include_past=True)
    assert len(st) == 2 and st[0].text.startswith("Tools read this pass") and st[1].valid_to is not None


def test_governor_counts_passes_not_turns(con):
    for k, turn in enumerate([1, 2, 3, 1, 2]):
        con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, "
                    "cost_inr, agent, turn) VALUES (?,?,?,?,?,?,?,?,?,?,?)", [k + 1, NOW, "live", gv.OPUS, "q", "", "{}",
                                                                              "done", 1.0, "brain", turn])
    assert gv.calls_today(con, "brain", NOW) == 2
    for k in range(2):
        con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, question, request_sha, request_json, status, "
                    "cost_inr, agent, turn) VALUES (?,?,?,?,?,?,?,?,?,?,?)", [10 + k, NOW, "live", gv.OPUS, "q", "", "{}",
                                                                              "done", 1.0, "brain", 1])
    with pytest.raises(gv.BudgetRefused, match="4 calls today"):
        gv.check(con, "brain", 1.0, 100, 100, NOW, "economy", CFG)
    assert gv.check(con, "brain", 1.0, 100, 100, NOW, "economy", CFG, turn=3) == []      # a pass already admitted
    with pytest.raises(gv.BudgetRefused, match="input tokens"):
        gv.check(con, "brain", 1.0, 99_000, 100, NOW, "economy", CFG, turn=3)          # every other limit per turn


# --- the suggestion ledger --------------------------------------------------------------------------------------------------

def test_quality_is_judged_from_the_facts_at_the_time():
    ok = {"guard": "ok", "drift": {"share_rule": "equal share of ...", "gap_pct": -2.0, "over_cap": False, "held": True}}
    assert sg.quality("add", ok)[0] == "sound"
    assert sg.quality("add", {**ok, "guard": "fail"})[0] == "unsound"
    assert sg.quality("add", {"guard": "ok", "drift": {**ok["drift"], "gap_pct": 1.0}})[0] == "weak"
    assert sg.quality("trim", {"guard": "ok", "drift": {**ok["drift"], "held": False}})[0] == "unsound"
    assert sg.quality("wait", ok)[0] == "weak" and "PLAN A12" in sg.quality("wait", ok)[1]


def test_suggestions_scored_against_the_index_taken_or_declined(con):
    idx = _prices(con, CCC, np.full(60, 100.0), end=date(2026, 12, 31))           # a flat index (its own series here)
    index = pd.Series(idx.values, index=idx.index)
    s = _prices(con, AAA, np.r_[np.full(30, 100.0), np.full(30, 110.0)], end=date(2026, 12, 31))
    ref = (s.index[10].date(), 100.0)
    made = datetime.combine(s.index[10].date(), datetime.min.time()) + timedelta(hours=10)
    kw = dict(pass_id=1, model=gv.OPUS, isin=AAA, symbol="AAA", reasoning="r", data={}, horizon_days=30, now=made,
              shadow=True, ref=ref, ref_qty=10.0)
    a = sg.record(con, kind="add", text="Add AAA.", facts={"guard": "ok", "drift": {"share_rule": "equal share", "gap_pct": -1}}, **kw)
    t = sg.record(con, kind="trim", text="Trim AAA.", **kw)
    w = sg.record(con, kind="wait", text="Wait on AAA.", **kw)
    r = sg.record(con, kind="review", text="Review the mix.", **{**kw, "isin": None, "symbol": None})
    sg.answer(con, t, "declined", made)
    with pytest.raises(ValueError):
        sg.answer(con, a, "maybe", made)
    later = made + timedelta(days=31)
    assert sg.score_due(con, made + timedelta(days=5), index, qty_fn=lambda i: 10.0) == 0     # not yet due
    assert sg.score_due(con, later, index, qty_fn=lambda i: 15.0) == 4
    got = {x["id"]: x for x in sg.recent(con)}
    assert got[a]["outcome"] == "good" and got[a]["answer"] == "taken" and got[a]["answer_source"] == "portfolio"
    assert got[t]["outcome"] == "bad" and got[t]["answer"] == "declined"           # scored on paper
    assert got[w]["outcome"] == "bad" and got[r]["outcome"] == "n/a"
    assert got[a]["outcome_json"]["excess_pct"] == pytest.approx(10.0) and got[a]["outcome_json"]["nifty500_pct"] == 0
    rec = sg.record_table(con)
    assert rec["kinds"]["add"]["rate"] == "1 of 1" and rec["luck"]["sound_good"] == 1 and rec["luck"]["weak_bad"] == 1
    text = sg.lessons_text(con, gv.OPUS)
    assert "1 of 1" in text and "never retire" in text and "add AAA: good" in text


# --- memory that updates ----------------------------------------------------------------------------------------------------

def test_a_correction_keeps_the_old_row_and_the_reason(con):
    old = mem.remember(con, "decision", "no more AAA this year", subject="AAA", now=NOW)
    new = mem.correct(con, old, "no more AAA until March", "he said March on 26 Oct", by="brain pass #3", now=NOW)
    rows = mem.recall(con, subject="AAA", asof=NOW.date(), include_past=True)
    assert {m.mem_id: m.kind for m in rows}[new] == "decision"
    assert next(m for m in rows if m.mem_id == old).valid_to is not None
    assert any(m.kind == "reason" and f"#{new} corrects #{old}" in m.text for m in rows)
    with pytest.raises(ValueError):
        mem.correct(con, new, "x", " ", by="b", now=NOW)


def test_decisions_get_their_outcome_written_back_once(con):
    _prices(con, AAA, np.r_[np.full(40, 100.0), np.full(20, 92.0)], end=NOW.date())
    mem.remember(con, "decision", "hold AAA through results", subject="AAA", now=NOW - timedelta(days=45))
    assert keeper.write_outcomes(con, NOW) == 1 and keeper.write_outcomes(con, NOW) == 0
    o = mem.recall(con, kinds=["outcome"], asof=NOW.date())
    assert o[0].subject == "AAA" and "-8.0%" in o[0].text


# --- redaction ----------------------------------------------------------------------------------------------------------------

STATEMENT = """Statement of account for TESTNAME KUMAR
Address: Flat 4, Example Road, Sometown 400001
PAN: ABCDE1234F   Email: test.name@example.com   Mobile: 9876543210
A/c No: 50100123456789   IFSC: HDFC0001234   UPI: testname@okhdfc
Folio No 12345678/90   DP ID IN30012345678901   Client ID 1234567
Date        Description                 Amount     Balance
01-10-2026  SIP AXIS BLUECHIP FUND       5,000.00   1,23,456.78
02-10-2026  NEFT FROM SB12345678        25,000.00   1,48,456.78"""


def test_redact_replaces_identity_and_keeps_the_transactions(tmp_path):
    gate = egress.Gate(ids={"SB12345678"}, names=["testname"])
    with pytest.raises(egress.EgressBlocked):
        egress.check(STATEMENT, gate)
    out, counts = redact.for_api(STATEMENT, gate, address=[])
    for gone in ("ABCDE1234F", "test.name@example.com", "9876543210", "50100123456789", "HDFC0001234", "okhdfc",
                 "12345678/90", "IN30012345678901", "1234567", "SB12345678", "Example Road", "TESTNAME"):
        assert gone not in out, gone
    assert "SIP AXIS BLUECHIP FUND" in out and "5,000.00" in out and "1,23,456.78" in out and "01-10-2026" in out
    assert out.count("[ACCOUNT-") >= 4 and "[PAN]" in out and "[ADDR]" in out and "[NAME]" in out
    assert counts["PAN"] == 1 and counts["his name"] == 1 and counts["address"] == 1
    same = redact.redact("again SB12345678 and SB12345678", gate, address=[])[0]
    assert same == "again [ACCOUNT-1] and [ACCOUNT-1]"
    assert redact.redact("Lives at Plot 9 Greenview", gate, address=["greenview"])[0] == "[ADDR]"
    block = "Mr Test\nFlat 4, Sunrise Apartments\nNear Old Temple Road\nSometown 400001\n\nDate Amount\n01-10-2026 5,000.00"
    out, counts = redact.redact(block, gate, address=[])
    assert out.split("\n")[1:4] == ["[ADDR]"] * 3 and counts["address"] == 3 and "5,000.00" in out
    # a tool's one-line JSON: a filing's registered office is not his address; his own address words still go
    js = '{"title": "Change of registered address, 12 MG Road", "url": "https://x/400001.pdf", "note": "near Greenview"}'
    out, _ = redact.redact(js, gate, address=["greenview"], lines=False)
    assert "MG Road" in out and "400001" in out and "Greenview" not in out
    egress.check(out, gate, skip=("address",))
    with pytest.raises(egress.EgressBlocked, match="his address"):            # his own words block any call
        egress.check("meet near Greenview", egress.Gate(address=["greenview"]))
    assert redact.redact("near Greenview", egress.Gate(address=["greenview"]))[0] == "[ADDR]"   # read from the gate


def test_his_address_words_come_from_his_statements_not_from_common_words(tmp_path):
    gate = egress.Gate(names=["testname kumar"])
    st1 = "Statement\nTESTNAME KUMAR\nFlat 4, Sunrise Apartments\nNear Banyan Lane, Mumbai 400001\nDate Amount"
    st2 = "CAS\nMr TESTNAME KUMAR\nSunrise Apartments, Banyan Lane\nMumbai 400001\nISIN Qty"
    st3 = "Broker\nOffice: Kamath House, Some Road, Bengaluru 560001\nTESTNAME KUMAR\nClient code"
    words = redact.address_from([st1, st2, st3], gate, common={"mumbai"})
    assert words == ["banyan", "sunrise"]                        # repeated, rare; not 'mumbai', not road vocabulary
    p = tmp_path / "api_budget.toml"
    p.write_text('[budget]\ncap = 2500\n\n[egress]\nnames = ["testname kumar"]\n', encoding="utf-8")
    redact.write_address(p, words)
    redact.write_address(p, words)                               # replaced, not added twice
    text = p.read_text(encoding="utf-8")
    assert text.count("address = ") == 1 and "cap = 2500" in text and 'names = ["testname kumar"]' in text
    assert egress.names(p, "address", 3) == ["banyan", "sunrise"]


def test_filing_texts_are_kept_for_my_names_newest_first(con, monkeypatch, tmp_path):
    from pflab.hq import readers
    from pflab.kg import graph as g
    for k, (isin, days) in enumerate([(AAA, 1), (AAA, 30), (BBB, 2), (CCC, 1), (AAA, 200)]):
        d = g.doc(con, "filing", f"f{k}", NOW - timedelta(days=days), f"filing {k}", url=f"https://www.bseindia.com/{k}.pdf",
                  now=NOW)
        g.edge(con, d, "about", f"company:{isin}", NOW, "test")
    got = []

    def fake(con_, row, out_dir, get=None):
        got.append(row["url"])
        con_.execute("UPDATE kg_docs SET text_status='ok' WHERE doc_id=?", [row["doc_id"]])
        return "text"
    monkeypatch.setattr(readers, "fetch_filing_text", fake)
    rep = readers.keep_texts(con, [AAA], [BBB], tmp_path, NOW, limit=2, pause=0)
    assert got == ["https://www.bseindia.com/0.pdf", "https://www.bseindia.com/2.pdf"] and rep == {"kept": 2, "failed": 0, "left": 1}
    readers.keep_texts(con, [AAA], [BBB], tmp_path, NOW, pause=0)
    assert got[-1] == "https://www.bseindia.com/1.pdf" and len(got) == 3        # CCC not mine; 200 days too old


# --- cited-page fetch ---------------------------------------------------------------------------------------------------------

def test_fetch_reads_only_a_cited_page_and_keeps_only_its_numbers(con, tmp_path):
    from pflab.kg import graph as g
    g.doc(con, "analyst_note", "api-call-1", NOW - timedelta(days=2), "AAA results",
          attrs={"answer": "Revenue rose [W1].\n\nSources:\n[W1] AAA Q2 - https://news.example.in/aaa-q2-results"}, now=NOW)
    assert "https://news.example.in/aaa-q2-results" in fetch.cited_urls(con, NOW)
    with pytest.raises(ValueError, match="cites"):
        fetch.run(con, "https://example.com/other", "q", Fake(), egress.Gate(), NOW, "economy", CFG)
    page = SimpleNamespace(type="web_fetch_tool_result", content=SimpleNamespace(
        type="web_fetch_result", content=SimpleNamespace(type="document", source=SimpleNamespace(
            type="text", media_type="text/plain", data="Revenue 1,234 crore; margin 18.2%."))))
    msg = SimpleNamespace(content=[page, SimpleNamespace(type="text", text="Revenue was 1,234 crore. Profit grew 40%.")],
                          stop_reason="end_turn", model=gv.SONNET,
                          usage=SimpleNamespace(input_tokens=5000, output_tokens=100, cache_read_input_tokens=0,
                                                cache_creation_input_tokens=0))
    c = Fake([msg])
    out = fetch.run(con, "https://news.example.in/aaa-q2-results", "What was revenue?", c, egress.Gate(), NOW, "economy", CFG)
    assert "1,234 crore" in out["text"] and "40%" not in out["text"] and out["dropped"] == 1
    sent = c.messages.sent[0]
    assert sent["model"] == gv.SONNET and sent["tools"][0]["type"] == fetch.TOOL
    assert sent["tools"][0]["allowed_domains"] == ["news.example.in"] and sent["tools"][0]["max_uses"] == 1
    row = con.execute("SELECT agent, cost_inr FROM api_calls").fetchone()
    assert row[0] == "fetch"
    # BSE refuses the fetcher: the readers' local copy of a filing is read instead, and the answer says so
    txt = tmp_path / "f.txt"
    txt.write_text("[page 1]\nOrder book 4,321 crore.", encoding="utf-8")
    d = g.doc(con, "filing", "f1", NOW - timedelta(days=1), "Order win", url="https://www.bseindia.com/a/f1.pdf", now=NOW)
    con.execute("UPDATE kg_docs SET text_path=? WHERE doc_id=?", [str(txt), d])
    refused = SimpleNamespace(content=[SimpleNamespace(type="web_fetch_tool_result", content=SimpleNamespace(
        type="web_fetch_tool_result_error", error_code="url_not_accessible"))], stop_reason="end_turn", model=gv.SONNET,
        usage=SimpleNamespace(input_tokens=900, output_tokens=40, cache_read_input_tokens=0, cache_creation_input_tokens=0))
    read = SimpleNamespace(content=[SimpleNamespace(type="text", text="The order book is 4,321 crore.")], stop_reason="end_turn",
                           model=gv.SONNET, usage=refused.usage)
    c2 = Fake([read])                                                               # BSE: straight to the local copy
    out = fetch.run(con, "https://www.bseindia.com/a/f1.pdf", "Order book?", c2, egress.Gate(), NOW, "economy", CFG)
    assert "4,321 crore" in out["text"] and "refuses" in out["how"] and len(c2.messages.sent) == 1
    assert "tools" not in c2.messages.sent[0] and "Order book 4,321" in c2.messages.sent[0]["messages"][0]["content"]
    d2 = g.doc(con, "filing", "f2", NOW - timedelta(days=1), "Order win", url="https://archives.example.in/f2.pdf", now=NOW)
    con.execute("UPDATE kg_docs SET text_path=? WHERE doc_id=?", [str(txt), d2])
    c3 = Fake([refused, read])                                                      # another site refuses: then local
    out = fetch.run(con, "https://archives.example.in/f2.pdf", "Order book?", c3, egress.Gate(), NOW, "economy", CFG)
    assert "url_not_accessible" in out["how"] and len(c3.messages.sent) == 2 and "4,321 crore" in out["text"]
    est = gv.cost_inr(gv.SONNET, 1000 + fetch.CONTENT_CAP, gv.LIMITS["fetch"].max_out, 90.0)
    assert est > gv.cost_inr(gv.SONNET, 1000, gv.LIMITS["fetch"].max_out, 90.0)    # priced with the page at its cap
