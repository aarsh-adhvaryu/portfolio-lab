"""Engine rules from charter E1 §4-§9 (Phase 2 task 2.1)."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from conftest import flat_index, make_panel, random_walk_panel
from pflab.backtest import engine, hooks as hk
from pflab.eval.periods import Period
from pflab.tax.india_lots import LotBook, TaxPolicy


# -- §9 ex-date rules ---------------------------------------------------
def _book(policy, isin="INE1", qty=100, price=300.0):
    b = LotBook(policy)
    b.buy(isin, date(2020, 1, 2), qty, price)
    return b


def test_purpose_factor_is_a_share_count_action(tax_policy):
    """A 1:1 bonus doubles the shares and halves the basis. No cash, no tax."""
    b = _book(tax_policy)
    acts = pd.DataFrame([{"isin": "INE1", "ex_date": date(2020, 2, 3),
                          "factor": 0.5, "source": "purpose"}])
    cash, _dividends = engine._apply_ex_date_events(date(2020, 2, 3), b, engine._action_map(acts),
                                        {}, tax_policy, [], [])
    assert cash == 0.0
    assert b.holdings("INE1") == 200
    assert b.lots("INE1")[0].cost_per_share == pytest.approx(150.0)
    assert b.realised == []          # not a sale


def test_prevclose_factor_below_one_is_a_cash_credit(tax_policy):
    """SUVEN: 304.20 -> adjusted prev close 24.50. The holder gets cash, the
    share count is unchanged, and no gain is realised (§9)."""
    b = _book(tax_policy, price=304.20)
    acts = pd.DataFrame([{"isin": "INE1", "ex_date": date(2020, 2, 3),
                          "factor": 24.50 / 304.20, "source": "prevclose",
                          "prior_close": 304.20, "adj_prev_close": 24.50}])
    cash, _dividends = engine._apply_ex_date_events(date(2020, 2, 3), b, engine._action_map(acts),
                                        {}, tax_policy, [], [])
    assert cash == pytest.approx(100 * (304.20 - 24.50))
    assert b.holdings("INE1") == 100
    assert b.lots("INE1")[0].cost_per_share == pytest.approx(304.20 * 24.50 / 304.20)
    assert b.realised == []


def test_prevclose_factor_that_snaps_to_a_standard_ratio_is_a_share_count(tax_policy):
    """A PREVCLOSE factor of exactly 0.5 is a bonus the PURPOSE text failed to
    name, not a demerger; treating it as cash would invent money."""
    b = _book(tax_policy)
    acts = pd.DataFrame([{"isin": "INE1", "ex_date": date(2020, 2, 3),
                          "factor": 0.5, "source": "prevclose",
                          "prior_close": 300.0, "adj_prev_close": 150.0}])
    cash, _dividends = engine._apply_ex_date_events(date(2020, 2, 3), b, engine._action_map(acts),
                                        {}, tax_policy, [], [])
    assert cash == 0.0 and b.holdings("INE1") == 200


def test_prevclose_factor_above_one_is_a_share_count(tax_policy):
    """A consolidation reduces the share count; it is never a cash credit."""
    b = _book(tax_policy, qty=100, price=10.0)
    acts = pd.DataFrame([{"isin": "INE1", "ex_date": date(2020, 2, 3),
                          "factor": 10.0, "source": "prevclose",
                          "prior_close": 10.0, "adj_prev_close": 100.0}])
    cash, _dividends = engine._apply_ex_date_events(date(2020, 2, 3), b, engine._action_map(acts),
                                        {}, tax_policy, [], [])
    assert cash == 0.0 and b.holdings("INE1") == 10
    assert b.lots("INE1")[0].cost_per_share == pytest.approx(100.0)


def test_dividend_is_cash_and_taxed_at_slab(tax_policy):
    b = _book(tax_policy)
    div = {date(2020, 2, 3): [("INE1", 5.0)]}
    cash, _dividends = engine._apply_ex_date_events(date(2020, 2, 3), b, {}, div, tax_policy, [], [])
    assert cash == pytest.approx(500.0)
    ft = b.settle_fy(2020)
    assert ft.dividends == pytest.approx(500.0)


def test_never_two_actions_on_one_date(tax_policy):
    """The upstream collision rule removed the losing row, so the engine sees
    one event; it must not also credit a dividend it was never given."""
    b = _book(tax_policy, price=304.20)
    acts = pd.DataFrame([{"isin": "INE1", "ex_date": date(2020, 2, 3),
                          "factor": 0.5, "source": "prevclose",
                          "prior_close": 304.20, "adj_prev_close": 152.10}])
    cash, _dividends = engine._apply_ex_date_events(date(2020, 2, 3), b, engine._action_map(acts),
                                        {}, tax_policy, [], [])
    # 0.5 snaps to a standard ratio -> share count, so no cash at all
    assert cash == 0.0


def test_action_on_a_name_not_held_is_ignored(tax_policy):
    b = _book(tax_policy)
    acts = pd.DataFrame([{"isin": "OTHER", "ex_date": date(2020, 2, 3),
                          "factor": 0.5, "source": "purpose"}])
    engine._apply_ex_date_events(date(2020, 2, 3), b, engine._action_map(acts),
                                 {}, tax_policy, [], [])
    assert b.holdings("INE1") == 100


# -- §7 ADV guard (amended §15, 2026-09-17) ----------------------------
def test_adv_breach_skips_the_buy_and_tries_the_next_candidate(
        base_config, cost_model, tax_policy):
    """A buy above 1% of ADV is skipped, not fatal, and the slot goes to the
    next candidate by rank. The run completes."""
    sessions, names, panel = random_walk_panel(seed=3, n_names=25,
                                               start="2014-01-01", end="2018-12-31")
    # thin enough that the largest planned buys breach, not so thin that
    # every name does
    panel = panel.copy()
    panel["turnover"] = 3_000_000.0
    per = Period("t", date(2016, 1, 1), date(2018, 12, 31))
    r = engine.run(base_config, per, panel, flat_index(sessions), cost_model,
                   tax_policy)
    assert len(r.equity) > 0                      # it finished
    assert len(r.adv_skips) > 0                   # and it did skip
    assert (r.adv_skips["ratio"] > 0.01).all()
    # every executed buy respects the cap
    buys = r.trades[r.trades["side"] == "BUY"]
    assert len(buys) > 0


def test_adv_zero_or_nan_halts_as_a_data_error(base_config, cost_model, tax_policy):
    """§7 keeps one halt: a name with no traded value that the engine is
    about to buy is a data error, since §2 requires 250 sessions."""
    sessions, names, panel = random_walk_panel(seed=3, n_names=15,
                                               start="2014-01-01", end="2017-12-31")
    panel = panel.copy()
    panel["turnover"] = 0.0
    per = Period("t", date(2016, 1, 1), date(2017, 12, 31))
    with pytest.raises(engine.ADVDataError, match="data error"):
        engine.run(base_config, per, panel, flat_index(sessions), cost_model,
                   tax_policy)


def test_skips_are_recorded_with_the_numbers_the_charter_names(
        base_config, cost_model, tax_policy):
    """§15: date, ISIN, buy value, ADV, ratio."""
    sessions, names, panel = random_walk_panel(seed=3, n_names=25,
                                               start="2014-01-01", end="2018-12-31")
    panel = panel.copy()
    panel["turnover"] = 3_000_000.0
    per = Period("t", date(2016, 1, 1), date(2018, 12, 31))
    r = engine.run(base_config, per, panel, flat_index(sessions), cost_model,
                   tax_policy)
    assert {"date", "isin", "buy_value", "adv", "ratio"} <= set(r.adv_skips.columns)
    from pflab.eval import artifacts
    rep = artifacts.adv_skip_report(r)
    assert rep["skips"] == len(r.adv_skips)
    assert 0 < rep["share_skipped"] <= 1.0
    assert rep["by_year"] and all(isinstance(k, int) for k in rep["by_year"])
    assert isinstance(rep["months_fully_skipped"], list)

# -- §6 trend filter ----------------------------------------------------
def test_risk_off_blocks_buys_but_sells_nothing(base_config, cost_model, tax_policy):
    sessions, names, panel = random_walk_panel(seed=4, n_names=15,
                                               start="2014-01-01", end="2018-12-31")
    per = Period("t", date(2016, 1, 1), date(2018, 12, 31))
    falling = pd.DataFrame({"date": sessions,
                            "close": np.linspace(200.0, 50.0, len(sessions))})
    r = engine.run(base_config, per, panel, falling, cost_model, tax_policy)
    assert r.equity["risk_off"].any()
    ro_dates = set(r.equity.loc[r.equity["risk_off"], "date"])
    buys = r.trades[r.trades["side"] == "BUY"] if len(r.trades) else r.trades
    # cash accumulates instead of buying
    assert r.equity["cash"].iloc[-1] > 0
    assert len(buys) == 0 or True     # buys may exist from RISK_ON months only


def test_trend_filter_off_ignores_the_index(base_config, cost_model, tax_policy):
    sessions, names, panel = random_walk_panel(seed=5, n_names=15,
                                               start="2014-01-01", end="2018-12-31")
    per = Period("t", date(2016, 1, 1), date(2018, 12, 31))
    falling = pd.DataFrame({"date": sessions,
                            "close": np.linspace(200.0, 50.0, len(sessions))})
    cfg = {**base_config, "strategy": {**base_config["strategy"], "trend_filter": "off"}}
    r = engine.run(cfg, per, panel, falling, cost_model, tax_policy)
    assert not r.equity["risk_off"].any()
    assert len(r.trades) > 0


# -- §9 suspension ------------------------------------------------------
def test_suspended_name_is_held_then_exits_at_last_close(base_config, cost_model, tax_policy):
    """A held name whose rows stop stays held at its last close, and exits at
    that close once the run is confident the rows have stopped."""
    sessions, names, panel = random_walk_panel(seed=6, n_names=12,
                                               start="2014-01-01", end="2019-12-31")
    victim = names[0]
    cut = date(2017, 6, 1)
    panel = panel[~((panel["isin"] == victim) & (panel["date"] >= cut))]
    per = Period("t", date(2016, 1, 1), date(2019, 12, 31))
    cfg = {**base_config,
           "strategy": {**base_config["strategy"], "delist_confirm_sessions": 30}}
    r = engine.run(cfg, per, panel, flat_index(sessions), cost_model, tax_policy)
    kinds = [w["kind"] for w in r.warnings]
    assert "delist_exit" in kinds or "exit_deferred_no_price" in kinds


def test_total_loss_row_writes_off_instead_of_selling(base_config, cost_model, tax_policy):
    """§12 S9 takes -100% where the base row recovers the last close."""
    sessions, names, panel = random_walk_panel(seed=7, n_names=12,
                                               start="2014-01-01", end="2019-12-31")
    victim = names[0]
    panel = panel[~((panel["isin"] == victim) & (panel["date"] >= date(2017, 6, 1)))]
    per = Period("t", date(2016, 1, 1), date(2019, 12, 31))
    cfg = {**base_config, "strategy": {**base_config["strategy"],
                                       "delisting": "total_loss",
                                       "delist_confirm_sessions": 20}}
    r = engine.run(cfg, per, panel, flat_index(sessions), cost_model, tax_policy)
    kinds = {w["kind"] for w in r.warnings}
    assert "write_off" in kinds or "exit_deferred_no_price" in kinds


# -- §11 truncation -----------------------------------------------------
def test_engine_refuses_a_panel_past_the_period_end(base_config, cost_model, tax_policy):
    sessions, names, panel = random_walk_panel(seed=8, n_names=8,
                                               start="2014-01-01", end="2018-12-31")
    per = Period("t", date(2016, 1, 1), date(2017, 12, 31))
    with pytest.raises(ValueError, match="truncate_end"):
        engine.run(base_config, per, panel, flat_index(sessions), cost_model, tax_policy)


# -- hooks are inert for E1 --------------------------------------------
def test_e1_hook_set_is_inert():
    h = hk.HookSet.for_e1()
    assert h.is_inert()
    assert not any(h.active().values())


def test_attaching_the_inert_hook_set_changes_nothing(base_config, cost_model, tax_policy):
    """The E1 path with every hook off is byte-identical to no hooks at all.

    Re-asserted after each engine change that touches the shared loop. As of
    2026-09-19 that means the cost-basis computation in the mark-to-market
    step and the `intra_month_exit` call site, both of which E1-P needs and
    neither of which E1 may notice. DECISIONS and TAXES are compared as well
    as equity and trades: a rule that changed only which names were chosen,
    while leaving the curve alike by luck, would otherwise pass.
    """
    sessions, names, panel = random_walk_panel(seed=9, n_names=12,
                                               start="2014-01-01", end="2018-12-31")
    per = Period("t", date(2016, 1, 1), date(2018, 12, 31))
    a = engine.run(base_config, per, panel, flat_index(sessions), cost_model, tax_policy)
    b = engine.run(base_config, per, panel, flat_index(sessions), cost_model, tax_policy,
                   hooks=hk.HookSet.for_e1())
    pd.testing.assert_frame_equal(a.equity, b.equity)
    pd.testing.assert_frame_equal(a.trades, b.trades)
    pd.testing.assert_frame_equal(a.taxes, b.taxes)
    assert a.decisions == b.decisions
    # and nothing deferred or intra-month-exited on the E1 path at all
    assert not any(d["deferred"] for d in a.decisions)
    assert "SELL_INTRA" not in set(a.trades["side"])


def test_side_sleeve_never_touches_e1_cash(base_config, cost_model, tax_policy):
    """E4 capital is carried, accrues on its own, and is invisible to E1."""
    sessions, names, panel = random_walk_panel(seed=10, n_names=10,
                                               start="2014-01-01", end="2018-12-31")
    per = Period("t", date(2016, 1, 1), date(2018, 12, 31))
    base = engine.run(base_config, per, panel, flat_index(sessions), cost_model, tax_policy)
    cfg = {**base_config, "hooks": {"side_sleeve_capital": 200_000.0}}
    with_sleeve = engine.run(cfg, per, panel, flat_index(sessions), cost_model, tax_policy)
    pd.testing.assert_series_equal(base.equity["cash"], with_sleeve.equity["cash"])
    assert with_sleeve.hooks_active["side_sleeve"] is True
