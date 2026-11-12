"""S84 F1 (room for the system's own Indian picks, his decision 2026-11-12) and F5 (the strategist's first message carries the scorecard and the PICKS section once). Synthetic data only.

The fixtures are those of tests/test_s83_picks.py (a small paper book: three Kite stocks, a gold ETF, cash)."""
from __future__ import annotations

import json
import re
from datetime import datetime, time, timedelta

import pytest

from pflab.core import pick_share, picks, picks_card, state as st
from pflab.lab import first_session_s82 as first
from pflab.lab import strategist
from pflab.learner import s83
from pflab.paper import book
from test_s83_picks import AAA, BBB, CCC, DAYS, FFF, INDEX, NOW, PROTOCOL, START, con, item, small_turnover, step  # noqa: F401


def _kite_weight(con) -> float:
    wts, _ = picks._weights(con, "IN", START)
    return sum(wts.get(i, 0.0) for i in (AAA, BBB, FFF))


# --- F1: the start rule ----------------------------------------------------------------------------------------------------------------

def test_the_share_becomes_his_kite_weight_plus_twenty_points_once_and_never_lower(con):
    assert pick_share.share(con, "IN")["share"] == pytest.approx(0.40) and not pick_share.decision_done(con)
    kw = _kite_weight(con)
    assert 0.2 < kw < 0.4                                                                       # the fixture's Kite stocks hold a quarter to a third of the India part
    out = pick_share.set_start_by_decision(con, NOW)
    assert out["done"] and out["new"] == pytest.approx(min(0.60, kw + 0.20), abs=2e-3) and out["new"] > 0.40
    sh = pick_share.share(con, "IN")
    assert sh["share"] == pytest.approx(out["new"]) and sh["shrinking"] is False and "his decision 2026-11-12" in sh["source"]
    n = con.execute("SELECT count(*) FROM sleeve_share_s83 WHERE market='IN'").fetchone()[0]
    again = pick_share.set_start_by_decision(con, NOW)
    assert again["done"] is False and con.execute("SELECT count(*) FROM sleeve_share_s83 WHERE market='IN'").fetchone()[0] == n       # idempotent by its reason
    assert pick_share.settings("IN")["start_share"] == 0.40 and pick_share.settings("IN")["max_share"] == 0.60                  # the range and the config's start stay
    assert pick_share.share(con, "US")["share"] == pytest.approx(0.50)                                                           # the US share is untouched


def test_the_start_is_capped_at_the_maximum_floored_at_the_current_share_and_waits_without_his_stocks(con, monkeypatch):
    monkeypatch.setattr(picks, "_weights", lambda c, m, d: ({AAA: 0.30, BBB: 0.20, FFF: 0.10}, {}))                 # Kite weight 60% + 20 points: over the maximum
    assert pick_share.set_start_by_decision(con, NOW)["new"] == pytest.approx(0.60)
    con.execute("DELETE FROM sleeve_share_s83")
    con.execute("INSERT INTO sleeve_share_s83 VALUES (1, 'IN', ?, 0.55, 0.55, 'judged level', '{}')", [START])
    monkeypatch.setattr(picks, "_weights", lambda c, m, d: ({AAA: 0.10}, {}))                                       # 10% + 20 points = 30% is under the current 55%: it stays
    assert pick_share.set_start_by_decision(con, NOW)["new"] == pytest.approx(0.55)
    con.execute("DELETE FROM sleeve_share_s83")
    monkeypatch.setattr(picks, "_weights", lambda c, m, d: ({}, {}))
    out = pick_share.set_start_by_decision(con, NOW)
    assert out["done"] is False and "waiting" in out["why"] and not pick_share.decision_done(con)


