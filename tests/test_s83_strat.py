"""S83 L3 (the strategist names stocks), L8 (the first picks) and the US side of the picks. A scripted fake model stands in for Opus (rule 7: no real data, no paid call)."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from pflab.core import card, pick_share, picks, picks_card
from pflab.lab import first_session_s82 as first
from pflab.lab import service as lab
from pflab.lab import strategist, tools
from tests.test_s82_fills import _api_cfg, paid, scripted, tick, Msg  # noqa: F401  (fixtures and helpers)
from tests.test_s83_picks import BRK, CCC, NOW, START, TEXT, con, item, step  # noqa: F401  (the fixture: a small book with prices)


def ctx_for(con, tmp_path, now=NOW, sid=7):
    return tools.make_ctx(con, tmp_path, tmp_path, now, sid)


def score_five(con, market="IN"):
    """Five picks of the market with a one-month score each (the table of the score agent)."""
    for i in range(1, 6):
        con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, state, proposed_on) VALUES (?, ?, ?, ?, 'system', 'held', ?)", [500 + i, market, f"Y{i}", f"Y{i}", START])
        con.execute("INSERT INTO pick_scores_s83 (score_id, kind, ref_id, market, isin, horizon_months, excess_pct, return_pct, index_return_pct) VALUES (?, 'pick', ?, ?, ?, 1, 1.5, 3.0, 1.5)",
                    [800 + i, 500 + i, market, f"Y{i}"])


LEARNED = "My momentum-only picks lagged the index at one month, so I now ask for a margin trend and a clean balance sheet before I name a stock."


# --- the tools --------------------------------------------------------------------------------------------------------------------------------

def test_the_three_picks_tools_are_registered_short_and_take_no_size_price_or_weight():
    defs = {d["name"]: d for d in tools.definitions()}
    for n in ("propose_picks", "withdraw_pick", "skip_idea", "write_note"):
        assert n in defs and len(defs[n]["description"]) <= 480, (n, len(defs[n]["description"]))
    blob = json.dumps([defs[n]["input_schema"] for n in ("propose_picks", "withdraw_pick", "skip_idea")]).lower()
    for word in ("size", "price", "weight", "amount", "quantity", "qty", "percent", "share_of"):
        assert word not in blob, word
    assert set(defs["propose_picks"]["input_schema"]["properties"]) == {"market", "items", "learned_from"}
    assert set(defs["propose_picks"]["input_schema"]["properties"]["items"]["items"]["properties"]) == {"symbol", "thesis", "break_condition", "storylines"}
    assert len(tools.definitions()) <= 22
    assert all(len(d["description"]) < 480 for d in tools.definitions())


def test_propose_withdraw_and_skip_are_thin_wrappers_and_refusals_come_back_in_plain_words(con, tmp_path):
    ctx = ctx_for(con, tmp_path)
    text, err = tools.run(ctx, "propose_picks", {"market": "IN", "items": [{"symbol": "CCC", "thesis": TEXT, "break_condition": BRK, "storylines": []},
                                                                             {"symbol": "NOSUCH", "thesis": TEXT, "break_condition": BRK}]})
    out = json.loads(text)
    assert not err and out["ok"] and [a["symbol"] for a in out["accepted"]] == ["CCC"] and "not a listed share" in out["refused"][0]["reason"]
    row = con.execute("SELECT session_ref, source, state FROM picks_s83 WHERE symbol='CCC'").fetchone()
    assert row == ("strategist session 7", "system", "proposed") and ctx.stats["picks"] == 1
    text, err = tools.run(ctx, "propose_picks", {"market": "IN", "items": [{"symbol": "NOSUCH", "thesis": TEXT, "break_condition": BRK}]})
    out = json.loads(text)
    assert err and out["ok"] is False and "NOSUCH" in out["problem"] and "not a listed share" in out["problem"]
    text, err = tools.run(ctx, "propose_picks", {"market": "XX", "items": [item("CCC")]})
    assert err and "IN or US" in json.loads(text)["problem"]
    text, err = tools.run(ctx, "propose_picks", {"market": "IN", "items": []})
    assert err and "at least one" in json.loads(text)["problem"]
    text, err = tools.run(ctx, "skip_idea", {"market": "IN", "symbol": "DDD", "why": "too thin a story to hold for a year"})
    assert not err and json.loads(text)["ok"] and ctx.stats["skips"] == 1
    assert con.execute("SELECT symbol, session_ref FROM skips_s83").fetchone() == ("DDD", "strategist session 7")
    text, err = tools.run(ctx, "skip_idea", {"market": "IN", "symbol": "DDD", "why": "no"})
    assert err and "why you skipped" in json.loads(text)["problem"]
    text, err = tools.run(ctx, "withdraw_pick", {"market": "IN", "symbol": "CCC", "reason": "the margin trend I leaned on has turned down for two quarters"})
    assert not err and json.loads(text)["held"] is False
    assert con.execute("SELECT state FROM picks_s83 WHERE symbol='CCC'").fetchone()[0] == "withdrawn"
    text, err = tools.run(ctx, "withdraw_pick", {"market": "IN", "symbol": "ZZZ", "reason": "the margin trend I leaned on has turned down"})
    assert err and "not an active pick" in json.loads(text)["problem"]


def test_once_five_picks_have_a_score_the_batch_and_the_note_must_say_what_was_learned(con, tmp_path):
    ctx = ctx_for(con, tmp_path)
    ok = json.loads(tools.run(ctx, "write_note", {"text": "Looked at the book; nothing to change this week and no pick named."})[0])
    assert ok["ok"] and con.execute("SELECT learned FROM core_notes_s80").fetchone()[0] is None          # not needed yet
    score_five(con)
    assert picks.needs_learned(con, "IN") and not picks.needs_learned(con, "US")
    text, err = tools.run(ctx, "propose_picks", {"market": "IN", "items": [item("CCC")], "learned_from": "too short"})
    out = json.loads(text)
    assert err and "scorecard" in out["problem"] and "40" in out["problem"] and con.execute("SELECT count(*) FROM picks_s83 WHERE symbol='CCC'").fetchone()[0] == 0
    text, err = tools.run(ctx, "write_note", {"text": "A note that forgets the part about what the scorecard taught."})
    assert err and "learned" in json.loads(text)["problem"]
    text, err = tools.run(ctx, "write_note", {"text": "A note with the part about the scorecard.", "learned": "short"})
    assert err
    ok = json.loads(tools.run(ctx, "propose_picks", {"market": "IN", "items": [item("CCC")], "learned_from": LEARNED})[0])
    assert ok["ok"] and con.execute("SELECT learned_from FROM picks_s83 WHERE symbol='CCC'").fetchone()[0] == LEARNED
    ok = json.loads(tools.run(ctx, "write_note", {"text": "A note with the part about the scorecard.", "learned": LEARNED})[0])
    assert ok["ok"]
    assert lab.last_learned(con)["learned"] == LEARNED and lab.notes(con, 1)[0]["learned"] == LEARNED


# --- the session: a scripted model through the real run_session, llm.call, governor and egress ---------------------------------------------------

class Script:
    """Each create() call returns the next scripted turn: a list of (tool, input) pairs, or the text 'Done.'. The first request's first user message is kept."""
    def __init__(self, turns):
        self.turns, self.n, self.first = list(turns), 0, None
        self.messages = SimpleNamespace(count_tokens=lambda **k: SimpleNamespace(input_tokens=3000))
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **p):
        if self.first is None:
            self.first = p["messages"][0]["content"][0]["text"]
            self.system = p["system"][0]["text"]
        t = self.turns[min(self.n, len(self.turns) - 1)] if self.n < len(self.turns) else None
        self.n += 1
        if t is None:
            return Msg([SimpleNamespace(type="text", text="Done.")])
        blocks = [SimpleNamespace(type="tool_use", id=f"tu{self.n}_{i}", name=name, input=inp) for i, (name, inp) in enumerate(t)]
        return Msg(blocks, "tool_use")


