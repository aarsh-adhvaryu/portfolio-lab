"""S82 lab agent: C3 (the 60% broad-index rail everywhere it is enforced; the index fallback scoped to the India core; the repair of an S81-style index-only target) and C4 (the two
registered studies: the rule in code against the protocol, registration counted once, a buy-and-hold book that never rebalances, a stop applied or not by the switch). Synthetic data only."""
from __future__ import annotations

import json
import re
import sys
import types
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from pflab import core
from pflab.core import exits, policy, rails, sleeves
from pflab.lab import alloc_lab, c4_replay, c4_study, engine, runner, service, swing
from pflab.paper import allocation, book
from pflab.paper import rails as hard
from pflab.learner import counter, s79
from tests.test_s81_core_lab import DAYS, ETFS, FAIL, PASS, REASONS, STOCKS, NOW, _hist, _state, con  # noqa: F401  (the fixture `con` is the S81 core-lab book)
from tests.test_s81_swing import CFG, toy

SYMS = ("NIFTYBEES", "MONIFTY500", "JUNIORBEES", "GOLDBEES", "MON100")


# --- C3: the 60% rail for the broad-market index ETFs --------------------------------------------------------------------------------------------

def test_the_limits_by_symbol_a_broad_index_etf_60_every_other_etf_35_a_stock_10_a_sector_25():
    assert hard.limit_of("etf", "NIFTYBEES") == 0.60 and hard.limit_of("etf", "MONIFTY500") == 0.60 and hard.limit_of("etf", "niftybees") == 0.60
    assert hard.limit_of("etf", "JUNIORBEES") == 0.35                                # the Nifty Next 50 is NOT a broad-market index ETF
    assert hard.limit_of("etf", "GOLDBEES") == 0.35 and hard.limit_of("etf", "MON100") == 0.35 and hard.limit_of("etf", None) == 0.35
    assert hard.limit_of("equity", "NIFTYBEES") == 0.10 and hard.limit_of(None, "X") == 0.10        # only an ETF gets an ETF rail
    assert hard.MAX_SECTOR == 0.25 and hard.MAX_STOCK == 0.10 and hard.MAX_ETF == 0.35
    assert core.settings()["rails"]["broad_index_etfs"] == ["NIFTYBEES", "MONIFTY500"] and core.settings()["rails"]["broad_index_cap"] == 0.60


def test_policy_cap_of_and_the_rails_clip_allow_a_60_percent_broad_index_position_and_trim_a_40_percent_other_etf_to_35(con):
    assert policy.cap_of({"asset_class": "etf", "symbol": "NIFTYBEES"}) == 0.60 and policy.cap_of({"asset_class": "etf", "symbol": "JUNIORBEES"}) == 0.35
    assert policy.cap_of({"asset_class": "equity", "symbol": "STK0"}) == 0.10
    s = _state(con)
    s["cash"] = 10.0 * s["value"]                                                    # room in cash: only the position rails are under test
    nifty, gold = ETFS["NIFTYBEES"][0], ETFS["GOLDBEES"][0]
    out = rails.clip_weights(s, {nifty: 0.60, gold: 0.40, STOCKS[0][0]: 0.20})
    assert out[nifty]["target"] == pytest.approx(0.60) and not out[nifty]["why"]     # 60% in a broad-market index ETF is allowed
    assert out[gold]["target"] == pytest.approx(0.35) and "rail 35%" in out[gold]["why"][0]      # a 40% non-broad ETF is cut to 35%
    assert out[STOCKS[0][0]]["target"] == pytest.approx(0.10)                       # a stock stays at 10%
    out2 = rails.clip_weights(s, {nifty: 0.70})
    assert out2[nifty]["target"] == pytest.approx(0.60)                              # and no further


def test_the_fill_time_rail_in_paper_rails_uses_the_same_limits(con):
    day = DAYS[-1]
    total = book.holdings(con, day)["value"]
    assert hard.buy_room(con, ETFS["NIFTYBEES"][0], day) == pytest.approx(0.60 * total)
    assert hard.buy_room(con, ETFS["MONIFTY500"][0], day) == pytest.approx(0.60 * total)
    assert hard.buy_room(con, ETFS["GOLDBEES"][0], day) == pytest.approx(0.35 * total)
    assert hard.buy_room(con, STOCKS[0][0], day) < 0.10 * total + 1e-6
    assert "60%" in hard.describe()["one ETF"]
    assert hard.rails_denominator(con, day) == pytest.approx(total)                  # no US sub-book open: the whole book is the rupee book


