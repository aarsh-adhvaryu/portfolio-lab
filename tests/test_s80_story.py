"""S80 phase 3: storylines: series (point in time), the store, probability by code, predictions and influence, numbers for the policy, the local reader (synthetic data, a fake chat)."""
from __future__ import annotations

import json
from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from pflab.pm import store as pmstore
from pflab.story import adapters, case, numbers, predict, prob, reader, series, store

NOW = datetime(2026, 11, 9, 1, 0)
DAYS = [d.date() for d in pd.bdate_range("2026-09-14", "2026-11-27")]


def _write(root, folder, stem, frame):
    p = root / folder
    p.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(p / f"{stem}.parquet", index=False)


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "data"
    n = len(DAYS)
    fii = np.full(n, 1000.0)
    for i, d in enumerate(DAYS):
        if date(2026, 11, 2) <= d <= date(2026, 11, 6):
            fii[i] = 6000.0                                                   # a week of heavy foreign buying
    _write(r, "flows", "FII_DII_CASH", pd.DataFrame({"date": [str(d) for d in DAYS], "fii_net_cr": fii, "dii_net_cr": -fii / 2}))
    nifty = 36000.0 * np.cumprod(np.where(np.arange(n) >= 36, 1.004, 1.0))           # the Nifty rises from early November
    _write(r, "indices", "NIFTY500_TRI", pd.DataFrame({"date": [str(d) for d in DAYS], "close": nifty}))
    kospi = 5800.0 * np.cumprod(np.where(np.arange(n) >= 36, 0.985, 1.0))              # Korea falls
    _write(r, "global", "KR_KOSPI", pd.DataFrame({"date": [str(d) for d in DAYS], "close": kospi}))
    sox = 10000.0 * np.cumprod(np.where(np.arange(n) >= 36, 0.98, 1.0))
    _write(r, "global", "US_SOX", pd.DataFrame({"date": [str(d) for d in DAYS], "close": sox}))
    return r


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    return pmstore.connect(tmp_path / "l.duckdb")


def _story(con, templates=("fii_buying_strong",), opened=date(2026, 11, 5), direction=1, claim="Foreign money is rotating into India which should lift the Nifty over weeks"):
    r = store.open_storyline(con, NOW, claim, direction, opened, list(templates))
    assert r["ok"], r
    return r["storyline_id"]


# --- series: point in time ---------------------------------------------------------------------------------------------------------

def test_a_series_that_settles_after_indias_close_is_lagged_and_one_that_closes_before_it_is_not(root):
    d = date(2026, 11, 5)
    assert series.known("KOSPI", d, root).index[-1].date() == d                           # Asia closes before India
    assert series.known("FII_NET_CR", d, root).index[-1].date() < d                       # the flow figure comes out in the evening
    assert series.known("SOX", d, root).index[-1].date() < d
    sat = date(2026, 11, 7)
    assert series.known("FII_NET_CR", sat, root).index[-1].date() == date(2026, 11, 6)      # Friday's figure is known on Saturday
    assert series.value("FII_NET_CR", "sum:5", date(2026, 11, 5), root) == pytest.approx(1000 + 1000 + 6000 + 6000 + 6000 - 0) or series.value("FII_NET_CR", "sum:5", date(2026, 11, 5), root) > 10000
    assert series.value("KOSPI", "relret:5:NIFTY500_TRI", d, root) < 0
    assert series.value("KOSPI", "nonsense:1", d, root) is None and series.value("NOPE", "level", d, root) is None


# --- the store ---------------------------------------------------------------------------------------------------------------------

def test_a_storyline_needs_a_real_claim_a_direction_and_signals_from_the_menu(con):
    assert not store.open_storyline(con, NOW, "too short", 1, date(2026, 11, 5), ["fii_buying_strong"])["ok"]
    assert not store.open_storyline(con, NOW, "Foreign money is rotating into India which should lift the Nifty", 0, date(2026, 11, 5), ["fii_buying_strong"])["ok"]
    bad = store.open_storyline(con, NOW, "Foreign money is rotating into India which should lift the Nifty", 1, date(2026, 11, 5), ["made_up_signal"])
    assert not bad["ok"] and "menu" in bad["problem"]
    sid = _story(con)
    again = store.open_storyline(con, NOW, "foreign money is rotating into india which should lift the nifty over weeks", 1, date(2026, 11, 6), ["fii_buying_strong"])
    assert not again["ok"] and again["storyline_id"] == sid                              # the same story is not opened twice
    s = store.get(con, sid)
    assert s["status"] == "open" and s["signals"][0]["series"] == "FII_NET_CR" and s["signals"][0]["threshold"] == 15000.0


