"""E1d — E1 with the fund's volatility-scaled score as the RANKING signal.

All synthetic. Nothing here runs E1d on real data: the charter is DRAFT and
locks at its first development run, which is Aarsh's to start.

What these lock down is the four pieces E1d needed that E1c did not:
`strategy.score_windows` (§5 S1/S2), the sweep table (§5), the config, and
`classify_e1d` (§6). Plus the one property the charter leans on hardest:
E1d changes ranking ONLY, so E1 §5's equal-weight buys must be untouched.
"""
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from conftest import random_walk_panel
from pflab.eval import classify, sweep as S
from pflab.signals.vol_scaled import vol_scaled_ratios


def _wide(seed=5, n=40, start="2010-01-01", end="2018-12-31"):
    sessions, names, panel = random_walk_panel(seed=seed, n_names=n,
                                               start=start, end=end)
    return panel.pivot_table(index="date", columns="isin", values="adj_close",
                             aggfunc="last")


# -- §5 S1/S2: the score's two components, one at a time ----------------
def test_score_windows_selects_which_components_are_built():
    w = _wide()
    both = vol_scaled_ratios(w, windows=(126, 252))
    six = vol_scaled_ratios(w, windows=(126,))
    twelve = vol_scaled_ratios(w, windows=(252,))
    assert len(both) == 2 and len(six) == 1 and len(twelve) == 1
    # S1 is the 6-month half of the pair, S2 the 12-month half, unchanged
    pd.testing.assert_frame_equal(six[0], both[0])
    pd.testing.assert_frame_equal(twelve[0], both[1])


def test_the_two_components_actually_differ():
    """If they did not, S1 and S2 would be the same row and §5 would be lying."""
    w = _wide()
    a, b = vol_scaled_ratios(w, windows=(126, 252))
    common = a.stack().dropna().index.intersection(b.stack().dropna().index)
    assert len(common) > 100
    assert not np.allclose(a.stack().dropna().reindex(common).to_numpy(),
                           b.stack().dropna().reindex(common).to_numpy())


def test_single_window_makes_the_two_orders_coincide():
    """The readiness note's claim: with one ingredient, averaging z-scores and
    z-scoring the average are the same operation. S8 is therefore not
    confounded with S1 or S2."""
    from pflab.signals.vol_scaled import standardise
    w = _wide()
    part = vol_scaled_ratios(w, windows=(252,))[0]
    d = part.dropna(how="all").index[-1]
    row = part.loc[d].dropna()
    a = standardise([row], order="average_then_z")
    b = standardise([row], order="z_then_average")
    pd.testing.assert_series_equal(a, b)


def test_engine_reads_score_windows_and_rejects_an_empty_one():
    from pflab.backtest import engine
    from pflab.eval.periods import Period
    from conftest import flat_index
    sessions, names, panel = random_walk_panel(seed=3, n_names=30,
                                               start="2010-01-01", end="2014-12-31")
    period = Period("t", date(2012, 1, 1), date(2014, 12, 31))
    cfg = {"strategy": {"id": "E1d", "signal": "vol_scaled_6_12",
                        "score_windows": [], "n_hold": 5, "band_exit_rank": 10,
                        "sip_amount": 50000.0, "trend_filter": "off"},
           "universe": {"series": ["EQ"], "min_sessions": 100,
                        "top_n_by_turnover": 30, "turnover_window": 60,
                        "min_price": 1.0, "max_adv_fraction": 1.0}}
    from pflab.execution.costs import CostModel
    from pflab.tax.india_lots import TaxPolicy
    with pytest.raises(ValueError, match="score_windows"):
        engine.run(cfg, period, panel, flat_index(sessions),
                   CostModel(), TaxPolicy(), actions=None)


# -- §5 the sweep table -------------------------------------------------
def test_e1d_sweep_is_the_base_row_plus_eleven():
    rows = S.e1d_rows()
    assert list(rows) == ["base"] + [f"S{i}" for i in range(1, 12)]
    assert rows["base"] == {}


def test_s11_is_the_published_only_membership_window():
    """S10's first five development years run on a declared proxy; S11 asks
    the same question where Nifty 200 membership is published (2012 on)."""
    rows = S.e1d_rows()
    assert rows["S11"]["period.start"] == "2012-01-01"
    assert rows["S11"]["universe.mode"] == "index_members"
    assert rows["S11"]["universe.index"] == "NIFTY200"