def test_the_denominator_hook_points_at_the_whole_book_when_it_exists(con, monkeypatch):
    from pflab.us import wholebook
    day = DAYS[-1]
    total = book.holdings(con, day)["value"]
    monkeypatch.setattr(wholebook, "whole_book_inr", lambda c, d, root=None: {"whole_inr": 2.0 * total})
    assert hard.rails_denominator(con, day) == pytest.approx(2.0 * total)
    assert hard.buy_room(con, ETFS["NIFTYBEES"][0], day) == pytest.approx(0.60 * 2.0 * total)       # the rails are a share of the WHOLE book (A57)
    monkeypatch.setattr(wholebook, "whole_book_inr", lambda c, d, root=None: (_ for _ in ()).throw(RuntimeError("no fx")))
    assert hard.rails_denominator(con, day) == pytest.approx(total)                  # a failure never skips a rail: the rupee book


def test_the_exit_managers_rail_trim_reads_the_same_limit():
    src = open(exits.__file__, encoding="utf-8").read()
    assert "hard.limit_of(ac, meta[isin].get(\"symbol\"))" in src and "hard.MAX_ETF if ac" not in src


def test_the_lab_replay_agrees_with_the_live_rails():
    cfg = {**engine.DEFAULT_CFG, **runner.cost_config()}                              # what a job carries: the host's broad list and cap
    for sym in SYMS:
        assert engine.position_cap({"etf": True, "symbol": sym}, cfg) == hard.limit_of("etf", sym), sym
    assert engine.position_cap({"etf": False, "symbol": "X"}, cfg) == 0.10
    meta = {"ETF:NIFTYBEES": {"symbol": "NIFTYBEES", "etf": True, "sector": None}, "ETF:JUNIORBEES": {"symbol": "JUNIORBEES", "etf": True, "sector": None},
            "S1": {"symbol": "S1", "etf": False, "sector": "Banks"}}
    w = engine.clip_weights({"ETF:NIFTYBEES": 0.60, "ETF:JUNIORBEES": 0.40}, meta, cfg)
    assert w["ETF:NIFTYBEES"] == pytest.approx(0.60) and w["ETF:JUNIORBEES"] == pytest.approx(0.35)
    assert engine.clip_weights({"S1": 0.20}, meta, cfg)["S1"] == pytest.approx(0.10)
    base = engine.clip_weights({"ETF:NIFTYBEES": 0.60}, meta, {**engine.DEFAULT_CFG, "broad_syms": []})          # a job with no broad list keeps the old 35% (an old job folder)
    assert base["ETF:NIFTYBEES"] == pytest.approx(0.35)


def test_a_replay_gives_the_policy_the_60_percent_cap_in_its_state():
    seen = {}

    def decide(state, f, s, sl, params=None):
        seen.update(state["caps"])
        return {}
    idx = pd.bdate_range("2012-01-02", periods=90)
    px = pd.DataFrame({"ETF:NIFTYBEES": 100.0, "ETF:JUNIORBEES": 100.0, "S1": 100.0}, index=idx)
    meta = {"ETF:NIFTYBEES": {"symbol": "NIFTYBEES", "etf": True, "sector": None, "tax": "EQUITY"}, "ETF:JUNIORBEES": {"symbol": "JUNIORBEES", "etf": True, "sector": None, "tax": "EQUITY"},
            "S1": {"symbol": "S1", "etf": False, "sector": None, "tax": "EQUITY"}}
    data = {"px": px, "turnover": px * 0 + 1e9, "meta": meta, "index": px["S1"], "bench": px["S1"]}
    engine.replay(decide, {}, data, idx[0], idx[-1], {"min_history": 20, "turn_window": 40})
    assert seen["ETF:NIFTYBEES"] == 0.60 and seen["ETF:JUNIORBEES"] == 0.35 and seen["S1"] == 0.10


# --- C3: the index fallback is scoped to the India core ---------------------------------------------------------------------------------------------

