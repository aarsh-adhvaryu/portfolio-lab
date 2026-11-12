"""S84 (T4, T5, T8): the outcomes in rupees (`think/odds.py`), the registered rule (`think/rule.py`), the scoring and calibration (`think/score.py`) and the live protocol. Synthetic data only (rule 7)."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pflab import think
from pflab.core import tax_rows
from pflab.ledger import events as ev
from pflab.ledger import system
from pflab.paper import book
from pflab.pm import store
from pflab.think import cases, odds, rule

WIN, NEW, OPP, IDX = "INE000A01011", "INE000B01012", "INE000C01013", "INF000G01015"
NOW = datetime(2026, 11, 12, 16, 0)
DAYS = [d.date() for d in pd.bdate_range("2025-08-01", "2026-11-12")]
DAY = DAYS[-1]
PROTOCOL = Path(__file__).resolve().parents[1] / "docs" / "protocols" / "s84_thinking_live_protocol.md"
RATES = {5: {"n": 30, "p10": -0.10, "p50": 0.0, "p90": 0.10}, 20: {"n": 30, "p10": -0.20, "p50": 0.0, "p90": 0.20}, 60: {"n": 30, "p10": -0.30, "p50": 0.0, "p90": 0.30},
         "basis": "history", "history_n": 30, "kind": "move", "detail": "30 synthetic cases"}
CAL = {"worst": "unlikely", "likely": "even", "best": "unlikely"}
BUY = {"worst": "very unlikely", "likely": "even", "best": "likely"}                      # a case for buying: the good outcome is likelier than the bad one


def _path(seed: int, end: float, n: int, vol: float = 0.015) -> np.ndarray:
    """A random walk with a fixed seed that ends exactly at `end` on the last day."""
    r = np.random.default_rng(seed).normal(0.0, vol, n)
    p = 100.0 * np.exp(np.cumsum(r))
    return p * (end / p[-1])


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    c = store.connect(tmp_path / "l.duckdb")
    for isin, cls, tc, sym, name, sec in ((WIN, "equity", "EQUITY", "WIN", "Win Ltd", "Banks"), (NEW, "equity", "EQUITY", "NEW", "New Ltd", "Auto"), (OPP, "equity", "EQUITY", "OPP", "Opp Ltd", "Pharma"),
                                          (IDX, "etf", "LISTED_NONEQUITY", "IDXBEES", "Index Bees", None)):
        c.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, sector, source, built_at) VALUES (?, 'isin', ?, ?, TRUE, ?, ?, ?, 'synthetic', now())",
                  [isin, cls, tc, sym, name, sec])
    c.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha')")
    log = ev.EventLog()
    log.append(ev.Event(kind="deposit", account_id="ZER", date=date(2023, 1, 1), amount=9_000_000.0))
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2024, 1, 10), isin=WIN, qty=4000, price=50.0))          # long-term, a gain of Rs 50 a share at 100
    log.append(ev.Event(kind="buy", account_id="ZER", date=date(2026, 9, 1), isin=NEW, qty=1000, price=90.0))           # short-term
    ev.save(c, log, NOW)
    paths = {WIN: _path(1, 100.0, len(DAYS)), NEW: _path(2, 100.0, len(DAYS)), OPP: _path(3, 200.0, len(DAYS)), IDX: _path(4, 50.0, len(DAYS), 0.008)}
    for isin, p in paths.items():
        c.executemany("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", [[isin, d, float(x)] for d, x in zip(DAYS, p)])
    system.switch(c, tmp_path, DAYS[-6], NOW, start_cash=20_000_000.0)
    book.seed(c, DAYS[-6], NOW)
    book.catch_up(c, DAY, datetime.combine(DAY, datetime.min.time()) + timedelta(hours=21))
    c.execute("INSERT INTO paper_trades VALUES (9001, ?, 9001, NULL, ?, 'X', 'sell', 100, 100.0, 10.0, 200000.0, 40000.0, ?)",
              [date(2026, 8, 3), WIN, json.dumps({"gains": {"st_eq": 200000.0}})])
    monkeypatch.setattr(odds, "_index_series", lambda market, root=None: None)           # no index file in a test: raw returns
    return c


def _case(con, isin=WIN, symbol="WIN", kind="move", klass=None, pending=None, signals=((("move_1d"), -0.095),), day=DAY):
    sids = [cases.record_signal(con, datetime.combine(day, datetime.min.time()) + timedelta(hours=15), market="IN", isin=isin, symbol=symbol, signal=n, value=v, threshold=0.05, surprise=3.0,
                                exposure_inr=400000, score=2.0) for n, v in signals]
    cid = cases.open_case(con, datetime.combine(day, datetime.min.time()) + timedelta(hours=15), market="IN", kind=kind, isin=isin, symbol=symbol, title=f"{symbol} moved", exposure_inr=400000,
                          exposure_pct=0.02, score=2.0, signal_ids=sids)
    cases.set_case(con, cid, klass=klass, pending=pending)
    return cid


def _answer(klass, option=None, words=None, pending=None, isin=OPP, symbol="OPP", **kw):
    words = words or (BUY if option == "buy_in_parts" else CAL)
    res = kw.pop("pending_resolved_on", None)
    return {"class": klass, "pending": pending, "pending_resolved_on": res, "choices": [{"isin": isin, "symbol": symbol, "option": option, "words": words, **kw}]}


@pytest.fixture
def fixed_rates(monkeypatch):
    monkeypatch.setattr(odds, "base_rates", lambda con, kind, **kw: dict(RATES))


def _whole(con):
    return odds.whole_book(con, DAY)


# --- the protocol is the code ----------------------------------------------------------------------------------------------------------------------

def test_the_protocols_json_block_is_the_codes_constants_and_the_configs():
    block = json.loads(re.search(r"```json rule\n(.*?)\n```", PROTOCOL.read_text(encoding="utf-8"), re.S).group(1))
    assert block == json.loads(json.dumps(rule.RULE))                                     # the whole block, key for key
    s = think.settings()
    for k in ("bet_worst_pct_book", "reserve_third_per_name", "market_fall_reserve_share", "parts", "parts_gap_sessions", "damage_wait_sessions", "new_low_sessions", "new_low_clear_days",
              "sale_beats_holding_pts", "stretched_sigmas", "big_trade_share", "advisory_after_scored", "base_rate_min_n"):
        assert block[k] == pytest.approx(s[k]), k
    assert block["word_p_start"] == think.WORD_P and block["advisory_after_scored"] == 20 and block["base_rate_min_n"] == 20


# --- base rates ------------------------------------------------------------------------------------------------------------------------------------

def _crash_world(con, n_names: int, drop_every: int = 120, future_crash: bool = False):
    """`n_names` names with a -8% day every `drop_every` sessions (then a drift of +0.3% a day for a while): the history a base rate reads."""
    rows = []
    for k in range(n_names):
        isin = f"INE9{k:05d}01"
        r = np.random.default_rng(100 + k).normal(0.0004, 0.01, len(DAYS))
        for j in range(60 + k, len(DAYS), drop_every):
            r[j] = -0.08
            r[j + 1:j + 21] += 0.003
        if future_crash:
            r[-40] = -0.3
        p = 100.0 * np.exp(np.cumsum(r))
        rows += [[isin, d, float(x)] for d, x in zip(DAYS, p)]
    con.executemany("INSERT INTO prices VALUES (?, ?, ?, 'EQ', 'nse_bhavcopy', now())", rows)


def test_base_rates_come_from_stored_history_with_the_count_and_never_look_ahead(con):
    _crash_world(con, 12)
    asof = DAYS[-120]
    a = odds.base_rates(con, "move", move=-0.08, isin=WIN, asof=asof, market="IN")
    assert a["basis"] == "history" and a["history_n"] >= 20 and a[20]["n"] == a["history_n"]
    assert a[20]["p10"] < a[20]["p50"] < a[20]["p90"] and a[5]["n"] >= a[20]["n"] >= a[60]["n"]
    assert a[20]["p50"] > 0                                                              # the synthetic world rebounds after a crash day
    before = json.dumps(a, default=str)
    _crash_world_future = con.execute("SELECT count(*) FROM prices WHERE date > ?", [asof]).fetchone()[0]
    assert _crash_world_future > 0
    con.execute("UPDATE prices SET close = close * 0.2 WHERE date > ?", [asof])           # a crash after the day changes nothing the day could know
    b = odds.base_rates(con, "move", move=-0.08, isin=WIN, asof=asof, market="IN")
    assert json.dumps(b, default=str) == before


def test_under_twenty_cases_the_count_is_said_and_the_own_range_stands_in(con):
    r = odds.base_rates(con, "move", move=-0.08, isin=WIN, asof=DAY, market="IN")             # only 4 names in the store, no -8% days
    assert r["basis"] == "own range" and r["history_n"] < 20 and "only" in r["detail"] and str(r["history_n"]) in r["detail"]
    vol = odds.daily_vol(odds.closes(con, "IN", WIN, "WIN", DAY, 260))
    assert r[20]["p10"] == pytest.approx(np.exp(-odds.Z90 * vol * np.sqrt(20)) - 1) and r[20]["p50"] == 0.0 and r[20]["p90"] > 0
    assert r["vol_source"] == "its own last 250 sessions"
    short = odds.base_rates(con, "move", move=-0.08, isin="INE000Z00000", asof=DAY, market="IN")
    assert short["basis"] == "own range" and "30%" in short["vol_source"]


# --- outcomes in rupees, worked by hand --------------------------------------------------------------------------------------------------------------

def test_a_sale_and_a_hold_in_rupees_after_the_charges_and_the_tax_of_the_engine(con):
    cid = _case(con)
    px = book.close_on(con, WIN, DAY)[1]
    qty = book.positions(con)[WIN]
    assert qty == 4000 and px == pytest.approx(100.0)
    v0 = qty * px
    sell = odds.outcomes(con, cid, "sell", isin=WIN, asof=DAY, rates=dict(RATES), words=CAL)
    fee = book._charges("equity", "sell", v0)
    gain = v0 - qty * 50.0 - fee                                                         # one long-term lot
    tax = 0.125 * (gain - 125000.0)                                                      # the exemption row of the year (the test's other gains are short-term)
    assert sell["tax_inr"] == pytest.approx(tax, rel=1e-6) and sell["size_inr"] == pytest.approx(v0)
    assert sell["worst_inr"] == sell["likely_inr"] == sell["best_inr"] == pytest.approx(v0 - fee - tax - v0, rel=1e-6)
    assert sell["worst_pct_book"] == pytest.approx(sell["worst_inr"] / _whole(con)) and sell["basis"] == "history"
    hold = odds.outcomes(con, cid, "hold", isin=WIN, asof=DAY, rates=dict(RATES), words=CAL)
    d_h = odds._horizon_day(DAY, 20)
    for key, m in (("worst_inr", -0.20), ("likely_inr", 0.0), ("best_inr", 0.20)):
        v = v0 * (1 + m)
        fee_m = book._charges("equity", "sell", v)
        tax_m = 0.125 * max(0.0, (v - qty * 50.0 - fee_m) - 125000.0)
        assert hold[key] == pytest.approx(v - fee_m - tax_m - v0, rel=1e-6), key
    assert hold["worst_inr"] < sell["worst_inr"] and hold["best_inr"] > sell["best_inr"] and d_h > DAY
    w = odds.weights(CAL, cases.probabilities(con))
    assert w == pytest.approx([0.25 / 1.0, 0.5 / 1.0, 0.25 / 1.0]) and hold["expected_inr"] == pytest.approx(sum(a * b for a, b in zip(w, (hold["worst_inr"], hold["likely_inr"], hold["best_inr"]))))
    assert odds.weights(None) == [0.3, 0.4, 0.3] and odds.weights({"worst": "bad"}) == [0.3, 0.4, 0.3]    # no words, or a word not on the list: 30 / 40 / 30
    trim = odds.outcomes(con, cid, "trim", isin=WIN, asof=DAY, rates=dict(RATES), words=CAL)
    assert trim["size_inr"] == pytest.approx(v0 / 2) and trim["worst_inr"] < trim["likely_inr"] < trim["best_inr"]
    # the trim's sale now uses the year's exemption; the half kept is valued at the horizon on top of it (the exemption is not used twice)
    half_fee = book._charges("equity", "sell", v0 / 2)
    gain_now = v0 / 2 - qty / 2 * 50.0 - half_fee
    tax_now = 0.125 * max(0.0, gain_now - 125000.0)
    fee_h = book._charges("equity", "sell", v0 / 2)
    gain_h = v0 / 2 - qty / 2 * 50.0 - fee_h
    tax_h = 0.125 * (max(0.0, gain_now + gain_h - 125000.0) - max(0.0, gain_now - 125000.0))
    assert trim["likely_inr"] == pytest.approx((v0 / 2 - half_fee - tax_now) + (v0 / 2 - fee_h - tax_h) - v0, rel=1e-6)


def test_a_buy_in_rupees_after_charges_and_the_short_term_tax_and_a_name_not_held_has_nothing_at_stake_in_a_hold(con):
    cid = _case(con, isin=OPP, symbol="OPP")
    b = odds.outcomes(con, cid, "buy_in_parts", isin=OPP, asof=DAY, bet_inr=100000.0, rates=dict(RATES), words=CAL)
    n = 100000.0
    buy = book._charges("equity", "buy", n)
    v = n * 1.2
    sell = book._charges("equity", "sell", v)
    tax = 0.20 * max(0.0, v - n - sell)
    assert b["best_inr"] == pytest.approx(n * ((v - sell - tax) / (n + buy) - 1.0), rel=1e-6) and b["size_inr"] == 100000.0
    assert b["worst_inr"] < 0 < b["best_inr"] and b["worst_pct_book"] == pytest.approx(b["worst_inr"] / _whole(con))
    h = odds.outcomes(con, cid, "hold", isin=OPP, asof=DAY, rates=dict(RATES))
    assert (h["worst_inr"], h["likely_inr"], h["best_inr"], h["expected_inr"]) == (0.0, 0.0, 0.0, 0.0) and "not held" in " ".join(h["notes"])


def test_the_one_percent_bet_is_sized_from_the_worst_case_and_a_wider_worst_case_sizes_it_down(con):
    cid = _case(con, isin=OPP, symbol="OPP")
    whole = _whole(con)
    s = odds.bet_size(con, cid, OPP, DAY, rates=dict(RATES))
    w = s["worst_per_inr"]
    assert -0.21 < w < -0.199 and s["limit_inr"] == pytest.approx(0.01 * whole)
    assert s["size_inr"] == pytest.approx(0.01 * whole / abs(w))
    o = odds.outcomes(con, cid, "buy_in_parts", isin=OPP, asof=DAY, rates=dict(RATES))                 # no bet stated: the A66 size
    assert o["size_inr"] == pytest.approx(s["size_inr"]) and o["worst_pct_book"] == pytest.approx(-0.01, rel=1e-6)
    wide = {**RATES, 20: {"n": 30, "p10": -0.60, "p50": 0.0, "p90": 0.60}}
    s2 = odds.bet_size(con, cid, OPP, DAY, rates=wide)
    assert s2["size_inr"] < s["size_inr"] / 2.5 and s2["size_inr"] * abs(s2["worst_per_inr"]) == pytest.approx(0.01 * whole)
    calm = {**RATES, 20: {"n": 30, "p10": 0.01, "p50": 0.02, "p90": 0.05}}                            # a bad case with no loss: no size from the limit
    assert odds.bet_size(con, cid, OPP, DAY, rates=calm)["size_inr"] is None


def test_the_option_table_maps_the_words_through_the_stores_probabilities(con, fixed_rates):
    cid = _case(con)
    ans = {"class": "temporary", "choices": [{"isin": WIN, "symbol": "WIN", "option": "hold", "words": {"worst": "very likely", "likely": "unlikely", "best": "very unlikely"}}]}
    t = odds.option_table(con, cid, ans, DAY)
    assert {r["option"] for r in t} == set(think.OPTIONS) and [r["option"] for r in t if r["chosen"]] == ["hold"] and {r["track"] for r in t} == {"model", "alt"}
    base = next(r for r in t if r["option"] == "hold")
    assert base["weights"] == pytest.approx([0.95 / 1.25, 0.25 / 1.25, 0.05 / 1.25])
    con.execute("DELETE FROM think_calibration_s84")
    cases.seed_calibration(con, DAY)
    con.execute("UPDATE think_calibration_s84 SET probability=0.5 WHERE word='very likely'")           # the table moves the weights
    t2 = odds.option_table(con, cid, ans, DAY)
    assert next(r for r in t2 if r["option"] == "hold")["weights"] == pytest.approx([0.5 / 0.8, 0.25 / 0.8, 0.05 / 0.8])
    opp = _case(con, isin=OPP, symbol="OPP")
    t3 = odds.option_table(con, opp, _answer("temporary", "buy_in_parts"), DAY)
    assert {r["option"] for r in t3} == {"freeze", "wait", "buy_in_parts", "nothing"}                  # not held: no sell, trim or hold


# --- the rule --------------------------------------------------------------------------------------------------------------------------------------

def test_a_held_name_with_damage_is_a_thesis_break_and_is_sold_and_an_unclear_one_with_something_pending_is_frozen(con, fixed_rates):
    cid = _case(con)
    d = rule.decide(con, cid, _answer("damage", "hold", isin=WIN, symbol="WIN"), DAY)
    v0 = 400000.0
    assert d["rule_option"] == "sell" and d["thesis_break"] and d["size_inr"] == pytest.approx(v0) and "thesis break" in d["reason"] and d["refused"] is False
    assert d["big_trade_check"] is (v0 > 0.02 * _whole(con))
    f = rule.decide(con, cid, _answer("unclear", "sell", isin=WIN, symbol="WIN", pending="the board's decision"), DAY)
    assert f["rule_option"] == "freeze" and "board" in f["reason"] and f["size_inr"] == 0.0 and not f["thesis_break"]


def test_a_sale_must_beat_holding_by_one_point_of_the_position(con, monkeypatch):
    cid = _case(con)
    w_bad = {"worst": "very likely", "likely": "unlikely", "best": "very unlikely"}
    monkeypatch.setattr(odds, "base_rates", lambda con, kind, **kw: dict(RATES))
    d = rule.decide(con, cid, _answer("temporary", "hold", words=w_bad, isin=WIN, symbol="WIN"), DAY)
    assert d["rule_option"] == "sell" and "beats holding" in d["reason"]                                 # an expected -14% against a bar of 1%
    even = rule.decide(con, cid, _answer("temporary", "sell", words=CAL, isin=WIN, symbol="WIN"), DAY)
    assert even["rule_option"] == "hold" and "no sale beats holding" in even["reason"]                   # symmetric words: a sale gains nothing over holding
    slight = {**RATES, 20: {"n": 30, "p10": -0.05, "p50": -0.004, "p90": 0.03}}                          # expected about -1.5%: a sale clears 1% of the position only if it beats holding by that
    monkeypatch.setattr(odds, "base_rates", lambda con, kind, **kw: dict(slight))
    w = {"worst": "even", "likely": "even", "best": "even"}
    d2 = rule.decide(con, cid, _answer("temporary", "hold", words=w, isin=WIN, symbol="WIN"), DAY)
    t = {o: odds.outcomes(con, cid, o, isin=WIN, asof=DAY, rates=dict(slight), words=w) for o in ("sell", "hold", "trim")}
    gain = t["sell"]["expected_inr"] - t["hold"]["expected_inr"]
    assert (d2["rule_option"] in ("sell", "trim")) == (max(gain, t["trim"]["expected_inr"] - t["hold"]["expected_inr"]) >= 0.01 * 400000.0)


def _buy_case(con, **kw):
    return _case(con, isin=OPP, symbol="OPP", **kw)


def _calm_tail(con, isin, n_up: int = 4):
    """The name rallies for its last `n_up` sessions (so it is no longer making new lows)."""
    p = con.execute("SELECT close FROM prices WHERE isin=? AND date=?", [isin, DAYS[-n_up - 1]]).fetchone()[0]
    for k in range(1, n_up + 1):
        con.execute("UPDATE prices SET close=? WHERE isin=? AND date=?", [p * (1.0 + 0.004 * k), isin, DAYS[-n_up - 1 + k]])


def _new_lows(con, isin):
    p = con.execute("SELECT min(close) FROM prices WHERE isin=? AND date>=?", [isin, DAYS[-30]]).fetchone()[0]
    for k in range(1, 6):
        con.execute("UPDATE prices SET close=? WHERE isin=? AND date=?", [p * (1.0 - 0.01 * k), isin, DAYS[-6 + k]])


def test_new_money_is_sized_by_the_one_percent_limit_the_stock_rail_and_a_third_of_the_reserve(con, fixed_rates):
    _calm_tail(con, OPP)
    whole = _whole(con)
    cid = _buy_case(con)
    big = rule.decide(con, cid, _answer("temporary", "buy_in_parts"), DAY, reserve_free_inr=60_000_000.0)         # reserve not binding: the 1% limit binds
    total = big["parts"]["total_inr"]
    assert big["rule_option"] == "buy_in_parts" and not big["refused"] and big["parts"]["n"] == 3 and big["parts"]["this_part"] == 1
    assert total == pytest.approx(0.01 * whole / abs(odds.bet_size(con, cid, OPP, DAY, rates=dict(RATES))["worst_per_inr"]), rel=1e-9)
    assert big["size_inr"] == pytest.approx(total / 3) and "the 1% limit" in " ".join(big["guards"]) and big["big_trade_check"] is True        # every reserve buy is checked
    third = rule.decide(con, cid, _answer("temporary", "buy_in_parts"), DAY, reserve_free_inr=300_000.0)          # a third of the reserve per name binds
    assert third["parts"]["total_inr"] == pytest.approx(100_000.0) and third["size_inr"] == pytest.approx(100_000.0 / 3) and "a third of the reserve" in " ".join(third["guards"])
    wide = {**RATES, 20: {"n": 30, "p10": -0.60, "p50": 0.0, "p90": 0.80}}                                          # the bad case is wider: sized DOWN to fit 1%
    import pflab.think.odds as o
    o.base_rates = lambda con, kind, **kw: dict(wide)
    try:
        d = rule.decide(con, cid, _answer("temporary", "buy_in_parts"), DAY, reserve_free_inr=60_000_000.0)
    finally:
        o.base_rates = lambda con, kind, **kw: dict(RATES)
    assert d["rule_option"] == "buy_in_parts" and d["parts"]["total_inr"] < total / 2.5
    assert abs(d["outcome"]["worst_inr"]) == pytest.approx(0.01 * whole, rel=1e-6) and d["outcome"]["worst_pct_book"] == pytest.approx(-0.01, rel=1e-6)


def test_a_bet_that_does_not_fit_or_is_not_positive_or_is_too_small_is_refused(con, fixed_rates):
    _calm_tail(con, OPP)
    cid = _buy_case(con)
    tiny = rule.decide(con, cid, _answer("temporary", "buy_in_parts"), DAY, reserve_free_inr=3000.0)               # a third of Rs 3,000, a part of Rs 333
    assert tiny["rule_option"] == "nothing" and tiny["refused"] and tiny["size_inr"] == 0.0 and "minimum trade" in tiny["reason"] + " ".join(tiny["guards"])
    bad = {"worst": "very likely", "likely": "unlikely", "best": "very unlikely"}
    neg = rule.decide(con, cid, _answer("temporary", "buy_in_parts", words=bad), DAY, reserve_free_inr=60_000_000.0)
    assert neg["rule_option"] == "nothing" and neg["refused"] and "not positive" in " ".join(neg["guards"])
    none = rule.decide(con, cid, _answer("temporary", "buy_in_parts"), DAY, reserve_free_inr=0.0)                  # no reserve: nothing may be spent
    assert none["rule_option"] == "nothing" and none["refused"] and none["size_inr"] == 0.0


def test_the_timing_guards_each_way(con, fixed_rates):
    cid = _buy_case(con)
    _new_lows(con, OPP)
    low = rule.decide(con, cid, _answer("temporary", "buy_in_parts"), DAY, reserve_free_inr=60_000_000.0)
    assert low["rule_option"] == "wait" and low["refused"] and "new lows" in " ".join(low["guards"])
    _calm_tail(con, OPP)
    ok = rule.decide(con, cid, _answer("temporary", "buy_in_parts"), DAY, reserve_free_inr=60_000_000.0)
    assert ok["rule_option"] == "buy_in_parts"
    dmg = rule.decide(con, cid, _answer("damage", "buy_in_parts", pending="the board's decision"), DAY, reserve_free_inr=60_000_000.0)       # a damage name: no buying, wait for the event
    assert dmg["rule_option"] == "wait" and dmg["size_inr"] == 0.0
    # it WAS a damage case; the pending outcome is public now but fewer than 10 sessions ago: still wait; 10 sessions ago: allowed
    c2 = _buy_case(con, klass="damage")
    young = rule.decide(con, c2, _answer("temporary", "buy_in_parts", pending_resolved_on=str(DAYS[-4])), DAY, reserve_free_inr=60_000_000.0)
    assert young["rule_option"] == "wait" and "sessions after its pending outcome" in " ".join(young["guards"])
    old = rule.decide(con, c2, _answer("temporary", "buy_in_parts", pending_resolved_on=str(DAYS[-11])), DAY, reserve_free_inr=60_000_000.0)
    assert old["rule_option"] == "buy_in_parts"
    assert rule.decide(con, c2, _answer("temporary", "buy_in_parts"), DAY, reserve_free_inr=60_000_000.0)["rule_option"] == "wait"              # a damage case with no public outcome: wait


def test_a_missed_run_is_not_bought_on_a_stretched_day_and_a_calm_one_is(con, fixed_rates):
    cid = _case(con, isin=OPP, symbol="OPP", kind="missed_run", signals=(("missed_run", 22.0),))
    _calm_tail(con, OPP)
    p = con.execute("SELECT close FROM prices WHERE isin=? AND date=?", [OPP, DAY]).fetchone()[0]
    con.execute("UPDATE prices SET close=? WHERE isin=? AND date=?", [p * 1.25, OPP, DAY])                       # far above its 20-session average
    d = rule.decide(con, cid, _answer("temporary", "buy_in_parts"), DAY, reserve_free_inr=60_000_000.0)
    assert d["rule_option"] == "wait" and d["refused"] and "pullback" in " ".join(d["guards"])
    con.execute("UPDATE prices SET close=? WHERE isin=? AND date=?", [p, OPP, DAY])
    assert rule.decide(con, cid, _answer("temporary", "buy_in_parts"), DAY, reserve_free_inr=60_000_000.0)["rule_option"] == "buy_in_parts"


def test_three_parts_five_sessions_apart_and_the_market_fall_half_reserve(con, fixed_rates):
    _calm_tail(con, OPP)
    cid = _buy_case(con)
    first = rule.decide(con, cid, _answer("temporary", "buy_in_parts"), DAY, reserve_free_inr=300_000.0)
    cases.add_option(con, cid, NOW, track="rule", isin=OPP, symbol="OPP", option="buy_in_parts", worst_inr=0, likely_inr=0, best_inr=0, expected_inr=0, worst_pct_book=0, size_inr=first["size_inr"], chosen=True)
    cases.record_decision(con, cid, DAYS[-3], isin=OPP, symbol="OPP", rule_option="buy_in_parts", model_option="buy_in_parts", acted_option="buy_in_parts")
    soon = rule.decide(con, cid, _answer("temporary", "buy_in_parts"), DAY, reserve_free_inr=300_000.0)              # 3 sessions after the first part: wait
    assert soon["rule_option"] == "wait" and "sessions since the last part" in " ".join(soon["guards"])
    cases.record_decision(con, cid, DAYS[-8], isin=OPP, symbol="OPP", rule_option="buy_in_parts", model_option=None, acted_option="buy_in_parts")
    cases.record_decision(con, cid, DAYS[-14], isin=OPP, symbol="OPP", rule_option="buy_in_parts", model_option=None, acted_option="buy_in_parts")
    assert rule.decide(con, cid, _answer("temporary", "buy_in_parts"), DAY, reserve_free_inr=300_000.0)["rule_option"] in ("hold", "nothing")      # all three parts done
    c2 = _buy_case(con)
    cases.record_decision(con, c2, DAYS[-8], isin=OPP, symbol="OPP", rule_option="buy_in_parts", model_option=None, acted_option="buy_in_parts")
    cases.add_option(con, c2, NOW, track="rule", isin=OPP, symbol="OPP", option="buy_in_parts", worst_inr=0, likely_inr=0, best_inr=0, expected_inr=0, worst_pct_book=0, size_inr=30_000.0, chosen=True)
    later = rule.decide(con, c2, _answer("temporary", "buy_in_parts"), DAY, reserve_free_inr=300_000.0)              # 8 sessions after: the second part may go
    assert later["rule_option"] == "buy_in_parts" and later["parts"]["this_part"] == 2
    gone = rule.decide(con, c2, _answer("damage", "buy_in_parts", pending="the regulator"), DAY, reserve_free_inr=300_000.0)                  # ... but not once the thesis no longer holds
    assert gone["rule_option"] == "wait"
    fall = _case(con, isin=IDX, symbol="IDXBEES", kind="market_fall", signals=(("market_down_20d", 0.11),))
    _calm_tail(con, IDX)
    m = rule.decide(con, fall, _answer("market_fear", "buy_in_parts", isin=IDX, symbol="IDXBEES"), DAY, reserve_free_inr=400_000.0)
    assert m["rule_option"] == "buy_in_parts" and m["parts"]["total_inr"] <= 0.5 * 400_000.0 + 1e-6 and m["parts"]["n"] == 3        # at most half the reserve, three parts


def test_the_rule_and_the_models_choice_are_both_kept_and_the_big_trade_check(con, fixed_rates):
    cid = _case(con)
    d = rule.decide(con, cid, _answer("damage", "hold", isin=WIN, symbol="WIN"), DAY)
    did = cases.record_decision(con, cid, DAY, isin=WIN, symbol="WIN", rule_option=d["rule_option"], model_option="hold", acted_option=d["rule_option"], reason=d["reason"])
    rec = cases.decisions(con, cid)[0]
    assert rec["rule_option"] == "sell" and rec["model_option"] == "hold" and rec["differs"] is True and rec["acted_option"] == "sell" and did
    whole = _whole(con)
    assert rule.needs_big_trade_check(con, "sell", 0.021 * whole, DAY) and not rule.needs_big_trade_check(con, "sell", 0.019 * whole, DAY)
    assert rule.needs_big_trade_check(con, "buy_in_parts", 1.0, DAY) and not rule.needs_big_trade_check(con, "hold", 10 * whole, DAY)