def test_a_session_reads_the_scorecard_names_stocks_records_skips_and_is_not_wasted(con, tmp_path, paid):
    cl = Script([[("propose_picks", {"market": "IN", "items": [{"symbol": "CCC", "thesis": TEXT, "break_condition": BRK, "storylines": []}]}),
                  ("skip_idea", {"market": "IN", "symbol": "DDD", "why": "a story I could not tie to results in two quarters"})],
                 [("write_note", {"text": "First picks: named CCC for its steady margins; skipped DDD for want of a story."}), ("finish", {"summary": "named one pick, skipped one"})]])
    s = strategist.run_session(con, tmp_path, tmp_path, NOW, "the weekly session (re-examine the allocation)", client=cl, data={}, box=None)
    assert s["status"] == "done" and s["picks"] == 1 and s["skips"] == 1 and s["lab_runs"] == 0, s          # picks work is not a wasted session
    assert "PICKS SCORE" in cl.first and "PICKS, India" in cl.first and "share is 40%" in cl.first         # the scorecard and the sleeve are in the first message
    assert "PICKS, US" in cl.first and "propose_picks" in cl.system and "you never write a size, a price or a weight" in cl.system
    assert "do not pick stocks by hand" not in cl.system
    assert con.execute("SELECT symbol, session_ref FROM picks_s83 WHERE source='system'").fetchall() == [("CCC", f"strategist session {s['session_id']}")]
    assert lab.latest_strategist_note(con)["note"].startswith("First picks")


