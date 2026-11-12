"""S84 T10: the daily desk (`think/desk.py`). A scripted model and fake neighbours stand in (rule 7: synthetic, no paid call)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from pflab.lab import strategist
from pflab.pm import store
from pflab.think import cases, desk

NOW = datetime(2026, 11, 12, 17, 0)              # a Thursday, after the Indian close
AAA, BBB = "INE000A01011", "INE000B01012"


class Model:
    """A scripted gateway: one answer per role, a fixed cost, every call recorded."""
    def __init__(self, cost=10.0, answers=None):
        self.cost, self.calls, self.answers = cost, [], answers or {}

    def __call__(self, con, role, system, messages, **kw):
        self.calls.append({"role": role, "purpose": kw.get("purpose"), "case_id": kw.get("case_id"), "text": messages[0]["content"]})
        a = self.answers.get(kw.get("purpose")) or self.answers.get(role) or {"finding": "Nothing here changes the plan.", "needs_decision": "none", "next_step": "Look again after the next close."}
        return {"text": json.dumps(a), "json": a, "tool_calls": [], "cost_rupees": self.cost, "cached_tokens": 500, "engine": "anthropic", "model": "sonnet" if role != "decide" else "opus",
                "thinking": "medium" if role != "decide" else "high"}


@pytest.fixture
def con(tmp_path, monkeypatch):
    c = store.connect(tmp_path / "t.duckdb")
    monkeypatch.setattr(desk, "call_fn", None)
    monkeypatch.setattr(desk, "modules", {})
    monkeypatch.setattr(desk, "cap_left", lambda con, now: 1000.0)
    monkeypatch.setattr(desk, "_market_open_day", lambda m, d: True)
    monkeypatch.setattr(desk, "_scope", lambda con, day, market=None: [])
    monkeypatch.setattr(desk, "_events_since", lambda con, isins, t0, now: {})
    monkeypatch.setattr(desk, "_sleeve_room", lambda con, m, d: None)
    monkeypatch.setattr(desk, "_picks_by_isin", lambda con, d: {})
    monkeypatch.setattr(desk, "scorecard_text", lambda con, d: "India picks: nothing has been scored yet.")
    return c


def with_model(monkeypatch, **kw):
    m = Model(**kw)
    monkeypatch.setattr(desk, "call_fn", m)
    return m


def a_case(con, sym="AAA", isin=AAA, pct=0.03, look=date(2026, 11, 12), score=2.0):
    cid = cases.open_case(con, NOW - timedelta(days=2), market="IN", kind="move", isin=isin, symbol=sym, title=f"{sym} fell sharply", exposure_inr=30000, exposure_pct=pct, score=score)
    cases.set_case(con, cid, state="waiting", klass="unclear", pending="the board's decision", next_look_on=look)
    return cid


def a_holding(con, monkeypatch, isin=AAA, sym="AAA", events=True):
    monkeypatch.setattr(desk, "_scope", lambda con, day, market=None: [{"name": sym, "isin": isin, "symbol": sym, "market": "IN", "exposure_inr": 50000.0, "exposure_pct": 0.05, "why": "held"}])
    if events:
        monkeypatch.setattr(desk, "_events_since", lambda con, isins, t0, now: {isin: [{"isin": isin, "kind": "leadership_crisis", "severity": "high", "ts": NOW - timedelta(hours=5),
                                                                                    "text": "the chief executive is on leave pending a board inquiry"}]})
    else:
        cases.record_signal(con, NOW - timedelta(hours=3), market="IN", isin=isin, symbol=sym, signal="move_1d", value=-0.04, threshold=0.03, surprise=1.4, exposure_inr=50000, score=1.0)


# --- a quiet day, a busy day, the budget ------------------------------------------------------------------------------------------------------------------------------------------

def test_a_quiet_day_costs_nothing_and_is_a_two_line_note(con, monkeypatch):
    m = with_model(monkeypatch)
    assert desk.agenda(con, NOW, "india_close") == [] and desk.due(con, NOW) == []
    r = desk.run_desk(con, NOW, "india_close")
    assert r["status"] == "quiet" and r["cost_rupees"] == 0.0 and m.calls == []
    assert len(r["plan"].splitlines()) == 2 and "quiet day" in r["plan"]
    assert desk.plan_text(con, NOW.date()) == r["plan"]
    assert desk.run_desk(con, NOW, "india_close")["skipped"].endswith("already ran")                 # a slot is worked once a day


def test_a_busy_day_works_the_agenda_in_order_and_stops_at_its_budget(con, monkeypatch):
    m = with_model(monkeypatch, cost=10.0)
    a_case(con, pct=0.01)                                                                    # under the 2% line: only read
    a_holding(con, monkeypatch, isin=BBB, sym="BBB")
    cases.record_signal(con, NOW, market="IN", isin=BBB, symbol="BBB", signal="move_1d", value=-0.05, threshold=0.03, surprise=2.0, exposure_inr=1, score=1.0)
    con.execute("INSERT INTO storylines_s80 (storyline_id, market, claim, kind, direction, subject, opened_on, status, prior, probability, updated_at) VALUES (1,'IN','crude stays high','x',1,'s',?, 'open',0.5,0.8,?)",
                [NOW.date(), NOW])
    monkeypatch.setattr(desk, "settings", lambda: {**desk.DEFAULTS, "daily_budget_rupees": 25.0})
    kinds = [i["kind"] for i in desk.agenda(con, NOW, "india_close")]
    assert kinds == ["case", "holding", "storyline"]                                         # cases, then holdings, then storylines
    r = desk.run_desk(con, NOW, "india_close")
    st = desk.steps(con, r["session_id"])
    assert [s["status"] for s in st] == ["done", "done", "done"] and r["status"] == "budget"        # 10 + 10 = 20 < 25: the third still runs; 30 > 25 ends the day
    assert r["cost_rupees"] == 30.0 and [c["role"] for c in m.calls] == ["read"] * 3
    assert st[0]["model"] == "sonnet" and st[0]["thinking"] == "medium" and st[0]["cached_tokens"] == 500
    # the day's budget is shared by the slots of the day: a second session the same day does not start work
    r2 = desk.run_desk(con, NOW.replace(hour=9), "us_morning")
    assert r2["status"] in ("quiet", "budget", "skipped")
    assert desk.budget_status(con, NOW.date())["left"] == 0.0


def test_the_budget_stops_the_agenda_midway_and_says_what_was_not_reached(con, monkeypatch):
    m = with_model(monkeypatch, cost=20.0)
    a_case(con, pct=0.01)
    a_holding(con, monkeypatch, isin=BBB, sym="BBB")
    monkeypatch.setattr(desk, "settings", lambda: {**desk.DEFAULTS, "daily_budget_rupees": 15.0})
    r = desk.run_desk(con, NOW, "india_close")
    st = desk.steps(con, r["session_id"])
    assert [s["status"] for s in st] == ["done", "not_reached"] and len(m.calls) == 1 and r["status"] == "budget"
    assert "Stopped early" in r["plan"] and "not reached" in r["plan"]


def test_his_cap_with_no_room_stops_the_desk_and_a_failed_call_does_not_stop_the_rest(con, monkeypatch):
    m = with_model(monkeypatch)
    a_case(con, pct=0.01)
    monkeypatch.setattr(desk, "cap_left", lambda con, now: 0.0)
    r = desk.run_desk(con, NOW, "india_close")
    assert r["status"] == "budget" and m.calls == [] and "cap" in r["stopped"]
    # a failing model call is recorded and the next item goes on
    monkeypatch.setattr(desk, "cap_left", lambda con, now: 100.0)
    n = {"i": 0}

    def flaky(con, role, system, messages, **kw):
        n["i"] += 1
        if n["i"] == 1:
            raise RuntimeError("the vendor is down")
        return Model()(con, role, system, messages, **kw)
    monkeypatch.setattr(desk, "call_fn", flaky)
    a_holding(con, monkeypatch, isin=BBB, sym="BBB")
    r = desk.run_desk(con, NOW + timedelta(days=1), "catchup", covers="india_close")
    assert [s["status"] for s in desk.steps(con, r["session_id"])] == ["failed", "done"]


# --- the weekly review, the catch-up -----------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_weekly_review_still_runs_once_a_week_and_the_desk_never_starts_it(con, monkeypatch, tmp_path):
    from tests.test_s82_fills import _api_cfg
    from pflab.agents import analyst as an
    monkeypatch.setattr(an, "config", lambda path=None: _api_cfg())
    with_model(monkeypatch)
    ran = {"n": 0}

    def fake_run(con, pm_dir, root, now, reason, *, client, **kw):
        ran["n"] += 1
        sid = con.execute("SELECT coalesce(max(session_id),0)+1 FROM core_sessions_s80").fetchone()[0]
        con.execute("INSERT INTO core_sessions_s80 (session_id, started_at, reason, status, model, budget_inr, cost_inr, lab_runs, variants, challengers) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [sid, now_of(), reason[:300], "done", "claude-opus-5-5", 300.0, 12.5, 1, 1, 0])
        return {"session_id": sid, "status": "done", "cost_inr": 12.5, "lab_runs": 1}
    stamp = {"t": NOW}
    now_of = lambda: stamp["t"]
    monkeypatch.setattr(strategist, "run_session", fake_run)
    from pflab.lab import first_session_s82 as first
    monkeypatch.setattr(first, "reasons", lambda con, now: [])
    a = strategist.tick(con, tmp_path, tmp_path, NOW, lambda: object(), data={}, box=None)
    assert ran["n"] == 1 and "desk" in a and a["desk"].get("status") in ("quiet", "done")
    stamp["t"] = NOW + timedelta(days=1)
    b = strategist.tick(con, tmp_path, tmp_path, NOW + timedelta(days=1), lambda: object(), data={}, box=None)
    assert ran["n"] == 1 and b.get("nothing_due") and "desk" in b                         # the weekly session did not run again; the desk keeps its own day
    assert not any("desk" in (r or "") for r in strategist.due(con, NOW + timedelta(days=2)))


def test_a_day_off_is_caught_up_in_one_session_not_one_per_missed_day(con, monkeypatch):
    m = with_model(monkeypatch)
    a_holding(con, monkeypatch)
    con.execute("INSERT INTO desk_sessions_s84 VALUES (1, ?, 'india_close', 'india_close', ?, ?, ?, 'done', 0, 30, '[]', 'x', '')", [date(2026, 11, 8), datetime(2026, 11, 8, 17), datetime(2026, 11, 8, 17), datetime(2026, 11, 8, 16)])
    mode, covers = desk.mode_for(con, NOW)
    assert mode == "catchup" and covers == "us_morning,india_close"
    desk.tick_hook(con, NOW)
    rows = con.execute("SELECT mode, covers, since_at FROM desk_sessions_s84 WHERE session_id > 1").fetchall()
    assert len(rows) == 1 and rows[0][0] == "catchup" and rows[0][2] == datetime(2026, 11, 8, 17)           # ONE session, covering everything since the last one
    assert desk.mode_for(con, NOW) is None and desk.tick_hook(con, NOW + timedelta(minutes=5)).get("nothing_open")
    assert len(m.calls) == 1


def test_one_session_after_the_close_and_one_in_the_us_morning(con, monkeypatch):
    with_model(monkeypatch)
    con.execute("INSERT INTO desk_sessions_s84 VALUES (1, ?, 'india_close', 'india_close', ?, ?, ?, 'done', 0, 30, '[]', 'x', '')", [date(2026, 11, 11), datetime(2026, 11, 11, 17), datetime(2026, 11, 11, 17), datetime(2026, 11, 11, 16)])
    assert desk.pending_slots(con, NOW.replace(hour=8)) == ["us_morning"] and desk.pending_slots(con, NOW.replace(hour=6)) == []
    assert desk.mode_for(con, NOW.replace(hour=8)) == ("us_morning", "us_morning")
    desk.run_desk(con, NOW.replace(hour=8), "us_morning")
    assert desk.pending_slots(con, NOW.replace(hour=9)) == [] and desk.pending_slots(con, NOW.replace(hour=15, minute=50)) == ["india_close"]
    monkeypatch.setattr(desk, "_market_open_day", lambda m, d: False)                       # a holiday: no slot
    assert desk.pending_slots(con, NOW.replace(day=14)) == []


# --- spending follows results --------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_budget_halves_from_the_a55_date_while_the_decisions_are_behind_doing_nothing(con, monkeypatch):
    behind = SimpleNamespace(scorecard=lambda con: {"scored": 20, "vs_nothing_inr": -5000.0})
    ahead = SimpleNamespace(scorecard=lambda con: {"scored": 20, "vs_nothing_inr": 5000.0})
    few = SimpleNamespace(scorecard=lambda con: {"scored": 12, "vs_nothing_inr": -5000.0})
    desk.modules["score"] = behind
    early, late = date(2026, 11, 20), date(2026, 12, 10)
    b = desk.budget_status(con, early)
    assert b["budget"] == 30.0 and b["behind"] and not b["halved"] and "recorded, not applied" in b["why"]       # A55: function first
    b = desk.budget_status(con, late)
    assert b["budget"] == 15.0 and b["halved"] and "spending follows results" in b["why"]
    desk.modules["score"] = ahead
    assert desk.budget_status(con, late)["budget"] == 30.0 and not desk.budget_status(con, late)["halved"]
    desk.modules["score"] = few
    assert desk.budget_status(con, late)["budget"] == 30.0                                    # under 20 scored: no verdict yet
    desk.modules.pop("score")
    assert desk.budget_status(con, late)["budget"] == 30.0


def test_the_cost_line_says_rupees_per_decision_that_beat_doing_nothing(con):
    assert "no decision has been scored yet" in desk.cost_line(con, NOW)
    con.execute("INSERT INTO desk_sessions_s84 VALUES (1, ?, 'india_close', 'india_close', ?, ?, ?, 'done', 40, 30, '[]', 'x', '')", [NOW.date(), NOW, NOW, NOW])
    con.execute("INSERT INTO desk_steps_s84 VALUES (1, 1, 1, 'case', 'case:1', 'IN', 'AAA', ?, 'a', 'sonnet', 'low', 40, 0, 'done', 'x')", [NOW])
    cid = a_case(con)
    did = cases.record_decision(con, cid, NOW.date(), isin=AAA, symbol="AAA", rule_option="sell", model_option="sell", acted_option="sell")
    con.execute("INSERT INTO think_scores_s84 VALUES (1, ?, 5, 'rule', 'sell', 100, 100, ?)", [did, NOW.date()])
    con.execute("INSERT INTO think_scores_s84 VALUES (2, ?, 20, 'rule', 'sell', -50, -50, ?)", [did, NOW.date()])
    assert "none of 1 scored" not in desk.cost_line(con, NOW) and "Rs 40 for each of the 1 decision" in desk.cost_line(con, NOW)


# --- knowledge: never pay twice, write back, mark used, rule 8 -------------------------------------------------------------------------------------------------------------------------

class Recall:
    def __init__(self, fresh=None):
        self.fresh, self.used, self.written = fresh, [], []

    def recall(self, con, now, **kw):
        it = {"kind": "analyst_note", "id": 7, "day": "2026-11-01", "source": "analyst", "title": "BBB note", "text": "an earlier read of the name"}
        return {"items": [it], "text": "an earlier read of the name (analyst note 2026-11-01)", "n": 1}

    def mark_used(self, con, items, *, by_kind, by_ref, day):
        self.used.append((by_kind, by_ref, len(items)))

    def same_subject_fresh(self, con, now, **kw):
        return self.fresh

    def write_back(self, con, now, **kw):
        self.written.append(kw)
        return 1


def test_a_fresh_note_on_an_unchanged_subject_is_used_not_bought_again(con, monkeypatch):
    m = with_model(monkeypatch)
    a_holding(con, monkeypatch, events=False)                                                # a move signal, no new event
    rc = Recall(fresh={"id": 7, "title": "BBB note", "day": "2026-11-10"})
    desk.modules["recall"] = rc
    r = desk.run_desk(con, NOW, "india_close")
    st = desk.steps(con, r["session_id"])
    assert m.calls == [] and r["cost_rupees"] == 0.0 and st[0]["status"] == "used" and "note already held" in st[0]["finding"] and rc.used == [("desk", str(st[0]["step_id"]), 1)]


def test_what_the_desk_reads_is_recalled_marked_used_and_what_it_finds_is_written_back(con, monkeypatch):
    m = with_model(monkeypatch)
    a_holding(con, monkeypatch)                                                              # an event: a read is due
    rc = Recall()
    desk.modules["recall"] = rc
    r = desk.run_desk(con, NOW, "india_close")
    assert "WHAT WE ALREADY KNOW" in m.calls[0]["text"] and "analyst note 2026-11-01" in m.calls[0]["text"]
    assert rc.used and rc.used[0][0] == "desk" and rc.written and rc.written[0]["source"] == "desk" and rc.written[0]["symbol"] == "AAA" and rc.written[0]["cost_rupees"] == 10.0


def test_a_model_sentence_with_a_number_not_in_the_facts_is_dropped(con, monkeypatch):
    with_model(monkeypatch, answers={"read": {"finding": "It will fall 40% more by Friday.", "needs_decision": "none", "next_step": "Look again."}})
    a_holding(con, monkeypatch)
    r = desk.run_desk(con, NOW, "india_close")
    f = desk.steps(con, r["session_id"])[0]["finding"]
    assert "40%" not in f and "leadership crisis" in f                                       # replaced by the code's own line from the facts
    assert desk.sourced("About 5.0% of the book.", "AAA, about 5.0% of the book") and not desk.sourced("About 9% of the book", "about 5.0% of the book")


# --- decisions: a withdrawal, the idea search ---------------------------------------------------------------------------------------------------------------------------------------------

class Tools:
    def __init__(self):
        self.calls = []

    def run(self, ctx, name, args):
        self.calls.append((name, args))
        if name == "propose_picks":
            return json.dumps({"ok": True, "accepted": [{"symbol": i["symbol"]} for i in args["items"]], "refused": []}), False
        return json.dumps({"ok": True, "held": False}), False


def test_a_broken_pick_goes_to_opus_and_a_withdrawal_goes_through_the_tool(con, monkeypatch):
    from pflab.lab import tools
    t = Tools()
    monkeypatch.setattr(tools, "run", t.run)
    m = with_model(monkeypatch, answers={"read": {"finding": "The event breaks the pick's thesis.", "needs_decision": "withdrawal", "next_step": "Decide."},
                                         "decide": {"action": "withdraw", "reason": "The chief executive is on leave pending a board inquiry, so the governance thesis is broken."}})
    a_holding(con, monkeypatch)
    monkeypatch.setattr(desk, "_picks_by_isin", lambda con, d: {AAA: {"symbol": "AAA", "isin": AAA, "market": "IN", "thesis": "a clean governance record and steady margins", "break_condition": "a governance event"}})
    r = desk.run_desk(con, NOW, "india_close")
    assert [c["role"] for c in m.calls] == ["read", "decide"] and t.calls[0][0] == "withdraw_pick" and t.calls[0][1]["symbol"] == "AAA" and len(t.calls[0][1]["reason"]) >= 20
    assert [s["status"] for s in desk.steps(con, r["session_id"])] == ["done", "done"] and desk.steps(con, r["session_id"])[1]["model"] == "opus"
    # the model says keep: no sale
    t.calls.clear()
    m.answers["decide"] = {"action": "keep", "reason": "The event is about a different company."}
    con.execute("UPDATE desk_sessions_s84 SET status='failed'")
    desk.run_desk(con, NOW.replace(minute=30), "india_close")
    assert t.calls == []


def test_the_idea_search_screens_shortlists_cards_decides_and_code_records_it(con, monkeypatch):
    from pflab.lab import screen, tools
    t = Tools()
    monkeypatch.setattr(tools, "run", t.run)
    shown = {}

    def screen_stocks(con, now, market, filters, sort, n, root=None, detail="full"):
        shown["filters"] = filters
        return {"rows": [{"symbol": "ZZ1", "sector": "Banks"}, {"symbol": "ZZ2", "sector": "Chemicals"}]}
    monkeypatch.setattr(screen, "screen_stocks", screen_stocks)
    monkeypatch.setattr(screen, "company_card", lambda con, now, m, sym, root=None: {"symbol": sym})
    monkeypatch.setattr(screen, "fit_card", lambda c, n: c)
    monkeypatch.setattr(desk, "_sleeve_room", lambda con, m, d: 0.1 if m == "IN" else None)
    monkeypatch.setattr(desk, "_sector_to_avoid", lambda con, m, d: "Banks")
    m = with_model(monkeypatch, answers={"desk idea shortlist": {"symbols": ["zz2", "NOPE"], "why": "a different sector"},
                                         "desk idea decision": {"picks": [{"symbol": "ZZ2", "thesis": "a steady chemicals maker with a clean record of results", "break_condition": "margins fall", "storylines": []},
                                                                           {"symbol": "ZZ9", "thesis": "not on the shortlist", "break_condition": "x"}],
                                                                "skips": [{"symbol": "ZZ2", "why": "x"}], "learned_from": "the scorecard is still empty"}})
    ag = desk.agenda(con, NOW, "india_close")
    assert [i["kind"] for i in ag] == ["idea"] and "outside" in ag[0]["why"]
    r = desk.run_desk(con, NOW, "india_close")
    assert [c["role"] for c in m.calls] == ["read", "decide"] and r["cost_rupees"] == 20.0
    names = [c[0] for c in t.calls]
    assert names == ["propose_picks", "skip_idea"] and [i["symbol"] for i in t.calls[0][1]["items"]] == ["ZZ2"]           # ZZ9 was not on the shortlist
    blob = json.dumps(t.calls).lower()
    assert all(w not in blob for w in ("weight", "\"size\"", "price", "quantity"))
    assert "named ZZ2" in r["plan"]
    assert desk.agenda(con, NOW.replace(minute=40), "india_close") == []                  # one search a day per market
    us = desk.agenda(con, NOW, "us_morning")
    assert us == []                                                                         # no US room: no US search


def test_a_case_over_the_two_percent_line_is_thought_through_once_a_day_by_the_case_module(con, monkeypatch):
    m = with_model(monkeypatch)
    cid = a_case(con, pct=0.05)
    seen = []

    def think_case(con, now, case_id, *, root=None):
        seen.append(case_id)
        cases.add_step(con, case_id, now, "understand", engine="anthropic", model="opus", thinking="high", cost_rupees=7.0)
        return {"case_id": case_id, "ok": True, "class": "unclear", "state": "waiting"}              # what the real `think_case` returns (the integration proved a "summary" key wrong)
    desk.modules["session"] = SimpleNamespace(think_case=think_case)
    ag = desk.agenda(con, NOW, "india_close")
    assert ag[0]["kind"] == "case" and ag[0]["over_2pct"]
    r = desk.run_desk(con, NOW, "india_close")
    assert seen == [cid] and r["cost_rupees"] == 17.0                                          # 7 for the case's own step + 10 for the desk's read
    assert "unclear, now waiting" in m.calls[0]["text"]
    con.execute("UPDATE desk_sessions_s84 SET status='failed'")
    desk.run_desk(con, NOW.replace(minute=30), "india_close")
    assert seen == [cid]                                                                        # a case that has a step today is not thought through again


def test_the_plan_text_names_what_was_done_and_the_looks_due(con, monkeypatch):
    with_model(monkeypatch)
    a_case(con, pct=0.01, look=date(2026, 11, 13))
    cases.set_case(con, 1, next_look_on=date(2026, 11, 12))
    r = desk.run_desk(con, NOW, "india_close")
    assert "Desk, 12 Nov" in r["plan"] and "Next session" in r["plan"] and "Looks due" in r["plan"]
    assert desk.sessions(con)[0]["status"] == "done" and desk.plan_text(con, NOW.date() + timedelta(days=1)) == r["plan"]


def test_the_desk_is_off_with_its_switch(con, monkeypatch):
    m = with_model(monkeypatch)
    a_case(con)
    monkeypatch.setattr(desk, "settings", lambda: {**desk.DEFAULTS, "desk_on": False})
    assert desk.run_desk(con, NOW, "india_close")["skipped"] and desk.due(con, NOW) == [] and desk.tick_hook(con, NOW) == {"off": True} and m.calls == []


# --- through the real door, with a scripted vendor client ------------------------------------------------------------------------------------------------------------------------------

def test_the_desk_goes_through_the_gateway_as_the_agent_desk_and_a_refusal_stops_the_day(con, monkeypatch):
    from pflab.agents import analyst as an
    from pflab.llm import gateway
    from tests.test_s84_gate import Fake, _cfg
    monkeypatch.setattr(an, "config", lambda path=None: _cfg())
    monkeypatch.setattr(desk, "cap_left", lambda con, now: 1000.0)
    ans = {"finding": "The case is waiting on the board.", "needs_decision": "none", "next_step": "Look again."}
    f = Fake(blocks=[SimpleNamespace(type="text", text=json.dumps(ans))], model="claude-sonnet-5-5")
    gateway.set_client(f)
    try:
        a_case(con, pct=0.01)
        a_holding(con, monkeypatch, isin=BBB, sym="BBB")
        r = desk.run_desk(con, NOW, "india_close")
        assert r["status"] in ("done", "budget") and f.sent and r["cost_rupees"] > 0
        st = desk.steps(con, r["session_id"])
        assert st[0]["status"] == "done" and st[0]["thinking"] == "medium" and "sonnet" in st[0]["model"] and st[0]["finding"].startswith("The case is waiting")
        assert con.execute("SELECT count(*) FROM api_calls WHERE agent='desk'").fetchone()[0] >= 1
        assert desk.spent_today(con, NOW.date()) >= r["cost_rupees"] - 1e-9
        # the governor refuses (cap spent): the rest of the agenda is not reached and the day is marked as stopped by it
        monkeypatch.setattr(an, "config", lambda path=None: _cfg(cap=0.01))
        r2 = desk.run_desk(con, NOW + timedelta(days=1), "catchup", covers="india_close")
        assert r2["status"] == "budget" and r2["stopped"]
    finally:
        gateway.set_client(None)
