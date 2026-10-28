"""Acceptance cases for the 2026-09-27 audit, Deliverable 1, defects 1-4
(`docs/BUILT.md`; E1 §15 measurement corrections of
the same date). `tools/audit/verify_accounting.py` reproduced each defect;
these assert the corrected outcome."""
from __future__ import annotations

import copy
import dataclasses
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.backtest import engine, hooks as hk
from pflab.eval.periods import Period
from pflab.execution.costs import CostModel
from pflab.tax.india_lots import LotBook, TaxPolicy

FREE = CostModel(multiplier=0.0)
POLICY = TaxPolicy()


def panel(sessions, prices, name="TEST", dividend=None):
    prices = np.asarray(prices, dtype=float)
    return pd.DataFrame({
        "date": sessions, "isin": name, "symbol": name, "series": "EQ",
        "instrument_type": "STK", "open": prices, "high": prices,
        "low": prices, "close": prices,
        "prev_close": np.r_[prices[0], prices[:-1]],
        "volume": 100000, "turnover": 1e10, "adj_factor": 1.0,
        "adj_open": prices, "adj_close": prices,
        "dividend": [float((dividend or {}).get(d, 0.0)) for d in sessions]})


def config(**strategy):
    s = {"n_hold": 1, "band_exit_rank": 999, "max_buys_per_month": 1,
         "lookback_sessions": 1, "skip_sessions": 0,
         "sip_amount": 10000.0, "initial_cash": 0.0,
         "cash_rate_annual": 0.0, "trend_filter": "off",
         "delisting": "last_close", "delist_confirm_sessions": 250}
    s.update(strategy)
    return {"strategy": s, "universe": {
        "series": ["EQ"], "min_sessions": 1, "top_n_by_turnover": 500,
        "turnover_window": 1, "min_price": 0.0, "max_adv_fraction": 1.0}}


def run(cfg, p, actions=None, hooks=None, cost=FREE, policy=POLICY):
    return engine.run(cfg, Period("synthetic", min(p.date), max(p.date)),
                      p, None, cost, policy, actions=actions, hooks=hooks)


def sell_on(day, isin="TEST"):
    """A hook that sells `isin` at the open of `day`, and only then."""
    return hk.HookSet(intra_month_exit=lambda t, held, state:
                      [isin] if t == day and isin in held else [])


SPLIT_EX = date(2020, 2, 17)                 # mid-month, after the Feb 3 buy
SS = list(pd.bdate_range("2020-01-01", "2020-03-06").date)
SPLIT = pd.DataFrame([{"isin": "TEST", "ex_date": SPLIT_EX, "factor": 0.5,
                       "source": "purpose"}])


def total_on(r, d):
    return float(r.equity.loc[r.equity.date == d, "total"].iloc[0])


# -- defect 1: corporate actions at the start of the ex-date ---------------
def test_existing_holder_keeps_value_through_a_split():
    r = run(config(), panel(SS, [100.0 if d < SPLIT_EX else 50.0 for d in SS]), SPLIT)
    before = total_on(r, date(2020, 2, 14))
    assert total_on(r, SPLIT_EX) == pytest.approx(before)
    w = [x for x in r.warnings if x["kind"] == "share_count_action"]
    assert w and w[0]["shares_added"] == 200          # 200 held -> 400


def test_first_time_buyer_on_split_ex_date_gets_no_extra_shares():
    """The audit's case: buying 400 shares for ₹20,000 on the ex-date is
    worth ₹20,000, not ₹40,000."""
    ex = date(2020, 2, 3)
    ss = list(pd.bdate_range("2020-01-01", "2020-02-04").date)
    a = pd.DataFrame([{"isin": "TEST", "ex_date": ex, "factor": 0.5, "source": "purpose"}])
    r = run(config(), panel(ss, [100.0 if d < ex else 50.0 for d in ss]), a)
    assert r.trades.loc[r.trades.side == "BUY", "qty"].sum() == 400
    assert total_on(r, ex) == pytest.approx(20000.0)
    assert not [w for w in r.warnings if w["kind"] == "share_count_action"]


