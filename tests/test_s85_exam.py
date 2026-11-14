"""S85 exam and shadow (`llm/exam.py`, `think/shadow.py`, per-engine calibration in `think/cases.py` / `think/score.py`). Synthetic data and scripted fakes only: no vendor is called."""
from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from pflab import think
from pflab.llm import exam, gateway
from pflab.pm import store
from pflab.think import cases, odds, rule, score, session, shadow

NOW = datetime(2026, 11, 13, 10, 0)


@pytest.fixture
def con(tmp_path):
    c = store.connect(tmp_path / "t.duckdb")
    gateway.set_client(None)
    return c


def good_answer(opt="hold", klass="market_fear"):
    return {"happened": "The shares moved with the market.", "class": klass, "pending": "", "choices": [{"symbol": "AAA", "option": opt, "reason": "an ordinary move"}],
            "likelihood": {"worst": "unlikely", "likely": "likely", "best": "unlikely", "base_rate_set": "20"}}


def make_fake(mode="good", bad_every=0):
    """A scripted engine: `mode` good | number | list | malformed | notool. Returns (fake, log)."""
    log = []

    def fake(**c):
        log.append(c["role"])
        msgs = c["messages"]
        schema = c.get("schema")
        first = msgs[0]["content"] if isinstance(msgs[0]["content"], str) else ""
        n = len(log)
        if c.get("tools"):
            has_tr = any(isinstance(m.get("content"), list) and any(b.get("type") == "tool_result" for b in m["content"]) for m in msgs)
            if has_tr:
                return {"text": "It returned a close.", "cost_rupees": 0.01}
            if mode == "notool":
                return {"text": "I cannot.", "cost_rupees": 0.01}
            return {"text": "", "tool_calls": [{"id": "t1", "name": "lookup_close", "input": {"symbol": "ZZTOY"}}], "cost_rupees": 0.01}
        if schema is not None and "facts" in json.dumps(schema)[:200]:                       # the reading part: echo facts found by keyword
            doc = first
            facts = [w for w in ("approved", "plant", "auditor", "borrowings", "director") if w in doc]
            facts = list(facts)
            return {"json": {"facts": facts[:4], "numbers": []}, "cost_rupees": 0.02}        # misses one fact on purpose
        a = good_answer()
        if bad_every and n % bad_every == 0 or mode == "malformed":
            return {"text": "not json at all", "cost_rupees": 0.03}
        if mode == "number":
            a["choices"][0]["size_inr"] = 5000
        if mode == "list":
            a["class"] = "panic"
        # a good answer that agrees with the reference for the first stored case, otherwise a plain hold
        return {"json": a, "text": json.dumps(a), "cost_rupees": 0.03}
    return fake, log


def test_a_good_engine_passes_the_form_part_and_gets_a_grade_in_words(con):
    fake, log = make_fake("good")
    r = exam.run(con, "openai", thinking=("medium",), now=NOW, fake=fake)
    rep = r["levels"]["medium"]
    assert rep["form_pass"] and rep["form"]["ok"] == 20 and rep["form"]["tool_call"]
    assert rep["reading"]["docs"] == 10 and rep["reading"]["missed"] == 10          # one fact missed in each of ten documents
    assert exam.passed(con, "openai")
    g = exam.grade(con, "openai")
    assert g.startswith("agrees on ") and " of 6 decisions" in g and "misses 10 facts in 10 documents" in g
    assert rep["cost"]["cost_rupees"] > 0 and rep["cost"]["desk_day_rupees"] > 0 and rep["cost"]["seconds_per_call"] >= 0
    # the verdict is what `use` reads
    assert gateway.exam_state(con, "openai")["form_pass"] is True


def test_an_engine_that_writes_a_number_fails_the_form_part(con):
    fake, _ = make_fake("number")
    r = exam.run(con, "openai", now=NOW, fake=fake)["levels"]["medium"]
    assert not r["form_pass"] and r["form"]["number"] == 20
    assert not exam.passed(con, "openai")
    assert exam.grade(con, "openai").startswith("FAILED the form part")


