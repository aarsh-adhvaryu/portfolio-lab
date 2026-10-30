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

@pytest.fixture(autouse=True)
def _stable_channel(monkeypatch):
    """The suite runs as the installed app would (S65): a checkout without release.toml is the workshop and blocks outward sends and
    paid calls; the tests of that guard set the channel themselves."""
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    monkeypatch.delenv("PFLAB_PAID", raising=False)
    monkeypatch.delenv("PFLAB_LIVE", raising=False)


@pytest.fixture(autouse=True)
def _mail_on_for_its_own_tests(monkeypatch):
    """The product has email OFF (2026-10-30); the tests of the mail code switch it on, and the tests of the off state delete this variable."""
    monkeypatch.setenv("PFLAB_MAIL", "on")


@pytest.fixture(autouse=True)
def _no_backup_decision(monkeypatch):
    """Tests never read the investor's own backup decision in configs/service.toml (S58b); a test that needs one sets it."""
    from pflab.service import backup
    monkeypatch.setattr(backup, "declined", lambda config_path=None: None)


@pytest.fixture(autouse=True)
def _local_sandbox(request, monkeypatch):
    """The suite runs the workshop's code in the local subprocess (fast, the same everywhere); a test marked `docker`
    uses the real Docker sandbox (S64 Phase 4)."""
    if request.node.get_closest_marker("docker"):
        monkeypatch.delenv("PFLAB_SANDBOX", raising=False)
    else:
        monkeypatch.setenv("PFLAB_SANDBOX", "local")


@pytest.fixture(autouse=True)
def _fresh_probe_cache():
    """The system picture caches its slow probes (Ollama, Docker) between calls; a test never sees another test's answer."""
    from pflab.app import system
    with system._LOCK:
        system._CACHE.clear()
        system._BUSY.clear()
    yield


@pytest.fixture(autouse=True)
def _fake_investor_name(monkeypatch):
    """Tests never read the investor's real name list (S63); the analyst's gate sees an invented one."""
    from pflab.agents import analyst
    monkeypatch.setattr(analyst, "egress_names", lambda: ["ravi kumar"])


@pytest.fixture(autouse=True)
def _no_learned_models(monkeypatch):
    """Tests never read the learner's model choices on this PC (S62); a test that needs them passes a path."""
    from pflab.hq import models
    monkeypatch.setattr(models, "LEARNED_NAME", "__no_learned_models_in_tests__.toml")


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
                      annual_drift=0.0, sigma=0.015, start_price=100.0, tick=None):
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
        if tick:
            # Real prices are quoted in paise. Rounding also makes a byte-
            # identity digest independent of the last bit of np.exp, which
            # differs across CPUs (NumPy dispatches SIMD exp per platform).
            prices[n] = np.round(prices[n] / tick) * tick
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