def test_the_index_only_variant_moves_gold_into_the_broad_index_etfs_and_keeps_the_sleeves_and_the_international_share():
    p = alloc_lab.index_only_params()
    assert p["gold"] == 0.0 and p["idx"] == pytest.approx(0.50) and p["intl"] == pytest.approx(0.10) and p["longterm"] == pytest.approx(0.40)
    assert p["idx_syms"] == ["NIFTYBEES", "MONIFTY500"] and "JUNIORBEES" not in p["idx_syms"]
    assert alloc_lab.candidates()["index_hold_s82"]["params"] == p and "index_hold" not in alloc_lab.candidates()


def test_the_fallback_keeps_the_us_sub_books_share_and_the_longterm_sleeve(con, tmp_path):
    alloc_lab.seed(con, tmp_path, NOW)
    _hist(con, "alloc_default", FAIL)
    _hist(con, "index_hold_s82", PASS)
    out = alloc_lab.tick(con, tmp_path, None, NOW)
    assert out["adopted_index_only"]["adopted"] is True
    act = allocation.active_target(con)
    assert act["classes"]["international"] == 10.0 and act["classes"]["gold"] == 0.0 and act["classes"]["equity"] == 90.0     # the international share stays (held in the US sub-book)
    assert sleeves.stored(con, act["target_id"])["sleeves"] == {"core": 60.0, "longterm": 40.0}
    sh = _state(con)["sleeve_target"]
    assert sh["longterm"] == pytest.approx(0.40) and sh["international"] == pytest.approx(0.10) and sh["gold"] == 0.0 and sh["index"] == pytest.approx(0.50)
    # the US sub-book's own state (`us_*_s81`) belongs to the `us` agent and is not read here: the target keeps the share that book is funded to hold (asserted on the target above)


def test_the_fallback_keeps_the_active_targets_own_split_not_a_fixed_one(con, tmp_path):
    r = allocation.propose_allocation(con, {"equity": 60, "gold": 20, "international": 10, "cash": 10}, REASONS, NOW, sectors={}, by="the strategist")
    con.execute("INSERT OR REPLACE INTO allocation_sleeves_s81 VALUES (?,?,?,?,?)", [r["target_id"], "IN", json.dumps({"core": 55.0, "longterm": 45.0}), None, NOW])
    allocation.review_target(con, r["target_id"], "approve", "test", NOW)
    out = alloc_lab.adopt_index_only(con, NOW, "A test of the fallback: it must keep the active target's sleeves, international and cash shares and move only the gold into the index.")
    assert out["adopted"] and out["classes"] == {"equity": 80.0, "gold": 0.0, "international": 10.0, "cash": 10.0} and out["sleeves"] == {"core": 55.0, "longterm": 45.0}


def _old_style_index_only(con):
    """What the S81 fallback left in a store: core 100 / longterm 0, no international, no gold, adopted by 'the lab (A50 index rule)'."""
    r = allocation.propose_allocation(con, {"equity": 100.0, "gold": 0.0, "international": 0.0, "cash": 0.0}, "After tax and charges the allocation fails the index rule: the system owns the index (S81).", NOW,
                                      sectors={}, by=alloc_lab.OLD_ADOPTER)
    con.execute("INSERT OR REPLACE INTO allocation_sleeves_s81 VALUES (?,?,?,?,?)", [r["target_id"], "IN", json.dumps({"core": 100.0, "longterm": 0.0}), "index_hold", NOW])
    allocation.review_target(con, r["target_id"], "approve", "adopted by code (S81)", NOW)
    return r["target_id"]


def test_the_repair_replaces_an_s81_index_only_target_once_with_a_dated_note(con, tmp_path):
    old = _old_style_index_only(con)
    assert allocation.active_target(con)["target_id"] == old
    out = alloc_lab.rescope_old_index_only(con, NOW)
    assert out["rescoped"] is True and out["replaced"] == old
    act = allocation.active_target(con)
    assert act["target_id"] != old and act["classes"] == {"equity": 90.0, "gold": 0.0, "international": 10.0, "cash": 0.0}
    assert sleeves.stored(con, act["target_id"])["sleeves"] == {"core": 60.0, "longterm": 40.0} and sleeves.stored(con, act["target_id"])["variant_policy"] == "index_hold_s82"
    assert str(NOW.date()) in act["reasons"] and "scoped to the India core" in act["reasons"] and "US sub-book" in act["reasons"]
    assert con.execute("SELECT status FROM system_allocation_s79 WHERE target_id=?", [old]).fetchone()[0] == "superseded"
    assert con.execute("SELECT count(*) FROM alloc_verdicts_s81 WHERE outcome='adopted'").fetchone()[0] == 1
    n = con.execute("SELECT count(*) FROM system_allocation_s79").fetchone()[0]
    again = alloc_lab.rescope_old_index_only(con, NOW)
    assert again == {"rescoped": False} and con.execute("SELECT count(*) FROM system_allocation_s79").fetchone()[0] == n          # idempotent


