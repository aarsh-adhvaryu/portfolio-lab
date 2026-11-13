"""S85 `loopchat` (E7): the chat and the thinking loop (`think/chat_hooks.py`). Synthetic data and scripted fakes only (no paid call). The world is the S84 case fixture (a paper book with WIN and CALM
held, NEWX not held)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from pflab.core import picks
from pflab.entrance import store, tools
from pflab.hq import rules
from pflab.lab import screen
from pflab.think import cases, chat_hooks, desk, score, session, watch
from tests.test_s84_case import CALM, DAY, DAYS, Gate, NEWX, NOW, WIN, ans, con  # noqa: F401  (the fixture and helpers)


class VGate:
    """A scripted gateway for the suggested-stock read: one verdict per call; records every call."""

    def __init__(self, *verdicts):
        self.verdicts, self.calls = list(verdicts), []

    def call(self, con, role, system, messages, *, purpose="", schema=None, agent="think", chat_id=None, **kw):
        self.calls.append({"role": role, "purpose": purpose, "agent": agent, "chat_id": chat_id, "text": json.dumps(messages, default=str)})
        v = self.verdicts.pop(0) if self.verdicts else verdict("pass", why="nothing to add")
        return {"json": v, "text": json.dumps(v), "cost_rupees": 0.4, "engine": "claude", "model": "claude-sonnet-5-5", "thinking": "medium"}


def verdict(v, **kw):
    out = {"verdict": v, "why": "a plain reason with no figures", "thesis": "A steady business whose order book is growing faster than its costs, which is what the thesis rests on.",
           "break_condition": "the order book stops growing", "takes_from": "", "learned_from": "", "wait_kind": "none", "wait_text": ""}
    out.update(kw)
    return out


def card(ok=True, mk="IN"):
    liq = {"median_traded_value_inr_60d": 9e8 if ok else 2e7, "clears_picks_floor": ok, "floor_inr": 5e7}
    return {"ok": True, "market": mk, "liquidity": liq}


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    monkeypatch.setattr(watch, "_index", lambda market, root=None: None)
    monkeypatch.setattr(picks, "traded_value_source", lambda c, m, i, s, d: (9e8, 60))
    monkeypatch.setattr(screen, "company_card", lambda con, now, market, symbol, root=None, **kw: card(True, market))
    chat_hooks.DEPS.clear()
    yield
    chat_hooks.DEPS.clear()


def _chat(con):
    return store.new_chat(con, NOW)


def _vg(*v):
    g = VGate(*v)
    chat_hooks.DEPS["gateway"] = g
    return g


def _msgs(con, chat_id):
    return [m for m in store.messages(con, chat_id) if m.get("kind") == "loop"]


# --- (1) look into --------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_look_into_opens_a_case_at_once_and_its_first_message_has_his_words(con):
    chat = _chat(con)
    cid = chat_hooks.look_into(con, NOW, "WIN", chat, why="the order book looked odd to me")
    c = cases.get_case(con, cid)
    assert c["state"] == "open" and c["opened_by"] == "you" and c["isin"] == WIN
    o = chat_hooks.origin(con, cid)
    assert o["chat_id"] == chat and o["source"] == "you_look" and o["state"] == "open"
    g = Gate([ans("hold", "unclear", sym="WIN")])
    session.DEPS["gateway"] = g
    r = session.think_case(con, NOW, cid)
    assert r["ok"]
    assert "the order book looked odd to me" in json.dumps(g.seen_messages[0])                 # the first message the model reads holds his words


def test_look_into_counts_in_the_days_three_and_a_full_day_queues_it_for_the_next_day_and_says_so(con):
    chat = _chat(con)
    for sym in ("WIN", "CALM", "NEWX"):
        assert chat_hooks.look_into_result(con, NOW, sym, chat, "look")["how"] == "opened"
    assert cases.cases_opened_on(con, DAY) == 3
    r = chat_hooks.look_into_result(con, NOW, "WIN", chat, "again")                           # WIN has an open case: joined, not a fourth
    assert r["how"] == "joined"
    con.execute("UPDATE think_cases_s84 SET state='closed' WHERE isin=?", [NEWX])
    q = chat_hooks.look_into_result(con, NOW, "NEWX", chat, "once more")
    assert q["how"] == "queued" and "next day" in q["message"] and cases.get_case(con, q["case_id"])["state"] == "noticed"
    assert cases.cases_opened_on(con, DAY) == 3                                                # still three: the fourth did not count
    assert chat_hooks.release_queued(con, NOW) == []                                           # no room today
    nxt = NOW + timedelta(days=3)
    assert chat_hooks.release_queued(con, nxt) == [q["case_id"]]
    assert cases.get_case(con, q["case_id"])["state"] == "open" and cases.cases_opened_on(con, nxt.date()) == 1


def test_an_unknown_name_is_said_plainly(con):
    r = chat_hooks.look_into_result(con, NOW, "NOSUCHCO", _chat(con), "x")
    assert not r["ok"] and r["case_id"] is None and chat_hooks.look_into(con, NOW, "NOSUCHCO", None) == 0


# --- (2) a suggested stock --------------------------------------------------------------------------------------------------------------------------------------------------

def test_a_pick_verdict_goes_through_propose_picks_and_the_name_joins_the_watch_for_120_sessions(con):
    chat = _chat(con)
    g = _vg(verdict("pick", takes_from=""))
    r = chat_hooks.suggest_stock(con, NOW, "NEWX", "I think it is a steady compounder", chat)
    assert r["ok"] and r["verdict"] == "pick", r
    assert con.execute("SELECT state, source FROM picks_s83 WHERE isin=?", [NEWX]).fetchone()[0] in ("proposed", "buying", "held")
    assert [c["role"] for c in g.calls] == ["read"] and g.calls[0]["agent"] == "chat" and g.calls[0]["chat_id"] == chat and g.calls[0]["purpose"] == "suggest_stock"
    w = chat_hooks.watch_from_you(con, DAY)[0]
    assert w["isin"] == NEWX and w["verdict"] == "pick" and w["chat_id"] == chat and w["since"] == DAY
    sessions = len([d for d in pd.bdate_range(DAY + timedelta(days=1), w["until"])])
    assert 110 <= sessions + 1 <= 125                                                           # about 120 trading sessions ahead
    assert any(e["isin"] == NEWX and "from you" in e["why"] for e in watch.scope(con, DAY))      # T1's signals run on it
    note = con.execute("SELECT source FROM recall_notes_s84 WHERE isin=?", [NEWX]).fetchone()
    assert note and note[0] == "you"                                                           # recall finds it tomorrow


def test_the_model_never_writes_a_size_the_pick_has_none(con):
    _vg(verdict("pick"))
    chat_hooks.suggest_stock(con, NOW, "NEWX", "good", _chat(con))
    cols = [r[1] for r in con.execute("PRAGMA table_info('picks_s83')").fetchall()]
    assert "weight" not in cols and "size_inr" not in cols
    assert "size" not in json.dumps(chat_hooks.VERDICT_SCHEMA["properties"]) and "price" not in json.dumps(chat_hooks.VERDICT_SCHEMA["properties"])


def test_a_name_that_fails_the_liquidity_floor_is_passed_with_the_reason_and_still_watched(con, monkeypatch):
    monkeypatch.setattr(screen, "company_card", lambda con, now, market, symbol, root=None, **kw: card(False, market))
    g = _vg()
    chat = _chat(con)
    r = chat_hooks.suggest_stock(con, NOW, "NEWX", "my friend likes it", chat)
    assert r["verdict"] == "pass" and r["floor_ok"] is False and "floor" in r["why"] and "crore" in r["why"]
    assert g.calls == []                                                                        # no paid read for a name that cannot be held
    assert con.execute("SELECT count(*) FROM skips_s83 WHERE isin=?", [NEWX]).fetchone()[0] == 1       # scored against the index like every skip
    assert con.execute("SELECT count(*) FROM picks_s83 WHERE isin=?", [NEWX]).fetchone()[0] == 0
    w = chat_hooks.watch_from_you(con, DAY)[0]
    assert w["verdict"] == "pass" and w["isin"] == NEWX


def test_a_wait_for_verdict_stores_the_condition_and_a_pullback_reopens_it(con):
    chat = _chat(con)
    _vg(verdict("wait_for", wait_kind="pullback_10", why="good but dear today"))
    r = chat_hooks.suggest_stock(con, NOW, "NEWX", "it looks dear but good", chat)
    assert r["verdict"] == "wait_for" and "10% pullback" in r["condition_text"]
    assert con.execute("SELECT count(*) FROM skips_s83 WHERE isin=?", [NEWX]).fetchone()[0] == 1
    assert chat_hooks.scan(con, NOW + timedelta(minutes=5)) == []                              # no pullback yet
    con.execute("UPDATE prices SET close=85 WHERE isin=? AND date=?", [NEWX, DAY])
    opened = chat_hooks.scan(con, NOW + timedelta(minutes=6))
    assert len(opened) == 1
    c = cases.get_case(con, opened[0])
    assert c["isin"] == NEWX and "condition he suggested we wait for" in json.dumps([s["detail_json"] for s in c["signals"]])
    assert chat_hooks.scan(con, NOW + timedelta(minutes=7)) == []                              # once


def test_the_same_name_twice_in_a_day_costs_one_read(con):
    g = _vg(verdict("pass"))
    chat = _chat(con)
    a = chat_hooks.suggest_stock(con, NOW, "NEWX", "x", chat)
    b = chat_hooks.suggest_stock(con, NOW, "NEWX", "x again", chat)
    assert len(g.calls) == 1 and b.get("repeat") and b["verdict"] == a["verdict"]


def test_at_most_five_names_a_day_the_rest_wait_for_the_next_desk(con):
    chat = _chat(con)
    syms = []
    for k in range(7):                                                                          # seven more listed names
        isin, sym = f"INE000X0{k}012", f"XX{k}"
        con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, 'Auto', 'synthetic', now())",
                    [isin, sym, f"Xx{k} Ltd"])
        for d in DAYS[-30:]:
            con.execute("INSERT INTO prices VALUES (?, ?, 100.0, 'EQ', 'nse_bhavcopy', now())", [isin, d])
        syms.append(sym)
    g = _vg(*[verdict("pass") for _ in range(7)])
    out = [chat_hooks.suggest_stock(con, NOW, s, "try", chat) for s in syms]
    assert [o["verdict"] for o in out[:5]] == ["pass"] * 5 and out[5]["verdict"] == "queued" and out[6]["verdict"] == "queued"
    assert "5 suggested names a day" in out[5]["message"] and len(g.calls) == 5
    assert con.execute("SELECT count(*) FROM watch_from_you_s85 WHERE state='queued'").fetchone()[0] == 2
    nxt = NOW + timedelta(days=1)
    done = chat_hooks.run_queued_suggestions(con, nxt)                                          # the next desk takes them up
    assert len(done) == 2 and len(g.calls) == 7 and con.execute("SELECT count(*) FROM watch_from_you_s85 WHERE state='queued'").fetchone()[0] == 0
    assert any("From the desk" in m["text"] for m in _msgs(con, chat))                           # and says so in that chat


def test_the_watch_list_runs_out_after_120_sessions(con):
    _vg(verdict("pass"))
    chat_hooks.suggest_stock(con, NOW, "NEWX", "x", _chat(con))
    w = chat_hooks.watch_from_you(con, DAY)[0]
    assert any(e["isin"] == NEWX and "from you" in e["why"] for e in watch.scope(con, w["until"]))
    late = w["until"] + timedelta(days=1)
    assert not any(e["isin"] == NEWX and "from you" in e["why"] for e in watch.scope(con, late))
    assert chat_hooks.expire(con, late) == 1 and chat_hooks.watch_from_you(con, late) == []


def _index_series(n=len(DAYS)):
    r = np.array([0.001 if k % 2 else -0.001 for k in range(n)], dtype=float)
    return pd.Series(1000.0 * np.cumprod(1.0 + r), index=pd.to_datetime(DAYS))


def test_a_passed_name_that_runs_20_points_ahead_reopens_and_is_told_in_the_chat(con, monkeypatch, tmp_path):
    chat = _chat(con)
    passed_on = DAYS[-30]
    _vg(verdict("pass", why="not convinced by the margins"))
    chat_hooks.suggest_stock(con, datetime.combine(passed_on, datetime.min.time()) + timedelta(hours=12), "NEWX", "worth a look?", chat)
    monkeypatch.setattr(watch, "_index", lambda market, root=None: _index_series())
    con.execute("UPDATE prices SET close=130 WHERE isin=? AND date > ?", [NEWX, passed_on])      # 30 points ahead of a flat index
    r = watch.run(con, NOW, mode="close", root=tmp_path)
    mine = [cid for cid in r["cases_opened"] if cases.get_case(con, cid)["isin"] == NEWX]
    assert mine and cases.get_case(con, mine[0])["kind"] == "missed_run"
    session.DEPS["gateway"] = Gate([ans("hold", "unclear", sym="NEWX", pending="")])
    session.think_case(con, NOW, mine[0])
    told = _msgs(con, chat)
    assert told and "a name you suggested is back on the table" in told[-1]["text"].lower() and "not convinced by the margins" in told[-1]["text"]
    assert chat_hooks.origin(con, mine[0])["source"] == "watch_from_you"


# --- (3) a note from him ----------------------------------------------------------------------------------------------------------------------------------------------------

def _doc(con, doc_id=1, claims=("Win Ltd's board has opened an investigation into its order book",), isins=(WIN,), name="broker note", chat=None):
    facts = [{"claim": c, "quote": c, "page": 1} for c in claims]
    con.execute("INSERT INTO received_docs_s85 (doc_id, sha, name, mime, kind, path, size_bytes, received_at, chat_id, msg_id, pages, status, summary, facts_json, isins_json, event_id, note_doc, cost_inr) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [doc_id, f"sha{doc_id}", name, "application/pdf", "pdf", "x", 10, NOW, chat, None, 2, "read", "a note", json.dumps(facts),
                                                                   json.dumps(list(isins)), None, None, 0.0])
    return doc_id


def test_a_note_on_a_held_name_opens_a_case_whose_first_message_has_the_claims_and_the_answer_is_what_the_case_did(con):
    chat = _chat(con)
    d = _doc(con, chat=chat)
    session.DEPS["gateway"] = g = Gate([ans("hold", "unclear", sym="WIN")])
    rows = chat_hooks.note_from_him(con, NOW, d, chat)
    r = [x for x in rows if x.get("symbol") == "WIN"][0]
    assert r["state"] == "case" and r["how"] == "opened" and r["thought"]["ok"]
    assert "opened an investigation into its order book" in json.dumps(g.seen_messages[0])     # the case's first message has the note's claims
    c = cases.get_case(con, r["case_id"])
    assert c["opened_by"] == "you" and c["kind"] == "news"
    assert "hold" in r["text"] and "if it goes badly -Rs 5,000" in r["text"] and "most likely Rs 1,000" in r["text"] and "if well Rs 9,000" in r["text"]    # one option, worst / likely / best in rupees
    assert chat_hooks.note_text(rows).startswith("WIN")
    assert any("because of the note you sent" in m["text"].lower() for m in _msgs(con, chat))   # the loop told that chat


def test_the_same_note_sent_twice_costs_one_read_and_opens_nothing_new(con):
    chat = _chat(con)
    d = _doc(con, chat=chat)
    session.DEPS["gateway"] = g = Gate([ans("hold", "unclear", sym="WIN")])
    first = chat_hooks.note_from_him(con, NOW, d, chat)
    n_calls, n_cases = len(g.calls), con.execute("SELECT count(*) FROM think_cases_s84").fetchone()[0]
    again = chat_hooks.note_from_him(con, NOW + timedelta(hours=1), d, chat)
    assert len(g.calls) == n_calls and con.execute("SELECT count(*) FROM think_cases_s84").fetchone()[0] == n_cases
    assert all(r.get("repeat") for r in again) and [r["symbol"] for r in again] == [r["symbol"] for r in first]


def test_a_note_that_adds_nothing_says_where_it_is_already_known_from(con):
    from pflab.think import recall
    chat = _chat(con)
    earlier = NOW - timedelta(days=3)
    recall.write_back(con, earlier, isin=WIN, symbol="WIN", title="Board investigation at Win", text="Win Ltd's board has opened an investigation into its order book, reported by the press.",
                      source="analyst")
    d = _doc(con, chat=chat)
    g = Gate([])
    session.DEPS["gateway"] = g
    rows = chat_hooks.note_from_him(con, NOW, d, chat)
    r = [x for x in rows if x.get("symbol") == "WIN"][0]
    assert r["state"] == "nothing_new" and r["known_from"]["source"] == "analyst" and "nothing new: already known from analyst" in r["text"]
    assert g.calls == [] and con.execute("SELECT count(*) FROM think_cases_s84").fetchone()[0] == 0


def test_a_note_about_the_whole_market_goes_to_the_storylines_and_tomorrows_plan(con):
    chat = _chat(con)
    d = _doc(con, claims=("Foreign investors turned net buyers of Indian equities this week",), isins=(), name="market note", chat=chat)
    rows = chat_hooks.note_from_him(con, NOW, d, chat)
    assert rows[0]["state"] == "market" and con.execute("SELECT count(*) FROM think_cases_s84").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM market_notes_s85").fetchone()[0] == 1
    assert "net buyers of Indian equities" in desk.plan_text(con, DAY + timedelta(days=1))      # the pre-open plan carries it
    assert con.execute("SELECT count(*) FROM recall_notes_s84 WHERE source='you'").fetchone()[0] == 1


def test_a_document_about_an_exposed_name_reaches_the_watch_as_an_event_like_any_other(con, tmp_path):
    from pflab.kg2 import you
    for k in range(4):                                                                          # what `readers` writes for documents he sent (news, a lead), here four on the day
        r = you.row(WIN, "you:isin_in_text", "the ISIN is written in the document", sha=f"s{k}", received_at=NOW - timedelta(hours=k + 1), headline=f"note {k} on the order book")
        con.execute("INSERT INTO kg2_event (event_id, isin, source, ref, ts, event_date, kind, severity, headline, link_rule, link_proof, dedupe_key, ts_rule) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [r["event_id"], r["isin"], "you", r["ref"], datetime.fromisoformat(r["received_at"]), date.fromisoformat(r["event_date"]), r["kind"], r["severity"], r["headline"],
                     r["link_rule"], r["link_proof"], r["dedupe_key"], "received_time"])
    res = watch.run(con, NOW, mode="close", root=tmp_path)
    assert any(s["isin"] == WIN and s["signal"] == "news_burst" for s in cases.signals(con))


# --- (5) the overrule and the chat tools -------------------------------------------------------------------------------------------------------------------------------------

def _says(**kw):
    f = {"kind": "none", "scope": "none", "value": "", "name": "", "market": "both", "until": "", "share_pct": 0, "terms": [], "amount_rupees": 0, "extra_rupees": 0, "below_high_pct": 0,
         "max_weight_pct": 0, "carry_over": False, "change_kind": "none", "change_key": "", "change_value": "", "loosens": False, "summary": ""}
    f.update(kw)
    return lambda system, messages, schema: f


def test_an_overrule_is_a_standing_instruction_and_a_record_on_the_case_scored_both_ways(con, monkeypatch):
    from pflab.think import odds
    chat = _chat(con)
    cid = chat_hooks.look_into(con, NOW, "WIN", chat, "check it")
    session.DEPS["gateway"] = Gate([ans("sell", "damage", sym="WIN")])
    from tests.test_s84_case import Rule
    Rule.nxt = {"rule_option": "sell", "size_inr": 0.0, "parts": 3, "reason": "damage is a thesis break", "guards": [], "refused": False}
    session.think_case(con, NOW, cid)
    r = chat_hooks.overrule(con, NOW, "WIN", "hold", chat, case_id=cid, words="hold it", gateway_call=_says(kind="hold_name", name="WIN", summary="hold WIN"))
    assert r["ok"] and r["user_option"] == "hold" and r["loop_option"] == "sell" and r["rule_id"]
    assert any(x["kind"] == "hold_name" and x["machine"].get("isin") == WIN for x in rules.active(con, DAY))                                  # a standing instruction on the name
    steps = [s for s in cases.steps(con, cid) if s["step"] == "overruled"]
    assert steps and json.loads(steps[0]["payload_json"])["user_option"] == "hold"
    # score both ways: move the overrule 30 sessions back so its 5-, 20- and 60-session horizons are inside the stored prices
    con.execute("UPDATE overrules_s85 SET day=?", [DAYS[-30]])
    monkeypatch.setattr(score, "_moves", lambda con, case, isin, symbol, d0, root=None: [-0.10, 0.0, 0.10])
    n = chat_hooks.score_user(con, DAY)
    assert n > 0
    tr = {r_[0] for r_ in con.execute("SELECT DISTINCT track FROM think_scores_s84 WHERE decision_id >= ?", [chat_hooks.USER_BASE]).fetchall()}
    assert {"user", "user_loop"} <= tr                                                          # his choice and the loop's, each scored against doing nothing
    assert chat_hooks.score_user(con, DAY) == 0                                                 # idempotent
    assert score._track(con, "user")["by_horizon"][5]["n"] >= 1 and chat_hooks.scorecard_text(con, DAY)


def test_an_overrule_that_loosens_a_rail_is_refused_and_a_name_without_a_case_still_makes_the_rule(con):
    r = chat_hooks.overrule(con, NOW, "WIN", "hold", None, gateway_call=_says(kind="hold_name", name="WIN", summary="hold WIN"))
    assert r["ok"] and r["case_id"] is None and "no case on this name" in r["message"]
    bad = chat_hooks.overrule(con, NOW, "WIN", "bad_action")
    assert not bad["ok"]


def test_the_chat_tools_are_registered_and_read_what_the_loop_holds(con):
    for name in ("thinking_cases", "case_outcomes", "decision_scorecard", "reserve", "what_do_you_know", "look_into", "suggest_stock", "overrule"):
        assert name in tools.REGISTRY and tools.REGISTRY[name][0]["name"] == name
    ctx = type("C", (), {})()
    ctx.con, ctx.now, ctx.chat_id, ctx.his_text = con, NOW, _chat(con), "look into WIN"
    out = tools.REGISTRY["look_into"][1](ctx, {"name": "WIN", "why": "he asked"})
    assert out["ok"] and out["how"] == "opened"
    cid = out["case_id"]
    session.DEPS["gateway"] = Gate([ans("hold", "unclear", sym="WIN")])
    session.think_case(con, NOW, cid)
    assert "WIN" in tools.REGISTRY["thinking_cases"][1](ctx, {})["text"]
    table = tools.REGISTRY["case_outcomes"][1](ctx, {"case_id": cid})
    assert "hold" in table["text"] and "bad" in table["text"]
    assert table["names"][0]["symbol"] == "WIN" and {o["option"] for o in table["names"][0]["options"]} == {"sell", "trim", "hold", "freeze", "wait", "buy_in_parts", "nothing"}
    assert table["names"][0]["acted"] == "hold" and table["names"][0]["why"]
    assert tools.REGISTRY["decision_scorecard"][1](ctx, {})["text"]
    assert tools.REGISTRY["reserve"][1](ctx, {})["text"]
    know = tools.REGISTRY["what_do_you_know"][1](ctx, {"name": "WIN"})
    assert know["symbol"] == "WIN" and "items" in know


# --- (6) a case that acts tells the chat --------------------------------------------------------------------------------------------------------------------------------------

def test_a_case_that_acts_because_of_something_from_the_entrance_says_so_in_that_chat(con, monkeypatch):
    monkeypatch.setattr(session, "_whole_book", lambda con, day: 1e12)
    from tests.test_s84_case import Rule
    chat = _chat(con)
    store.add_message(con, chat, "user", "look into WIN", channel="laptop", now=NOW)
    other = store.new_chat(con, NOW + timedelta(seconds=1), title="Another chat")
    assert other != chat
    cid = chat_hooks.look_into(con, NOW, "WIN", chat, "it worries me")
    Rule.nxt = {"rule_option": "trim", "size_inr": 100000.0, "parts": 3, "reason": "the rule trims on damage", "guards": [], "refused": False}
    session.DEPS["gateway"] = Gate([ans("trim", "damage", sym="WIN")], checks=["pass"])
    r = session.think_case(con, NOW, cid)
    assert r["ok"] and r["decisions"][0]["acted"] == "trim"
    mine = _msgs(con, chat)
    assert len(mine) == 1 and "you asked me to look into this" in mine[0]["text"].lower() and "trim" in mine[0]["text"] and "the rule trims on damage" in mine[0]["text"]
    assert _msgs(con, other) == []                                                              # told in the chat it came from, not in another
    assert chat_hooks.tell_chat(con, NOW, cid) is None                                          # once per stage
    Rule.nxt = {"rule_option": "hold", "size_inr": 0.0, "parts": 3, "reason": "the rule holds", "guards": [], "refused": False}


def test_the_new_files_have_no_control_characters():
    import pathlib
    for p in ("src/pflab/think/chat_hooks.py", "src/pflab/pm/mig_s79/m_loopchat85.py", "tests/test_s85_loopchat.py"):
        txt = pathlib.Path(__file__).resolve().parents[1].joinpath(p).read_text(encoding="utf-8")
        assert not [c for c in txt if ord(c) < 32 and c not in "\n\t\r"], p