def test_s11_shortens_the_period_and_s10_does_not():
    from datetime import date
    from pflab.eval.periods import Period
    table = S.e1d_rows()
    dev = Period("development", date(2007, 1, 1), date(2016, 12, 31))
    assert S.period_for_row(dev, "S10", table).start == date(2007, 1, 1)
    assert S.period_for_row(dev, "S11", table).start == date(2012, 1, 1)
    assert S.period_for_row(dev, "base", table).start == date(2007, 1, 1)


def test_e1d_rows_match_the_charter_table():
    """Charter E1d §5, row for row. A row that drifts from the charter is the
    thing GATE's G3 would silently miscount."""
    rows = S.e1d_rows()
    assert rows["S1"] == {"strategy.score_windows": [126]}
    assert rows["S2"] == {"strategy.score_windows": [252]}
    assert rows["S3"] == {"strategy.n_hold": 20, "strategy.band_exit_rank": 40}
    assert rows["S4"] == {"strategy.n_hold": 35, "strategy.band_exit_rank": 70}
    assert rows["S5"] == {"costs.multiplier": 2.0}
    assert rows["S6"] == {"strategy.trend_filter": "off"}
    assert rows["S7"] == {"strategy.trend_filter": "sell_to_cash"}
    assert rows["S8"] == {"strategy.score_order": "z_then_average"}
    assert rows["S9"] == {"strategy.delisting": "total_loss"}
    assert rows["S10"]["universe.mode"] == "index_members"
    assert rows["S10"]["universe.index"] == "NIFTY200"


def test_no_e1d_row_touches_weighting():
    """§3: the score ranks only. A row that set a weighting scheme would make
    E1d two changes, not one, and GATE judges one."""
    for name, row in S.e1d_rows().items():
        for key in row:
            assert "weighting" not in key, f"{name} changes weighting"
            assert key != "strategy.selection_n", f"{name} changes selection_n"


# -- the config ---------------------------------------------------------
def _cfg():
    from pflab.backtest.runner import load_config
    return load_config(Path(__file__).resolve().parents[1] / "configs" / "e1d.toml")


def test_config_carries_the_one_change_and_keeps_equal_weights():
    c = _cfg()
    s = c["strategy"]
    assert s["id"] == "E1d"
    assert s["signal"] == "vol_scaled_6_12"
    assert s["score_windows"] == [126, 252]
    assert s["score_order"] == "average_then_z"
    # §3 "ranking only": no weighting key at all, so construct.buy_list runs
    assert "weighting" not in s and "selection_n" not in s


def test_config_is_e1_everywhere_except_the_score():
    """§3: 'Everything else is E1 as locked.' Anything that differs from
    configs/e1.toml outside the score block is a second change."""
    from pflab.backtest.runner import load_config
    root = Path(__file__).resolve().parents[1]
    e1 = load_config(root / "configs" / "e1.toml")["strategy"]
    e1d = _cfg()["strategy"]
    allowed = {"id", "charter", "signal", "score_order", "score_windows"}
    for k, v in e1.items():
        if k in allowed:
            continue
        assert e1d.get(k) == v, f"strategy.{k}: E1d has {e1d.get(k)!r}, E1 has {v!r}"
    for k in e1d:
        assert k in e1 or k in allowed, f"E1d adds strategy.{k}, which E1 has not"


def test_config_universe_is_e1s_whole_500_not_an_index():
    c = _cfg()
    assert c["universe"]["mode"] == "turnover_top_n"
    assert c["universe"]["top_n_by_turnover"] == 500
    # but the membership block is present so S10 can switch modes
    assert c["membership"]["index"] == "NIFTY200"


def test_config_output_dir_does_not_collide_with_another_experiment():
    assert _cfg()["report"]["output_dir"] == "experiments/E1d"


# -- §6 the classifier --------------------------------------------------
def _crit(cagr, dd, b2=0.08, b3=0.13, b5=0.10, rows=("base",)):
    return {"rows": {r: {"cagr": cagr, "max_drawdown": dd, "turnover_per_year": 1.5}
                     for r in rows},
            "benchmarks": {"NIFTY500_TRI": {"cagr": b2, "max_drawdown": -0.55},
                           "NIFTY200_MOMENTUM30_TRI": {"cagr": b3, "max_drawdown": -0.5},
                           "NIFTY500_MOMENTUM50_TRI": {"cagr": b5, "max_drawdown": -0.5}}}


