"""S52 study library (pflab.quant.tfm2): variance proxy, point-in-time inputs, targets, baselines, losses and the
pooled tests. Synthetic data only; no TimesFM, no GPU."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from pflab.quant import tfm2 as tf


def bars(n=40, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    o = np.r_[c[0], c[:-1]] * np.exp(rng.normal(0, 0.002, n))
    h = np.maximum(o, c) * 1.004
    l = np.minimum(o, c) * 0.996
    d = [date(2010, 1, 4) + timedelta(days=i) for i in range(n)]
    return pd.DataFrame({"date": d, "open": o, "high": h, "low": l, "close": c})


def test_variance_proxy_is_garman_klass_plus_overnight_and_falls_back_to_r2():
    df = bars()
    df.loc[5, "high"] = df.loc[5, "low"]                         # a broken bar (H == L)
    r, v = tf.variance_proxy(df)
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = 7
    gk = 0.5 * np.log(h[t] / l[t]) ** 2 - (2 * np.log(2) - 1) * np.log(c[t] / o[t]) ** 2 + np.log(o[t] / c[t - 1]) ** 2
    assert v[t] == pytest.approx(gk) and v[5] == pytest.approx(r[5] ** 2) and np.isnan(v[0])
    assert r[t] == pytest.approx(np.log(c[t] / c[t - 1]))


def test_input_series_is_logged_and_floored_and_log5_uses_only_the_past():
    v = np.array([np.nan, 0.0, 1e-4, 1e-4, 1e-4, 1e-4, 4e-4])
    x = tf.input_series(v, "log")
    assert x[1] == pytest.approx(np.log(tf.LOG_FLOOR)) and x[2] == pytest.approx(np.log(1e-4))
    x5 = tf.input_series(v, "log5")
    assert x5[6] == pytest.approx(np.log(np.mean(v[2:7])))       # rows 2..6 only, nothing after 6


def test_forecast_index_skips_spent_years_and_needs_history_and_a_horizon():
    d = pd.bdate_range("2003-01-01", "2026-03-31").date
    idx = tf.forecast_index(d, h=10)
    got = pd.to_datetime(pd.Series(d[idx]))
    assert got.min() >= pd.Timestamp("2005-01-01") and idx.min() >= tf.MIN_HISTORY
    assert not ((got >= "2022-01-01") & (got <= "2025-12-31")).any()
    assert idx.max() == len(d) - 11
    assert (np.diff(tf.forecast_index(d, h=252, step=5)) % 5 == 0).all()


def test_vix_alignment_same_session_or_previous():
    vix = pd.DataFrame({"date": [date(2026, 1, 5), date(2026, 1, 6)], "close": [20.0, 30.0]})
    md = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
    same = tf.aligned_vix(md, vix, True)
    prev = tf.aligned_vix(md, vix, False)
    assert np.allclose(np.exp(same), [20, 30, 30])
    assert np.isnan(prev[0]) and np.allclose(np.exp(prev[1:]), [20, 30])


def test_variance_from_deciles_is_a_mean_not_a_median():
    q = np.tile(np.log(np.geomspace(1e-4, 9e-4, 9)), (1, 10, 1))         # symmetric in logs, skewed in levels
    f = tf.rv_from_deciles(q)
    assert f[0] == pytest.approx(np.mean(np.geomspace(1e-4, 9e-4, 9)))
    assert f[0] > np.exp(q[0, 0, 4])                                         # above the median decile


def test_scale_and_log_har_recover_a_known_relation():
    rng = np.random.default_rng(3)
    n = 3000
    lv = np.cumsum(rng.normal(0, 0.05, n)) * 0.1 + np.log(1e-4)
    v = np.exp(lv)
    rv = np.exp(lv + 0.1) * np.exp(rng.normal(0, 0.01, n))
    dev = np.zeros(n, bool)
    dev[:2000] = True
    f = tf.har_log_v(v, rv, dev)
    assert np.nanmean(np.abs(np.log(f[2100:2900] / rv[2100:2900]))) < 0.05
    assert tf.fit_scale(rv, v, dev) == pytest.approx(np.mean(rv[:2000] / v[:2000]))


def test_pooled_dm_favours_the_lower_loss_across_markets():
    rng = np.random.default_rng(4)
    d1 = pd.bdate_range("2015-01-01", periods=400).date
    d2 = pd.bdate_range("2015-01-02", periods=400).date
    rows = [(d, rng.uniform(0, 1, 400), rng.uniform(0.3, 1.3, 400)) for d in (d1, d2)]
    out = tf.pooled_dm(rows)
    assert out["mean_diff"] > 0 and out["p"] < 0.001 and out["n"] == len(set(d1) | set(d2))
    assert tf.pooled_dm([(d, b, a) for d, a, b in rows])["p"] > 0.99


def test_fall_chance_matches_the_normal_and_rises_with_variance():
    p1 = tf.fall_chance(np.array([[0.02 ** 2]]))
    from scipy.stats import norm
    assert p1[0] == pytest.approx(norm.cdf(-1.0))
    path = np.full((2, 10), 1e-4)
    path[1] *= 4
    p = tf.fall_chance(path)
    assert p[1] > p[0] and 0 < p[0] < 1


def test_pooled_auc_bootstrap_detects_a_better_score():
    rng = np.random.default_rng(5)
    e = [rng.integers(0, 2, 300).astype(float) for _ in range(3)]
    good = [x + rng.normal(0, 0.5, 300) for x in e]
    noise = [rng.normal(0, 1, 300) for _ in range(3)]
    out = tf.pooled_auc_diff_bootstrap(good, noise, e, reps=200)
    assert out["diff"] > 0.2 and out["p"] < 0.01


def test_pinball_and_coverage():
    q = np.tile(np.arange(1, 10, dtype=float), (2, 1))
    assert tf.pinball(np.array([5.0, 5.0]), q)[0] == pytest.approx(np.mean(
        [max(l * (5 - k), (l - 1) * (5 - k)) for l, k in zip(tf.DECILES, range(1, 10))]))
    assert tf.coverage(np.array([5.0, 20.0]), q) == 0.5


def test_bootstrap_range_uses_only_returns_completed_by_t():
    lnc = np.r_[np.zeros(300), np.full(50, 5.0)]                  # a jump after t = 299
    idx = np.array([299])
    q = tf.range_bootstrap(lnc, idx, h=10)
    assert np.allclose(q, 0.0)


def test_normal_ranges_and_return_benchmarks():
    rng = np.random.default_rng(6)
    r = rng.normal(0.0004, 0.01, 2000)
    idx = np.array([1000, 1500])
    q = tf.range_normal(r, idx, 252, "ewma")
    assert q.shape == (2, 9) and (np.diff(q, axis=1) > 0).all()
    assert tf.expanding_mean_return(r, idx, 252)[0] == pytest.approx(np.mean(r[:1001]) * 252)
    y = np.array([1.0, 2.0, 3.0])
    assert tf.oos_r2(y, y, np.zeros(3)) == 1.0


def test_clark_west_rewards_a_model_with_signal():
    rng = np.random.default_rng(7)
    d = pd.bdate_range("2015-01-01", periods=500).date
    sig = rng.normal(0, 1, 500)
    y = sig + rng.normal(0, 1, 500)
    out = tf.clark_west_pooled([(d, y, sig, np.zeros(500))], lag=5)
    assert out["t"] > 3


def test_expiry_week_is_the_week_of_the_last_thursday_or_the_session_before():
    d = pd.bdate_range("2026-10-19", "2026-11-30").date
    f = dict(zip(d, tf.expiry_week_flags(d)))
    assert [k for k, v in f.items() if v and k.month == 10] == [date(2026, 10, 26), date(2026, 10, 27),
                                                               date(2026, 10, 28), date(2026, 10, 29)]
    d2 = [x for x in d if x != date(2026, 11, 26)]                 # last Thursday of November shut
    f2 = dict(zip(d2, tf.expiry_week_flags(d2)))
    assert [k for k, v in f2.items() if v and k.month == 11] == [date(2026, 11, 23), date(2026, 11, 24),
                                                                date(2026, 11, 25)]


def test_turnover_target_and_baselines():
    rng = np.random.default_rng(8)
    d = pd.bdate_range("2008-01-01", periods=600).date
    lt = 15 + rng.normal(0, 0.3, 600)
    lt[100] = np.nan
    cov = tf.calendar_covariates(d)
    idx = np.arange(30, 590, 5)
    y = tf.turnover_target(lt, idx)
    assert y[0] == pytest.approx(np.log(np.mean(np.exp(lt[31:36]))))
    b = tf.turnover_baselines(lt, cov, idx, np.arange(len(idx)) < 60)
    assert set(b) == {"mean20", "har_cal"} and np.isfinite(b["har_cal"]).all()
    q = np.tile(np.full(9, 15.0), (len(idx), 5, 1))
    assert tf.turnover_from_deciles(q)[0] == pytest.approx(15.0)


def test_quarter_series_baselines_respect_gaps():
    qe = list(pd.date_range("2012-03-31", periods=14, freq="QE").date)
    qe.pop(10)                                                     # a missing quarter
    q = pd.DataFrame({"quarter_end": qe, "revenue": np.exp(np.arange(13) * 0.1 + 5), "net_profit": 10.0})
    s = tf.quarter_series(q)
    assert (s["usable_from"] - pd.to_datetime(s["quarter_end"])).dt.days.eq(60).all()
    b = tf.results_baselines(s["ln_revenue"].to_numpy(), s["quarter_end"], "ln_revenue")
    assert b["same_q_last_year"][8] == pytest.approx(s["ln_revenue"][4])
    assert b["with_trailing_growth"][8] == pytest.approx(s["ln_revenue"][4] + 0.4)
    assert np.isnan(b["same_q_last_year"][10])                   # quarter 10 follows a gap
    assert np.isnan(b["same_q_last_year"][11])                   # its run is too short


def test_company_t():
    out = tf.company_t({"a": np.array([0.2, 0.1]), "b": np.array([0.3]), "c": np.array([0.25, 0.2]),
                        "d": np.array([-0.05])})
    assert out["n"] == 4 and out["share_better"] == 0.75 and out["t"] > 0