def test_an_engine_that_breaks_a_closed_list_fails(con):
    fake, _ = make_fake("list")
    r = exam.run(con, "openai", now=NOW, fake=fake)["levels"]["medium"]
    assert not r["form_pass"] and r["form"]["list"] == 20 and not exam.passed(con, "openai")


def test_three_malformed_answers_in_twenty_fail_but_two_do_not(con):
    fake, _ = make_fake("good", bad_every=9)
    r = exam.run(con, "e2", now=NOW, fake=fake)["levels"]["medium"]
    assert r["form"]["malformed"] == 2 and r["form_pass"]
    fake, _ = make_fake("good", bad_every=5)             # 4 of 20
    r = exam.run(con, "e3", now=NOW, fake=fake)["levels"]["medium"]
    assert r["form"]["malformed"] >= 3 and not r["form_pass"]


def test_an_engine_whose_tool_call_does_not_work_fails(con):
    fake, _ = make_fake("notool")
    r = exam.run(con, "openai", now=NOW, fake=fake)["levels"]["medium"]
    assert not r["form"]["tool_call"] and not r["form_pass"]


def test_two_thinking_levels_are_graded_separately(con):
    fake, _ = make_fake("good")
    r = exam.run(con, "openai", thinking="medium,high", now=NOW, fake=fake)
    assert set(r["levels"]) == {"medium", "high"}
    rows = con.execute("SELECT thinking FROM engine_exam_s85 WHERE engine='openai' ORDER BY exam_id").fetchall()
    assert [x[0] for x in rows] == ["medium", "high"]


def test_use_is_refused_before_a_passing_exam_and_allowed_after(con):
    assert not exam.passed(con, "openai") and "has not been examined" in exam.grade(con, "openai")
    r = gateway.use(con, "openai", yes=True, now=NOW)
    assert not r["ok"] and "exam" in r["reason"]
    fake, _ = make_fake("number")
    exam.run(con, "openai", now=NOW, fake=fake)
    r = gateway.use(con, "openai", yes=True, now=NOW)
    assert not r["ok"] and "failed the exam" in r["reason"]


def test_the_spend_cap_stops_the_exam(con):
    fake, log = make_fake("good")
    r = exam.run(con, "openai", now=NOW, fake=fake, spend_cap_rupees=0.2)["levels"]["medium"]
    assert r["stopped_at_cap"] and len(log) < 40 and not r["form_pass"]


def test_nothing_is_sent_without_a_recorded_consent(con, monkeypatch):
    sent = []
    monkeypatch.setattr(gateway, "call", lambda *a, **k: sent.append(1) or {})
    con.execute("UPDATE engine_consent_s85 SET active=FALSE WHERE vendor='openai'")
    r = exam.run(con, "openai", now=NOW)
    assert r["refused"] and not sent and "Yes" in r["text"]
    con.execute("UPDATE engine_consent_s85 SET active=TRUE WHERE vendor='openai'")
    # with the consent the exam goes through the door with scope='exam'
    seen = []
    monkeypatch.setattr(gateway, "call", lambda *a, **k: seen.append(k.get("scope")) or {"text": "", "cost_rupees": 0.0})
    exam.run(con, "openai", now=NOW, spend_cap_rupees=1.0)
    assert seen and set(seen) == {"exam"}


def test_cheaper_is_measured_against_the_engine_in_use_else_list_price(con):
    fake_a, _ = make_fake("good")
    fa = lambda **c: {**fake_a(**c), "cost_rupees": 0.30}
    exam.run(con, "claude", now=NOW, fake=fa)                      # the in-use engine measured: Rs 0.30 a call
    fake_b, _ = make_fake("good")
    fb = lambda **c: {**fake_b(**c), "cost_rupees": 0.03}
    rep = exam.run(con, "openai", now=NOW, fake=fb)["levels"]["medium"]
    assert rep["cheaper"] and rep["cheaper"]["basis"] == "measured" and rep["cheaper"]["times"] > 5
    assert "times cheaper than claude" in rep["grade"]


# --- shadow ---------------------------------------------------------------------------------------------------------------------------------------------------------

