"""Shared synthetic fixtures for the Phase 2 engine tests.

Everything here is generated, so the tests stay fast and never touch
PFLAB_DATA_DIR or the sealed period.
"""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from pflab.eval.periods import Period
from pflab.execution.costs import CostModel
from pflab.tax.india_lots import TaxPolicy

PANEL_COLUMNS = ["date", "isin", "symbol", "series", "instrument_type", "open",
                 "high", "low", "close", "prev_close", "volume", "turnover",
                 "adj_factor", "adj_close", "adj_open", "dividend"]


def make_panel(sessions, names, prices, turnover=5e9, dividend=None):
    """prices: {isin: array aligned with sessions}. Turnover is deliberately
    huge so the §7 ADV guard never fires in tests that are not about it."""
    rows = []
    for j, isin in enumerate(names):
        px = prices[isin]
        prev = np.concatenate([[px[0]], px[:-1]])
        for i, d in enumerate(sessions):
            rows.append({
                "date": d, "isin": isin, "symbol": f"S{j}", "series": "EQ",
                "instrument_type": "STK", "open": px[i], "high": px[i],
                "low": px[i], "close": px[i], "prev_close": prev[i],
                "volume": 100000, "turnover": turnover, "adj_factor": 1.0,
                "adj_close": px[i], "adj_open": px[i],
                "dividend": (dividend or {}).get((isin, d), 0.0)})
    return pd.DataFrame(rows, columns=PANEL_COLUMNS)


def random_walk_panel(seed=0, n_names=40, start="2014-01-01", end="2021-12-31",
                      annual_drift=0.0, sigma=0.015, start_price=100.0):
    """A cross-section with NO predictability: every name is an independent
    random walk whose median path grows at `annual_drift`.

    `annual_drift` is the compound annual growth of the median path, so
    `annual_drift=0.06` means every asset earns 6% a year in expectation and
    nothing distinguishes one name from another. That is the null the task 2.5
    control needs (see tests/test_negative_control.py); `annual_drift=0.0`
    gives a flat market for the rule tests, where the level does not matter.
    """
    rng = np.random.default_rng(seed)
    sessions = [d for d in pd.bdate_range(start, end).date]
    names = [f"INE{i:03d}A01011" for i in range(n_names)]
    mu = np.log1p(annual_drift) / 252.0
    prices = {}
    for n in names:
        prices[n] = start_price * np.exp(np.cumsum(rng.normal(mu, sigma, len(sessions))))
    return sessions, names, make_panel(sessions, names, prices)


def flat_index(sessions, level=100.0):
    """An index that never triggers RISK_OFF."""
    return pd.DataFrame({"date": sessions, "close": [level] * len(sessions)})


@pytest.fixture
def cost_model():
    return CostModel.from_toml("configs/costs_zerodha.toml")


@pytest.fixture
def tax_policy():
    return TaxPolicy.from_toml("configs/tax_policy_in.toml")


@pytest.fixture
def base_config():
    return {
        "strategy": {"lookback_sessions": 252, "skip_sessions": 21, "n_hold": 10,
                     "band_exit_rank": 20, "max_buys_per_month": 6,
                     "sip_amount": 50_000.0, "initial_cash": 0.0,
                     "cash_rate_annual": 0.06, "trend_filter": "sma10",
                     "delisting": "last_close"},
        "universe": {"series": ["EQ"], "min_sessions": 250,
                     "top_n_by_turnover": 500, "turnover_window": 126,
                     "min_price": 10.0, "max_adv_fraction": 0.01},
        "costs": {"multiplier": 1.0},
    }


@pytest.fixture
def period_2016_2021():
    return Period("test", date(2016, 1, 1), date(2021, 12, 31))
