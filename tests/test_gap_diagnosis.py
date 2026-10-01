"""tools/gap_diagnosis.py's computed controls (diagnostic, not promotable):
the band rule read off stored ranks, the frictionless equal-weight selection
series, and the equity-share blend. Synthetic."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import gap_diagnosis as gd  # noqa: E402


def test_band_rule_keeps_inside_band_and_fills_from_the_top():
    d = [{"month_end": "2020-01-31", "ranks": {"A": 1, "B": 2, "C": 3, "D": 4}},
         {"month_end": "2020-02-29", "ranks": {"A": 4, "B": 9, "C": 1, "D": 2}},
         {"month_end": "2020-03-31", "ranks": {}}]                 # no ranks: unchanged
    ch = gd.chosen_names(d, n_hold=2, band=4)
    assert ch[pd.Timestamp("2020-01-31")] == ["A", "B"]
    assert ch[pd.Timestamp("2020-02-29")] == ["A", "C"]          # B out past the band
    assert ch[pd.Timestamp("2020-03-31")] == ["A", "C"]


def _panel(prices, divs=None):
    rows = []
    for isin, ps in prices.items():
        for k, (d, p) in enumerate(ps):
            rows.append({"date": pd.Timestamp(d), "isin": isin, "adj_close": p,
                         "adj_factor": 1.0,
                         "dividend": (divs or {}).get((isin, d), 0.0)})
    return pd.DataFrame(rows)


def test_selection_is_equal_weight_with_dividends_and_sip():
    s = ["2020-01-31", "2020-07-31", "2021-01-29"]
    panel = _panel({"A": list(zip(s, [100, 110, 110])), "B": list(zip(s, [50, 50, 45]))},
                   {("B", "2021-01-29"): 5.0})
    sessions = [pd.Timestamp(x) for x in s]
    dec = [{"month_end": "2020-01-31", "ranks": {"A": 1, "B": 2}}]
    flows = [(sessions[0], 100.0)]
    m = gd.selection_metrics(dec, panel, sessions, flows, n_hold=2, band=4)
    # day 1: A +10%, B 0 -> +5%; day 2: weights drift (110/105, 50/105), A 0, B 0 (45+5)/50
    assert m["terminal"] == pytest.approx(105.0)
    assert m["mean_equity_weight"] == 1.0


def test_blend_at_full_weight_is_the_sleeve_and_at_zero_is_cash():
    idx = pd.to_datetime(["2020-01-01", "2020-07-01", "2021-01-01"])
    r = pd.Series([0.0, 0.10, -0.05], index=idx)
    flow = pd.Series([100.0, 0.0, 0.0], index=idx)
    full = gd.blend(r, pd.Series(1.0, index=idx), flow, 0.0)
    assert full["terminal"] == pytest.approx(100 * 1.10 * 0.95)
    none = gd.blend(r, pd.Series(0.0, index=idx), flow, 0.0)
    assert none["terminal"] == pytest.approx(100.0)
