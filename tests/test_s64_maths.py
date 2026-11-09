"""S64 Phase 2: the maths layer (tools only): risk-free rate from futures carry, CAPM, process tests, co-movement, the
sector-reversion helpers, study registration, the brain's new tool. Synthetic data only."""
from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from pflab.data import riskfree
from pflab.hq import tools as tl
from pflab.learner import claims, counter, templates as tp
from pflab.pm import store
from pflab.quant import comove, process
from pflab.risk import capm


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "m.duckdb")


# --- risk-free ------------------------------------------------------------------------------------------------------------

def test_implied_rate_from_a_synthetic_future():
    spot, days, r, q = 20_000.0, 30, 0.07, 0.012
    fut = spot * (1 + (r - q) * days / 365)                       # F = S (1 + (r - q) T)
    f = pd.DataFrame({"expiry": [date(2024, 2, 29), date(2024, 3, 28)], "close": [fut, fut * 1.01]})
    got = riskfree.implied_rate(f, spot, q * 100, date(2024, 1, 30))
    assert got == pytest.approx(r, abs=1e-6)
    assert riskfree.implied_rate(f.iloc[:0], spot, 1.2, date(2024, 1, 30)) is None
    near = pd.DataFrame({"expiry": [date(2024, 2, 1)], "close": [spot]})            # 2 days: too close to use
    assert riskfree.implied_rate(near, spot, 1.2, date(2024, 1, 30)) is None


def test_riskfree_at_uses_a_median_of_three_and_falls_back_to_assumed():
    t = pd.DataFrame({"rate": [0.05, 0.10, 0.06, 0.20], "label": ["estimate (futures carry)"] * 4},
                     index=pd.to_datetime(["2020-01-31", "2020-02-29", "2020-03-31", "2020-04-30"]))
    assert riskfree.at(t, date(2020, 4, 30))[0] == pytest.approx(0.10)                # median of 0.10, 0.06, 0.20
    assert riskfree.at(t, date(2019, 1, 1)) == (riskfree.ASSUMED, riskfree.ASSUMED_LABEL)


# --- CAPM -----------------------------------------------------------------------------------------------------------------

def _months(n):
    return pd.date_range("2015-01-31", periods=n, freq="ME")


def test_capm_recovers_beta_and_alpha():
    rng = np.random.default_rng(5)
    idx = _months(84)
    m = pd.Series(rng.normal(0.01, 0.04, 84), index=idx)
    rf = pd.Series(0.005, index=idx)
    s = rf + 0.004 + 1.3 * (m - rf) + rng.normal(0, 0.01, 84)
    f = capm.fit(s, m, rf)
    assert f["n"] == 60 and f["beta"] == pytest.approx(1.3, abs=0.15) and f["r2"] > 0.8
    assert f["alpha_ann"] == pytest.approx(0.048, abs=0.05)
    assert "beta 1.3" in capm.describe(f)


def test_capm_alpha_that_is_noise_is_called_not_different_from_zero():
    rng = np.random.default_rng(6)
    idx = _months(70)
    m = pd.Series(rng.normal(0.01, 0.04, 70), index=idx)
    rf = pd.Series(0.005, index=idx)
    f = capm.fit(rf + 0.9 * (m - rf) + rng.normal(0, 0.03, 70), m, rf)
    assert abs(f["alpha_t"]) < 2 and "not different from 0" in capm.describe(f)


def test_capm_short_history_gives_no_fit_and_hac_lags_and_expected_return():
    idx = _months(20)
    s = pd.Series(np.linspace(0, 0.1, 20), index=idx)
    f = capm.fit(s, s, pd.Series(0.005, index=idx))
    assert f["beta"] is None and "36 needed" in f["note"] and capm.describe(f) == f["note"]
    assert capm.hac_lags(60) == 3 and capm.hac_lags(100) == 4
    assert capm.expected_return(1.2, 0.065, 0.06) == pytest.approx(0.137)


# --- process ----------------------------------------------------------------------------------------------------------------