class ShadowGate:
    def __init__(self, answers=None, fail=False, cost=1.0):
        self.calls, self.answers, self.fail, self.cost = [], list(answers or []), fail, cost

    def shadows(self, con):
        return ["openai"]

    def current_engine(self, con=None):
        return "claude"

    def settings(self):
        return {"shadow_daily_rupees": 25}

    def refusal_reason(self, e):
        return None

    def call(self, con, role, system, messages, **kw):
        self.calls.append({"role": role, **{k: kw.get(k) for k in ("engine", "scope", "case_id")}})
        if self.fail:
            raise RuntimeError("vendor down")
        if role == "read":
            return {"text": "A reading.", "cost_rupees": self.cost}
        a = self.answers.pop(0) if self.answers else good_answer("sell", "damage")
        return {"json": a, "text": json.dumps(a), "cost_rupees": self.cost}


def _row(option):
    return {"track": "model", "isin": "INE000A01011", "symbol": "AAA", "option": option, "worst_inr": -100.0, "likely_inr": 10.0, "best_inr": 50.0, "expected_inr": 5.0, "worst_pct_book": 0.001, "size_inr": 0.0,
            "basis": "table"}


@pytest.fixture
def case(con, monkeypatch):
    c = cases.open_case(con, NOW, market="IN", kind="move", isin="INE000A01011", symbol="AAA", title="AAA fell")
    cid = c["case_id"] if isinstance(c, dict) else c
    monkeypatch.setattr(odds, "option_table", lambda con, cid, nans, day, cache=None: [_row("hold"), _row("sell"), _row("nothing")])
    monkeypatch.setattr(rule, "decide", lambda con, cid, nans, day, cache=None: {"all": [{"symbol": "AAA", "rule_option": "hold"}], "rule_option": "hold"})
    monkeypatch.setattr(session, "_isin_map", lambda con, case, ans: {"AAA": "INE000A01011"})
    return cases.get_case(con, cid)


def test_shadow_stores_its_choice_beside_the_rules_and_never_acts(con, case):
    acted = []
    gate = ShadowGate()
    shadow.DEPS["gateway"] = gate
    try:
        import pflab.think.session as s
        orig = s.act
        s.act = lambda *a, **k: acted.append(1) or []
        out = shadow.run(con, NOW, case, "FIRST", [], date(2026, 11, 13))
    finally:
        s.act = orig
        shadow.DEPS.clear()
    assert out and out[0]["rows"][0]["option"] == "sell" and out[0]["rows"][0]["rule"] == "hold"
    assert not acted
    tracks = {o["track"]: o for o in cases.options(con, case["case_id"])}
    assert tracks["shadow:openai"]["option"] == "sell" and tracks["shadow:openai"]["chosen"] and tracks["shadow_rule:openai"]["option"] == "hold"
    assert all(c["engine"] == "openai" and c["scope"] == "shadow" for c in gate.calls) and {c["role"] for c in gate.calls} == {"read", "decide"}
    assert con.execute("SELECT count(*) FROM think_decisions_s84").fetchone()[0] == 0           # nothing decided, nothing ordered


def test_a_shadow_failure_is_one_line_on_the_case_never_an_error(con, case):
    shadow.DEPS["gateway"] = ShadowGate(fail=True)
    try:
        out = shadow.run(con, NOW, case, "FIRST", [], date(2026, 11, 13))
    finally:
        shadow.DEPS.clear()
    assert out == []
    notes = [json.loads(s["payload_json"]) for s in cases.steps(con, case["case_id"]) if s["step"] == "shadow_note"]
    assert notes and "vendor down" in notes[0]["note"]


def test_a_shadow_answer_with_a_number_is_not_stored_as_a_choice(con, case):
    bad = good_answer("sell", "damage")
    bad["choices"][0]["size_inr"] = 9000
    shadow.DEPS["gateway"] = ShadowGate(answers=[bad, bad])
    try:
        out = shadow.run(con, NOW, case, "FIRST", [], date(2026, 11, 13))
    finally:
        shadow.DEPS.clear()
    assert out == [] and not [o for o in cases.options(con, case["case_id"]) if o["track"].startswith("shadow")]


