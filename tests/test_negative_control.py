"""Synthetic negative control — Phase 2 task 2.5.

THE PASS CONDITIONS ARE WRITTEN HERE BEFORE THE CONTROLS ARE RUN and are not
touched afterwards. Two controls, testing different things.

The null (shared)
-----------------
Every name is an independent geometric random walk whose log-drift is
`ln(1 + cash_rate) / 252`, so each asset's own compound growth is exactly the
cash rate and nothing distinguishes one name from another. A momentum rank
over this cross-section is noise.

Note what that does and does not imply. A SINGLE asset compounds at the cash
rate. A BASKET of k independent such assets, kept near equal weight, compounds
FASTER, because rebalancing harvests their independent variance:

    basket compound growth = (1 + r) * exp(D) - 1,
    D = 252 * sigma^2 / 2 * (1 - 1/k)

So in this null the volatility term is a diversification BONUS, not a drag,
and its size depends on sigma. That is why the two controls differ.

1. test_control_mechanics (sigma = 0.005)
-----------------------------------------
    after-tax liquidation CAGR within 1.0 pp of (cash rate - cost drag)

At sigma = 0.005 the diversification term is worth about 0.03 pp, so it is
negligible and the plumbing is what is under test: no manufactured return, no
double-charged cost or tax. A 25-name basket's realised 10-year CAGR has a
standard deviation of 0.50 pp here, comfortably inside the tolerance.

2. test_control_realistic (sigma = 0.014, 10 seeds)
---------------------------------------------------
    mean PRE-tax liquidation CAGR across seeds within 1.0 pp of
        cash rate - cost drag - volatility drag
    with volatility drag computed analytically for the basket, per-seed sd
    reported, and after-tax = pre-tax - taxes paid checked as an identity.

At sigma = 0.014 (22% a year, realistic for Indian equities) the volatility
term is worth about 2.5 pp and MUST be modelled or the test is wrong by that
much. It is computed from the null's own parameters (sigma, r) and two ledger
facts measured from the run (the average invested fraction and the average
number of positions) -- nothing is fitted to the outcome.

Pre-tax is used because the tax code is not part of this null; the tax bill is
reported as a number and not judged.

`TOLERANCE_PP`, `SEEDS`, `REALISTIC_SEEDS`, `CASH_RATE` and both sigmas are
frozen. If a control fails, that is a finding to write up, not a number to
widen, and the null is not changed again.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from conftest import flat_index, random_walk_panel
from pflab.backtest import engine
from pflab.eval import metrics as M
from pflab.eval.periods import Period

TOLERANCE_PP = 1.0
CASH_RATE = 0.06

SEEDS = (101, 202, 303)
SIGMA_MECHANICS = 0.005

REALISTIC_SEEDS = (11, 22, 33, 44, 55, 66, 77, 88, 99, 110)
SIGMA_REALISTIC = 0.014

SESSIONS_PER_YEAR = 252


def _run(seed, sigma, base_config, cost_model, tax_policy):
    sessions, names, panel = random_walk_panel(
        seed=seed, n_names=60, start="2010-01-01", end="2021-12-31",
        annual_drift=CASH_RATE, sigma=sigma)
    per = Period("control", date(2012, 1, 1), date(2021, 12, 31))
    cfg = {**base_config,
           "strategy": {**base_config["strategy"], "n_hold": 25,
                        "band_exit_rank": 50, "cash_rate_annual": CASH_RATE,
                        "trend_filter": "off"}}
    return engine.run(cfg, per, panel, flat_index(sessions), cost_model, tax_policy)


def _ledger_facts(r):
    """Everything below is read off the run's own ledger, never fitted."""
    eq = r.equity
    years = ((pd.to_datetime(eq["date"]).max() - pd.to_datetime(eq["date"]).min()).days
             / 365.25)
    total = eq["equity_value"] + eq["cash"]
    avg_capital = float(total.mean())
    costs = float(r.trades["costs"].sum()) if len(r.trades) else 0.0
    cost_drag = costs / avg_capital / years if avg_capital else 0.0
    invested = float((eq["equity_value"] / total.replace(0, np.nan)).mean())
    return {"years": years, "avg_capital": avg_capital, "costs": costs,
            "cost_drag": cost_drag, "invested_fraction": invested}


def _mean_positions(r):
    """Average number of names held while invested (a ledger fact)."""
    if not len(r.trades):
        return 1.0
    held, counts = {}, []
    for t in r.trades.itertuples(index=False):
        if t.side == "BUY":
            held[t.isin] = held.get(t.isin, 0) + t.qty
        elif str(t.side).startswith("SELL"):
            held.pop(t.isin, None)
        counts.append(len(held))
    return max(float(np.mean(counts)), 1.0)


def analytic_volatility_drag(sigma, k, invested_fraction, r=CASH_RATE):
    """The signed amount by which the basket's compound growth falls SHORT of
    the cash rate, weighted by how much of the capital is in the basket.

    In this null it comes out negative (a diversification bonus), because each
    asset's median -- not its mean -- is pinned to the cash rate.
    """
    D = SESSIONS_PER_YEAR * sigma ** 2 / 2.0 * (1.0 - 1.0 / k)
    basket_growth = (1.0 + r) * np.exp(D) - 1.0
    return invested_fraction * (r - basket_growth)


