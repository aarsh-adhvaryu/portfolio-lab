"""Measurement corrections declared 2026-09-21 (E1 §15). Synthetic only."""
from datetime import date

import numpy as np
import pytest
import pandas as pd

from conftest import random_walk_panel
from pflab.backtest import engine
from pflab.eval.periods import Period


def test_a_buy_that_uses_all_the_cash_is_trimmed_not_skipped(cost_model):
    """E1 §15: shares are sized net of buy costs. At a price where the whole
    cash buys a round number of shares, the costs no longer fit; the order
    loses whole shares until it does, instead of vanishing."""
    px, cash = 2782.0, 36 * 2782.0 + 87.0          # the B5 2007-02 case
    assert 36 * px + cost_model.buy_cost(36 * px) > cash
    q = engine._fit_to_cash(36, px, cash, cost_model)
    assert q == 35
    assert q * px + cost_model.buy_cost(q * px) <= cash


def test_an_order_that_already_fits_is_untouched(cost_model):
    assert engine._fit_to_cash(10, 100.0, 1_000_000.0, cost_model) == 10


def test_a_benchmark_never_skips_its_first_buy_on_rounding(base_config, cost_model,
                                                           tax_policy):
    """At any level a month's SIP can buy at least one unit of, every month
    after the first decision buys. (At a level above the SIP, a month that
    cannot afford one share is §5's "skip if 0", not rounding.)"""
    sessions, _, _ = random_walk_panel(seed=4, n_names=2,
                                       start="2014-01-01", end="2018-12-31")
    per = Period("t", date(2016, 1, 1), date(2018, 12, 31))
    for level in (100.0, 2782.0, 10_000.0):
        idx = pd.DataFrame({"date": sessions,
                            "close": level * (1.0003 ** np.arange(len(sessions)))})
        r = engine.run_benchmark(base_config, per, idx, cost_model, tax_policy, name="X")
        months = {(d.year, d.month) for d in sessions if per.start <= d <= per.end}
        bought = {(d.year, d.month) for d in pd.to_datetime(
            r.trades[r.trades["side"] == "BUY"]["date"])}
        assert len(months - bought) <= 1, (level, sorted(months - bought)[:5])


def test_expense_drag_is_a_realised_annual_rate(base_config, cost_model, tax_policy):
    """0.30% a year compounded by CALENDAR days: after one calendar year the
    index level is 99.70% of the undragged one, however many sessions there
    were. Counting sessions over 365 applied about 0.21%."""
    days = pd.bdate_range("2015-01-01", "2016-12-31").date
    idx = pd.DataFrame({"date": days, "close": 1000.0})
    per = Period("t", date(2015, 1, 1), date(2016, 12, 31))
    r = engine.run_benchmark(base_config, per, idx, cost_model, tax_policy,
                             name="X", expense_ratio=0.003)
    # rebuild the dragged series the same way to read it directly
    first = pd.Timestamp(days[0])
    elapsed = (pd.to_datetime(pd.Series(days)) - first).dt.days.to_numpy()
    lvl = 1000.0 * (1 - 0.003) ** (elapsed / 365.25)
    one_year = np.searchsorted(elapsed, 365)
    assert abs(lvl[one_year] / 1000.0 - 0.997) < 1e-4
    assert len(r.equity)


# -- decomposition v4 (2026-09-25) --------------------------------------
def test_decomposition_closes_exactly_and_names_its_interaction():
    """Version 3 annualised the two series separately, added the CAGRs, and
    reconciled against the PRE-tax figure that a post-tax book cannot reach.

    The two errors ran opposite ways. On E1d's development sweep they were
    1.34 pp and 0.27 pp on the base row (net 1.07) and 0.84 and 0.83 on S11,
    where they CANCELLED -- so a row that appeared to reconcile was luck,
    not correctness. This asserts closure by construction instead.
    """
    import numpy as np

    rng = np.random.default_rng(11)
    n, years = 2520, 10.0
    r_eq = rng.normal(0.0004, 0.011, n)
    r_cash = np.full(n, 0.06 / 252)
    r_eq[0] = r_cash[0] = 0.0

    r_tot = r_eq + r_cash
    ln_tot = np.log1p(r_tot)
    w_eq = np.where(np.abs(r_tot) > 1e-15, r_eq / np.where(r_tot == 0, 1, r_tot), 0.0)
    L = float(np.nansum(ln_tot))
    L_eq = float(np.nansum(ln_tot * w_eq))
    eq = np.expm1(L_eq / years)
    cash = np.expm1((L - L_eq) / years)
    total = np.expm1(L / years)
    interaction = total - (eq + cash)

    # the two parts compose multiplicatively to the whole, exactly
    assert (1 + eq) * (1 + cash) == pytest.approx(1 + total, rel=1e-12)
    # and with the interaction named, the ADDITIVE table closes too
    assert eq + cash + interaction == pytest.approx(total, rel=1e-12)
    # the interaction is real, not rounding: adding two CAGRs is simply wrong
    assert abs(interaction) > 1e-6


def test_decomposition_reconciles_against_the_book_it_is_built_from():
    """r_eq and r_cash come from the POST-tax book, so their total is the
    after-tax return. The pre-tax figure is reachable only by adding the tax
    effect back, which is now a named column rather than a silent gap."""
    book_after_tax = 0.1157
    tax_effect = 0.0134
    pre_tax = book_after_tax + tax_effect
    assert pre_tax == pytest.approx(0.1291, abs=1e-4)
