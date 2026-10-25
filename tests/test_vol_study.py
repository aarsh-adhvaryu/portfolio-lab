"""S50 volatility / fall-risk study: point in time, losses, tests, decision rules. SYNTHETIC data."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from pflab.quant import vol_study as vs


def garch(n=4000, seed=1):
    rng = np.random.default_rng(seed)
    r, v = np.zeros(n), 1e-4
    for t in range(n):
        v = 2e-6 + 0.08 * (r[t - 1] ** 2 if t else 0) + 0.9 * v
        r[t] = rng.standard_normal() * np.sqrt(v)
    return r


def test_targets_use_only_the_future_and_baselines_only_the_past():
    r = garch(300)
    rv, fall = vs.target_rv(r), vs.target_fall(r)
    assert rv[10] == pytest.approx((r[11:21] ** 2).mean()) and np.isnan(rv[-1]) and np.isnan(rv[-10])
    assert fall[5] == float((r[6:16] <= -0.02).any())
    r2 = r.copy()
    r2[200:] = 0.5                                                   # change the future only
    for f in (vs.trailing, vs.ewma):
        assert np.allclose(f(r)[:200], f(r2)[:200], equal_nan=True)
    assert vs.trailing(r)[30] == pytest.approx((r[9:31] ** 2).mean())


def test_qlike_is_zero_only_at_the_truth_and_dm_sees_a_better_model():
    assert vs.qlike(np.array([2.0]), np.array([2.0]))[0] == pytest.approx(0.0)
    assert vs.qlike(np.array([2.0]), np.array([1.0]))[0] > vs.qlike(np.array([2.0]), np.array([4.0]))[0] > 0
    r = garch()
    rv = vs.target_rv(r)
    ok = np.isfinite(rv) & np.isfinite(vs.ewma(r))
    good = vs.qlike(rv[ok], vs.ewma(r)[ok])
    bad = vs.qlike(rv[ok], np.full(ok.sum(), np.nanmean(rv)))        # a constant forecast on clustered volatility
    assert vs.dm_one_sided(good, bad)["p"] < 0.01 and vs.dm_one_sided(bad, good)["p"] > 0.99


def test_auc_and_block_bootstrap():
    e = np.array([0, 0, 1, 1, 0, 1, 0, 1] * 50, float)
    perfect, noise = e + 0.0, np.random.default_rng(3).random(len(e))
    assert vs.auc(perfect, e) == 1.0 and vs.auc(-perfect, e) == 0.0
    b = vs.auc_diff_bootstrap(perfect, noise, e, reps=300)
    assert b["diff"] > 0.3 and b["p"] < 0.01


def test_har_fits_on_development_only():
    r = garch()
    m = np.zeros(len(r), bool)
    m[:1500] = True
    beta = vs.har_fit(r, m)
    r2 = r.copy()
    r2[2500:] *= 3                                                   # outside development: same coefficients
    assert np.allclose(beta, vs.har_fit(r2, m))


def test_decision_rules_pick_a_better_forecast_and_reject_a_worse_one():
    n = 6250                                                         # reaches 2026: the holdout must exist
    dates = pd.bdate_range("2003-01-01", periods=n).strftime("%Y-%m-%d").to_numpy()
    r = garch(n, seed=2)                                             # a 2026 window with calm and falling spells
    rv = vs.target_rv(r)
    truthy = np.where(np.isfinite(rv), rv * np.exp(np.random.default_rng(2).normal(0, 0.05, n)), np.nan)  # near-oracle
    flat = np.full(n, np.nanmean(rv))
    hawkes = np.random.default_rng(4).random(n)
    res = vs.evaluate(dates, r, {"good": {"sq_256": truthy, "abs_256": flat}, "bad": {"sq_256": flat}}, hawkes)
    g, b = res["versions"]["good"], res["versions"]["bad"]
    assert g["chosen_config"] == "sq_256" and g["passes_q1"] and not b["passes_q1"]
    assert res["adopt_q1"] == "good" and g["passes_q2"] and res["adopt_q2"] == "good" and len(res["fall_logit"]) == 2
    short = vs.evaluate(dates[:6000], r[:6000], {"good": {"sq_256": truthy[:6000]}}, hawkes[:6000])
    assert not short["versions"]["good"]["passes_q1"]                # no 2026 holdout: cannot pass