def test_the_repair_leaves_other_targets_and_an_empty_store_alone(con):
    assert alloc_lab.rescope_old_index_only(con, NOW) == {"rescoped": False}
    r = allocation.propose_allocation(con, {"equity": 100.0, "gold": 0.0, "international": 0.0, "cash": 0.0}, REASONS, NOW, sectors={}, by="the strategist")      # the same split, but the strategist's own
    con.execute("INSERT OR REPLACE INTO allocation_sleeves_s81 VALUES (?,?,?,?,?)", [r["target_id"], "IN", json.dumps({"core": 100.0, "longterm": 0.0}), None, NOW])
    allocation.review_target(con, r["target_id"], "approve", "test", NOW)
    assert alloc_lab.rescope_old_index_only(con, NOW) == {"rescoped": False} and allocation.active_target(con)["target_id"] == r["target_id"]


def test_tick_repairs_first_and_retires_the_old_variant(con, tmp_path):
    old = _old_style_index_only(con)
    alloc_lab.seed(con, tmp_path, NOW)
    from pflab.lab import policy_api
    code = alloc_lab.render_code({"idx": 0.98, "gold": 0.0, "intl": 0.0, "longterm": 0.0})
    assert service.add_variant(con, tmp_path, NOW, "index_hold", code, "the S81 index-only variant kept for the record")["ok"]
    _hist(con, "alloc_default", PASS)
    _hist(con, "index_hold_s82", PASS)
    out = alloc_lab.tick(con, tmp_path, None, NOW)
    assert out["rescoped"]["rescoped"] is True and allocation.active_target(con)["target_id"] != old
    assert con.execute("SELECT status FROM core_policies_s80 WHERE policy_id='index_hold'").fetchone()[0] == "retired"
    assert "index_hold" not in alloc_lab.family(con) and "index_hold_s82" in alloc_lab.family(con)
    assert alloc_lab.tick(con, tmp_path, None, NOW)["rescoped"] == {"rescoped": False}


# --- C4: the rule in code against the protocol -----------------------------------------------------------------------------------------------------

def _blocks():
    text = c4_study.PROTOCOL.read_text(encoding="utf-8")
    return [json.loads(b) for b in re.findall(r"```json rule\n(.*?)\n```", text, re.S)]


def test_the_rule_in_code_is_the_protocols_rule_block_and_its_amendment():
    first, a1 = _blocks()
    assert first == json.loads(json.dumps(c4_study.RULE)) and a1 == json.loads(json.dumps(c4_study.RULE_A1))
    assert c4_study.RULE["history"] == ["2005-01-01", "2017-12-31"] and c4_study.RULE["final_window_used"] is False        # 2018-2021 is not touched
    assert c4_replay.BOOK["n_names"] == c4_study.RULE["stock_book"]["n_names"] and c4_replay.BOOK["max_weight"] == c4_study.RULE["stock_book"]["max_weight"]
    assert c4_replay.BOOK["invested"] == c4_study.RULE_A1["stock_book_invested"] and c4_replay.BOOTSTRAP == c4_study.RULE["bootstrap"]
    s = c4_study.RULE["stops"]
    assert {k: c4_replay.STOPS[k] for k in ("sigmas", "horizon_days", "vol_window", "min_pct", "max_pct", "fallback_vol")} == {k: s[k] for k in ("sigmas", "horizon_days", "vol_window", "min_pct", "max_pct", "fallback_vol")}
    assert (exits.settings()["longterm"]["stop_sigmas"], exits.settings()["longterm"]["stop_horizon_days"], exits.settings()["longterm"]["stop_min_pct"], exits.settings()["longterm"]["stop_max_pct"]) == (s["sigmas"], s["horizon_days"], s["min_pct"], s["max_pct"])
    assert {k: swing.SLIP[k] for k in c4_study.RULE["slippage"]} == c4_study.RULE["slippage"]
    from pflab.lab import harvest_replay as H
    assert {k: H.DEFAULT_RULE[k] for k in c4_study.RULE["harvest"]} == c4_study.RULE["harvest"]


