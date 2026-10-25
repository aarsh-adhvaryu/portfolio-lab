"""Byte-identity of E1's engine paths on synthetic data.

The digests below were captured on 2026-09-27 from the engine BEFORE E3-R's
target-equity mechanism and sell-down code were added (commit c33feb3 plus
E2-D1's inert config block). E3-R's changes must leave every E1 path
exactly where it was: same trades, same equity curve, same decisions. The
real-data check (E1 base on development and validation against
experiments/E1/regression) is `tools/e1_identity.py`, which is the investor's to
run; this is the fast guard that runs with every `pytest -q`.
"""
from __future__ import annotations

import dataclasses
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


class _STTInBasis(CostModel):
    """The pre-2026-09-27 lot book: STT deducted in computing gains."""
    def buy_stt(self, notional):
        return 0.0

    def sell_stt(self, notional):
        return 0.0


def run(tf, neutralised=False):
    sessions, names, panel = random_walk_panel(seed=11, n_names=40,
                                               start="2013-01-01", end="2019-12-31",
                                               annual_drift=0.08, sigma=0.02,
                                               tick=0.01)
    cm = CostModel.from_toml("configs/costs_zerodha.toml")
    tp = TaxPolicy.from_toml("configs/tax_policy_in.toml")
    if neutralised:
        cm = _STTInBasis(**{f.name: getattr(cm, f.name) for f in dataclasses.fields(cm)})
        tp = dataclasses.replace(tp, interest_rate=0.0)
    return engine.run(_cfg(tf), Period("g", date(2014, 6, 1), date(2019, 12, 31)),
                      panel, _wavy_index(sessions), cm, tp)


# Captured 2026-09-27 and confirmed identical on HEAD c33feb3's own code,
# imported from a detached worktree. Re-captured the same day on a paise-
# rounded fixture (`tick=0.01`) from 8dea146's code in a detached worktree:
# the unrounded fixture's digest moved with the last bit of np.exp, which is
# why the audit's Linux run disagreed on all three (a 1-ULP change to 30% of
# panel prices changes the digest; see docs/reviews/accounting-correction-2.md).
GOLDEN_BEFORE_ACCOUNTING = {
    "sma10": "32cbcab4992cccbc79fd80481383f81eb307e1bf56c348f1c9c4448b86c0f28d",
    "sell_to_cash": "4a0128fe71d55481bc02e545d0ca142b31f500c38176bb113a90c487b92c19fb",
    "off": "9fdd48dcd7c5d49ed83c9d0c78564754402315a652bfca8ee80b24a4835a1a86",
}
# Re-pinned 2026-09-27 after the audit's accounting corrections (E1 §15).
# Attributed, not blindly updated: with STT kept in basis and cash interest
# untaxed (`neutralised` below) the corrected engine reproduces every
# GOLDEN_BEFORE_ACCOUNTING digest exactly, so these two corrections are the
# whole of the change on this fixture (it has no corporate actions,
# dividends or suspensions).
GOLDEN = {
    "sma10": "aec38a666caadefe66a91f59e76a16de15a21fb8038ea850466d9686f876583e",
    "sell_to_cash": "34c260d1359be400c3b3ec0a9973edcbd93bc45411f7c13fb107cc7c3b8791b9",
    "off": "fdbe0ca044857393b668f72c57da6635bc254abf58b135efce830e11a9d33da9",
}


@pytest.mark.parametrize("tf", sorted(GOLDEN))
def test_e1_paths_are_byte_identical_to_before_e3r(tf):
    res = run(tf)
    if tf != "off":
        assert any(d["risk_off"] for d in res.decisions), "fixture must exercise RISK_OFF"
    assert digest(res) == GOLDEN[tf]


@pytest.mark.parametrize("tf", sorted(GOLDEN_BEFORE_ACCOUNTING))
def test_accounting_corrections_are_the_whole_change(tf):
    assert digest(run(tf, neutralised=True)) == GOLDEN_BEFORE_ACCOUNTING[tf]


def test_decision_dicts_built_from_sets_are_written_sorted():
    """E1 §15 2026-09-27 (determinism) and 2026-09-28: a dict built from a
    set is sorted, so decisions.json is byte-identical across processes
    without sort_keys."""
    res = run("sma10")
    rc = [d["reference_close"] for d in res.decisions if d.get("reference_close")]
    assert rc and all(list(r) == sorted(r) for r in rc)
