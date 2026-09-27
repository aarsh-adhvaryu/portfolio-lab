"""E1-P — patience (§3) and the two negative controls (§4).

All synthetic. Nothing here touches PFLAB_DATA_DIR or the sealed period.
Each test asserts a charter sentence, not an implementation detail.
"""
from datetime import date, timedelta

import pandas as pd
import pytest
from dateutil.relativedelta import relativedelta

from conftest import flat_index, random_walk_panel
from pflab.backtest import engine, hooks as hk
from pflab.eval.periods import Period
from pflab.tax.india_lots import is_long_term


# -- §3 the rule itself -------------------------------------------------
def test_defer_window_is_inclusive_at_twelve_months():
    """A lot exactly 12 months old is still SHORT-term, so it is exactly the
    lot patience exists for. Excluding the endpoint would drop it."""
    d = hk.patience_defer()
    m = date(2016, 6, 30)
    for months, want in ((8, False), (9, True), (11, True), (12, True)):
        buy = m - relativedelta(months=months)
        assert d(m, "X", 60.0, [(m - buy).days], None) is want, months
    # one day past twelve months it is already long-term: nothing to gain
    buy = m - relativedelta(months=12) - timedelta(days=1)
    assert is_long_term(buy, m)
    assert d(m, "X", 60.0, [(m - buy).days], None) is False


def test_defer_respects_the_rank_ceiling():
    """§3: slipped, not broken. Rank 101 is broken."""
    d = hk.patience_defer(rank_ceiling=100.0)
    m = date(2016, 6, 30)
    age = [(m - (m - relativedelta(months=10))).days]
    assert d(m, "X", 100.0, age, None) is True
    assert d(m, "X", 100.5, age, None) is False
    assert d(m, "X", None, age, None) is False       # off the ranked list


def test_defer_uses_the_oldest_lot():
    """FIFO sells the oldest lot first, so that is the lot whose tax
    treatment is at stake. Declared in docs/notes/E1P-readiness.md."""
    d = hk.patience_defer()
    m = date(2016, 6, 30)
    old = (m - (m - relativedelta(months=10))).days      # in the window
    young = (m - (m - relativedelta(months=2))).days     # not
    assert d(m, "X", 60.0, [young, old], None) is True
    assert d(m, "X", 60.0, [young], None) is False


class _Lot:
    """Minimal stand-in for tax.india_lots.Lot: the two fields S4 reads."""
    def __init__(self, buy_date, cost_per_share, qty=1):
        self.buy_date, self.cost_per_share, self.qty = buy_date, cost_per_share, qty


def test_s4_defers_only_a_lot_in_gain():
    """§6 S4: a loss is sold, because the STCL is worth harvesting."""
    d = hk.patience_defer(require_gain=True)
    m = date(2016, 6, 30)
    old_buy = m - relativedelta(months=10)
    age = [(m - old_buy).days]

    class S:
        positions = {"X": 10}
        cost_basis = {"X": 100.0}
        lots = {"X": [_Lot(old_buy, 100.0, 10)]}
        holdings_value = {"X": 1200.0}      # 120/share: a gain
    assert d(m, "X", 60.0, age, S) is True
    S.holdings_value = {"X": 900.0}         # 90/share: a loss
    assert d(m, "X", 60.0, age, S) is False


