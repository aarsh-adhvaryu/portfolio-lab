"""E1 gap attribution (audit Deliverable 2): the two diagnostic-only engine
knobs and the tool's arithmetic. Neither knob is reachable from a charter
config; the golden digests in test_engine_golden.py prove E1's path is
unchanged."""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from test_engine_golden import GOLDEN, _cfg, digest, run as golden_run
from pflab.backtest import engine
from pflab.eval.periods import Period
from pflab.execution.costs import CostModel
from pflab.tax.india_lots import TaxPolicy
from conftest import random_walk_panel
from test_engine_golden import _wavy_index

_spec = importlib.util.spec_from_file_location(
    "gap_attribution", Path(__file__).resolve().parents[1] / "tools" / "gap_attribution.py")
ga = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ga)


def _run(**strategy):
    sessions, _, panel = random_walk_panel(seed=11, n_names=40, start="2013-01-01",
                                           end="2019-12-31", annual_drift=0.08,
                                           sigma=0.02, tick=0.01)
    cfg = _cfg("sma10")
    cfg["strategy"].update(strategy)
    return engine.run(cfg, Period("g", date(2014, 6, 1), date(2019, 12, 31)), panel,
                      _wavy_index(sessions), CostModel.from_toml("configs/costs_zerodha.toml"),
                      TaxPolicy.from_toml("configs/tax_policy_in.toml")), panel


def test_e1_path_unchanged():
    assert digest(golden_run("sma10")) == GOLDEN["sma10"]


def test_topup_ceiling_blocks_buys_into_band_names():
    res, _ = _run(topup_max_rank=8)
    blocked = 0
    for d in res.decisions:
        nb = set(d.get("no_buy", ()))
        assert all(d["ranks"].get(i, 1e9) > 8 for i in nb)
        blocked += len(nb)
    assert blocked > 0
    by_month = {pd.Timestamp(d["month_end"]).to_period("M"): set(d.get("no_buy", ()))
                for d in res.decisions}
    buys = res.trades[res.trades.side == "BUY"]
    for r in buys.itertuples():
        prev = (pd.Timestamp(r.date).to_period("M") - 1)
        assert r.isin not in by_month.get(prev, set())


def test_lottery_is_deterministic_seeded_and_ignores_momentum():
    a, _ = _run(signal="lottery", lottery_seed=1)
    b, _ = _run(signal="lottery", lottery_seed=1)
    c, _ = _run(signal="lottery", lottery_seed=2)
    m, _ = _run()
    assert digest(a) == digest(b)
    assert digest(a) != digest(c)
    # same eligible set and dates as momentum, different picks
    assert [d["n_eligible"] for d in a.decisions] == [d["n_eligible"] for d in m.decisions]
    assert a.decisions[0]["entries"] != m.decisions[0]["entries"]
    # a fixed score per name: the order among names never changes
    r0, r5 = a.decisions[0]["ranks"], a.decisions[5]["ranks"]
    common = [i for i in r0 if i in r5]
    assert sorted(common, key=r0.get) == sorted(common, key=r5.get)


def test_zero_tax_and_metrics():
    tp = ga.zero_tax(TaxPolicy.from_toml("configs/tax_policy_in.toml"))
    assert (tp.stcg_rate, tp.ltcg_rate, tp.interest_rate, tp.dividend_rate) == (0, 0, 0, 0)
    res, _ = _run()
    m = ga.row_metrics(res)
    assert m["contributed"] > 0 and m["terminal"] > 0
    assert -0.5 < m["xirr"] < 0.5 and 0 < m["mean_equity_weight"] <= 1.0


def test_terminal_at_and_required():
    flows = [(date(2020, 1, 1), 100.0), (date(2021, 1, 1), 0.0)]
    assert ga.terminal_at(0.10, flows) == pytest.approx(110.0, rel=1e-3)
    req = ga.required({"B2": {"cagr": 0.08, "xirr": 0.09},
                       "B5": {"cagr": 0.137, "xirr": 0.12}})
    assert req["binding"] == "§5 B5+2"
    assert req["§5 B5+2"]["cagr"] == pytest.approx(0.157)


def test_mom_weighted_row_runs_and_differs():
    over = ga.CONTROLS["mom_weighted"][2]
    res, _ = _run(**{k.split(".", 1)[1]: v for k, v in over.items()})
    base, _ = _run()
    assert any(d.get("target_weights") for d in res.decisions)
    assert digest(res) != digest(base)