def test_a_session_with_no_picks_and_no_lab_run_is_still_wasted(con, tmp_path, paid):
    cl = Script([[("write_note", {"text": "Nothing was done this week at all, honestly."}), ("finish", {"summary": "nothing"})]])
    s = strategist.run_session(con, tmp_path, tmp_path, NOW, "the weekly session (re-examine the allocation)", client=cl, data={}, box=None)
    assert s["status"] == "wasted"


# --- the card's PICKS section -------------------------------------------------------------------------------------------------------------------

def test_the_picks_section_has_each_pick_the_share_and_why_and_the_last_learned(con, tmp_path):
    picks.adopt_kite_holdings(con, NOW)
    out = picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s1")
    pid = out["accepted"][0]["pick_id"]
    con.execute("INSERT INTO pick_scores_s83 (score_id, kind, ref_id, market, isin, horizon_months, excess_pct, return_pct, index_return_pct) VALUES (1, 'pick', ?, 'IN', 'x', 3, 2.5, 6.0, 3.5)", [pid])
    lab.write_note(con, NOW, 3, "A note about the week with enough words in it.", learned=LEARNED)
    b = picks_card.build(con, START + timedelta(days=10))
    inb = b["IN"]
    assert inb["share"] == 0.40 and "starting share" in inb["share_why"] and inb["on"]
    ccc = next(p for p in inb["picks"] if p["symbol"] == "CCC")
    assert ccc["state"] == "proposed" and ccc["days_held"] == 10 and ccc["vs_index"]["excess_pct"] == 2.5 and ccc["break_condition"] == BRK
    kite = [p for p in inb["picks"] if p["source"] == "kite"]
    assert kite and all("Kite" in picks_card._market_text(inb) for _ in kite[:1]) and kite[0]["vs_index"] is None
    assert 0.0 <= inb["room"] <= 0.40
    assert "+2.5 points against the index at 3 month(s)" in b["text"] and "not scored yet" in b["text"] and "Breaks if:" in b["text"] and "WHAT I LEARNED" in b["text"] and "margin trend" in b["text"]
    assert b["learned"]["learned"] == LEARNED
    json.dumps({k: v for k, v in b.items() if k != "text"}, default=str)                                       # JSON-able


def test_the_book_card_carries_the_picks_section_in_text_and_json(con):
    picks.adopt_kite_holdings(con, NOW)
    step(con, date(2026, 11, 2))
    row = con.execute("SELECT text, facts_json FROM core_cards_s80 ORDER BY day DESC LIMIT 1").fetchone()
    assert "PICKS, India" in row[0] and "WHAT I LEARNED (last note): nothing written yet" in row[0]
    facts = json.loads(row[1])
    assert facts["picks"]["IN"]["share"] == 0.40 and facts["picks"]["learned"] is None and "text" not in facts["picks"]


# --- L8: the first picks -----------------------------------------------------------------------------------------------------------------------------

def test_the_first_session_and_the_first_picks_are_one_session_and_both_keys_move_together(con, tmp_path, scripted, monkeypatch):
    monkeypatch.setattr(strategist, "due", lambda c, n: [])
    now = datetime(2026, 11, 12, 10, 0)
    out = tick(con, tmp_path, now)
    assert scripted["n"] == 1 and out["first_session_s82"] == "done"
    assert first.state(con)["status"] == "done" and first.state(con, first.KEY_PICKS)["status"] == "done" and first.state(con, first.KEY_PICKS)["session_id"] == first.state(con)["session_id"]
    assert tick(con, tmp_path, now + timedelta(days=2)).get("nothing_due") and scripted["n"] == 1
    assert first.reasons(con, now + timedelta(days=30)) == []


