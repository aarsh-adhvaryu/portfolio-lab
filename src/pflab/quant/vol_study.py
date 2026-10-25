"""S50: volatility and fall-risk forecasts for the Nifty 500 (docs/research/timesfm_protocol.md).

Point in time throughout: a value at index t uses returns up to t; the target at t is built from t+1..t+H only.
Baselines and scoring live here (main venv); TimesFM's forecasts were made in `.venv-train` by the S50 tool (retired in S63)
and read back as arrays aligned to the same dates.
"""
from __future__ import annotations

from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

H = 10
FLOOR = 1e-10
PERIODS = {"dev": ("2005-01-01", "2014-12-31"), "val": ("2015-01-01", "2019-12-31"),
           "desc": ("2020-01-01", "2025-12-31"), "holdout": ("2026-01-01", "2099-12-31")}
FALL = -0.02
SEED = 20261020


def target_rv(r: np.ndarray, h: int = H) -> np.ndarray:
    """Realised mean r^2 over t+1..t+h at each t (NaN where fewer than h sessions follow)."""
    sq = np.asarray(r, float) ** 2
    out = np.full(len(sq), np.nan)
    c = np.concatenate([[0.0], np.cumsum(sq)])
    for t in range(len(sq) - h):
        out[t] = (c[t + 1 + h] - c[t + 1]) / h
    return out


def target_fall(r: np.ndarray, h: int = H, threshold: float = FALL) -> np.ndarray:
    """1.0 when a session of `threshold` or worse comes in t+1..t+h, else 0.0 (NaN at the end)."""
    f = (np.asarray(r, float) <= threshold).astype(float)
    out = np.full(len(f), np.nan)
    for t in range(len(f) - h):
        out[t] = float(f[t + 1:t + 1 + h].max())
    return out


def trailing(r: np.ndarray, n: int = 22) -> np.ndarray:
    s = pd.Series(np.asarray(r, float) ** 2)
    return s.rolling(n, min_periods=n).mean().to_numpy()


def ewma(r: np.ndarray, lam: float = 0.94, warm: int = 22) -> np.ndarray:
    sq = np.asarray(r, float) ** 2
    out = np.full(len(sq), np.nan)
    if len(sq) < warm:
        return out
    v = sq[:warm].mean()
    out[warm - 1] = v
    for t in range(warm, len(sq)):
        v = lam * v + (1 - lam) * sq[t]
        out[t] = v
    return out


def har_features(r: np.ndarray) -> np.ndarray:
    sq = pd.Series(np.asarray(r, float) ** 2)
    return np.column_stack([np.ones(len(sq)), sq.to_numpy(), sq.rolling(5).mean().to_numpy(),
                            sq.rolling(22).mean().to_numpy()])