def test_first_time_buyer_on_dividend_ex_date_gets_no_dividend():
    ex = date(2020, 2, 3)
    ss = list(pd.bdate_range("2020-01-01", "2020-02-04").date)
    r = run(config(), panel(ss, [100.0 if d < ex else 90.0 for d in ss],
                            dividend={ex: 10.0}))
    assert r.equity.dividends.sum() == 0.0


def test_seller_on_split_ex_date_sells_the_post_split_holding():
    r = run(config(), panel(SS, [100.0 if d < SPLIT_EX else 50.0 for d in SS]),
            SPLIT, hooks=sell_on(SPLIT_EX))
    sale = r.trades[(r.trades.side == "SELL_INTRA") & (r.trades.date == SPLIT_EX)]
    assert int(sale.qty.iloc[0]) == 400 and float(sale.fill_price.iloc[0]) == 50.0
    assert total_on(r, SPLIT_EX) == pytest.approx(20000.0)
    assert sum(x.gain for x in r.realised) == pytest.approx(0.0)


def test_seller_on_dividend_ex_date_keeps_the_dividend():
    r = run(config(), panel(SS, [100.0 if d < SPLIT_EX else 90.0 for d in SS],
                            dividend={SPLIT_EX: 10.0}), hooks=sell_on(SPLIT_EX))
    assert r.equity.dividends.sum() == pytest.approx(2000.0)   # 200 x ₹10
    assert total_on(r, SPLIT_EX) == pytest.approx(20000.0)


def test_partial_seller_quantity_follows_the_split():
    """A partial sale planned at M in pre-split shares (E3-R's sell-down) is
    re-expressed in post-split shares at execution; the decision recorded at
    M is not rewritten."""
    dec = {"month_end": date(2020, 1, 31), "reference_close": {"TEST": 100.0},
           "selldown": {"plan": [["TEST", 40]]},
           "tranche_sell": {"isin": "TEST", "qty": 30}}
    recorded = copy.deepcopy(dec)
    b = LotBook(POLICY)
    b.buy("TEST", date(2020, 1, 2), 100, 100.0)
    f = {}
    engine._apply_ex_date_events(SPLIT_EX, b, engine._action_map(SPLIT), {},
                                 POLICY, [], [], last_close={"TEST": 100.0},
                                 share_factors=f)
    out = engine._rescale_pending(dec, f)
    assert b.holdings("TEST") == 200
    assert out["selldown"]["plan"] == [["TEST", 80]]
    assert out["tranche_sell"]["qty"] == 60
    assert out["reference_close"]["TEST"] == pytest.approx(50.0)
    assert dec == recorded
    b.sell("TEST", SPLIT_EX, 80, 50.0)                 # 40 of the old shares
    assert b.holdings("TEST") == 120


# -- defect 2: suspension --------------------------------------------------
DEAD = list(pd.bdate_range("2019-01-01", "2020-06-30").date)


def _suspension_panel(cut, back=None, back_price=100.0):
    live = [d for d in DEAD if d < cut or (back is not None and d >= back)]
    px = [100.0 if d < cut else back_price for d in live]
    return pd.concat([panel(live, px),
                      panel(DEAD, [1.0] * len(DEAD), name="CALENDAR")],
                     ignore_index=True)