def test_registration_counts_three_tests_once_and_the_protocol_must_be_unchanged(con):
    n0 = counter.n_tests(con)
    assert c4_study.protocol_ok(con)["registered"] is False
    got = c4_study.register(con, NOW)
    assert got == ["s82:c4a:index", "s82:c4a:stocks", "s82:c4b:stops"] and counter.n_tests(con) == n0 + 3
    assert c4_study.register(con, NOW) == [] and counter.n_tests(con) == n0 + 3
    assert c4_study.protocol_ok(con) == {"registered": True, "unchanged": True, "why": None}
    assert s79.register_c4(con, NOW) == [] and counter.n_tests(con) == n0 + 3
    con.execute("UPDATE learn_tests SET params_json=? WHERE note='s82:c4a:index'", [json.dumps({"protocol_sha256": "0" * 64})])
    assert c4_study.protocol_ok(con)["unchanged"] is False                            # a protocol edited after registration is caught
    with pytest.raises(RuntimeError):
        c4_study.run(con, None, None, NOW)                                            # and the run refuses


def test_claim_a_verdict_needs_all_three_conditions():
    arm = {"dL": 0.004, "tax_saved": 50000.0, "extra_costs": 3000.0, "t": 4.0}
    assert c4_study.claim_a_verdict(arm, 98)["ok"] is True
    v = c4_study.claim_a_verdict({**arm, "dL": 0.0004}, 98)
    assert not v["ok"] and "needs +0.050%" in v["failed"][0]
    v = c4_study.claim_a_verdict({**arm, "extra_costs": 60000.0}, 98)
    assert not v["ok"] and "does not exceed" in v["failed"][0]
    v = c4_study.claim_a_verdict({**arm, "t": 1.5}, 98)
    assert not v["ok"] and v["t_bar"] == pytest.approx(counter.t_needed(98)) and "bar" in v["failed"][0]
    assert c4_study.claim_a_verdict({**arm, "t": 3.0}, 98)["ok"] is False and c4_study.claim_a_verdict({**arm, "t": 3.0}, 2)["ok"] is True      # the bar rises with N


def _b(wf_with, wf_without, l_with, l_without):
    return {"with_stops": {"worst_fall": wf_with, "liq_cagr": l_with}, "without_stops": {"worst_fall": wf_without, "liq_cagr": l_without}}


def test_claim_b_keeps_the_stops_only_for_a_20_percent_cut_at_no_more_than_1_point_a_year():
    assert c4_study.claim_b_verdict(_b(0.40, 0.56, 0.095, 0.100))["ok"] is True       # cut 28.6%, cost 0.5 point
    assert c4_study.claim_b_verdict(_b(0.448, 0.56, 0.095, 0.100))["ok"] is True      # exactly 20%
    v = c4_study.claim_b_verdict(_b(0.46, 0.56, 0.095, 0.100))
    assert not v["ok"] and "cut of 18%" in v["failed"][0]
    v = c4_study.claim_b_verdict(_b(0.40, 0.56, 0.085, 0.100))
    assert not v["ok"] and "cost" in v["failed"][0] and "+1.50%" in v["failed"][0]
    v = c4_study.claim_b_verdict(_b(0.5092, 0.5631, 0.0911, 0.1016))                  # the recorded run
    assert not v["ok"] and len(v["failed"]) == 2


def test_the_recorded_result_follows_the_rule_and_is_written_onto_a_store_once(con):
    rec = json.loads(c4_study.RESULTS.read_text(encoding="utf-8"))
    assert rec["protocol_sha256"] == c4_study.protocol_sha() and rec["window"] == ["2005-01-01", "2017-12-31"]
    for k in ("a_index", "a_stocks"):
        assert c4_study.claim_a_verdict(rec[k], rec["n_tests"]) == rec[k]["verdict"] and rec[k]["verdict"]["ok"] is False
    assert c4_study.claim_b_verdict(rec["b"])["ok"] == rec["b"]["verdict"]["ok"] is False
    assert rec["switches"] == {"exits.harvest_core": False, "exits.harvest_longterm": False, "exits.longterm.stop": False} == c4_study.switches(rec)
    c = core.settings()                                                              # the config carries exactly what the recorded verdicts switch
    ex = exits.settings()
    assert ex["harvest_core"] is False and ex["harvest_longterm"] is False and ex["longterm"]["stop"] is rec["switches"]["exits.longterm.stop"]
    assert c4_study.apply_recorded(con, NOW) == 0                                    # not registered on this store yet: nothing is written
    c4_study.register(con, NOW)
    assert c4_study.apply_recorded(con, NOW) == 3 and c4_study.apply_recorded(con, NOW) == 0
    rows = con.execute("SELECT note, passed FROM learn_tests WHERE note LIKE 's82:%' ORDER BY note").fetchall()
    assert rows == [("s82:c4a:index", False), ("s82:c4a:stocks", False), ("s82:c4b:stops", False)]
    assert c4_study.stored(con, "b_stops")["verdict"] == "fail"
    with pytest.raises(RuntimeError):
        c4_study.run(con, None, None, NOW)                                            # a second run is refused