def test_s4_tests_the_oldest_lot_not_the_position_average():
    """§3's per-lot resolution, locked 2026-09-19: "S4 tests the oldest lot's
    own unrealised gain, not the position average."

    The two disagree exactly when it matters. Here the oldest lot is under
    water at 150 while a later, cheaper lot at 50 drags the position average
    to 100 and shows a gain at a price of 120. FIFO would realise the oldest
    lot, i.e. a LOSS -- which is the short-term capital loss S4 exists to
    harvest -- so S4 must not defer.
    """
    d = hk.patience_defer(require_gain=True)
    m = date(2016, 6, 30)
    old_buy = m - relativedelta(months=10)
    young_buy = m - relativedelta(months=1)
    age = [(m - old_buy).days, (m - young_buy).days]

    class S:
        positions = {"X": 20}
        cost_basis = {"X": 100.0}                     # the average: a "gain"
        lots = {"X": [_Lot(old_buy, 150.0, 10),       # oldest: at a loss
                      _Lot(young_buy, 50.0, 10)]}
        holdings_value = {"X": 2400.0}                # 120/share
    assert d(m, "X", 60.0, age, S) is False, "deferred on the average, not the lot"

    # reverse the lots: the oldest is now in gain, the average unchanged
    S.lots = {"X": [_Lot(old_buy, 50.0, 10), _Lot(young_buy, 150.0, 10)]}
    assert d(m, "X", 60.0, age, S) is True


def test_s5_is_a_pure_minimum_hold_on_every_lot():
    """§6 S5: six months on EVERY lot, regardless of rank, tax-blind.

    §4 sells a held name in full, so "every lot" can only be honoured by
    waiting for the YOUNGEST lot to reach the floor. Testing the oldest lot
    instead would sell a one-month-old lot the moment the oldest passed six
    months -- which is the thing S5 forbids.
    """
    d = hk.patience_defer(min_hold_months=6)
    m = date(2016, 6, 30)

    def age(months):
        return (m - (m - relativedelta(months=months))).days

    assert d(m, "X", 5000.0, [age(3)], None) is True      # rank is ignored
    assert d(m, "X", 51.0, [age(7)], None) is False       # past the floor
    # the decisive case: an old lot and a young one together
    assert d(m, "X", 51.0, [age(24), age(1)], None) is True
    assert d(m, "X", 51.0, [age(24), age(9)], None) is False


def test_s5_ignores_the_base_rule_entirely():
    """S5 is "pure patience, tax-blind": no 9-12 window, no rank ceiling."""
    d = hk.patience_defer(min_hold_months=6, min_months=9, max_months=12,
                          rank_ceiling=100.0)
    m = date(2016, 6, 30)
    young = (m - (m - relativedelta(months=2))).days
    # rank far past the ceiling and age far outside the window: still held
    assert d(m, "X", 9999.0, [young], None) is True


# -- §3 through the engine ----------------------------------------------
def _run(cfg, seed=21, n_names=60, **kw):
    """A wide enough cross-section that a BAND exit can happen at all.

    base_config holds 10 and bands out at rank 20, so a 14-name panel can
    never produce a band exit -- every rank is <= 14 -- and §3's rule, which
    fires only on band exits, would look inert when it is simply unreachable.
    """
    sessions, names, panel = random_walk_panel(seed=seed, n_names=n_names,
                                               start="2012-01-01", end="2018-12-31")
    per = Period("t", date(2014, 1, 1), date(2018, 12, 31))
    from conftest import flat_index as fi
    return engine.run(cfg, per, panel, fi(sessions), **kw), panel


def test_patience_defers_band_exits_and_e1_does_not(base_config, cost_model, tax_policy):
    cand = {**base_config, "hooks": {"patience": {"enabled": True}}}
    a, _ = _run(base_config, cost_model=cost_model, tax_policy=tax_policy)
    b, _ = _run(cand, cost_model=cost_model, tax_policy=tax_policy)
    assert not any(d["deferred"] for d in a.decisions), "E1 never defers"
    assert any(d["deferred"] for d in b.decisions), "the rule never fired"
    assert b.hooks_active["defer_exit"] is True


def test_a_deferred_name_is_not_sold_that_month(base_config, cost_model, tax_policy):
    """The charter's point: the sale waits, so it is not in that month's
    sell list."""
    cand = {**base_config, "hooks": {"patience": {"enabled": True}}}
    r, _ = _run(cand, cost_model=cost_model, tax_policy=tax_policy)
    sells = r.trades[r.trades["side"] == "SELL"]
    by_date = {d: set(g["isin"]) for d, g in sells.groupby("date")}
    checked = 0
    for d in r.decisions:
        for isin in d["deferred"]:
            # the exit would have executed at the next session's open; assert
            # it is absent from every sell that month
            for dt_, names in by_date.items():
                if d["month_end"] <= dt_ <= d["month_end"] + timedelta(days=20):
                    assert isin not in names
                    checked += 1
    assert checked, "no deferral reached a sell window"