def test_suspended_holding_is_marked_then_written_down_without_cash():
    """The audit's case: a holding last quoted 2019-02-04 must not become
    ₹20,000 of cash in 2020 without ever trading again."""
    cut = date(2019, 2, 5)
    cfg = config()
    cfg["universe"]["min_price"] = 10.0                      # CALENDAR never bought
    r = run(cfg, _suspension_panel(cut))
    assert not r.trades.side.isin(["SELL_DELIST", "SELL"]).any()
    wd = [w for w in r.warnings if w["kind"] == "write_down"]
    assert len(wd) == 1 and wd[0]["missing_sessions"] == 250 and wd[0]["qty"] == 200
    eq = r.equity.set_index("date")
    day_before = eq.index[eq.index < wd[0]["date"]][-1]
    assert eq.at[day_before, "equity_value"] == pytest.approx(20000.0)  # still marked
    assert eq.at[wd[0]["date"], "equity_value"] == pytest.approx(0.0)
    assert eq.at[wd[0]["date"], "cash"] == pytest.approx(eq.at[day_before, "cash"])
    assert [x for x in r.realised if x.isin == "TEST"] == []        # no tax loss


def test_s9_writes_down_on_the_twentieth_missing_session():
    cfg = config(delisting="total_loss")
    cfg["strategy"].pop("delist_confirm_sessions")
    cfg["universe"]["min_price"] = 10.0
    r = run(cfg, _suspension_panel(date(2019, 2, 5)))
    wd = [w for w in r.warnings if w["kind"] == "write_down"]
    assert len(wd) == 1 and wd[0]["missing_sessions"] == 20


def test_pending_exit_executes_at_the_first_session_it_trades_again():
    cut, back = date(2019, 2, 5), date(2019, 3, 18)
    cfg = config()
    cfg["universe"]["min_price"] = 10.0
    r = run(cfg, _suspension_panel(cut, back, back_price=80.0),
            hooks=sell_on(date(2019, 2, 11)))
    assert any(w["kind"] == "intra_month_exit_no_price" for w in r.warnings)
    sells = r.trades[r.trades.side.str.startswith("SELL") & (r.trades["isin"] == "TEST")]
    assert len(sells) == 1
    assert sells.date.iloc[0] == back and float(sells.fill_price.iloc[0]) == 80.0
    assert any(w["kind"] == "exit_retried" for w in r.warnings)


def test_written_down_name_that_trades_again_is_recovered_at_its_quote():
    cut, back = date(2019, 2, 5), date(2020, 3, 2)          # > 250 sessions
    cfg = config()
    cfg["universe"]["min_price"] = 10.0
    r = run(cfg, _suspension_panel(cut, back, back_price=60.0))
    assert any(w["kind"] == "write_down" for w in r.warnings)
    rec = r.trades[r.trades.side == "SELL_RECOVERY"]
    assert len(rec) == 1 and rec.date.iloc[0] == back
    gains = [x for x in r.realised if x.isin == "TEST"]
    assert sum(x.gain for x in gains) == pytest.approx(200 * (60.0 - 100.0))
    assert all(x.buy_date == date(2019, 2, 1) for x in gains)   # original lot


# -- defect 3: tax ---------------------------------------------------------
def test_cash_interest_is_taxed_at_slab_in_its_fy():
    """The audit's cash-only book: two years of 6% on ₹2.4 lakh of SIPs."""
    ss = list(pd.bdate_range("2019-01-01", "2020-12-31").date)
    cfg = config(cash_rate_annual=0.06)
    cfg["universe"]["min_sessions"] = 100000                 # never buys
    r = run(cfg, panel(ss, [100.0] * len(ss)))
    paid = float(r.equity.tax_paid_cum.iloc[-1])
    terminal = float(r.equity.liquidation_tax.iloc[-1])
    assert paid > 0 and terminal > 0
    # every rupee of interest is taxed once, at 30% + 4% cess
    growth = float(r.equity.total.iloc[-1]) + paid - float(r.equity.flow.sum())
    assert paid + terminal == pytest.approx(growth * 0.30 * 1.04, rel=1e-9)
    assert set(r.taxes["fy"]) == {2019, 2020}
    assert (r.taxes["interest"] > 0).all()


def _terminal_rows():
    return pd.DataFrame({"date": [date(2020, 1, 2), date(2020, 1, 3)],
                         "equity_value": [0.0, 0.0],
                         "cash": [20000.0, 20000.0], "flow": [20000.0, 0.0]})