def test_the_judgment_rule_still_needs_a_system_pick_bought_and_steps_from_the_new_share(con):
    pick_share.set_start_by_decision(con, NOW)
    start = pick_share.share(con, "IN")["share"]
    rec = lambda c_, m_, d_: {"sessions": 60, "sleeve_return_after_tax": 0.05, "index_return": 0.03, "points_a_year": 3.0}      # noqa: E731
    assert pick_share.judge(con, NOW, "IN", START, rec)["judged"] is False                                          # no system pick bought yet: the gate stays
    con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, state, proposed_on) VALUES (99, 'IN', ?, 'CCC', 'system', 'held', ?)", [CCC, START])
    j = pick_share.judge(con, NOW, "IN", START, rec)
    assert j["judged"] and j["new"] == pytest.approx(min(0.60, start + 0.05))                                       # one step of five points


# --- F1: the sizing -------------------------------------------------------------------------------------------------------------------

def test_ordinary_picks_stop_at_ten_points_and_never_take_the_reserve(con, monkeypatch):
    assert picks.reserve_points("IN") == 10.0 and picks.reserve_points("US") == 10.0
    pick_share.set_start_by_decision(con, NOW)
    picks.propose(con, NOW, "IN", [item("CCC"), item("DDD")], session_ref="s1")
    s = st.build(con, START, None, INDEX)
    w = s["picks"]["weights"]
    sh = pick_share.share(con, "IN")["share"]
    system = w[CCC] + w.get("INE000D01014", 0.0)
    assert system <= 0.10 + 1e-3                                                                                   # ordinary picks use 10 of the 20 points
    kite_now = sum(r["value"] for r in s["rows"] if r["isin"] in (AAA, BBB, FFF)) / s["value"]
    assert kite_now + system <= sh - 0.10 + 1e-3                                                                   # the reserve's points are never planned for a pick
    card = picks_card.market_block(con, "IN", START)
    assert card["room"] <= max(0.0, sh - 0.10 - card["holds"]) + 1e-9
    assert "opportunity reserve" in picks_card.build(con, START)["text"]


def test_the_reserve_cash_refills_before_an_ordinary_pick_takes_any(con):
    pick_share.set_start_by_decision(con, NOW)
    picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s1")
    s = st.build(con, START, None, INDEX)
    total = s["value"]
    cur = {r["isin"]: r["value"] / total for r in s["rows"]}
    want = s["picks"]["weights"][CCC] - cur.get(CCC, 0.0)
    assert want > 0.05
    for cash_w, expect in ((0.10, 0.0), (0.13, 0.03), (0.40, want)):                                                # cash at the reserve: nothing; 3 points above it: 3 points; plenty: the whole gap
        s2 = {**s, "cash": cash_w * total, "bank": 0.0}
        got = picks.target_weights(con, s2, "IN")[CCC] - cur.get(CCC, 0.0)
        assert got == pytest.approx(min(want, expect), abs=1e-6), (cash_w, got)


def test_a_system_pick_is_bought_from_cash_over_the_closes_and_no_core_holding_is_sold(con, monkeypatch):
    small_turnover(monkeypatch, 0.03)
    pick_share.set_start_by_decision(con, NOW)
    picks.propose(con, NOW, "IN", [item("CCC")], session_ref="s1")
    bought = 0
    for d in [d for d in DAYS if d >= START][:12]:
        r = step(con, d)
        if isinstance(r.get("skipped"), str):
            continue
        bought += sum(1 for o in r.get("orders", []) if o["symbol"] == "CCC" and o["side"] == "buy")
    assert bought >= 2 and con.execute("SELECT state FROM picks_s83 WHERE symbol='CCC'").fetchone()[0] in ("buying", "held")
    sold = {r[0] for r in con.execute("SELECT DISTINCT isin FROM paper_trades WHERE side='sell'").fetchall()}
    assert "INF000G01015" not in sold and CCC not in sold                                                            # nothing in the core was sold to make room (gold ETF), no pick was sold
    assert sold <= {AAA}                                                                                             # the one sale is the fixture's Kite stock over the 10% company rail (a rail trim, as before S84)
    w = {r["isin"]: r["weight"] for r in book.holdings(con, DAYS[DAYS.index(START) + 14])["rows"]}
    assert w.get(CCC, 0.0) > 0.02


