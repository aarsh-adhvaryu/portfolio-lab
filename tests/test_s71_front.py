"""S71: the local model is the front of the chat, and the chat stays the way into the whole system: it acts through the same tools, checks what it writes against the
tool results, and hands anything it is unsure of to the cloud agent unchanged. A scripted local model stands in for Ollama; synthetic data only."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from pflab.app import assistant, chat, front
from pflab.hq import board, roster
from tests.test_s68_autonomy import NOW, con, rt  # noqa: F401  (fixtures)


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(front, "enabled", lambda: True)


@pytest.fixture
def all_intents(monkeypatch):
    """The handlers of start and amend are kept and tested, but the measurement switched those intents off by default (front.ENABLED)."""
    monkeypatch.setattr(front, "ENABLED", front.ENABLED + ("start", "amend", "decline"))


def model(intent="other", conf=0.95, draft="Done.", log=None):
    """A scripted local model: sorts a message into `intent`, and words a reply with `draft`."""
    def chat_(name, messages, **kw):
        if log is not None:
            log.append(kw.get("purpose"))
        if "sort what an investor types" in messages[0]["content"]:
            return SimpleNamespace(text=json.dumps({"intent": intent, "confidence": conf}))
        return SimpleNamespace(text=draft)
    return chat_


def _thread(con, last_ai="Here is my plan. Say approve to start."):
    cid = assistant.thread(con, NOW)
    chat._add(con, cid, "ai", "assistant", last_ai, "done", NOW)
    chat._add(con, cid, "me", "assistant", "x", "done", NOW)
    return cid, chat._add(con, cid, "ai", "assistant", "Working on it…", "working", NOW)


# --- classification --------------------------------------------------------------------------------------------------------------

def test_the_model_chooses_from_a_closed_list_and_an_invalid_choice_is_other(rt, con):
    assert front.classify(con, "How much have I got in cash?", "", model("portfolio", 0.9)) == {"intent": "portfolio", "confidence": 0.9, "how": "local model"}
    bad = lambda *a, **k: SimpleNamespace(text='{"intent": "launch_rockets", "confidence": 0.99}')
    assert front.classify(con, "Something", "", bad)["intent"] == "other"
    down = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("Ollama is not running"))
    c = front.classify(con, "Something", "", down)
    assert c["intent"] == "other" and c["confidence"] == 0.0 and "unavailable" in c["how"]


def test_numbers_come_from_his_words_only():
    assert front.percents("what if the market falls 20% or 35 percent, or 150%, or 0%?") == [20.0, 35.0]
    assert front.rupees("I have Rs 5 lakh to put in") == 500_000.0 and front.rupees("put 50k in over 6 months") == 50_000.0
    assert front.rupees("a 20% fall over 12 months") is None and front.rupees("I have 1,50,000 to deploy") == 150_000.0


# --- acting through the real tools -----------------------------------------------------------------------------------------------

def test_a_short_message_is_never_started_as_an_investigation(rt, con, all_intents):
    cid, aid = _thread(con, "Hello.")
    assert front.try_local(rt, con, cid, aid, "look into it", chat=model("start", 0.99)) is None and con.execute("SELECT count(*) FROM hq_missions").fetchone()[0] == 0


# --- the facts are rendered by code; the model only adds a paragraph that must pass the guard --------------------------------------

SHOCK = {"calc_id": 11, "kind": "scenario", "total_rupees": 4736119.5, "equity_rupees": 863804.0, "cash_and_debt_rupees": 3872315.5,
         "table": [{"index_fall_pct": 20.0, "loss_rupees": -172760.8, "loss_pct_of_total": -3.647728905488976}, {"index_fall_pct": 35.0, "loss_rupees": -302331.4, "loss_pct_of_total": -6.3834}],
         "assumptions": {"note": "the index falls are stated assumptions, not forecasts"}}
PORT = {"asof": "2026-11-01", "net_worth": "Rs 47,36,000", "statements_to": "2024-01-05",
        "buckets": [{"bucket": "cash", "weight_pct": 81.8, "value": "Rs 38,72,000"}, {"bucket": "equity", "weight_pct": 18.2, "value": "Rs 8,64,000"}],
        "holdings": [{"symbol": "LT", "bucket": "equity", "weight_pct": 4.62, "value": "Rs 2,19,000", "gain_pct": 3.4}],
        "direct_stocks": {"names": 6, "value": "Rs 8,64,000", "cost": "Rs 11,28,000", "unrealised_gain": "-Rs 2,64,000", "gain_pct": -23.4}}


def _stub_tools(monkeypatch, results, calls):
    def call(self, name, args):
        calls.append((name, args))
        self.steps.append(name)
        out = results.get(name, {"case_id": 7})
        self.texts[name] = json.dumps(out)
        return out
    monkeypatch.setattr(front.Run, "call", call)


def test_a_fall_question_runs_the_shock_tool_with_his_numbers_and_the_facts_are_exact(rt, con, monkeypatch):
    calls = []
    _stub_tools(monkeypatch, {"exposure_shock": SHOCK}, calls)
    cid, aid = _thread(con, "Hello.")
    q = "What would a 20% and a 35% fall cost me?"
    res = front.try_local(rt, con, cid, aid, q, chat=model("fall", 0.95, draft="The 20% case is the one to watch: most of your money is in cash, so the loss stays small."))
    assert res and res["cost"] == 0.0
    assert "If the index falls 20%: you lose about Rs 1,72,761, which is 3.6% of the portfolio." in res["text"]
    assert "If the index falls 35%: you lose about Rs 3,02,331, which is 6.4% of the portfolio." in res["text"] and "In plain words (written by the local model" in res["text"]
    assert ("exposure_shock", {"case_id": 7, "falls_json": "[20.0, 35.0]", "why": q}) in calls


def test_indian_grouping():
    from pflab.app import front_render as fr
    assert fr.inr(172760.8) == "Rs 1,72,761" and fr.inr(-264000) == "-Rs 2,64,000" and fr.inr(950) == "Rs 950" and fr.inr(10_00_00_000) == "Rs 10,00,00,000"


def test_a_paragraph_with_an_invented_number_is_dropped_but_the_exact_facts_are_still_delivered_locally(rt, con, monkeypatch):
    calls = []
    _stub_tools(monkeypatch, {"exposure_shock": SHOCK}, calls)
    cid, aid = _thread(con, "Hello.")
    log = []
    res = front.try_local(rt, con, cid, aid, "What would a 20% fall cost me?", chat=model("fall", 0.95, draft="A 20% fall would cost you about 9.9% of the portfolio.", log=log))
    assert res and "9.9%" not in res["text"] and "In plain words" not in res["text"] and "Rs 1,72,761" in res["text"]
    assert log.count("front") == 3                                              # the sorting call, the paragraph, one retry


def test_when_the_model_is_unreachable_after_sorting_the_facts_still_come(rt, con, monkeypatch):
    calls = []
    _stub_tools(monkeypatch, {"exposure_shock": SHOCK}, calls)
    cid, aid = _thread(con, "Hello.")
    state = {"n": 0}

    def flaky(name, messages, **kw):
        state["n"] += 1
        if "sort what an investor types" in messages[0]["content"]:
            return SimpleNamespace(text=json.dumps({"intent": "fall", "confidence": 0.95}))
        raise ConnectionError("Ollama went away")
    res = front.try_local(rt, con, cid, aid, "What would a 20% fall cost me?", chat=flaky)
    assert res and "Rs 1,72,761" in res["text"] and "In plain words" not in res["text"]


def test_a_sum_of_money_is_read_by_code_and_passed_on(rt, con, monkeypatch):
    calls = []
    deploy = {"calc_id": 12, "assumptions": {"amount_rupees": 50000.0, "fall_pct": 20.0, "decline_pct": 30.0},
              "policies": {"lump_now": "all in at the start", "current_staged": "equal tranches"}, "best_terminal_by_path": {"no_crash": "lump_now"},
              "table": [{"path": "no_crash", "policy": "lump_now", "return_pct": 9.5, "worst_value_vs_amount_pct": -1.0},
                        {"path": "no_crash", "policy": "current_staged", "return_pct": 6.1, "worst_value_vs_amount_pct": 0.5}], "note": "a hypothetical scenario study"}
    _stub_tools(monkeypatch, {"policy_scenarios": deploy}, calls)
    cid, aid = _thread(con, "Hello.")
    res = front.try_local(rt, con, cid, aid, "I have Rs 50k a month to invest, all at once or in parts?", chat=model("deploy", 0.9, draft="With no crash the lump sum came out ahead."))
    assert res and "Putting Rs 50,000 to work" in res["text"] and "lump_now 9.5% (worst -1.0%)" in res["text"] and "made-up price paths" in res["text"]
    assert any(n == "policy_scenarios" and a["amount"] == 50000.0 for n, a in calls)


def test_a_fall_with_no_percentage_in_his_words_is_not_guessed(rt, con, monkeypatch):
    calls = []
    _stub_tools(monkeypatch, {}, calls)
    cid, aid = _thread(con, "Hello.")
    assert front.try_local(rt, con, cid, aid, "What if the market falls a lot?", chat=model("fall", 0.95)) is None and calls == []


# --- the bars and the fall-through -----------------------------------------------------------------------------------------------

def test_an_unsure_or_open_turn_goes_to_the_cloud_agent(rt, con, monkeypatch):
    calls = []
    _stub_tools(monkeypatch, {}, calls)
    cid, aid = _thread(con, "Hello.")
    assert front.try_local(rt, con, cid, aid, "Is gold a good hedge in an AI crash?", chat=model("other", 0.99)) is None
    assert front.try_local(rt, con, cid, aid, "What if it falls 20%?", chat=model("fall", 0.80)) is None        # below the bar for an action (0.85)
    assert front.try_local(rt, con, cid, aid, "What do I hold?", chat=model("portfolio", 0.60)) is None          # below the bar for a read (0.70)
    assert calls == []


def test_any_trouble_in_the_front_is_the_cloud_agents_turn(rt, con, monkeypatch):
    cid, aid = _thread(con, "Hello.")
    monkeypatch.setattr(front, "classify", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("anything")))
    assert front.try_local(rt, con, cid, aid, "What do I hold?") is None


def test_the_assistant_uses_the_front_when_it_answers_and_the_cloud_agent_when_it_does_not(monkeypatch):
    finished, asked = [], []
    monkeypatch.setattr(chat, "_finish", lambda con, aid, text, *a, **k: finished.append(text))
    monkeypatch.setattr(assistant, "answer", lambda *a, **k: asked.append(1) or {"text": "cloud", "route": [], "meta": "", "status": "done", "cost": 1.0})
    rt_ = SimpleNamespace(cursor=lambda: SimpleNamespace(execute=lambda *a, **k: None), clock=lambda: NOW, bump=lambda *a: None)
    monkeypatch.setattr(front, "try_local", lambda *a, **k: {"text": "local", "route": [], "meta": "", "status": "done", "cost": 0.0})
    assistant._work(rt_, 1, 1, "q", "")
    assert finished == ["local"] and asked == []
    monkeypatch.setattr(front, "try_local", lambda *a, **k: None)
    assistant._work(rt_, 1, 2, "q", "")
    assert finished == ["local", "cloud"] and asked == [1]
    monkeypatch.setattr(front, "enabled", lambda: False)
    monkeypatch.setattr(front, "try_local", lambda *a, **k: (_ for _ in ()).throw(AssertionError("switched off")))
    assistant._work(rt_, 1, 3, "q", "")
    assert finished[-1] == "cloud"


# --- the measured defaults -----------------------------------------------------------------------------------------------------

def test_a_trade_or_a_target_change_is_never_kept_as_a_note_even_if_the_model_is_sure(rt, con):
    cid, aid = _thread(con, "Hello.")
    for q in ("Set my monthly limit for the AI to Rs 5000", "Sell half my Tata Motors today", "Raise my equity target to sixty percent"):
        assert front.try_local(rt, con, cid, aid, q, chat=model("remember", 1.0)) is None
    assert con.execute("SELECT count(*) FROM memory WHERE kind IN ('goal', 'note')").fetchone()[0] == 0

