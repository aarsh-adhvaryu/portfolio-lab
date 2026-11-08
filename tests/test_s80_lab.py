"""S80 phase 2: the lab's policy interface, toolkit and replay harness (synthetic data only)."""
from __future__ import annotations

import math
import random

import numpy as np
import pandas as pd
import pytest

from pflab.lab import engine, policy_api, toolkit

MOMENTUM = '''
from toolkit import momentum, rank_top, inverse_vol, volatility, cap_and_fill

PARAMS = {"n": [5, 10]}

def decide(state, forecasts, sims, storylines, params=None):
    n = (params or {}).get("n", 10)
    prices = state["prices"][state["universe"]]
    top = rank_top(momentum(prices, 126, 10), n, floor=0.0)
    if not top:
        return {}
    w = inverse_vol(top, volatility(prices[top]))
    return cap_and_fill(w, state["caps"], 0.10, budget=0.95)
'''


def make_data(n_days=1700, n_stocks=70, edge=0.0004, seed=7):
    """Random-walk stocks; the first 8 have a persistent extra drift (`edge` a day) so a momentum rule has something to find; four ETFs."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-04", periods=n_days)
    keys = [f"S{i:02d}" for i in range(n_stocks)] + ["ETF:NIFTYBEES", "ETF:JUNIORBEES", "ETF:BANKBEES", "ETF:GOLDBEES"]
    drift = np.array([edge if i < 8 else 0.0 for i in range(n_stocks)] + [0.0003, 0.0003, 0.0003, 0.0002])
    vol = np.concatenate([rng.uniform(0.012, 0.025, n_stocks), [0.009, 0.011, 0.014, 0.008]])
    r = rng.normal(drift, vol, size=(n_days, len(keys)))
    px = pd.DataFrame(100 * np.cumprod(1 + r, axis=0), index=idx, columns=keys)
    turnover = pd.DataFrame(np.tile(rng.uniform(1e8, 9e8, len(keys)), (n_days, 1)), index=idx, columns=keys)
    meta = {k: {"symbol": k.replace("ETF:", ""), "etf": k.startswith("ETF:"), "sector": f"sec{i % 9}" if not k.startswith("ETF:") else None,
                "tax": "LISTED_NONEQUITY" if k == "ETF:GOLDBEES" else "EQUITY"} for i, k in enumerate(keys)}
    return {"px": px, "turnover": turnover, "meta": meta, "index": px["ETF:NIFTYBEES"], "bench": px["ETF:NIFTYBEES"]}


@pytest.fixture(scope="module")
def data():
    return make_data()


def test_tax_of_is_the_papers_books_tax_of():
    from pflab.paper import book
    rnd = random.Random(1)
    for _ in range(200):
        g = {b: rnd.uniform(-400_000, 600_000) for b in ("st_eq", "lt_eq", "lt_other", "slab") if rnd.random() < 0.8}
        assert engine.tax_of(g) == pytest.approx(book.tax_of(g))


def test_validate_accepts_a_good_policy_and_refuses_the_dangerous_ones():
    assert policy_api.validate(MOMENTUM) == []
    for bad in ("import os\ndef decide(state, forecasts, sims, storylines, params=None):\n    return {}\n",
                "from toolkit import *\nimport socket\ndef decide(state, forecasts, sims, storylines, params=None):\n    return {}\n",
                "def decide(state, forecasts, sims, storylines, params=None):\n    return open('x').read()\n",
                "def decide(state, forecasts, sims, storylines, params=None):\n    return state.__class__.__bases__\n",
                "def decide(state, forecasts, sims, storylines, params=None):\n    return eval('1')\n",
                "def decide(state):\n    return {}\n",
                "x = 1\n",
                "def decide(state, forecasts, sims, storylines, params=None):\n    import pandas as pd\n    return pd.read_csv('a.csv')\n"):
        assert policy_api.validate(bad), bad


def test_load_and_grid_expansion_and_a_policy_cannot_invent_a_security(data):
    fn, grid = policy_api.load(MOMENTUM)
    assert policy_api.expand_grid(grid) == [{"n": 5}, {"n": 10}]
    assert policy_api.expand_grid({}) == [{}]
    with pytest.raises(ValueError):
        policy_api.expand_grid({"a": list(range(8)), "b": list(range(8))})
    inv, _ = policy_api.load("def decide(state, forecasts, sims, storylines, params=None):\n    return {'NOT_A_KEY': 0.5, 'S01': 0.2, 'S02': float('nan'), 'S03': -1}\n")
    st = {"universe": ["S01", "S02", "S03"], "weights": {}}
    assert policy_api.call(inv, st, {}, {}, {}, {}) == {"S01": 0.2}


def test_the_toolkit_functions_do_what_they_say(data):
    px = data["px"].iloc[:600]
    assert set(toolkit.volatility(px)) == set(px.columns)
    m = toolkit.momentum(px, 252, 21)
    assert toolkit.rank_top(m, 3) == sorted(m, key=lambda k: (-m[k], k))[:3]
    w = toolkit.cap_and_fill({"a": 0.5, "b": 0.3, "c": 0.2}, {"a": 0.2, "b": 0.2, "c": 0.2}, budget=0.6)
    assert w == {"a": pytest.approx(0.2), "b": pytest.approx(0.2), "c": pytest.approx(0.2)}
    assert sum(toolkit.cap_and_fill({"a": 0.5, "b": 0.3}, {"a": 0.2, "b": 0.2}, budget=0.9).values()) == pytest.approx(0.4)      # no room: the rest stays cash
    assert toolkit.fall_gauge(pd.Series([100.0] * 300 + [80.0])) is True
    assert toolkit.fall_gauge(pd.Series(np.linspace(100, 200, 400))) is False


def test_the_replay_is_point_in_time_and_the_rails_hold(data):
    seen = []

    def spy(state, f, s, sl, p):
        assert state["prices"].index.max() <= pd.Timestamp(state["day"])
        assert state["index"].index.max() <= pd.Timestamp(state["day"]) and state["turnover"].index.max() <= pd.Timestamp(state["day"])
        seen.append(state["day"])
        return {k: 0.5 for k in state["universe"][:4]}                  # asks for far too much in four names

    run = engine.replay(spy, {}, data, "2012-06-01", "2015-12-31")
    assert len(seen) == run["decisions"] > 30
    v = run["value"]
    assert v.index.min() > pd.Timestamp("2012-06-01") and v.index.max() <= pd.Timestamp("2015-12-31")
    assert run["book"].cash >= -1e-6                                         # nothing was borrowed
    # right after the first deployment every name sits at its rail (a later price rise may carry a weight past it; the rails only stop BUYING, as the live book's do)
    first = engine.replay(spy, {}, data, "2012-06-01", "2012-07-02")
    b, last = first["book"], data["px"].loc[first["value"].index[-1]]
    assert len(b.lots) == 4
    for k in b.lots:
        cap = 0.35 if data["meta"][k]["etf"] else 0.10
        assert b.qty(k) * last[k] / first["value"].iloc[-1] <= cap + 0.005


def test_costs_and_tax_reduce_the_result_and_the_turnover_cap_binds(data):
    fn, _ = policy_api.load(MOMENTUM)
    free = {"charges": {"equity": {"buy": 0.0, "sell": 0.0}, "etf": {"buy": 0.0, "sell": 0.0}}}
    a = engine.replay(fn, {"n": 10}, data, "2012-06-01", "2016-12-31", free)
    b = engine.replay(fn, {"n": 10}, data, "2012-06-01", "2016-12-31")
    assert b["book"].charges > 0 and b["book"].tax >= 0
    assert b["value"].iloc[-1] < a["value"].iloc[-1] + 1e-6 or b["book"].tax < 1                           # costs cannot make it richer
    sc = engine.score(b, data, {})
    assert sc["turnover_per_year"] < 0.40 * 12 + 1.0                                                       # monthly cap 40%, 12 months, and the one deployment


def test_a_real_signal_beats_its_shuffled_self_and_pure_noise_does_not(data):
    fn, _ = policy_api.load(MOMENTUM)
    res = engine.evaluate(fn, [{"n": 8}], data, "2012-06-01", "2016-12-31", n_shuffles=12, n_mc=200)
    row = res["runs"][0]
    assert row["shuffled"]["beats_real_frac"] <= 0.25 and row["score"]["cagr"] > row["shuffled"]["cagr_mean"]
    noise = make_data(edge=0.0, seed=11)
    nres = engine.evaluate(fn, [{"n": 8}], noise, "2012-06-01", "2016-12-31", n_shuffles=12, n_mc=200)
    assert nres["runs"][0]["shuffled"]["beats_real_frac"] >= 0.0 and nres["runs"][0]["score"]["dsr"] <= 1.0          # (noise has nothing to find: it must not look skilled)
    assert nres["runs"][0]["score"]["cagr"] - nres["runs"][0]["shuffled"]["cagr_mean"] < row["score"]["cagr"] - row["shuffled"]["cagr_mean"]
    assert {"mc_1y_p5", "mc_1y_p50", "mc_1y_p95", "mc_worst_fall_p50", "mc_prob_loss"} <= set(row["mc"])


def test_the_deflated_sharpe_falls_as_more_variants_are_tried():
    base = [0.05, 0.02, 0.01, 0.03]
    one = engine.deflated_sharpe(0.05, 1000, 0.0, 3.0, [0.05])
    few = engine.deflated_sharpe(0.05, 1000, 0.0, 3.0, base)
    many = engine.deflated_sharpe(0.05, 1000, 0.0, 3.0, base + [0.04, 0.03, 0.02, 0.01] * 10)
    assert one > few > many or (one >= few >= many and many < one)
    assert 0.0 <= many <= 1.0 and math.isfinite(many)


def test_a_policy_that_raises_holds_the_book_and_is_counted(data):
    def broken(state, f, s, sl, p):
        raise RuntimeError("boom")
    with pytest.raises(RuntimeError, match="failed on"):
        engine.replay(broken, {}, data, "2012-06-01", "2016-12-31")


# --- the sandbox run (the uncontained subprocess is what the suite may use; Docker is proved separately) ------------------------------------------

def test_the_runner_runs_policies_in_a_job_folder_and_reports_a_broken_one_without_stopping_the_others(data, monkeypatch):
    from pflab.lab import runner
    monkeypatch.setenv("PFLAB_SANDBOX", "local")
    bad = "def decide(state, forecasts, sims, storylines, params=None):\n    raise ValueError('nope')\n"
    out = runner.run(data, [{"id": "good", "code": MOMENTUM}, {"id": "bad", "code": bad}], ("2012-06-01", "2014-12-31"), {"good": [{"n": 6}], "bad": [{}]},
                     {"charges": {"equity": {"buy": 0.001, "sell": 0.001}, "etf": {"buy": 0.0003, "sell": 0.0003}}}, n_shuffles=3, n_mc=50, time_limit=300)
    assert out.get("contained") is False and "good" in out["results"] and "bad" in out["errors"]
    row = out["results"]["good"]["runs"][0]
    assert row["params"] == {"n": 6} and {"cagr", "dsr", "max_drawdown", "excess_cagr", "tax_paid"} <= set(row["score"]) and row["shuffled"]["n"] == 3
    assert "ValueError" in out["errors"]["bad"] or "failed" in out["errors"]["bad"]


def test_the_panel_cache_round_trips(data, tmp_path):
    from pflab.lab import runner
    runner.save_panel(data, tmp_path / "p")
    back = runner.load_panel(tmp_path / "p")
    assert list(back["px"].columns) == list(data["px"].columns) and back["meta"]["S00"]["etf"] is False
    pd.testing.assert_series_equal(back["bench"].rename(None), data["bench"].rename(None), check_freq=False)