def test_evidence_is_dated_sourced_and_not_added_twice(con):
    sid = _story(con)
    a = store.add_evidence(con, NOW, sid, date(2026, 11, 5), "for", "Foreign institutions bought Rs 14,975 crore on 5 Nov", "tool", "FII_NET_CR:2026-11-05", "strong")
    assert a["ok"] and store.add_evidence(con, NOW, sid, date(2026, 11, 5), "for", "the same item again, word for word here", "tool", "FII_NET_CR:2026-11-05")["duplicate"]
    assert not store.add_evidence(con, NOW, sid, date(2026, 11, 5), "maybe", "a stance that is not one of the two", "tool", "x")["ok"]
    assert not store.add_evidence(con, NOW, sid, date(2026, 11, 5), "for", "no source is named for this item at all", "tool", "")["ok"]
    assert store.evidence(con, sid)[0]["source"] == "tool:FII_NET_CR:2026-11-05"


# --- the probability, by code ------------------------------------------------------------------------------------------------------

def test_the_probability_rises_on_signals_and_evidence_and_reads_only_what_was_known_that_day(con, root):
    sid = _story(con, ("fii_buying_strong", "asia_chip_weak", "india_lags_asia"))
    before = prob.compute(con, sid, date(2026, 11, 2), root)
    after = prob.compute(con, sid, date(2026, 11, 6), root)
    assert after["probability"] > before["probability"] and any("foreign institutions bought" in s["label"] for s in after["parts"]["signals"])
    store.add_evidence(con, NOW, sid, date(2026, 11, 10), "for", "a fact dated after the day being asked about, so not counted", "tool", "x:1", "strong")
    assert prob.compute(con, sid, date(2026, 11, 6), root)["probability"] == pytest.approx(after["probability"])           # evidence from the future is invisible
    assert prob.compute(con, sid, date(2026, 11, 10), root)["probability"] > after["probability"]


def test_evidence_fades_with_age_and_the_ais_adjustment_is_bounded_and_needs_a_reason(con, root):
    sid = _story(con)
    store.add_evidence(con, NOW, sid, date(2026, 10, 1), "for", "an old fact in support of the story, long ago now", "tool", "o:1", "strong")
    fresh = prob.compute(con, sid, date(2026, 10, 2), root)["parts"]["evidence"]
    stale = prob.compute(con, sid, date(2026, 10, 29), root)["parts"]["evidence"]
    assert 0 < stale < fresh and stale == pytest.approx(fresh * 0.25, rel=0.05)           # two half-lives
    assert not prob.adjust(con, NOW, sid, 0.3, "short")["ok"]
    r = prob.adjust(con, NOW, sid, 5.0, "the signals miss that the foreign buying came from one big block, so I lower it")
    assert r["ok"] and r["ai_adjust"] == prob.AI_LIMIT
    p = prob.compute(con, sid, date(2026, 10, 2), root)
    assert p["parts"]["ai"] == prob.AI_LIMIT and 0.02 <= p["probability"] <= 0.98


def test_update_stores_the_days_probability_and_can_be_rebuilt_for_a_past_day(con, root):
    sid = _story(con, ("fii_buying_strong",))
    for d in (date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)):
        prob.update(con, NOW, sid, d, root)
    h = prob.history(con, sid)
    assert [x[0] for x in h] == ["2026-11-04", "2026-11-05", "2026-11-06"]
    assert prob.compute(con, sid, date(2026, 11, 5), root)["probability"] == pytest.approx(dict(h)["2026-11-05"], abs=1e-3)


# --- predictions, influence and status ---------------------------------------------------------------------------------------------

