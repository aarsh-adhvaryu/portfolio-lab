"""What kind of process a price (or a spread) behaves like (S64 Phase 2c). Layer: tool (code only).

Mean reversion is a property of the process, measured, not a trading signal. Each function is a standard test
(statsmodels for the ADF); `describe` puts them in one plain sentence for the brain and the stock page:

    adf              augmented Dickey-Fuller on a level (regression 'c', lags by AIC): p small -> reverts to a mean
    variance_ratio   Lo-MacKinlay (1988), heteroskedasticity-robust z*: VR(q) < 1 reversal, > 1 trend, 1 random walk
    ou_half_life     dx = a + b * x(-1): half-life = -ln 2 / ln(1 + b) when b < 0, else None (no reversion)
    hurst            aggregated-variance method; reported with its n and labelled noisy

It is a description of the past, never a signal (CLAUDE.md rule 12): the S39 pairs study found 9% of relations
stayed cointegrated and the strategy failed its registered rule.
"""
from __future__ import annotations

import math
from typing import Dict, Optional, Sequence

import numpy as np
import pandas as pd

QS = (2, 4, 8, 16)
P_LEVEL = 0.05
Z_LEVEL = 1.96


def _clean(x) -> np.ndarray:
    a = np.asarray(pd.Series(x).astype(float), dtype=float)
    return a[np.isfinite(a)]


def adf(x) -> dict:
    from statsmodels.tsa.stattools import adfuller
    a = _clean(x)
    if len(a) < 30 or float(np.std(a)) == 0.0:
        return {"stat": None, "p": None, "lags": None, "n": int(len(a))}
    stat, p, lags, nobs = adfuller(a, regression="c", autolag="AIC")[:4]
    return {"stat": float(stat), "p": float(p), "lags": int(lags), "n": int(nobs)}


def variance_ratio(r, qs: Sequence[int] = QS) -> Dict[int, dict]:
    """Lo-MacKinlay VR(q) with the robust z* for a series of (log) returns, overlapping q-period sums."""
    x = _clean(r)
    T = len(x)
    out: Dict[int, dict] = {}
    if T < 4 * max(qs):
        return {q: {"vr": None, "z": None, "n": T} for q in qs}
    mu = x.mean()
    d = x - mu
    s2 = float((d ** 2).sum() / (T - 1))
    denom = float((d ** 2).sum() ** 2)
    for q in qs:
        cs = np.convolve(x, np.ones(q), mode="valid")                    # sums of q consecutive returns
        m = q * (T - q + 1) * (1 - q / T)
        sq = float(((cs - q * mu) ** 2).sum() / m)
        vr = sq / s2
        theta = 0.0
        for j in range(1, q):
            dj = float((d[j:] ** 2 * d[:-j] ** 2).sum() / denom) * T          # T * sum / (sum^2): the delta_j
            theta += (2.0 * (q - j) / q) ** 2 * dj
        z = (vr - 1.0) / math.sqrt(theta / T) if theta > 0 else float("nan")
        out[q] = {"vr": float(vr), "z": float(z) if math.isfinite(z) else None, "n": T}
    return out


def ou_half_life(x) -> Optional[float]:
    """Half-life, in the series' own steps, of a mean-reverting level; None when the level does not revert."""
    a = _clean(x)
    if len(a) < 30:
        return None
    y, lag = np.diff(a), a[:-1]
    X = np.column_stack([np.ones(len(lag)), lag])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    b = float(coef[1])
    if not (-1.0 < b < 0.0):
        return None
    return float(-math.log(2.0) / math.log(1.0 + b))


def hurst(r) -> dict:
    """Hurst exponent of a return series by the aggregated-variance method (variance of block means ~ m^(2H-2)).
    H near 0.5 is a random walk. Noisy: reported with n."""
    x = _clean(r)
    n = len(x)
    if n < 250:
        return {"h": None, "n": n, "label": "noisy"}
    ms = sorted({int(m) for m in np.unique(np.geomspace(4, max(n // 10, 8), 8).astype(int))})
    lv, lm = [], []
    for m in ms:
        k = n // m
        if k < 8:
            continue
        v = x[:k * m].reshape(k, m).mean(axis=1).var(ddof=1)
        if v > 0:
            lv.append(math.log(v))
            lm.append(math.log(m))
    if len(lm) < 4:
        return {"h": None, "n": n, "label": "noisy"}
    slope = float(np.polyfit(lm, lv, 1)[0])
    return {"h": float(min(max(1.0 + slope / 2.0, 0.0), 1.0)), "n": n, "label": "noisy"}


def spread(a: pd.Series, b: pd.Series):
    """ln a - beta * ln b with beta from OLS on the common sessions: (spread Series, beta). Both are price levels."""
    j = pd.concat([np.log(a.astype(float)).rename("a"), np.log(b.astype(float)).rename("b")], axis=1, join="inner").dropna()
    if len(j) < 30:
        return pd.Series(dtype=float), float("nan")
    beta = float(np.polyfit(j["b"].to_numpy(), j["a"].to_numpy(), 1)[0])
    return (j["a"] - beta * j["b"]), beta


def describe(logp) -> dict:
    """The process of a log-price (or spread) series, daily: ADF, variance ratios, half-life, Hurst and one sentence."""
    s = pd.Series(logp).dropna()
    r = s.diff().dropna()
    a, vr, hl, h = adf(s), variance_ratio(r), ou_half_life(s), hurst(r)
    v4 = vr.get(4, {})
    if a["p"] is None or v4.get("vr") is None:
        return {"adf": a, "vr": vr, "half_life": hl, "hurst": h, "kind": "unknown", "n": int(len(s)),
                "sentence": f"too little history ({len(s)} sessions) to say what process it follows"}
    z = v4["z"] if v4["z"] is not None else 0.0
    if a["p"] < P_LEVEL:
        kind = "mean-reverting"
        sentence = f"reverts to a mean (ADF p {a['p']:.2f}" + (f"; half-life about {hl:.0f} sessions" if hl else "") + ")"
    elif abs(z) >= Z_LEVEL:
        kind = "short-term reversal" if v4["vr"] < 1 else "trending"
        sentence = (f"{'reverses' if v4['vr'] < 1 else 'trends'} over days (ADF p {a['p']:.2f}; "
                    f"VR(4) {v4['vr']:.2f}, z {z:+.1f})")
    else:
        kind = "random walk"
        sentence = f"behaves like a random walk (ADF p {a['p']:.2f}; VR(4) {v4['vr']:.2f}, z {z:+.1f})"
    return {"adf": a, "vr": {str(k): v for k, v in vr.items()}, "half_life": hl, "hurst": h, "kind": kind,
            "n": int(len(s)), "sentence": sentence,
            "label": "a description of the past, never a signal (S39: 9% of relations stayed cointegrated)"}