# --- F1: the amendment and the once-only picks session -----------------------------------------------------------------------------------

def test_the_amendment_pins_the_start_rule_and_is_counted_once(con):
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "Amendment A1, 2026-11-12" in text
    blk = json.loads(re.findall(r"```json amendment_a1\n(.*?)\n```", text, re.S)[0])
    assert blk == pick_share.RULE_A1 and blk["extra_points"] == blk["ordinary_points"] + blk["reserve_points"]
    assert blk["reserve_points"] == picks.reserve_points("IN") and blk["max_share"] == pick_share.RULE["IN"]["max_share"]
    assert pick_share.RULE["IN"]["start_share"] == 0.40                                                              # the rule block of section 4 is unchanged
    n0 = con.execute("SELECT count(*) FROM learn_tests").fetchone()[0]
    s83.register_picks_live(con, NOW)
    assert s83.register_picks_amendment_a1(con, NOW) == ["s84:picks_live_a1:IN"] and s83.register_picks_amendment_a1(con, NOW) == []
    assert con.execute("SELECT count(*) FROM learn_tests").fetchone()[0] == n0 + 3
    assert s83.protocol_ok(con)["unchanged"]


def test_the_first_indian_picks_session_is_once_only_waits_without_room_and_never_errors(con):
    now = datetime.combine(START, time(10, 0))
    assert first.REASON_PICKS_IN not in first.reasons(con, now)                                                      # no room written yet: nothing to name a pick for
    pick_share.set_start_by_decision(con, now)
    assert first.REASON_PICKS_IN in first.reasons(con, now) and first.KEY_PICKS_IN == "first_picks_in_s84" and first.KEYS[first.REASON_PICKS_IN] == "first_picks_in_s84"
    first.waiting(con, now, "no API key", keys=first.keys_in([first.REASON_PICKS_IN]))
    assert first.state(con, "first_picks_in_s84")["status"] == "waiting"
    assert first.REASON_PICKS_IN not in first.reasons(con, now)                                                      # one try a day
    assert first.REASON_PICKS_IN in first.reasons(con, now + timedelta(days=1))
    assert first.after_session(con, now, {"session_id": 7, "status": "done", "cost_inr": 12.0}, keys=first.keys_in([first.REASON_PICKS_IN])) == "done"
    assert first.REASON_PICKS_IN not in first.reasons(con, now + timedelta(days=9))                                  # done: never again


# --- F5: the first message ------------------------------------------------------------------------------------------------------------

def test_the_first_message_carries_the_scorecard_and_the_picks_section_once(con):
    pick_share.set_start_by_decision(con, NOW)
    from pflab.core import pick_score
    card_text = ("BOOK: value Rs 1\nSTORYLINES: none\nPICKS SCORE (after estimated tax, against the index):\n" + "\n".join(pick_score.scorecard_text(con, m) for m in ("IN", "US"))
                 + "\n" + picks_card.build(con, START)["text"])
    con.execute("INSERT INTO core_cards_s80 (day, made_at, text) VALUES (?, ?, ?)", [START, NOW, card_text])
    assert card_text.count("PICKS SCORE (") == 1 and card_text.count("PICKS, India") == 1
    msg = strategist._first_message(con, "a weekly session", 300.0, NOW)
    assert msg.count("PICKS SCORE (") == 1 and msg.count("PICKS, India") == 1 and msg.count("PICKS, US") == 1 and msg.count("WHAT I LEARNED") == 1
    assert "BOOK: value Rs 1" in msg and "STORYLINES: none" in msg                                                    # the rest of the card stays
    assert "PICKS, India" in card_text and "PICKS SCORE (" in con.execute("SELECT text FROM core_cards_s80").fetchone()[0]    # the stored card is unchanged (Today shows it)
    assert strategist.without_picks("BOOK: x") == "BOOK: x"                                                          # a card without the blocks is left as it is