def test_all_cash_book_still_owes_its_fys_tax():
    b = LotBook(POLICY)
    b.buy("TEST", date(2019, 12, 1), 100, 100.0)
    b.sell("TEST", date(2020, 1, 2), 100, 200.0)
    e, _ = engine._finalise(_terminal_rows(), b, {}, FREE, POLICY, [], [])
    assert float(e.liquidation_tax.iloc[-1]) == pytest.approx(2080.0)


def test_a_tax_computation_failure_invalidates_the_run():
    class Broken(LotBook):
        def simulate_liquidation(self, *a, **k):
            raise RuntimeError("injected")
    b = Broken(POLICY)
    b.buy("TEST", date(2019, 1, 1), 1, 100.0)
    with pytest.raises(RuntimeError, match="injected"):
        engine._finalise(_terminal_rows(), b, {"TEST": 100.0}, FREE, POLICY, [], [])


def test_bonus_shares_are_a_new_nil_cost_lot_dated_at_allotment():
    """The audit's case: 100 shares from 2018, a 1:1 bonus on 2020-02-03, all
    200 sold the next day."""
    b = LotBook(POLICY)
    b.buy("TEST", date(2018, 1, 1), 100, 100.0)
    assert b.bonus("TEST", 0.5, date(2020, 2, 3)) == 100
    lots = b.lots("TEST")
    assert [(l.buy_date, l.qty, l.cost_per_share) for l in lots] == [
        (date(2018, 1, 1), 100, 100.0), (date(2020, 2, 3), 100, 0.0)]
    rs = b.sell("TEST", date(2020, 2, 4), 200, 60.0)
    assert [(r.qty, r.cost, r.long_term) for r in rs] == [(100, 10000.0, True),
                                                         (100, 0.0, False)]


def test_engine_reads_the_bonus_part_of_a_purpose_factor():
    """A same-day 1:1 bonus and 2-for-1 split: the split re-denominates the
    old lot, the bonus adds a nil-cost lot dated at the ex-date."""
    b = LotBook(POLICY)
    b.buy("TEST", date(2018, 1, 1), 100, 400.0)
    a = pd.DataFrame([{"isin": "TEST", "ex_date": date(2020, 2, 3),
                       "factor": 0.25, "bonus_factor": 0.5, "source": "purpose"}])
    engine._apply_ex_date_events(date(2020, 2, 3), b, engine._action_map(a), {},
                                 POLICY, [], [], last_close={"TEST": 400.0})
    assert [(l.buy_date, l.qty, l.cost_per_share) for l in b.lots("TEST")] == [
        (date(2018, 1, 1), 200, 200.0), (date(2020, 2, 3), 200, 0.0)]


def test_split_keeps_dates_and_spreads_basis():
    b = LotBook(POLICY)
    b.buy("TEST", date(2018, 1, 1), 100, 100.0)
    b.buy("TEST", date(2019, 1, 1), 50, 120.0)
    b.adjust_shares("TEST", 0.5)
    assert [(l.buy_date, l.qty, l.cost_per_share) for l in b.lots("TEST")] == [
        (date(2018, 1, 1), 200, 50.0), (date(2019, 1, 1), 100, 60.0)]


def test_stt_is_a_cash_cost_but_not_in_gains():
    """Income Tax Act s.48: STT is not deductible. Cash pays it; the lot
    book's cost and proceeds exclude it."""
    cm = CostModel.from_toml("configs/costs_zerodha.toml")
    ss = list(pd.bdate_range("2019-01-01", "2019-03-29").date)
    hooks = sell_on(date(2019, 2, 15))       # one lot, bought 2019-02-01
    r = run(config(), panel(ss, [100.0] * len(ss)), hooks=hooks, cost=cm)
    buy = r.trades[r.trades.side == "BUY"].iloc[0]
    sell = r.trades[r.trades.side == "SELL_INTRA"].iloc[0]
    (rz,) = [x for x in r.realised]
    bn, sn = buy.qty * buy.fill_price, sell.qty * sell.fill_price
    assert buy.costs == pytest.approx(cm.buy_cost(bn))            # cash: all of it
    assert rz.cost == pytest.approx(bn + cm.buy_cost(bn) - cm.buy_stt(bn))
    assert rz.proceeds == pytest.approx(sn - cm.sell_cost(sn) + cm.sell_stt(sn))
    assert cm.buy_stt(bn) > 0 and cm.sell_stt(sn) > 0