def test_a_random_walk_is_not_mean_reverting_and_an_ou_half_life_is_recovered():
    rng = np.random.default_rng(7)
    rw = np.cumsum(rng.normal(0, 0.01, 1500))
    d = process.describe(pd.Series(rw))
    assert d["adf"]["p"] > 0.05 and d["kind"] == "random walk" and "random walk" in d["sentence"]
    assert process.variance_ratio(np.diff(rw))[4]["vr"] == pytest.approx(1.0, abs=0.25)
    hl_true, n = 10.0, 4000
    b = np.exp(-np.log(2) / hl_true)
    x = np.zeros(n)
    for k in range(1, n):
        x[k] = b * x[k - 1] + rng.normal(0, 1.0)
    hl = process.ou_half_life(x)
    assert hl == pytest.approx(hl_true, rel=0.3)
    assert process.adf(x)["p"] < 0.01 and process.describe(pd.Series(x))["kind"] == "mean-reverting"
    assert process.ou_half_life(rw) is None or process.ou_half_life(rw) > 100         # a walk does not revert


def test_variance_ratio_flags_reversal_and_trend_and_hurst_is_labelled_noisy():
    rng = np.random.default_rng(8)
    e = rng.normal(0, 1, 3000)
    rev = e - 0.5 * np.concatenate([[0], e[:-1]])                       # negative autocorrelation: VR below 1
    trend = e + 0.5 * np.concatenate([[0], e[:-1]])
    assert process.variance_ratio(rev)[4]["vr"] < 0.9 and process.variance_ratio(rev)[4]["z"] < -2
    assert process.variance_ratio(trend)[4]["vr"] > 1.1
    h = process.hurst(e)
    assert 0.35 < h["h"] < 0.65 and h["label"] == "noisy" and h["n"] == 3000
    assert process.hurst(e[:100])["h"] is None
    assert "too little" in process.describe(pd.Series(np.cumsum(e[:20])))["sentence"]


# --- co-movement ------------------------------------------------------------------------------------------------------------

def test_engle_granger_finds_a_cointegrated_pair_and_not_two_walks():
    rng = np.random.default_rng(9)
    n = 800
    common = np.cumsum(rng.normal(0, 0.01, n))
    idx = pd.bdate_range("2020-01-01", periods=n)
    a = pd.Series(common + rng.normal(0, 0.01, n), index=idx)
    b = pd.Series(common + rng.normal(0, 0.01, n), index=idx)
    w1, w2 = pd.Series(np.cumsum(rng.normal(0, 0.01, n)), index=idx), pd.Series(np.cumsum(rng.normal(0, 0.01, n)), index=idx)
    assert comove.eg_test(a, b)["p"] < 0.01
    assert comove.eg_test(w1, w2)["p"] > 0.05
    assert comove.eg_test(a.iloc[:100], b.iloc[:100])["p"] is None                  # too short
    st = comove.stability(a, b, window=252, steps=12)
    assert st["windows"] == 12 and st["share"] > 0.5


def test_benjamini_hochberg_and_the_run_summary():
    p = pd.Series([0.001, 0.009, 0.04, 0.2, 0.5, np.nan])
    r = comove.bh(p, q=0.10)
    assert list(r["significant"]) == [True, True, True, False, False, False]
    df = pd.DataFrame({"kind": ["pair"] * 4, "eg_p": [0.001, 0.2, 0.5, np.nan], "significant": [True, False, False, False]})
    s = comove.summary(df)
    assert s["pairs_tested"] == 3 and s["significant"] == 1 and "9% stayed cointegrated" in s["label"]
    assert "3 pairs tested, 1 significant" in s["text"]


def test_moves_with_reads_the_weekly_table(tmp_path):
    assert "has not produced" in comove.moves_with("AAA", tmp_path)["note"]
    rows = [{"asof": "2026-10-23", "group": "stock", "kind": "pair", "a": "i1", "b": "i2", "a_sym": "AAA", "b_sym": "BBB",
             "industry": "IT", "corr_5y": 0.7, "months": 60, "eg_p": 0.01, "eg_q": 0.05, "significant": True, "stability": 0.3,
             "windows": 36, "half_life": 20.0, "beta": 1.1, "johansen_rank": np.nan, "n_sessions": 750},
            {"asof": "2026-10-23", "group": "stock", "kind": "pair", "a": "i1", "b": "i3", "a_sym": "CCC", "b_sym": "AAA",
             "industry": "IT", "corr_5y": 0.4, "months": 60, "eg_p": 0.4, "eg_q": 0.9, "significant": False, "stability": np.nan,
             "windows": np.nan, "half_life": 40.0, "beta": 0.9, "johansen_rank": np.nan, "n_sessions": 750}]
    p = comove.out_path(tmp_path)
    p.parent.mkdir(parents=True)
    pd.DataFrame(rows).reindex(columns=comove.COLUMNS).to_parquet(p)
    out = comove.moves_with("aaa", tmp_path)
    assert [x["peer"] for x in out["peers"]] == ["BBB", "CCC"] and out["peers"][0]["cointegrated_after_bh"] is True
    assert out["peers"][1]["stable_share"] is None and "relations break" in out["label"]


