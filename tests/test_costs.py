from pathlib import Path

import pytest

from pflab.execution.costs import CostModel

CFG = Path(__file__).resolve().parents[1] / "configs" / "costs_zerodha.toml"


def test_buy_and_sell_costs_from_toml():
    cm = CostModel.from_toml(CFG)
    n = 100_000.0
    buy = cm.buy_cost(n)
    sell = cm.sell_cost(n)
    # STT dominates: 0.1% each side = 100; stamp 15 on buy; DP 15.34 on sell
    assert buy == pytest.approx(100 + 15 + (n * 0.0000297 + 0.1) * 1.18, rel=1e-6)
    assert sell == pytest.approx(100 + 15.34 + (n * 0.0000297 + 0.1) * 1.18, rel=1e-6)


def test_multiplier_scales_everything():
    cm = CostModel().scaled(2.0)
    assert cm.buy_cost(1000.0) == pytest.approx(2 * CostModel().buy_cost(1000.0))