def test_delisting_exits_are_never_deferred(base_config, cost_model, tax_policy):
    """§3. Holds by construction: the engine calls defer_exit only where the
    reason is 'band', and a delisting exit never enters that loop."""
    cand = {**base_config, "hooks": {"patience": {"enabled": True,
                                                  "rank_ceiling": 1e9,
                                                  "min_months": 0,
                                                  "max_months": 600,
                                                  "ignore_rank": True}}}
    sessions, names, panel = random_walk_panel(seed=31, n_names=12,
                                               start="2012-01-01", end="2018-12-31")
    # one name stops trading entirely
    victim = names[0]
    panel = panel[~((panel["isin"] == victim) &
                    (pd.to_datetime(panel["date"]).dt.date > date(2016, 6, 30)))]
    per = Period("t", date(2014, 1, 1), date(2018, 12, 31))
    r = engine.run(cand, per, panel, flat_index(sessions), cost_model, tax_policy)
    # even with a defer rule that says "always", the delisting still exits
    kinds = {w["kind"] for w in r.warnings}
    assert "write_down" in kinds          # E1 §15, 2026-09-27
    for d in r.decisions:
        assert victim not in d["deferred"] or victim in d["held"]


# -- §4 the negative controls -------------------------------------------
def test_stop_loss_sells_at_the_next_open(base_config, cost_model, tax_policy):
    cfg = {**base_config, "hooks": {"intra_month_exit": "stop_loss",
                                    "stop_loss_pct": 0.20}}
    r, _ = _run(cfg, seed=44, cost_model=cost_model, tax_policy=tax_policy)
    intra = r.trades[r.trades["side"] == "SELL_INTRA"]
    assert len(intra), "the control never fired"
    assert r.hooks_active["intra_month_exit"] is True
    # a control sale has no month-end reference price to slip against
    assert intra["reference_price"].isna().all()


def test_profit_take_fires_on_gains_not_losses(base_config, cost_model, tax_policy):
    cfg = {**base_config, "hooks": {"intra_month_exit": "profit_take",
                                    "profit_take_pct": 0.50}}
    r, _ = _run(cfg, seed=45, cost_model=cost_model, tax_policy=tax_policy)
    intra = r.trades[r.trades["side"] == "SELL_INTRA"]
    assert len(intra), "the control never fired"


def test_a_name_bought_today_is_not_sold_today(base_config, cost_model, tax_policy):
    """The call site runs after the month-start buy list, and `state` still
    carries yesterday's marks, so a purchase cannot trigger its own sale."""
    cfg = {**base_config, "hooks": {"intra_month_exit": "stop_loss",
                                    "stop_loss_pct": 0.0001}}
    r, _ = _run(cfg, seed=46, cost_model=cost_model, tax_policy=tax_policy)
    t = r.trades
    for d, g in t.groupby("date"):
        bought = set(g[g["side"] == "BUY"]["isin"])
        sold = set(g[g["side"] == "SELL_INTRA"]["isin"])
        assert not (bought & sold), f"{d}: bought and control-sold the same name"


def test_an_unknown_control_name_is_an_error():
    """A typo must not produce a silently inert run."""
    with pytest.raises(ValueError, match="intra_month_exit"):
        hk.from_config({"hooks": {"intra_month_exit": "stop-loss"}})


def test_controls_and_patience_are_independent(base_config, cost_model, tax_policy):
    """§4: the controls are 'everything else as E1', so they do not also
    carry §3's rule."""
    hs = hk.from_config({"hooks": {"intra_month_exit": "stop_loss",
                                   "patience": {"enabled": False}}})
    assert hs.active()["intra_month_exit"] is True
    assert hs.active()["defer_exit"] is False
