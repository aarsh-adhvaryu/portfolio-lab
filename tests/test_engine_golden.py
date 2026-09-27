"""Byte-identity of E1's engine paths on synthetic data.

The digests below were captured on 2026-09-27 from the engine BEFORE E3-R's
target-equity mechanism and sell-down code were added (commit c33feb3 plus
E2-D1's inert config block). E3-R's changes must leave every E1 path
exactly where it was: same trades, same equity curve, same decisions. The
real-data check (E1 base on development and validation against
experiments/E1/regression) is `tools/e1_identity.py`, which is Aarsh's to
run; this is the fast guard that runs with every `pytest -q`.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from conftest import random_walk_panel
from pflab.backtest import engine
from pflab.eval.periods import Period
from pflab.execution.costs import CostModel
from pflab.tax.india_lots import TaxPolicy


def _wavy_index(sessions):
    # a slow cycle, so the 10-month average is crossed several times and
    # RISK_OFF months exist in every configuration that reads it
    x = np.arange(len(sessions))
    return pd.DataFrame({"date": sessions,
                         "close": 100 * (1 + 0.25 * np.sin(x / 90.0)) * (1 + x / 4000)})


def _cfg(tf):
    return {"strategy": {"n_hold": 8, "band_exit_rank": 16, "sip_amount": 50000.0,
                         "trend_filter": tf, "max_buys_per_month": 6},
            "universe": {"series": ["EQ"], "min_sessions": 120, "top_n_by_turnover": 40,
                         "turnover_window": 60, "min_price": 1.0, "max_adv_fraction": 1.0}}


def digest(res) -> str:
    h = hashlib.sha256()
    h.update(res.trades.round(8).to_csv(index=False).encode())
    h.update(res.equity.round(6).to_csv(index=False).encode())
    h.update(json.dumps(res.decisions, sort_keys=True, default=str).encode())
    return h.hexdigest()


def run(tf):
    sessions, names, panel = random_walk_panel(seed=11, n_names=40,
                                               start="2013-01-01", end="2019-12-31",
                                               annual_drift=0.08, sigma=0.02)
    return engine.run(_cfg(tf), Period("g", date(2014, 6, 1), date(2019, 12, 31)),
                      panel, _wavy_index(sessions),
                      CostModel.from_toml("configs/costs_zerodha.toml"),
                      TaxPolicy.from_toml("configs/tax_policy_in.toml"))


# Captured 2026-09-27 and confirmed identical on HEAD c33feb3's own code,
# imported from a detached worktree.
GOLDEN = {
    "sma10": "c3dea6f0c0dc46cef6582698da78235fca646e506d5b00752b53f8f877ae0ec2",
    "sell_to_cash": "78fa2bef88e83409293eead2a0d37c8c996d5b695e76a1ecfec210617a5bafe3",
    "off": "bf378702b8c25181dbdcb81464d2bb330e9a326c6fadf0a56c64bc5a1cf66280",
}


@pytest.mark.parametrize("tf", sorted(GOLDEN))
def test_e1_paths_are_byte_identical_to_before_e3r(tf):
    res = run(tf)
    if tf != "off":
        assert any(d["risk_off"] for d in res.decisions), "fixture must exercise RISK_OFF"
    assert digest(res) == GOLDEN[tf]