def test_the_shadow_daily_budget_skips_further_calls(con, case):
    gate = ShadowGate(cost=30.0)                                     # one case spends more than the Rs 25 a day
    shadow.DEPS["gateway"] = gate
    try:
        shadow.run(con, NOW, case, "FIRST", [], date(2026, 11, 13))
        n = len(gate.calls)
        shadow.run(con, NOW, case, "FIRST", [], date(2026, 11, 13))
    finally:
        shadow.DEPS.clear()
    assert len(gate.calls) == n and shadow.spent_today(con, date(2026, 11, 13)) >= 25.0
    assert any("at the cap" in json.loads(s["payload_json"]).get("note", "") for s in cases.steps(con, case["case_id"]))


# --- per-engine calibration and the side-by-side scorecard -----------------------------------------------------------------------------------------------------------------

def test_calibration_tables_are_kept_per_engine_and_a_new_engine_starts_from_the_default(con):
    con.execute("INSERT INTO think_calibration_s84 VALUES ('likely', 0.60, 30, 18, DATE '2026-11-01')")
    assert cases.probabilities(con, "claude")["likely"] == 0.60
    assert cases.probabilities(con, "openai")["likely"] == think.WORD_P["likely"]          # a new engine: the default table
    con.execute("INSERT INTO think_calibration_engine_s85 VALUES ('openai', 'likely', 0.80, 25, 20, DATE '2026-11-01')")
    assert cases.probabilities(con, "openai")["likely"] == 0.80 and cases.probabilities(con, "claude")["likely"] == 0.60
    cases.ENGINE_CTX["engine"] = "openai"
    try:
        assert cases.probabilities(con)["likely"] == 0.80
    finally:
        cases.ENGINE_CTX.clear()


def test_the_scorecard_shows_both_engines_side_by_side(con):
    con.execute("INSERT INTO think_shadow_s85 VALUES (1, 1, 'openai', DATE '2026-11-01', 'INE000A01011', 'AAA', 'damage', 'sell', 'hold', 0.5, '', TIMESTAMP '2026-11-01 10:00:00', NULL)")
    con.execute("INSERT INTO think_scores_s84 VALUES (1, 1000000001, 20, 'shadow:openai', 'sell', 50.0, 40.0, DATE '2026-12-01')")
    con.execute("INSERT INTO think_scores_s84 VALUES (2, 1000000001, 20, 'shadow_rule:openai', 'hold', 10.0, 0.0, DATE '2026-12-01')")
    sc = score.scorecard(con)
    be = sc["by_engine"]
    assert be["claude"]["in_use"] and not be["openai"]["in_use"]
    assert be["openai"]["model_track"]["vs_nothing_inr"] == 40.0 and be["openai"]["rule_track"]["vs_nothing_inr"] == 0.0
    assert set(be["openai"]["by_word"]) <= set(think.WORDS)


def test_shadow_rows_are_scored_under_their_own_tracks(con, monkeypatch):
    import pandas as pd
    con.execute("INSERT INTO think_shadow_s85 VALUES (1, 1, 'openai', DATE '2026-11-02', 'INE000A01011', 'AAA', 'damage', 'sell', 'hold', 0.5, '', TIMESTAMP '2026-11-02 10:00:00', NULL)")
    seen = []

    def fake_sd(con, d, day, done, root, next_id):
        seen.append(d)
        return 0
    monkeypatch.setattr(score, "_score_decision", fake_sd)
    score.score_shadow(con, date(2026, 12, 20))
    assert seen and seen[0]["picks"] == [("shadow_rule:openai", "hold"), ("shadow:openai", "sell")] and seen[0]["decision_id"] == score.SHADOW_BASE + 1


def test_the_migration_is_in_place(con):
    for t in ("think_calibration_engine_s85", "think_shadow_s85", "engine_exam_s85"):
        assert con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0


def test_every_reading_keyword_occurs_in_its_own_source_document():
    """S86b (C4.1): the exam's reading part counts a fact found when its keyword is carried by the extract; a keyword the source never uses ("debt" for "borrowings") made every faithful reader
    miss one fact in every document (the 10 missed facts of 14 Nov were this fault, not the engine)."""
    from pflab.llm import exam
    docs = exam.documents()
    assert len(docs) == 10
    for d in docs:
        assert [k for k in d["facts"] if k not in d["text"].lower()] == [], d["company"]