def test_after_the_s82_session_only_the_picks_session_runs_and_once(con, tmp_path, scripted, monkeypatch):
    monkeypatch.setattr(strategist, "due", lambda c, n: [])
    now = datetime(2026, 11, 12, 10, 0)
    first._write(con, now - timedelta(days=3), "done", "the first session ran", session_id=1, cost=10.0)             # the S82 session ran before this release
    assert first.reasons(con, now) == [first.REASON_PICKS]
    seen = []
    import pflab.lab.strategist as st
    real = st.run_session

    def spy(con_, pm, root, n, reason, **kw):
        seen.append(reason)
        return scripted_run(con_, pm, root, n, reason, **kw)
    scripted_run = strategist.run_session                                                              # the scripted stand-in from the fixture
    monkeypatch.setattr(st, "run_session", spy)
    out = tick(con, tmp_path, now)
    assert len(seen) == 1 and first.REASON_PICKS[:40] in seen[0] and first.REASON not in seen[0] and out["first_session_s82"] == "done"
    assert tick(con, tmp_path, now + timedelta(days=1)).get("nothing_due")
    assert first.state(con)["attempts"] == 1                                                              # the S82 key was not touched again
    del real


def test_his_kite_stocks_are_adopted_at_that_first_open(con, tmp_path, scripted, monkeypatch):
    monkeypatch.setattr(strategist, "due", lambda c, n: [])
    assert con.execute("SELECT count(*) FROM picks_s83").fetchone()[0] == 0
    tick(con, tmp_path, datetime(2026, 10, 30, 10, 0))
    assert con.execute("SELECT count(*) FROM picks_s83 WHERE source='kite' AND state='held'").fetchone()[0] == 3
    assert picks.adopt_kite_holdings(con, datetime(2026, 10, 30, 10, 0)) == []                            # idempotent


def test_no_client_or_no_cap_room_says_no_picks_yet_and_never_raises(con, tmp_path, scripted, monkeypatch):
    from pflab.agents import analyst as an
    monkeypatch.setattr(strategist, "due", lambda c, n: [])
    now = datetime(2026, 11, 12, 10, 0)
    assert first.picks_line(con).startswith("no picks yet: the first picks session has not run")

    def no_key():
        raise RuntimeError("no API key in secrets.toml")
    out = tick(con, tmp_path, now, client_fn=no_key)
    assert "no cloud client" in out["skipped"] and scripted["n"] == 0
    line = first.picks_line(con)
    assert line.startswith("no picks yet: waiting: no cloud client") and "his Kite stocks, the core and SPY" in line
    assert first.state(con)["status"] == "waiting" and first.state(con, first.KEY_PICKS)["status"] == "waiting"
    monkeypatch.setattr(an, "config", lambda path=None: _api_cfg(cap=0.0))
    out = tick(con, tmp_path, now + timedelta(days=1))
    assert "no paid cap" in out["first_session_s82"] and scripted["n"] == 0
    assert "no picks yet: waiting: no paid cap" in first.picks_line(con)
    ex = card.today_extras(con)
    assert ex["picks"]["line"].startswith("no picks yet") and ex["picks"]["IN"]["share"] == 0.40


def test_a_failed_first_picks_session_leaves_the_book_as_it_is_and_stops_after_two_paid_failures(con, tmp_path, paid, monkeypatch):
    monkeypatch.setattr(strategist, "due", lambda c, n: [])
    monkeypatch.setattr(strategist, "run_session", lambda con_, *a, **k: {"session_id": 9, "status": "failed", "cost_inr": 3.0})
    before = con.execute("SELECT count(*) FROM picks_s83 WHERE source='system'").fetchone()[0]
    for k in range(4):
        tick(con, tmp_path, datetime(2026, 11, 12, 10, 0) + timedelta(days=k))
    assert first.state(con, first.KEY_PICKS)["paid_attempts"] == 2 and con.execute("SELECT count(*) FROM picks_s83 WHERE source='system'").fetchone()[0] == before
    assert "failed 2 times" in first.picks_line(con)


def test_once_the_system_has_a_pick_the_no_picks_line_goes_away(con):
    picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s1")
    assert first.picks_line(con) is None