def _write(tmp, name, crit):
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    import json
    (d / "criteria.json").write_text(json.dumps(crit), encoding="utf-8")
    return d


def test_classify_e1d_reports_gate_c1c4_and_mandate(tmp_path):
    cand = _crit(0.12, -0.50)
    stack = _crit(0.09, -0.55)
    out = classify.classify_e1d(_write(tmp_path, "cd", cand),
                                _write(tmp_path, "cv", cand),
                                _write(tmp_path, "sd", stack),
                                _write(tmp_path, "sv", stack))
    assert set(out) == {"gate", "charter_c1_c4", "mandate", "section7"}
    assert out["gate"]["stack"] == "E1 base"
    assert out["gate"]["verdict"] in {"ADOPT", "REJECT", "INCONCLUSIVE"}


def test_classify_e1d_has_no_e1c_section6_block(tmp_path):
    """E1c's §6 reported its gap to B3 and a weighting bound. E1d changes no
    weighting and may not restate C2, so carrying that block over would
    report a number with no charter behind it."""
    c = _crit(0.12, -0.50)
    out = classify.classify_e1d(_write(tmp_path, "a", c), _write(tmp_path, "b", c),
                                _write(tmp_path, "c", c), _write(tmp_path, "d", c))
    assert "section6" not in out


def test_classify_e1d_carries_section7_with_the_verdict(tmp_path):
    """§7: the hypothesis came from E1c's S6 on these same years. The verdict
    file must say so, or a later reader takes the number at face value."""
    c = _crit(0.12, -0.50)
    out = classify.classify_e1d(_write(tmp_path, "a", c), _write(tmp_path, "b", c),
                                _write(tmp_path, "c", c), _write(tmp_path, "d", c))
    s7 = out["section7"]
    assert "E1c" in s7["prior_exposure"]
    assert "sealed" in s7["consequence"]


def test_classify_e1d_notes_that_c1_c4_no_longer_decide_advance(tmp_path):
    c = _crit(0.12, -0.50)
    out = classify.classify_e1d(_write(tmp_path, "a", c), _write(tmp_path, "b", c),
                                _write(tmp_path, "c", c), _write(tmp_path, "d", c))
    assert "mandate" in out["charter_c1_c4"]["note"]


# -- GATE.md convention of 2026-09-25 -----------------------------------
def test_s11_does_not_apply_to_validation():
    """S11 asks S10's question on the published-membership years. Validation
    already begins in 2017, so there is nothing to shorten -- and E1d's
    validation sweep ran it as a duplicate of S10, reporting the same
    19.67% / 32.47% on the same 458 trades and counting one row twice."""
    from pflab.eval.periods import Period
    table = S.e1d_rows()
    dev = Period("development", date(2007, 1, 1), date(2016, 12, 31))
    val = Period("validation", date(2017, 1, 1), date(2021, 12, 31))
    assert S.row_applies(dev, "S11", table) is True
    assert S.row_applies(val, "S11", table) is False
    # every other row applies everywhere
    for r in table:
        if r != "S11":
            assert S.row_applies(val, r, table) is True


def test_a_non_applicable_row_is_excluded_from_the_denominator(tmp_path):
    """Counting it as a failure would penalise a charter for declaring a row
    honestly; counting it as a pass would be a free gift."""
    from pflab.eval import classify
    stack = {"rows": {"base": {"cagr": 0.10, "max_drawdown": 0.40,
                               "turnover_annual": 1.0}},
             "benchmarks": {}}
    cand = {"rows": {"base": {"cagr": 0.20, "max_drawdown": 0.30,
                              "turnover_annual": 1.0},
                     "S1": {"cagr": 0.20, "max_drawdown": 0.30,
                            "turnover_annual": 1.0},
                     "S11": {"not_applicable": True, "reason": "starts before"}},
            "benchmarks": {}}
    g = classify.gate_for_period(cand, stack)
    assert g["rows_total"] == 2          # NOT 3
    assert g["rows_holding"] == 2
    assert g["G3"] is True               # 2/2, not 2/3
    assert "S11" not in g["rows"]
