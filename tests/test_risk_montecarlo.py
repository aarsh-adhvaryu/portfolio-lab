"""S36 Monte Carlo and frontier on SYNTHETIC monthly returns."""
import numpy as np
import pandas as pd
import pytest

from pflab.risk import montecarlo as mc


def hist(n=120, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-01-31", periods=n, freq="ME")
    crash = np.zeros(n); crash[30:36] = -0.12                               # one clustered crash
    s = rng.normal(0.01, 0.05, n) + crash
    df = pd.DataFrame({"stocks": s, "n500": 0.8 * s + rng.normal(0, 0.01, n), "mom50": 0.9 * s + rng.normal(0, 0.02, n),
                       "gold": rng.normal(0.008, 0.04, n)}, index=idx)
    df["debt"] = (1 + mc.DEBT_RATE) ** (1 / 12) - 1
    df["cash"] = (1 + mc.CASH_RATE) ** (1 / 12) - 1
    return df[list(mc.ASSETS)]


def test_block_paths_replay_whole_stretches_of_history():
    R = hist().values
    p = mc.block_paths(R, 24, 50, np.random.default_rng(0))
    assert p.shape == (50, 24, 6)
    rows = {tuple(r) for r in R.round(12)}
    assert all(tuple(x) in rows for x in p[:, :, :].reshape(-1, 6).round(12))
    first = p[0, :12, 0]
    pos = [i for i in range(len(R) - 11) if np.allclose(R[i:i + 12, 0], first)]
    assert pos                                                              # a real 12-month block, in order


def test_gbm_keeps_riskless_assets_riskless_and_matches_mean():
    R = hist(240)
    p = mc.gbm_paths(R.values, 12, 4000, np.random.default_rng(0))
    assert np.allclose(p[:, :, 4], R["debt"].iloc[0]) and np.allclose(p[:, :, 5], R["cash"].iloc[0])
    assert np.log1p(p[:, :, 0]).mean() == pytest.approx(np.log1p(R["stocks"]).mean(), abs=0.003)


def test_summary_mix_and_drawdown():
    v = np.array([[1.1, 0.55, 0.6, 1.2]])
    assert mc.max_dd(v)[0] == pytest.approx(0.55 / 1.1 - 1)
    s = mc.summary(np.tile(np.array([1.0 + 0.01 * k for k in range(1, 13)]), (3, 1)), 12)
    assert s["p_fall_beyond_limit"] == 0 and s["y1"]["p50"] == pytest.approx(1.12)
    with pytest.raises(ValueError):
        mc.weights_of({"stocks": 0.5})


def test_frontier_and_lump_vs_staged_shapes():
    R = hist()
    fr = mc.frontier(R, 200)
    assert len(fr) == 200 and np.allclose(fr[list(mc.FRONTIER_ASSETS)].sum(axis=1), 1)
    pt = mc.point(R, {"debt": 0.9, "cash": 0.1})
    assert pt["worst_fall"] == pytest.approx(0.0) and pt["debt"] == pytest.approx(1.0)
    ls = mc.lump_vs_staged(R, {"stocks": 1.0}, months_staged=4, horizon=12, n=500)
    assert set(ls) == {"block", "gbm"} and 0 <= ls["block"]["p_staged_beats_lump"] <= 1
