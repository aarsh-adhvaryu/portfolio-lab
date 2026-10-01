"""tools/gap_ladder.py (diagnostic, not promotable): the fixed cumulative
order, the step arithmetic and the registered brake + cap share. Synthetic."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import gap_ladder as gl  # noqa: E402


def test_rungs_are_the_registered_cumulative_order():
    assert gl.ORDER == ("picks", "mechanics", "brake", "cap", "costs", "tax")
    over = {r[0]: r[2] for r in gl.RUNGS}
    assert over["mechanics"] == {"strategy.trend_filter": "off",
                                 "strategy.max_buys_per_month": gl.BIG}
    assert over["brake"] == {"strategy.max_buys_per_month": gl.BIG}  # brake back on
    assert over["cap"] == over["costs"] == over["tax"] == {}          # as chartered
    assert [(r[3], r[4]) for r in gl.RUNGS] == [(False, False)] * 3 + [(True, False), (True, True)]


def _row(cagr, xirr=None, terminal=None, dd=0.5):
    return {"cagr": cagr, "xirr": cagr if xirr is None else xirr,
            "terminal": 100 * cagr if terminal is None else terminal, "max_drawdown": dd}


def _ladder():
    rows = {"picks": _row(0.15), "mechanics": _row(0.14), "brake": _row(0.12),
            "cap": _row(0.10), "costs": _row(0.095), "tax": _row(0.085)}
    return rows, _row(0.14)                      # B5: gap 0.14 - 0.085 = 5.5 pp


def test_steps_sum_from_picks_to_base():
    rows, b5 = _ladder()
    s = gl.steps(rows, b5)
    assert [x["to"] for x in s] == list(gl.ORDER[1:])
    assert sum(x["change"]["cagr"] for x in s) == pytest.approx(0.085 - 0.15)
    assert s[1]["share"]["cagr"] == pytest.approx(0.02 / 0.055)      # brake


def test_brake_cap_share_is_mechanics_to_cap_over_gap():
    rows, b5 = _ladder()
    assert gl.brake_cap_share(rows, b5) == pytest.approx(0.04 / 0.055)
    rows["tax"] = _row(0.14)
    assert gl.brake_cap_share(rows, b5) is None                       # no gap