# --- C4: the buy-and-hold stock book and the stops ---------------------------------------------------------------------------------------------------

def _panel(n=200, crash_at=None, seed=5):
    """Six stocks that drift apart, one of which (S0) halves over 40 sessions from `crash_at`; the day's range is the close itself."""
    idx = pd.bdate_range("2012-01-02", periods=n)
    rng = np.random.default_rng(seed)
    close = {f"S{i}": 100 * np.cumprod(1 + rng.normal(0.0004 * i, 0.012 + 0.002 * i, n)) for i in range(6)}
    if crash_at is not None:
        close["S0"] = close["S0"].copy()
        ramp = np.ones(n)
        ramp[crash_at:crash_at + 40] = np.linspace(1.0, 0.5, 40)                      # a fall over 40 sessions (a gap would fill below any stop at the open)
        ramp[crash_at + 40:] = 0.5
        close["S0"] = close["S0"] * ramp
    px = pd.DataFrame(close, index=idx)
    o, h, l = (pd.DataFrame(1.0, index=idx, columns=px.columns) for _ in range(3))
    meta = {k: {"symbol": k, "etf": False, "sector": None, "tax": "EQUITY"} for k in px.columns}
    return {"px": px, "turnover": pd.DataFrame(1e9, index=idx, columns=px.columns), "meta": meta, "index": px["S1"], "bench": px["S1"], "ohlc": {"open": o, "high": h, "low": l}}


BOOK = {"n_names": 4, "turnover_window": 60, "vol_window": 60}
SCFG = {**CFG, "capital": 1_000_000.0, "slippage": "liquidity"}


def test_the_buy_and_hold_stock_book_is_bought_once_and_never_rebalanced():
    data = _panel()
    idx = data["px"].index
    bk = c4_replay.BuyHoldBook(False, BOOK)
    run = swing.replay_daily(bk.decide, {}, data, idx[0], idx[-1], {**SCFG, "deploy_once": True}, None, "monthly", False)
    b = run["book"]
    held = [k for k in b.lots if b.qty(k) > 1e-9]
    assert len(held) == 4 and bk.done and set(bk.names) == set(held)
    assert all(len(b.lots[k]) == 1 for k in held)                                     # one lot each: nothing was bought again or trimmed in 200 sessions of drifting weights
    assert b.traded == pytest.approx(sum(l[1] * l[2] for k in held for l in b.lots[k]), rel=0.01)       # everything traded is the first purchase
    assert sum(bk.names.values()) == pytest.approx(0.40, abs=0.02)                    # 4 names at the 10% cap
    first = {k: v for k, v in bk.names.items()}
    assert all(abs(v - 0.10) < 1e-9 for v in first.values())
    assert run["decisions"] == 1                                                      # one decision that named something; no month-end after it is taken


def test_the_book_selects_point_in_time_the_most_liquid_names_and_waits_for_enough_of_them():
    data = _panel()
    data["turnover"].iloc[:, 0] = 5e9                                                  # S0 is the most traded
    idx = data["px"].index
    bk = c4_replay.BuyHoldBook(False, {**BOOK, "n_names": 6})
    swing.replay_daily(bk.decide, {}, data, idx[0], idx[-1], {**SCFG, "deploy_once": True}, None, "monthly", False)
    assert bk.done and bk.first_day is not None and pd.Timestamp(bk.first_day) >= idx[20]       # not before the shares have `min_history` sessions
    bk2 = c4_replay.BuyHoldBook(False, {**BOOK, "n_names": 7})                          # only six exist: it never buys, it does not guess
    run = swing.replay_daily(bk2.decide, {}, data, idx[0], idx[-1], {**SCFG, "deploy_once": True}, None, "monthly", False)
    assert not bk2.done and not [k for k in run["book"].lots if run["book"].qty(k) > 0]