# -- defect 4: consolidation -----------------------------------------------
def test_small_lot_consolidation_leaves_one_share_and_a_cash_fraction():
    """The audit's case: lots of 1, 1 and 3 at 4-for-1 are one share and a
    quarter-share fraction, not three shares."""
    b = LotBook(POLICY)
    for i, q in enumerate([1, 1, 3]):
        b.buy("TEST", date(2019, 1, i + 1), q, 100.0)
    a = pd.DataFrame([{"isin": "TEST", "ex_date": date(2020, 2, 3), "factor": 4.0,
                       "source": "prevclose", "prior_close": 100.0,
                       "adj_prev_close": 400.0}])
    warns = []
    cash, _ = engine._apply_ex_date_events(date(2020, 2, 3), b, engine._action_map(a),
                                           {}, POLICY, warns, [],
                                           last_close={"TEST": 100.0})
    assert b.holdings("TEST") == 1
    assert cash == pytest.approx(0.25 * 400.0)          # at the adjusted price
    whole_basis = sum(l.qty * l.cost_per_share for l in b.lots("TEST"))
    (fr,) = [x for x in b.realised]
    assert whole_basis + fr.cost == pytest.approx(500.0)          # conserved
    assert fr.proceeds == pytest.approx(100.0) and b.fractions == []
    assert [w["units"] for w in warns if w["kind"] == "fractional_entitlement"] == [
        pytest.approx(0.25)]


@pytest.mark.parametrize("seed", range(5))
def test_consolidation_reconciles_across_many_small_lots(seed):
    rng = np.random.default_rng(seed)
    b = LotBook(POLICY)
    qtys = rng.integers(1, 9, size=17)
    prices = rng.uniform(50, 150, size=17)
    for i, (q, p) in enumerate(zip(qtys, prices)):
        b.buy("TEST", date(2019, 1, 1 + i), int(q), float(p))
    basis = float((qtys * prices).sum())
    factor = 7.0
    b.adjust_shares("TEST", factor)
    assert b.holdings("TEST") == int(qtys.sum() // factor)
    units = sum(f.units for f in b.fractions)
    assert units == pytest.approx(qtys.sum() / factor - qtys.sum() // factor)
    kept = sum(l.qty * l.cost_per_share for l in b.lots("TEST"))
    assert kept + sum(f.basis for f in b.fractions) == pytest.approx(basis)
    assert all(l.qty > 0 for l in b.lots("TEST"))


def test_bonus_fraction_is_paid_in_cash_at_nil_basis():
    b = LotBook(POLICY)
    b.buy("TEST", date(2019, 1, 1), 3, 90.0)
    a = pd.DataFrame([{"isin": "TEST", "ex_date": date(2020, 2, 3), "factor": 2 / 3,
                       "bonus_factor": 2 / 3, "source": "purpose"}])   # 1:2 bonus
    cash, _ = engine._apply_ex_date_events(date(2020, 2, 3), b, engine._action_map(a),
                                           {}, POLICY, [], [],
                                           last_close={"TEST": 90.0})
    assert b.holdings("TEST") == 4                    # 3 + 1 whole bonus share
    assert cash == pytest.approx(0.5 * 60.0)          # half a share at 90 x 2/3
    (fr,) = b.realised
    assert fr.cost == 0.0 and fr.buy_date == date(2020, 2, 3)
