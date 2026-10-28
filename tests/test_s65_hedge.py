"""S65 forward test F5: the stress gauge is causal and lags US data, the state machine, the paper position's timing, costs and tax, and the
once-only decision."""
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from pflab.learner import counter
from pflab.pm import store
from pflab.quant import stress_hedge as sh

IDX = pd.bdate_range("2019-01-01", periods=1500)


def panel(seed=1, crash_at=None):
    rng = np.random.default_rng(seed)
    r = rng.normal(0.0004, 0.01, len(IDX))
    vix = 15 + rng.normal(0, 1, len(IDX))
    if crash_at is not None:
        r[crash_at:crash_at + 20] = -0.03
        vix[crash_at:crash_at + 30] = 60
    nifty = 10000 * np.cumprod(1 + r)
    return pd.DataFrame({"nifty": nifty, "india_vix": vix, "us_vix": vix, "move": vix * 5, "hyg": 80 * np.cumprod(1 + r / 3), "lqd": 100.0,
                         "usdinr": 80 + np.cumsum(rng.normal(0, 0.05, len(IDX))), "dxy": 100 + np.cumsum(rng.normal(0, 0.1, len(IDX))),
                         "sp500": 4000 * np.cumprod(1 + r * 0.8 + rng.normal(0, 0.005, len(IDX)))}, index=IDX)


def test_the_gauge_never_looks_ahead_and_rises_in_a_crash():
    p = panel(crash_at=1200)
    g = sh.gauge(p)
    cut = sh.gauge(p.iloc[:1100])
    assert np.allclose(g.iloc[:1100].dropna(), cut.dropna())                       # the future does not change the past
    assert g.iloc[1215] > 0.85 and g.iloc[1215] > g.iloc[1100] + 0.1 and g.iloc[:251].isna().all()  # a year before any value


def test_us_values_are_used_only_from_the_next_indian_session(tmp_path):
    (tmp_path / "indices").mkdir()
    (tmp_path / "global").mkdir()
    (tmp_path / "macro").mkdir()
    d = pd.bdate_range("2026-01-05", periods=5)
    pd.DataFrame({"date": d, "close": [100.0] * 5}).to_parquet(tmp_path / "indices" / "NIFTY50_PRICE.parquet")
    pd.DataFrame({"date": d, "close": [15.0] * 5}).to_parquet(tmp_path / "indices" / "INDIA_VIX.parquet")
    pd.DataFrame({"date": d, "close": [10.0, 20.0, 30.0, 40.0, 50.0], "adj_close": 1.0}).to_parquet(tmp_path / "global" / "US_VIX.parquet")
    p = sh.inputs(tmp_path)
    assert list(p["us_vix"]) [1:] == [10.0, 20.0, 30.0, 40.0] and np.isnan(p["us_vix"].iloc[0])   # Monday's Indian session sees nothing of Monday's US


def test_the_state_needs_five_sessions_at_the_threshold_and_ends_at_once():
    g = pd.Series([0.5, 0.7, 0.8, 0.9, 0.75, 0.71, 0.72, 0.69, 0.9], index=IDX[:9])
    assert list(sh.state(g)) == [False, False, False, False, False, True, True, False, False]


def test_the_paper_position_earns_from_two_sessions_after_the_gauge_and_pays_costs_and_tax():
    idx = IDX[:10]
    book = pd.Series(0.0, index=idx)
    ir = pd.Series(0.0, index=idx)
    ir.iloc[3] = -0.10                                                              # the index falls on session 3
    on = pd.Series([False, True, True, True, True, False, False, False, False, False], index=idx)
    rec = sh.paper(book, ir, on)
    # on from session 1 -> held from session 3: the fall on session 3 is hedged (+5% on half the book)
    assert rec["episodes"] == 1 and rec["completed"] == 1
    assert rec["hedged"].iloc[2] == 1.0                                              # not yet in place the session after the gauge
    assert rec["hedged"].iloc[3] == pytest.approx(1.05 * (1 - sh.COST_EVENT * 0.5))      # the fall hedged, less the entry charge
    assert rec["tax"] > 0 and rec["cost"] > 0 and rec["plain"].iloc[-1] == 1.0
    late = sh.paper(book, ir, on, lag=3)
    assert late["hedged"].iloc[3] == 1.0 < rec["hedged"].iloc[3]                   # one session later and the fall is missed


def test_f5_is_counted_once_and_not_decided_before_24_months(tmp_path, monkeypatch):
    con = store.connect(tmp_path / "l.duckdb")
    n0 = counter.n_tests(con)
    out = sh.cycle(con, tmp_path, datetime(2027, 6, 1))
    assert out == {"decided": False, "months": 7} and counter.n_tests(con) == n0 + 1
    sh.cycle(con, tmp_path, datetime(2027, 7, 1))
    assert counter.n_tests(con) == n0 + 1


def test_the_decision_waits_for_two_episodes_then_decides_once(tmp_path, monkeypatch):
    con = store.connect(tmp_path / "l.duckdb")
    rec = {"completed": 1, "max_dd_hedged": -0.10, "max_dd_plain": -0.25, "ann_hedged": 0.10, "ann_plain": 0.105}
    monkeypatch.setattr(sh, "forward", lambda root, upto=None: rec)
    assert sh.cycle(con, tmp_path, datetime(2028, 11, 2))["waiting_for"] == "a second completed hedge episode"
    rec["completed"] = 2
    out = sh.cycle(con, tmp_path, datetime(2028, 12, 1))
    assert out["decided"] and out["passed"] is True
    assert con.execute("SELECT key FROM learned WHERE kind='finding' AND valid_to IS NULL").fetchall() == [("forward:F5",)]
    assert sh.cycle(con, tmp_path, datetime(2029, 1, 1)) == {"decided": True, "months": 26}        # once


def test_a_hedge_that_gives_up_too_much_return_fails(tmp_path, monkeypatch):
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(sh, "forward", lambda root, upto=None: {"completed": 3, "max_dd_hedged": -0.10, "max_dd_plain": -0.25,
                                                                 "ann_hedged": 0.08, "ann_plain": 0.10})
    assert sh.cycle(con, tmp_path, datetime(2028, 12, 1))["passed"] is False
    assert con.execute("SELECT count(*) FROM learned").fetchone()[0] == 0


def test_without_enough_stress_in_60_months_it_closes_without_a_pass(tmp_path, monkeypatch):
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(sh, "forward", lambda root, upto=None: {"completed": 1})
    assert sh.cycle(con, tmp_path, datetime(2031, 11, 2)) == {"decided": True, "passed": False, "why": "not enough stress to judge within 60 months"}