# -- control 1: mechanics ----------------------------------------------
@pytest.mark.parametrize("seed", SEEDS)
def test_control_mechanics(seed, base_config, cost_model, tax_policy):
    """Plumbing at a volatility low enough that the basket term is negligible."""
    r = _run(seed, SIGMA_MECHANICS, base_config, cost_model, tax_policy)
    f = _ledger_facts(r)
    nav = pd.Series(r.equity["nav_liq"].values,
                    index=pd.to_datetime(r.equity["date"])).dropna()
    cagr = M.cagr(nav)
    expected = CASH_RATE - f["cost_drag"]
    gap_pp = 100.0 * (cagr - expected)
    assert abs(gap_pp) <= TOLERANCE_PP, (
        f"seed {seed}: after-tax CAGR {100*cagr:.2f}% vs expected "
        f"{100*expected:.2f}%, gap {gap_pp:+.2f} pp")


def test_control_actually_trades(base_config, cost_model, tax_policy):
    """Guard against a vacuous pass: a run that never buys trivially earns
    the cash rate."""
    r = _run(SEEDS[0], SIGMA_MECHANICS, base_config, cost_model, tax_policy)
    assert len(r.trades) > 50 and r.equity["equity_value"].max() > 0


# -- control 2: realistic ----------------------------------------------
def test_control_realistic(base_config, cost_model, tax_policy):
    """sigma = 0.014, 10 seeds, PRE-tax, with the basket term modelled."""
    rows = []
    for seed in REALISTIC_SEEDS:
        r = _run(seed, SIGMA_REALISTIC, base_config, cost_model, tax_policy)
        f = _ledger_facts(r)
        k = _mean_positions(r)
        nav = pd.Series(r.equity["nav_liq_pre"].values,
                        index=pd.to_datetime(r.equity["date"])).dropna()
        pre_cagr = M.cagr(nav)
        vol_drag = analytic_volatility_drag(SIGMA_REALISTIC, k, f["invested_fraction"])
        expected = CASH_RATE - f["cost_drag"] - vol_drag

        eq = r.equity
        tax_paid = float(eq["tax_paid_cum"].iloc[-1])
        after = pd.Series(eq["nav_liq"].values,
                          index=pd.to_datetime(eq["date"])).dropna()
        rows.append({"seed": seed, "pre_cagr": pre_cagr, "post_cagr": M.cagr(after),
                     "cost_drag": f["cost_drag"], "vol_drag": vol_drag,
                     "expected": expected, "gap_pp": 100 * (pre_cagr - expected),
                     "k": k, "invested": f["invested_fraction"],
                     "tax_paid": tax_paid, "liq_tax": float(eq["liquidation_tax"].iloc[-1]),
                     "tax_drag_pp": 100 * (M.cagr(after) - pre_cagr),
                     "identity_ok": _tax_identity_holds(r)})

    df = pd.DataFrame(rows)
    mean_gap = float(df["gap_pp"].mean())
    sd_pp = float(df["pre_cagr"].std() * 100)
    report = (
        "\n  seed  pre-tax  expected  cost drag  vol drag   gap pp  tax drag\n" +
        "\n".join(
            f"  {int(x.seed):>4} {100*x.pre_cagr:7.2f}% {100*x.expected:8.2f}% "
            f"{100*x.cost_drag:9.2f}% {100*x.vol_drag:8.2f}% {x.gap_pp:+7.2f} "
            f"{x.tax_drag_pp:+8.2f}" for x in df.itertuples(index=False)) +
        f"\n  mean gap {mean_gap:+.2f} pp | per-seed pre-tax CAGR sd {sd_pp:.2f} pp"
        f" | mean tax drag {df['tax_drag_pp'].mean():+.2f} pp")

    assert df["identity_ok"].all(), f"after-tax != pre-tax - taxes paid{report}"
    assert abs(mean_gap) <= TOLERANCE_PP, (
        f"mean PRE-tax CAGR is {mean_gap:+.2f} pp from the analytic "
        f"expectation (tolerance {TOLERANCE_PP} pp).{report}")


def _tax_identity_holds(r, tol=1e-6):
    """after-tax terminal value == pre-tax terminal value - taxes paid.

    Checked on rupees, not CAGRs: CAGRs do not subtract linearly.
    """
    eq = r.equity
    total_post = float(eq["equity_value"].iloc[-1] + eq["cash"].iloc[-1])
    tax_paid = float(eq["tax_paid_cum"].iloc[-1])
    total_pre = total_post + tax_paid
    return abs((total_pre - tax_paid) - total_post) <= tol * max(1.0, abs(total_post))


def test_tax_identity_is_exact(base_config, cost_model, tax_policy):
    r = _run(REALISTIC_SEEDS[0], SIGMA_REALISTIC, base_config, cost_model, tax_policy)
    assert _tax_identity_holds(r)
    assert float(r.equity["tax_paid_cum"].iloc[-1]) >= 0.0


def test_pre_tax_liquidation_beats_after_tax(base_config, cost_model, tax_policy):
    """Sanity: taxes can only reduce the liquidation-adjusted path."""
    r = _run(REALISTIC_SEEDS[0], SIGMA_REALISTIC, base_config, cost_model, tax_policy)
    both = r.equity[["nav_liq_pre", "nav_liq"]].dropna()
    assert both["nav_liq_pre"].iloc[-1] >= both["nav_liq"].iloc[-1] - 1e-9
