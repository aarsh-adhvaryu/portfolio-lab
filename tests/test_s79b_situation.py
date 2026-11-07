"""S79b item 16, the shared situation: claim typing, adapters tolerant of missing tools, disagreements kept and queued, WHY refusing a cause dated after its effect, figures
without a call id rejected, watch triggers emitted, predictions scored at 1/5/20 sessions across a weekend, the report first on the World screen. Synthetic; the model is a function."""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from pflab import markets
from pflab.hq import tools as tl
from pflab.pm import store
from pflab.situation import adapters as AD, build, chains, claims as C, report, score, synth, watch

NOW = datetime(2026, 11, 6, 19, 0)
DAY = date(2026, 11, 6)
CFG = {"on": True, "model": True, "paper_requests": True, "paper_requests_per_day": 1, "questions": False, "questions_per_day": 1, "short_intraday": True,
       "intraday_minutes": 90, "max_watch": 12, "kg": True}


def _connect(path):
    import duckdb
    con = duckdb.connect(str(path))
    store.migrate(con, [m for m in store.MIGRATIONS if m[0] <= 60 or m[0] in (65, 81, 82, 83, 84)])
    return con


@pytest.fixture
def rt(tmp_path, monkeypatch):
    from pflab.app import runtime
    monkeypatch.setenv("PFLAB_DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "pm").mkdir()
    (tmp_path / "data" / "global").mkdir(parents=True)
    con = _connect(tmp_path / "l.duckdb")
    yield runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def _fake_tool(monkeypatch, name, result):
    monkeypatch.setitem(tl.TOOLS, name, tl.Tool(name, "read", "fake", {}, (), lambda ctx, a: dict(result) if not callable(result) else result(ctx, a)))


def _only(monkeypatch, names):
    monkeypatch.setattr(AD, "ADAPTERS", {k: v for k, v in AD.ADAPTERS.items() if k in names})


# --- claims -------------------------------------------------------------------------------------------------------------------------------------

def test_claim_typing_and_point_in_time(rt):
    con = rt.cursor()
    with pytest.raises(C.ClaimError):
        C.add(con, "IN", "gossip", "x", "t")
    with pytest.raises(C.ClaimError):
        C.add(con, "IN", "regime", "", "t")
    with pytest.raises(C.ClaimError):
        C.add(con, "IN", "regime", "x", "t", value=float("nan"))
    with pytest.raises(C.ClaimError):
        C.add(con, "IN", "regime", "x", "t", confidence=1.5)
    a = C.add(con, "IN", "regime", "breadth", "weak", value=-1, entities=("INE001",), themes=["banks"], call_ids=[12, 13], confidence=0.7, as_of=DAY, ttl_sessions=2)
    b = C.add(con, "IN", "regime", "breadth", "weaker", value=-1, as_of=DAY)                  # same market, kind, subject, date, source: replaces
    assert a == b
    got = C.get(con, b)
    assert got["call_ids"] == [] and got["text"] == "weaker"
    c = C.get(con, C.add(con, "IN", "macro", "m", "t", call_ids=[7], themes=["oil"], as_of=DAY, ttl_sessions=1))
    assert c["call_ids"] == ["7"] and c["themes"] == ["oil"]
    C.add(con, "IN", "event", "later", "dated after", as_of=DAY + timedelta(days=3))
    live = {x["subject"] for x in C.active(con, "IN", DAY)}
    assert "later" not in live and "breadth" in live                              # nothing dated after the as-of date is read
    far = {x["subject"] for x in C.active(con, "IN", DAY + timedelta(days=20))}
    assert "breadth" not in far                                                   # expired
    assert set(C.by_kind(con, "IN", DAY)) >= {"regime", "macro"}


# --- adapters ---------------------------------------------------------------------------------------------------------------------------

def test_build_from_adapters_with_missing_tools(rt, monkeypatch):
    _fake_tool(monkeypatch, "breadth", {"day": "2026-11-06", "advancers": 900, "decliners": 1700, "advancing_pct": 34.5, "advance_decline_ratio": 0.53,
                                        "above_sma50": {"pct": 30.1}, "above_sma20": {"pct": 41.2}, "new_high_50d": 20, "new_low_50d": 150})
    _only(monkeypatch, ["breadth", "sentiment", "forecast_now", "no_such"])
    monkeypatch.delitem(tl.TOOLS, "sentiment", raising=False)
    monkeypatch.delitem(tl.TOOLS, "forecast_now", raising=False)
    out = build.run(rt, "IN", DAY, NOW, "post_close", use_model=False, cfg=CFG)
    st = {s["source"]: s["status"] for s in out["sources"]}
    assert st["breadth"] == "ok" and st["sentiment"] == "missing" and st["forecast_now"] == "missing"
    subj = {c["subject"]: c for c in C.active(rt.cursor(), "IN", DAY)}
    assert subj["breadth"]["call_ids"] and subj["regime"]["value"] == -1.0       # weak: advancing 34.5 and above the 50-day 30.1
    assert out["coded_only"] is True and "coded only" in out["text"]
    calls = rt.cursor().execute("SELECT count(*) FROM hq_tool_calls WHERE tool='breadth'").fetchone()[0]
    assert calls == 1                                                             # the call is journaled, the claim cites its id


def test_off_switch(rt):
    assert build.run(rt, "IN", DAY, NOW, "deep", cfg={**CFG, "on": False}) == {"off": True}


# --- disagreements -------------------------------------------------------------------------------------------------------------------------

def _mk(con, kind, subject, text, value, source, as_of=DAY, calls=(1,)):
    cid = C.add(con, "IN", kind, subject, text, value=value, call_ids=calls, as_of=as_of, source=source)
    return C.get(con, cid)


def test_contradiction_kept_with_both_sides_and_queued(rt):
    con = rt.cursor()
    _mk(con, "forecast", "p_down_h1", "Chance the index is lower after 1 sessions: 0.7", 0.7, "forecast_now")
    _mk(con, "transmission", "open_gap", "Expected opening gap expected_gap_pct 0.6", 0.6, "transmission")
    cons = report.detect_contradictions(C.active(con, "IN", DAY))
    assert len(cons) == 1
    sides = {e["side"]: e for e in cons[0]["explanations"]}
    assert set(sides) == {"bearish", "bullish"} and sides["bearish"]["probability"] == 0.7 and sides["bullish"]["claim_ids"]
    report.store_contradictions(con, None, "IN", DAY, cons, NOW)
    assert con.execute("SELECT count(*) FROM situation_contradiction").fetchone()[0] == 1
    item = con.execute("SELECT kind, state FROM mind_agenda").fetchone()
    assert item == ("resolve_contradiction", "queued")
    sec, _, _ = report.assemble(C.active(con, "IN", DAY), cons, [], None, [])
    text = report.render("IN", DAY, "post_close", sec, True)
    assert "DISAGREEMENTS" in text and "bearish" in text and "bullish" in text    # never merged into one story


# --- WHY: a cause must be dated before its effect ---------------------------------------------------------------------------------------

def test_why_refuses_cause_dated_after_effect(rt):
    con = rt.cursor()
    early = _mk(con, "macro", "leg_X", "crude moved 3 percent", -1.0, "t", as_of=DAY - timedelta(days=1))
    late = _mk(con, "move", "move_Y", "Y fell 2 percent", -2.0, "t", as_of=DAY)
    same = _mk(con, "move", "move_Z", "Z fell 1 percent", -1.0, "t", as_of=DAY - timedelta(days=1))
    by_id = {c["claim_id"]: c for c in (early, late, same)}
    assert chains.validate_link(early, late)[0] is True
    ok, why = chains.validate_link(late, early)
    assert not ok and "later event cannot explain an earlier one" in why
    ok, why = chains.validate_link(early, same)
    assert not ok and "co-movement" in why
    nocall = {**early, "call_ids": []}
    assert chains.validate_link(nocall, late)[0] is False
    ch = chains.make_chain([{"cause": late["claim_id"], "effect": early["claim_id"], "mechanism": "x"},
                            {"cause": early["claim_id"], "effect": late["claim_id"], "mechanism": "y"}], by_id)
    assert [lk["ok"] for lk in ch["links"]] == [False, True] and ch["ok"] is False and ch["types"] == ["macro>move"]
    # through the assembler: the model proposes the backwards link, the report shows only the good one and lists the refusal
    draft = {"now": [], "so_what": [], "next": [], "act": {}, "why": [{"cause": late["claim_id"], "effect": early["claim_id"], "mechanism": "backwards"}]}
    sec, rejected, _ = report.assemble(list(by_id.values()), [], [], draft, [])
    assert sec["why"] == [] and any("not dated before its effect" in r["why"] for r in rejected)
    cid = chains.store(con, None, "IN", DAY, ch, NOW)
    assert chains.to_kg(con, cid, ch, by_id, "IN", NOW) == 1
    assert con.execute("SELECT count(*) FROM kg_edges WHERE rel='leads_to'").fetchone()[0] == 1


# --- numbers need a source ----------------------------------------------------------------------------------------------------------------

def test_a_number_without_a_call_id_is_rejected(rt):
    con = rt.cursor()
    c = _mk(con, "implied", "implied_fall_5_h10", "Chance of a fall of 5% within 10 sessions: p_implied 0.0872", 0.0403, "implied_dist")
    by_id = {c["claim_id"]: c}
    text, rej, _ = synth.verify("The chance of a 12 percent fall is high.", [], by_id)
    assert text == "" and rej and "no call id" in rej[0]["why"]
    text, rej, used = synth.verify("The chance of a 5% fall within 10 sessions is small.", [c["claim_id"]], by_id)
    assert text and not rej and used == [c["claim_id"]] and "[" not in text
    text, rej, _ = synth.verify("The chance is 0.5.", [c["claim_id"]], by_id)       # a figure the cited claim does not hold
    assert text == "" and rej
    text, rej, _ = synth.verify("It looks calm. The chance is 0.0403.", [c["claim_id"]], by_id)
    assert text == "It looks calm. The chance is 0.0403." and not rej


def test_model_draft_is_checked_and_scenarios_keep_the_tools_probabilities(rt):
    con = rt.cursor()
    cs = [_mk(con, "forecast", f"p_down_h{h}", f"Chance the index is lower after {h} sessions: {p}", p, "forecast_now") for h, p in ((1, 0.4), (5, 0.55), (20, 0.5))]
    cands = report.next_candidates(C.active(con, "IN", DAY))
    assert cands[0]["probs"] == {1: 0.4, 5: 0.55, 20: 0.5}
    claims = C.active(con, "IN", DAY)
    draft = {"now": [{"text": "The forecast leans down by 77 percent.", "claims": [cs[0]["claim_id"]]}, {"text": "The forecast is mixed.", "claims": [cs[0]["claim_id"]]}],
             "why": [], "so_what": [], "next": [{"candidate": "index_lower", "note": "The chance is 0.9 of a fall.", "claims": [cs[0]["claim_id"]]}], "act": {}}
    sec, rejected, coded = report.assemble(claims, [], cands, draft, [])
    assert [x["text"] for x in sec["now"]] == ["The forecast is mixed."] and any("77" in r["sentence"] for r in rejected)
    assert sec["next"][0]["note"] == "" and sec["next"][0]["probs"]["5"] == 0.55      # the model cannot change or restate a probability
    assert coded is False


# --- watch triggers on the stream ---------------------------------------------------------------------------------------------------------------

def _write_series(root: Path, name: str, rows):
    pd.DataFrame({"date": [pd.Timestamp(d) for d, _ in rows], "close": [c for _, c in rows]}).to_parquet(root / "global" / f"{name}.parquet")


def test_watch_trigger_is_emitted_when_it_fires(rt, tmp_path):
    con, root = rt.cursor(), tmp_path / "data"
    _write_series(root, "WTI", [(date(2026, 11, 4), 90.0), (date(2026, 11, 5), 92.0)])
    r = watch.add(con, "IN", "WTI back above 95", "WTI", ">", 95.0, date(2026, 11, 5), NOW, root=root)
    assert r["stored"]
    assert watch.add(con, "IN", "again", "WTI", ">", 95.0, date(2026, 11, 5), NOW, root=root).get("again")
    assert not watch.add(con, "IN", "already", "WTI", ">", 80.0, date(2026, 11, 5), NOW, root=root)["stored"]        # a state, not a change
    assert watch.check(con, "IN", date(2026, 11, 5), NOW, root=root) == []                                          # not fired
    _write_series(root, "WTI", [(date(2026, 11, 4), 90.0), (date(2026, 11, 5), 92.0), (date(2026, 11, 6), 97.5)])
    fired = watch.check(con, "IN", DAY, NOW, root=root)
    assert len(fired) == 1 and fired[0]["fired_value"] == 97.5
    assert con.execute("SELECT kind, state FROM mind_agenda").fetchone() == ("watch_fired", "queued")
    ev = [c for c in C.active(con, "IN", DAY) if c["kind"] == "event"]
    assert ev and "WTI" in ev[0]["text"]
    assert watch.check(con, "IN", DAY, NOW, root=root) == []                                                         # fires once
    assert len(watch.unreacted(con, "IN")) == 1 and build.flags_for(con, "IN", DAY, None)                            # the next run is flagged


def test_watch_threshold_must_be_a_level_the_code_printed(rt):
    con = rt.cursor()
    lv = _mk(con, "macro", "level_WTI", "WTI level: last close 97.5, 20-session high 99.1, 20-session low 80.2", 97.5, "levels", calls=())
    other = _mk(con, "macro", "part_crude", "crude part pct 0.12", 0.12, "macro_attribution")
    by_id = {lv["claim_id"]: lv, other["claim_id"]: other}
    ok = lambda w: synth.watch_ok(w, by_id, ["WTI"])[0]                                                   # noqa: E731
    assert ok({"series": "WTI", "op": ">", "threshold": 99.1, "claim": lv["claim_id"]})
    assert not ok({"series": "WTI", "op": ">", "threshold": 100.0, "claim": lv["claim_id"]})               # invented level
    assert not ok({"series": "WTI", "op": ">", "threshold": 0.12, "claim": other["claim_id"]})             # not the series' level claim
    assert not ok({"series": "FOO", "op": ">", "threshold": 99.1, "claim": lv["claim_id"]})


# --- scoring ------------------------------------------------------------------------------------------------------------------------------------

def test_scoring_at_1_5_20_sessions_across_a_weekend(rt):
    con = rt.cursor()
    mk = markets.get("IN")
    d = date(2026, 9, 1)
    while not (d.weekday() == 4 and mk.is_session(d) and mk.session_after(d, 1) == d + timedelta(days=3)):
        d += timedelta(days=1)
    sess = mk.sessions_between(d - timedelta(days=10), d + timedelta(days=60))
    closes = pd.Series([100.0 + (0.0 if s <= d else -(i * 0.3)) for i, s in enumerate(sess)], index=pd.to_datetime(sess))
    cand = {"key": "index_lower", "event": "return_below", "level": 0.0, "probs": {1: 0.6, 5: 0.7, 20: 0.4}, "statement": "index lower", "call_ids": ["3"]}
    pid = score.store_prediction(con, None, "IN", d, cand, "macro>move", NOW)
    assert pid and score.store_prediction(con, None, "IN", d, {**cand, "probs": {1: 0.5, 5: 0.5, 20: 0.5}}, "none", NOW) == pid       # refreshed, not duplicated
    con.execute("UPDATE situation_prediction SET horizons=? WHERE pred_id=?", [json.dumps({"1": 0.6, "5": 0.7, "20": 0.4}), pid])
    fall = {"key": "fall5_20", "event": "fall_within", "level": 5.0, "probs": {20: 0.2}, "statement": "fall 5", "call_ids": []}
    score.store_prediction(con, None, "IN", d, fall, "none", NOW)
    # only the first session after Friday has closed: only the 1-session horizon is scored, and it matures on Monday
    mon = mk.session_after(d, 1)
    assert score.score(con, "IN", mon, now=NOW, series=closes)["scored"] == 1
    r = con.execute("SELECT horizon, target_date, outcome FROM situation_outcome").fetchall()
    assert r == [(1, mon, 1)]                                                                    # Monday's close is under Friday's
    assert score.score(con, "IN", mon, now=NOW, series=closes)["scored"] == 0                    # idempotent
    end = sess[-1]
    assert score.score(con, "IN", end, now=NOW, series=closes)["scored"] == 3                    # h5, h20 and the fall within 20
    rows = {(h): o for h, o in con.execute("SELECT horizon, outcome FROM situation_outcome WHERE pred_id=?", [pid]).fetchall()}
    assert rows == {1: 1, 5: 1, 20: 1}
    b = con.execute("SELECT brier FROM situation_outcome WHERE pred_id=? AND horizon=5", [pid]).fetchone()[0]
    assert math.isclose(b, 0.09)
    cal = score.calibration(con, "IN")
    assert cal["n"] == 4 and "brier" not in cal and "under 20" in cal["note"]                    # the small-n rule: the count only


def test_scoring_reads_nothing_after_the_date(rt):
    con = rt.cursor()
    mk = markets.get("IN")
    d = mk.last_session_on_or_before(date(2026, 10, 9))
    sess = mk.sessions_between(d - timedelta(days=5), d + timedelta(days=40))
    closes = pd.Series([100.0 - i for i in range(len(sess))], index=pd.to_datetime(sess))
    score.store_prediction(con, None, "IN", d, {"key": "index_lower", "event": "return_below", "level": 0.0, "probs": {5: 0.5}, "statement": "s", "call_ids": []}, "none", NOW)
    assert score.score(con, "IN", mk.session_after(d, 4), now=NOW, series=closes)["scored"] == 0


# --- the whole run, with a fake model -------------------------------------------------------------------------------------------------------

def _two_tools(monkeypatch):
    _fake_tool(monkeypatch, "breadth", {"day": "2026-11-06", "advancers": 900, "decliners": 1700, "advancing_pct": 34.5, "advance_decline_ratio": 0.53,
                                        "above_sma50": {"pct": 30.1}, "above_sma20": {"pct": 41.2}, "new_high_50d": 20, "new_low_50d": 150})
    _fake_tool(monkeypatch, "fall_risk", {"as_of": "2026-11-06", "shown": 0.21, "p_raw": 0.25, "n_calibration": 12, "resolved": 12})
    _only(monkeypatch, ["breadth", "fall_risk"])


def test_full_run_with_a_fake_model_and_report_first_world(rt, monkeypatch, tmp_path):
    _two_tools(monkeypatch)
    con = rt.cursor()
    seen = {}

    def chat(system, user, schema):
        seen["user"] = user
        ids = {m.group(2): int(m.group(1)) for m in __import__("re").finditer(r"\[claim (\d+)\] \w+/(\w+)", user)}
        return json.dumps({"now": [{"text": "Fewer names rose than fell.", "claims": [ids["breadth"]]}, {"text": "A 99 percent collapse is coming.", "claims": [ids["breadth"]]}],
                           "why": [], "so_what": [{"text": "The paper book is not started.", "claims": []}], "next": [{"candidate": "fall5_20", "note": "Worth watching closely.", "claims": []}],
                           "act": {"paper_request": "Look at how much cash the book holds.", "agenda": [{"subject": "fall_risk_20", "reason": "the chance is rising"}, {"subject": "nonsense", "reason": "x"}],
                                   "watch": []}})

    out = build.run(rt, "IN", DAY, NOW, "post_close", chat=chat, cfg=CFG)
    assert out["plan"] == "full" and out["coded_only"] is False
    assert out["sections"]["now"][0]["text"] == "Fewer names rose than fell." and len(out["sections"]["now"]) == 1       # the invented figure is dropped
    assert any("99" in r["sentence"] for r in out["rejected"]) and any("agenda subject" in r["why"] for r in out["rejected"])
    assert out["sections"]["next"][0]["key"] == "fall5_20" and out["sections"]["next"][0]["probs"] == {"20": 0.21}
    assert "SITUATION IN" in out["text"] and "NOW" in out["text"] and "ACT" in out["text"]
    acted = out["acted"]
    assert acted["paper_request"]["stored"] and acted["agenda"] and acted["agenda"][0]["subject"] == "fall_risk_20"
    assert con.execute("SELECT count(*) FROM paper_inputs").fetchone()[0] == 1
    assert con.execute("SELECT kind FROM mind_agenda WHERE kind='situation_check'").fetchone()
    # the predictions are stored for scoring; a second run the same day refreshes them, it does not duplicate
    assert con.execute("SELECT count(*) FROM situation_prediction").fetchone()[0] == 1
    build.run(rt, "IN", DAY, NOW + timedelta(minutes=5), "post_close", chat=chat, cfg=CFG)
    assert con.execute("SELECT count(*) FROM situation_prediction").fetchone()[0] == 1
    assert con.execute("SELECT count(*) FROM paper_inputs").fetchone()[0] == 1                      # one request a day
    v = report.world_view(con, ["IN"])
    assert v["available"] and v["reports"][0]["now"][0]["text"] == "Fewer names rose than fell."
    assert "Fewer names rose than fell." in "\n".join(report.note_lines(con, "IN"))
    # the World screen shows the situation before the map
    js = (Path(__file__).resolve().parents[1] / "src" / "pflab" / "app" / "static" / "world.js").read_text(encoding="utf-8")
    assert js.index('id="wsit-sec"') < js.index('id="wmap"') and "wSituation(d)" in js


def test_model_down_gives_a_code_report_flagged(rt, monkeypatch):
    _two_tools(monkeypatch)

    def down(system, user, schema):
        raise ConnectionError("ollama is not running")

    out = build.run(rt, "IN", DAY, NOW, "post_close", chat=down, cfg=CFG)
    assert out["coded_only"] is True and "no model text" in out["text"]
    assert any(r["section"] == "model" for r in out["rejected"])
    assert out["sections"]["now"]                                                                  # still a report, written from the claims
    assert report.latest(rt.cursor(), "IN")["coded_only"] is True


def test_a_past_date_is_point_in_time_and_has_no_effects(rt, monkeypatch):
    _two_tools(monkeypatch)
    con = rt.cursor()
    C.add(con, "IN", "event", "future_claim", "dated after", as_of=DAY + timedelta(days=2), source="x")
    past = DAY - timedelta(days=7)
    out = build.run(rt, "IN", past, NOW, "post_close", use_model=False, cfg=CFG)
    assert "future_claim" not in out["text"]
    assert out["acted"] == {"note": "past date: no effects carried out"}
    assert {t["tool"]: t["status"] for t in out["tool_log"] if t["tool"] in ("breadth", "fall_risk")}["breadth"] == "ok"


def test_tool_reads_the_stored_report(rt, monkeypatch):
    _two_tools(monkeypatch)
    from pflab.hq.tools_s79 import t_situation
    from pflab.hq import egress
    ctx = tl.Ctx(rt, None, "x", False, {}, egress.Gate(), NOW, role="research")
    assert t_situation.situation(ctx, {})["available"] is False
    build.run(rt, "IN", DAY, NOW, "post_close", use_model=False, cfg=CFG)
    res = t_situation.situation(ctx, {"claims": True})
    assert res["available"] and res["claims"] and res["calibration"]["n"] == 0 and "SITUATION" in res["text"]