def test_the_comovement_tool_keeps_its_place_and_stock_facts_takes_capm_and_process():
    assert list(tl.TOOLS)[26] == "comovement" and tl.TOOLS["comovement"].kind == "read"      # later tools are appended after it (26 since S80 phase 4 cut tools before it)
    enum = tl.TOOLS["stock_facts"].params["parts"]["items"]["enum"]
    assert {"capm", "process"} <= set(enum)


# --- the sector-reversion helpers and study registration --------------------------------------------------------------------

def test_sector_index_key_by_taxonomy():
    assert tp.sector_index_key("A", "COMPUTERS - SOFTWARE") == "SECTOR_IT_TRI"
    assert tp.sector_index_key("B", "CONSUMER GOODS") == "SECTOR_FMCG_TRI"
    assert tp.sector_index_key("C", "Information Technology") == "SECTOR_IT_TRI"
    assert tp.sector_index_key("A", "SUGAR") is None and tp.sector_index_key(None, None) is None


def test_spread_z_sees_a_cheap_spread_and_a_walk_gives_no_cointegration():
    rng = np.random.default_rng(10)
    n = 756
    sector = np.cumsum(rng.normal(0, 0.01, n))
    stock = sector + rng.normal(0, 0.02, n)
    stock[-1] -= 0.08                                                  # cheap against the sector today
    p, z = tp.spread_z(stock, sector)
    assert p < 0.05 and z < -2
    p2, _ = tp.spread_z(np.cumsum(rng.normal(0, 0.01, n)), sector)
    assert p2 > 0.05


def test_register_study_makes_one_claim_per_test_and_the_fit_check_passes(con, tmp_path):
    now = datetime(2026, 10, 26, 10, 0)
    args = ("sector_reversion", {"direction": "low"},
            "A stock cheap relative to a sector index it is cointegrated with earns more than the sector next month.",
            "The bottom quintile of the spread's z.", "S64 study", "docs/protocols/s64_reversion_protocol.md", now)
    cid = claims.register_study(con, *args)
    assert claims.register_study(con, *args) == cid                    # asked twice: one claim
    assert claims.fits(args[2], args[3], "sector_reversion", {"direction": "low"})
    assert not claims.fits("momentum pays", "", "sector_reversion", {"direction": "low"})
    assert claims.register(con, cid, tmp_path / "proto", now) == "registered"
    with pytest.raises(ValueError):
        claims.register_study(con, "sector_reversion", {"direction": "sideways"}, "x", "y", "t", "u", now)
    # the reversal claim reuses the existing cross-section test; asked after the first, it is a separate claim
    c2 = claims.register_study(con, "cross_section", {"signal": "reversal_1m", "direction": "low", "months": 1},
                               "Last month's losers outperform next month: short-term reversal.", "The lowest quintile.",
                               "S64 study 2", "docs/protocols/s64_reversion_protocol.md", now)
    assert c2 != cid and claims.fits("Last month's losers outperform next month: short-term reversal.", "", "cross_section",
                                     {"signal": "reversal_1m"})


def test_the_bar_for_the_reversion_test_counts_it(con, tmp_path):
    now = datetime(2026, 10, 26, 10, 0)
    counter.seed(con, now)
    cid = claims.register_study(con, "sector_reversion", {"direction": "low"},
                                "A stock cheap relative to its sector index (cointegrated) earns more than the sector.",
                                "bottom quintile of z", "S64 study", "u", now)
    claims.register(con, cid, tmp_path / "proto", now)
    claims.test(con, cid, tmp_path, now, run=lambda *a: {"decision": "fail", "why": "dev t 0.4",
                                                         "development": {"t": 0.4, "n": 80}, "validation": {"t": 0.1, "n": 40}})
    row = con.execute("SELECT origin, threshold_dev FROM learn_tests WHERE claim_id=?", [cid]).fetchone()
    assert row[0] == "learner" and row[1] == pytest.approx(counter.t_needed(len(counter.SEED) + len(counter.CARRIED) + 1))