def har_fit(r: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """OLS coefficients of the next-H RV on (1, r^2, 5-day, 22-day mean r^2), on the rows in `mask` only."""
    X, y = har_features(r), target_rv(r)
    ok = mask & np.isfinite(y) & np.isfinite(X).all(axis=1)
    beta, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
    return beta


def har_forecast(r: np.ndarray, beta: np.ndarray) -> np.ndarray:
    return np.maximum(har_features(r) @ beta, FLOOR)


def qlike(rv: np.ndarray, f: np.ndarray) -> np.ndarray:
    f = np.maximum(np.asarray(f, float), FLOOR)
    x = np.asarray(rv, float) / f
    return x - np.log(np.maximum(x, FLOOR)) - 1


def dm_one_sided(loss_a: np.ndarray, loss_b: np.ndarray, lag: int = H - 1) -> Dict[str, float]:
    """Diebold-Mariano, H1: model a has the lower mean loss. d = loss_b - loss_a; Newey-West (HAC) standard error."""
    import statsmodels.api as sm
    from scipy.stats import norm
    d = np.asarray(loss_b, float) - np.asarray(loss_a, float)
    d = d[np.isfinite(d)]
    fit = sm.OLS(d, np.ones(len(d))).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    t = float(fit.tvalues[0])
    return {"mean_diff": float(d.mean()), "t": t, "p": float(1 - norm.cdf(t)), "n": int(len(d))}


def auc(score: np.ndarray, event: np.ndarray) -> float:
    from scipy.stats import rankdata
    s, e = np.asarray(score, float), np.asarray(event, float)
    ok = np.isfinite(s) & np.isfinite(e)
    s, e = s[ok], e[ok]
    n1, n0 = e.sum(), len(e) - e.sum()
    if n1 == 0 or n0 == 0:
        return float("nan")
    rk = rankdata(s)
    return float((rk[e == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def auc_diff_bootstrap(a: np.ndarray, b: np.ndarray, event: np.ndarray, block: int = 20, reps: int = 2000,
                       seed: int = SEED) -> Dict[str, float]:
    """AUC(a) - AUC(b) and a one-sided p (H1: a ranks better) from a moving-block bootstrap of the sessions."""
    ok = np.isfinite(a) & np.isfinite(b) & np.isfinite(event)
    a, b, e = np.asarray(a)[ok], np.asarray(b)[ok], np.asarray(event)[ok]
    n = len(e)
    rng = np.random.default_rng(seed)
    diffs = []
    starts_max = max(1, n - block + 1)
    for _ in range(reps):
        idx = np.concatenate([np.arange(s, s + block) for s in rng.integers(0, starts_max, size=n // block + 1)])[:n]
        da = auc(a[idx], e[idx]) - auc(b[idx], e[idx])
        if np.isfinite(da):
            diffs.append(da)
    diffs = np.asarray(diffs)
    return {"diff": auc(a, e) - auc(b, e), "p": float((diffs <= 0).mean()) if len(diffs) else float("nan"),
            "reps": int(len(diffs))}


def period_mask(dates: Sequence, name: str) -> np.ndarray:
    d = pd.to_datetime(pd.Series(dates))
    a, b = PERIODS[name]
    return ((d >= pd.Timestamp(a)) & (d <= pd.Timestamp(b))).to_numpy()


def evaluate(dates: Sequence, r: np.ndarray, tfm: Dict[str, Dict[str, np.ndarray]], hawkes: np.ndarray,
             version_alpha: float = 0.025) -> dict:
    """`tfm`: version -> config -> RV forecasts aligned with `dates`. Applies the registered rules (protocol)."""
    rv, fall = target_rv(r), target_fall(r)
    m = {k: period_mask(dates, k) & np.isfinite(rv) for k in PERIODS}
    beta = har_fit(r, m["dev"])
    base = {"trailing22": trailing(r), "ewma094": ewma(r), "har": har_forecast(r, beta)}

    def mean_q(f, k):
        ok = m[k] & np.isfinite(f)
        return float(qlike(rv[ok], f[ok]).mean()) if ok.any() else float("nan")

    out: dict = {"har_beta": beta.tolist(), "baselines": {b: {k: mean_q(f, k) for k in PERIODS} for b, f in base.items()}}
    best_base = min(base, key=lambda b: out["baselines"][b]["dev"])
    out["chosen_baseline"] = best_base
    fb = base[best_base]
    out["hawkes_auc"] = {k: auc(hawkes[m[k]], fall[m[k]]) for k in PERIODS}
    out["versions"] = {}
    for v, cfgs in tfm.items():
        dev_q = {c: mean_q(f, "dev") for c, f in cfgs.items()}
        best = min(dev_q, key=dev_q.get)
        f = cfgs[best]
        common = m["val"] & np.isfinite(f) & np.isfinite(fb)
        dm = dm_one_sided(qlike(rv[common], f[common]), qlike(rv[common], fb[common]))
        q = {k: mean_q(f, k) for k in PERIODS}
        hold_ratio = q["holdout"] / out["baselines"][best_base]["holdout"]
        q1 = bool(q["val"] < out["baselines"][best_base]["val"] and dm["p"] < version_alpha and hold_ratio <= 1.0)
        vm = m["val"] & np.isfinite(f) & np.isfinite(hawkes)
        boot = auc_diff_bootstrap(f[vm], hawkes[vm], fall[vm])
        a = {k: auc(f[m[k] & np.isfinite(f)], fall[m[k] & np.isfinite(f)]) for k in PERIODS}
        q2 = bool(boot["diff"] > 0 and boot["p"] < version_alpha and a["holdout"] >= out["hawkes_auc"]["holdout"])
        out["versions"][v] = {"dev_qlike_by_config": dev_q, "chosen_config": best, "qlike": q, "dm_val": dm,
                              "holdout_ratio": hold_ratio, "auc": a, "auc_val_vs_hawkes": boot,
                              "passes_q1": q1, "passes_q2": q2}
    vs = out["versions"]
    p1 = [v for v in vs if vs[v]["passes_q1"]]
    p2 = [v for v in vs if vs[v]["passes_q2"]]
    out["adopt_q1"] = min(p1, key=lambda v: vs[v]["qlike"]["val"]) if p1 else None
    out["adopt_q2"] = max(p2, key=lambda v: vs[v]["auc"]["val"]) if p2 else None
    if out["adopt_q2"]:                                 # the live fall-chance map, fitted on development only
        import statsmodels.api as sm
        f = vs[out["adopt_q2"]]["chosen_config"]
        x = tfm[out["adopt_q2"]][f]
        ok = m["dev"] & np.isfinite(x) & np.isfinite(fall)
        lg = sm.Logit(fall[ok], sm.add_constant(np.log(np.maximum(x[ok], FLOOR)))).fit(disp=0)
        out["fall_logit"] = lg.params.tolist()
    return out