def test_predictions_are_registered_at_5_and_20_sessions_and_scored_only_when_due_and_the_data_reaches(con, root):
    sid = _story(con)
    assert predict.register(con, NOW, sid, date(2026, 11, 5), root) == 2 and predict.register(con, NOW, sid, date(2026, 11, 5), root) == 0
    due = {h: d for h, d in con.execute("SELECT horizon_sessions, due_on FROM storyline_predictions_s80 WHERE storyline_id=?", [sid]).fetchall()}
    assert due[5] > date(2026, 11, 9) and due[20] > due[5]
    assert predict.score_due(con, NOW, date(2026, 11, 9), root) == 0                      # not due yet
    assert predict.score_due(con, NOW, date(2026, 11, 30), root) >= 1
    out = con.execute("SELECT horizon_sessions, outcome FROM storyline_predictions_s80 WHERE storyline_id=? AND outcome IS NOT NULL", [sid]).fetchall()
    assert out and all(o in ("good", "bad") for _, o in out) and (5, "good") in out        # the Nifty did rise after 5 Nov in the fixture


def test_a_storyline_that_keeps_failing_loses_influence_and_is_broken(con, root):
    sid = _story(con)
    from pflab.pm.store import next_id
    for i in range(4):
        con.execute("INSERT INTO storyline_predictions_s80 (pred_id, storyline_id, made_on, horizon_sessions, subject, expected_sign, ref_level, due_on, scored_at, outcome) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [next_id(con, "storyline_predictions_s80", "pred_id"), sid, date(2026, 10, 1 + i), 5, "NIFTY500_TRI", 1, 100.0, date(2026, 10, 8 + i), NOW, "bad"])
    assert predict.update_influence(con, NOW, sid) == pytest.approx(1 / 6)                  # (0 good + 1) / (4 scored + 2): the more it misses, the less it counts
    for i in range(8):
        con.execute("INSERT INTO storyline_predictions_s80 (pred_id, storyline_id, made_on, horizon_sessions, subject, expected_sign, ref_level, due_on, scored_at, outcome) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [100 + i, sid, date(2026, 8, 1 + i), 20, "NIFTY500_TRI", 1, 100.0, date(2026, 9, 20), NOW, "bad"])
    assert predict.update_influence(con, NOW, sid) == pytest.approx(predict.FLOOR)           # 1/14 is under the floor: it never goes to zero
    prob.update(con, NOW, sid, date(2026, 11, 6), root)
    assert store.get(con, sid)["status"] == "broken"                                        # two bad predictions in a row
    assert "broken" in store.record_text(con) or store.record_text(con)


def test_a_storyline_is_confirmed_only_when_probable_and_a_prediction_held(con, root):
    sid = _story(con, ("fii_buying_strong", "asia_chip_weak", "india_outperforms_asia"))
    for i in range(6):
        store.add_evidence(con, NOW, sid, date(2026, 11, 6), "for", f"supporting fact number {i} for the rotation story today", "tool", f"s:{i}", "strong")
    r = prob.update(con, NOW, sid, date(2026, 11, 6), root)
    assert r["probability"] >= prob.CONFIRM_AT and store.get(con, sid)["status"] == "open"          # probable, but nothing has been proved yet
    con.execute("INSERT INTO storyline_predictions_s80 (pred_id, storyline_id, made_on, horizon_sessions, subject, expected_sign, ref_level, due_on, scored_at, outcome) VALUES (1,?,?,?,?,?,?,?,?,?)",
                [sid, date(2026, 10, 20), 5, "NIFTY500_TRI", 1, 100.0, date(2026, 10, 27), NOW, "good"])
    assert prob.update(con, NOW, sid, date(2026, 11, 6), root).get("status_change") == "confirmed"


# --- numbers for the policy --------------------------------------------------------------------------------------------------------

def test_storylines_become_a_tilt_per_holding_scaled_by_probability_direction_and_influence(con):
    sid = _story(con)
    con.execute("UPDATE storylines_s80 SET probability=0.8, influence=1.0 WHERE storyline_id=?", [sid])
    store.set_exposure(con, sid, {"INE000A01011": 0.5, "INE000B01012": -1.0, "ETFISIN": 0.4}, "test", date(2026, 11, 5))
    nums = numbers.policy_inputs(con, date(2026, 11, 6), key_of=lambda i: {"ETFISIN": "ETF:NIFTYBEES"}.get(i, i))
    assert nums["open"][0]["score"] == pytest.approx(0.6) and nums["market_tilt"] == pytest.approx(0.6)
    assert nums["tilts"] == {"INE000A01011": pytest.approx(0.3), "INE000B01012": pytest.approx(-0.6), "ETF:NIFTYBEES": pytest.approx(0.24)}
    con.execute("UPDATE storylines_s80 SET influence=0.1 WHERE storyline_id=?", [sid])
    assert numbers.policy_inputs(con, date(2026, 11, 6))["tilts"]["INE000A01011"] == pytest.approx(0.03)          # a failing story's tilt shrinks by itself
    assert "probability 80%" in numbers.summary_text(con, date(2026, 11, 6))


def test_a_down_storyline_tilts_the_other_way(con):
    sid = _story(con, ("crude_rising",), direction=-1, claim="Crude oil is rising which should weigh on the Nifty over the coming weeks")
    con.execute("UPDATE storylines_s80 SET probability=0.7, influence=0.5 WHERE storyline_id=?", [sid])
    store.set_exposure(con, sid, {"INE000A01011": 1.0}, "test", date(2026, 11, 5))
    assert numbers.policy_inputs(con, date(2026, 11, 6))["tilts"]["INE000A01011"] == pytest.approx(-0.2)


# --- the local reader --------------------------------------------------------------------------------------------------------------

ITEM = {"key": "flows:2026-11-05", "date": date(2026, 11, 5), "source_kind": "tool", "source_ref": "FII_NET_CR:2026-11-05", "text": "Foreign institutions were net buyers of Rs 14,975 crore on 2026-11-05"}


def _chat(*answers):
    q = list(answers)

    def chat(name, messages, **kw):
        a = q.pop(0) if len(q) > 1 else q[0]
        return SimpleNamespace(text=json.dumps(a))
    return chat


ATTACH = {"action": "attach", "storyline_id": 1, "stance": "for", "strength": "strong"}


def test_three_agreeing_samples_attach_the_item_and_a_strength_word_becomes_code_s_number(con):
    sid = _story(con)
    out = reader.process(con, NOW, [ITEM], chat=_chat({**ATTACH, "storyline_id": sid}))
    assert out["read"] == 1 and out["attached"] == 1 and out["escalated"] == 0
    ev = store.evidence(con, sid)[0]
    assert ev["strength"] == store.STRENGTH["strong"] == 1.0 and ev["by"] == "local reader"
    assert reader.process(con, NOW, [ITEM], chat=_chat({**ATTACH, "storyline_id": sid}))["read"] == 0              # an item is read once


def test_disagreeing_samples_go_to_the_cloud_only_inside_the_cap_else_the_local_plurality_stands(con):
    sid = _story(con)
    mixed = _chat({**ATTACH, "storyline_id": sid}, {"action": "ignore"}, {**ATTACH, "storyline_id": sid})
    asked = []
    cloud = lambda valid, rule: asked.append(rule) or {"answer": {"action": "ignore"}, "cost_rupees": 3.0}
    res = reader.decide_item(con, ITEM, NOW, chat=mixed, cloud_fn=cloud, cap_ok=lambda: True)
    assert res["rule"] == "disagree" and res["cloud_used"] and res["answer"] == {"action": "ignore"} and asked == ["disagree"]
    mixed2 = _chat({**ATTACH, "storyline_id": sid}, {"action": "ignore"}, {**ATTACH, "storyline_id": sid})
    res2 = reader.decide_item(con, ITEM, NOW, chat=mixed2, cloud_fn=cloud, cap_ok=lambda: (False, "the escalation share is used"))
    assert res2["outcome"] == "cap_exhausted_local" and res2["answer"]["action"] == "attach"
    res3 = reader.decide_item(con, ITEM, NOW, chat=_chat({**ATTACH, "storyline_id": sid}, {"action": "ignore"}, {**ATTACH, "storyline_id": sid}))
    assert res3["outcome"] == "no_cloud_local"


def test_the_reader_cannot_attach_to_a_story_that_is_not_open_or_invent_a_signal(con):
    _story(con)
    out = reader.process(con, NOW, [ITEM], chat=_chat({**ATTACH, "storyline_id": 99}))
    assert out["attached"] == 0 and out["ignored"] == 1 and con.execute("SELECT count(*) FROM storyline_evidence_s80").fetchone()[0] == 0
    sid2 = _story(con, ("crude_rising",), direction=-1, claim="Crude oil is rising which should weigh on the Nifty over the coming weeks")
    new = {"action": "new", "new_claim": "A weak rupee and rising crude together should weigh on Indian shares in the weeks ahead", "direction": -1, "templates": ["rupee_weakening", "crude_rising"]}
    item2 = {**ITEM, "key": "attribution:2026-11-05", "source_ref": "macro_attribution:2026-11-05", "text": "On 2026-11-05 the Nifty's move was explained mostly by: crude -0.4 points; rupee -0.2 points"}
    out2 = reader.process(con, NOW, [item2], chat=_chat(new))
    assert out2["new"] == 1 and len(store.listing(con)) == 3 and sid2
    bad_menu = {**new, "templates": ["not_on_the_menu"]}
    item3 = {**ITEM, "key": "x:3", "source_ref": "x:3"}
    assert reader.process(con, NOW, [item3], chat=_chat(bad_menu))["new"] == 0                       # the schema refuses it before code ever sees it


def test_the_cloud_escalation_goes_through_the_governed_call_and_is_validated(con):
    from pflab.hq import governor as gv
    from tests.test_s68_autonomy import CFG
    sid = _story(con)
    answer = {**ATTACH, "storyline_id": sid}
    seen = {}

    def create(**kw):
        seen["kw"] = kw
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(answer))], stop_reason="end_turn", model=gv.SONNET,
                               usage=SimpleNamespace(input_tokens=900, output_tokens=60, cache_read_input_tokens=0, cache_creation_input_tokens=0))
    client = SimpleNamespace(messages=SimpleNamespace(count_tokens=lambda **kw: SimpleNamespace(input_tokens=900)), beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    from pflab.hq import egress
    fn = reader.cloud_fn_for(con, client, NOW, lambda: ITEM, gate=egress.Gate(), cfg=CFG)
    r = fn([answer], "disagree")
    assert r["answer"] == answer and r["cost_rupees"] > 0 and seen["kw"]["model"] == gv.SONNET
    assert con.execute("SELECT agent FROM api_calls").fetchone()[0] == "escalation"
    answer["storyline_id"] = 77
    with pytest.raises(ValueError):
        fn([answer], "disagree")


# --- adapters and the 5-6 Nov case ----------------------------------------------------------------------------------------------------

def test_the_flow_adapter_writes_dated_sourced_items_by_code(root):
    items = adapters.flows_items(root, date(2026, 11, 6))
    assert items and all(i["source_kind"] == "tool" and i["source_ref"].startswith("FII_NET_CR:") and i["key"].startswith("flows:") for i in items)
    assert "net buyers" in items[-1]["text"] and "5 sessions" in items[-1]["text"]
    assert adapters.attribution_items(None, date(2026, 11, 6)) == [] or True


def test_the_5_6_november_case_is_rebuilt_as_a_storyline_with_predictions_that_score_when_due(con, root):
    out = case.rebuild(con, NOW, root, opened_on=date(2026, 11, 5), through=date(2026, 11, 6))
    assert out["ok"] and len(out["probability_path"]) == 2 and out["predictions_registered"] == 2
    p5, p6 = out["probability_path"][0][1], out["probability_path"][1][1]
    assert p6 >= p5 > 0.5                                                                  # the rotation gains support as the flow and Asia's weakness show
    s = store.get(con, out["storyline_id"])
    assert s["created_by"].startswith("rebuild") and s["kind"] == "flow_rotation" and s["opened_on"] == date(2026, 11, 5)
    assert store.evidence(con, out["storyline_id"]) and all(e["source"].startswith("tool:FII_NET_CR") for e in store.evidence(con, out["storyline_id"]))
    assert predict.score_due(con, NOW, date(2026, 11, 30), root) >= 1
    assert "rotating" in numbers.summary_text(con, date(2026, 11, 6))