def test_a_stop_is_applied_or_not_applied_by_the_switch():
    data = _panel(crash_at=100)
    idx = data["px"].index
    res = c4_replay.claim_b(data, idx[0], idx[-1], SCFG, BOOK)
    w, wo = res["with_stops"], res["without_stops"]
    assert res["same_names"] is True and wo["stops_fired"] == 0 and w["stops_fired"] >= 1                  # the switch decides whether a stop sells
    assert w["worst_fall"] < wo["worst_fall"]                                          # S0 halves: the stop sold it on the way down, the book without a stop rode it
    assert all(0.12 <= d <= 0.35 for d in res["stop_distances"].values())              # the live exit plan's clamp
    # the live switch: configs/core.toml [exits.longterm] stop decides whether a plan carries a stop level at all
    cfg_off, cfg_on = exits.settings(), exits.settings()
    cfg_on["longterm"] = {**cfg_on["longterm"], "stop": True}
    assert exits.settings()["longterm"]["stop"] is False
    assert exits._levels(cfg_off, "longterm", 100.0, 0.25)["stop"] is None
    lv = exits._levels(cfg_on, "longterm", 100.0, 0.25)
    assert lv["stop"] is not None and lv["stop"] == pytest.approx(100.0 * (1.0 - lv["stop_pct"])) and 0.12 <= lv["stop_pct"] <= 0.35


def test_the_stop_distance_is_the_live_exit_plans_rule():
    cfg = exits.settings()
    for vol in (0.10, 0.25, 0.30, 0.45, 0.80):
        dist = min(max(2.0 * vol * np.sqrt(63 / 252.0), 0.12), 0.35)
        assert exits._levels({**cfg, "longterm": {**cfg["longterm"], "stop": True}}, "longterm", 100.0, vol)["stop_pct"] == pytest.approx(dist)
    flat = pd.Series(100.0, index=range(300))
    assert c4_replay.stop_distance(flat) == pytest.approx(0.12) or c4_replay.stop_distance(flat) == pytest.approx(min(max(2.0 * 0.05 * np.sqrt(63 / 252.0), 0.12), 0.35))     # a flat name: the volatility floor, the minimum distance
    assert c4_replay.stop_distance(pd.Series([100.0, 101.0])) == pytest.approx(min(max(2.0 * 0.30 * np.sqrt(63 / 252.0), 0.12), 0.35))      # too little history: the stated fallback


def test_claim_a_runs_with_and_without_harvesting_on_the_stock_book_and_reports_the_accounting():
    data = _panel(n=520, seed=11)
    idx = data["px"].index
    cfg = {**SCFG, "tax": {"st_rate": 0.20, "lt_rate": 0.125, "lt_exempt": 5000.0, "slab": 0.30, "lt_months": 12, "carry_years": 8}, "harvest_rule": {"min_room": 100.0}}
    out = c4_replay.claim_a("stocks", data, idx[0], idx[-1], cfg, BOOK)
    assert set(out) >= {"on", "off", "dL", "tax_saved", "extra_costs", "accounting_ok", "t", "same_names"} and out["same_names"] is True
    assert out["on"]["traded"] >= out["off"]["traded"]                                 # harvesting only ever adds trades
    assert out["accounting_ok"] == bool(out["tax_saved"] > out["extra_costs"])
    with pytest.raises(ValueError):
        c4_replay.claim_a("nonsense", data, idx[0], idx[-1], cfg)


def test_the_runner_job_carries_the_c4_files_and_the_broad_index_list(tmp_path):
    runner.write_job(tmp_path, _panel(n=60), [], ("2012-01-02", "2012-03-01"), {}, runner.cost_config(), 0, 0, 82, {"mode": "c4"})
    assert (tmp_path / "c4_replay.py").exists() and (tmp_path / "swing.py").exists()
    job = json.loads((tmp_path / "job.json").read_text(encoding="utf-8"))
    assert job["mode"] == "c4" and job["cfg"]["broad_syms"] == ["MONIFTY500", "NIFTYBEES"] and job["cfg"]["max_broad_etf"] == 0.60
