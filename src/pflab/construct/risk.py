"""Risk model for `construct` (S79b item 18A): a shrunk covariance of daily returns, point in time.

The sample covariance of many names over a year of days is noisy (its smallest eigenvalues are far too small, so an optimiser trusts diversification that is not
there). The estimate here is Ledoit-Wolf's analytic shrinkage toward a scaled identity (Ledoit and Wolf 2004, "A well-conditioned estimator for large-dimensional
covariance matrices"), implemented in numpy because scikit-learn is not a dependency of this project:

    S      = X'X / n                     (X centred, n days, p names)
    mu     = tr(S) / p
    d2     = ||S - mu I||_F^2 / p
    b2     = (1 / (n^2 p)) * sum_k ||x_k x_k' - S||_F^2          (the sampling noise of S)
    b      = min(b2, d2)
    shrunk = (b / d2) * mu I + (1 - b / d2) * S

`shrinkage` is b/d2 in [0, 1]: 0 means the sample covariance is trusted, 1 means only the identity target is. `tests/test_s79b_construct.py` checks the formula on a
known case (a true identity covariance, where the shrunk estimate is nearer the truth than the sample one) and against a direct loop version of the formula.

Point in time: `daily_returns` and `shrunk_cov` take only rows dated on or before `as_of` (the cut is made here, so a caller cannot leak a later day).
"""
from __future__ import annotations

from datetime import date
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def ledoit_wolf(X: np.ndarray, centre: bool = True) -> Tuple[np.ndarray, float]:
    """(shrunk covariance, shrinkage) of an (n, p) matrix of observations (rows = days). Deterministic; no random numbers."""
    X = np.asarray(X, float)
    if X.ndim != 2 or X.shape[0] < 2:
        raise ValueError("need at least two observations in a 2-D array")
    n, p = X.shape
    if centre:
        X = X - X.mean(axis=0, keepdims=True)
    S = X.T @ X / n
    mu = float(np.trace(S) / p)
    d2 = float(np.sum((S - mu * np.eye(p)) ** 2) / p)
    if d2 <= 1e-300:                                       # already spherical: nothing to shrink toward
        return S, 0.0
    # sum_k ||x_k x_k' - S||_F^2 = sum_k ||x_k||^4 - n ||S||_F^2   (expand the square)
    sq = np.einsum("ij,ij->i", X, X)
    b2 = float((np.sum(sq ** 2) - n * np.sum(S ** 2)) / (n * n * p))
    b = min(max(b2, 0.0), d2)
    s = b / d2
    return s * mu * np.eye(p) + (1.0 - s) * S, float(s)


def daily_returns(close: pd.DataFrame, as_of: date, window: int = 250, min_obs: int = 120, min_cover: float = 0.9) -> pd.DataFrame:
    """Simple daily returns of a panel of closes (columns = names), the last `window` rows dated <= as_of. A name with fewer than `min_obs` returns or less than
    `min_cover` of the window's days is dropped (its risk then comes from `fallback_vol`); remaining gaps are zero returns (no price move was seen)."""
    c = close[close.index <= pd.Timestamp(as_of)]
    r = c.pct_change(fill_method=None).iloc[1:].tail(window)
    if not len(r):
        return r
    keep = [k for k in r.columns if r[k].notna().sum() >= min_obs and r[k].notna().mean() >= min_cover]
    return r[keep].fillna(0.0)


def shrunk_cov(returns: pd.DataFrame, annualise: bool = True) -> Tuple[pd.DataFrame, float]:
    """(annual covariance as a DataFrame, shrinkage) from `daily_returns`. Empty frame when there is nothing to estimate."""
    if returns.shape[1] == 0 or returns.shape[0] < 20:
        return pd.DataFrame(), 0.0
    S, s = ledoit_wolf(returns.to_numpy(float))
    f = TRADING_DAYS if annualise else 1
    return pd.DataFrame(S * f, index=returns.columns, columns=returns.columns), s


def fallback_vol(default: float = 0.30) -> float:
    """Annual volatility for a name with too little history: a stated, deliberately high number (a new or thin name is riskier than the average one)."""
    return float(default)


def cov_for(names, returns: pd.DataFrame, forecast_vol: Optional[Dict[str, float]] = None, blend: float = 0.5, fallback: float = 0.30) -> Tuple[np.ndarray, Dict[str, str], float]:
    """The (p, p) annual covariance for `names` in order.

    Names with a return history take the shrunk covariance; their volatility is blended with the ensemble's own dispersion when it exists (`blend` = weight of the
    forecast's volatility, in the geometric sense: the correlation matrix is kept). A name without history gets `fallback` volatility and a correlation of
    0.3 with everything (a stated prior). Returns (matrix, {name: source note}, shrinkage)."""
    names = list(names)
    p = len(names)
    cov, s = shrunk_cov(returns)
    have = [k for k in names if k in cov.columns]
    sig = np.full(p, fallback)
    src: Dict[str, str] = {}
    for i, k in enumerate(names):
        if k in have:
            sig[i] = float(np.sqrt(max(cov.loc[k, k], 1e-12)))
            src[k] = "shrunk covariance of daily returns"
        else:
            src[k] = f"no return history: volatility {fallback:.0%} and correlation 0.3 assumed"
    corr = np.full((p, p), 0.3)
    np.fill_diagonal(corr, 1.0)
    if len(have) > 1:
        sub = cov.loc[have, have].to_numpy(float)
        d = np.sqrt(np.clip(np.diag(sub), 1e-12, None))
        c = sub / np.outer(d, d)
        ix = [names.index(k) for k in have]
        for a, ia in enumerate(ix):
            for b, ib in enumerate(ix):
                corr[ia, ib] = c[a, b]
    fv = forecast_vol or {}
    for i, k in enumerate(names):
        v = fv.get(k)
        if v is not None and np.isfinite(v) and v > 0:
            sig[i] = float(np.exp((1 - blend) * np.log(sig[i]) + blend * np.log(v)))
            src[k] += "; volatility blended with the ensemble's dispersion"
    M = corr * np.outer(sig, sig)
    M = (M + M.T) / 2.0
    w = np.linalg.eigvalsh(M)[0]
    if w < 1e-10:                                            # keep it positive definite (a numerical guard, not a modelling choice)
        M = M + (1e-10 - w) * np.eye(p)
    return M, src, s
