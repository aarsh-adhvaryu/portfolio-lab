"""Market-model residuals and past reactions to similar events (PLAN S20).

Rewritten 2026-10-06 from the archive's E2-A study module (`tools/MIGRATED.md`): the pre-registered
pass/fail machinery (cohort t-tests, `verdict`, period gates) is gone. What stays is descriptive
and answers one question for a held or watched name: when events of this kind happened before,
what did the share do relative to what the market alone would explain? Nothing here passes or
fails anything, and nothing is a forecast.

Method: market model `r_i = alpha + beta * r_m + e`, fitted by OLS on the `window` sessions that
end `gap` sessions before the event (so the run-up to the event is not in the fit). The abnormal
return is the realised return minus alpha + beta * r_m; a cumulative abnormal return (CAR) over k
sessions is the sum of daily residuals, with standard error sigma * sqrt(k).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

WINDOW = 120          # estimation sessions
GAP = 5               # sessions between the end of the fit and the event
MIN_OBS = 60


def newey_west_t(x: Sequence[float], lags: int = 5) -> Optional[float]:
    """t-statistic of the mean of `x`, autocorrelation-robust (Bartlett kernel); None when the series
    is too short for the lag length. Kept from the archive module; used for descriptive summaries."""
    a = np.asarray([v for v in x if v is not None and np.isfinite(v)], dtype=float)
    n = len(a)
    if n <= lags + 1:
        return None
    mu = a.mean()
    e = a - mu
    s = float(e @ e) / n
    for L in range(1, lags + 1):
        s += 2.0 * (1.0 - L / (lags + 1.0)) * float(e[L:] @ e[:-L]) / n
    if s <= 0:
        return None
    return float(mu / np.sqrt(s / n))


@dataclass(frozen=True)
class MarketModel:
    alpha: float
    beta: float
    sigma: float          # std of daily residuals
    n: int


def fit(ret_i: pd.Series, ret_m: pd.Series, event: date, *, window: int = WINDOW, gap: int = GAP,
        min_obs: int = MIN_OBS) -> Optional[MarketModel]:
    """OLS market model on the `window` shared sessions ending `gap` sessions before `event`.
    None if fewer than `min_obs` usable pairs: no beta from a handful of points."""
    df = pd.concat([ret_i.rename("i"), ret_m.rename("m")], axis=1, sort=True).dropna()
    df.index = pd.to_datetime(df.index)
    pos = df.index.searchsorted(pd.Timestamp(event), side="left")
    est = df.iloc[max(0, pos - gap - window): max(0, pos - gap)]
    if len(est) < min_obs or float(est["m"].var(ddof=1)) <= 0:
        return None
    b = float(np.cov(est["i"], est["m"], ddof=1)[0, 1] / est["m"].var(ddof=1))
    a = float(est["i"].mean() - b * est["m"].mean())
    resid = est["i"] - (a + b * est["m"])
    return MarketModel(a, b, float(resid.std(ddof=2)), len(est))


def abnormal(ret_i: pd.Series, ret_m: pd.Series, mm: MarketModel) -> pd.Series:
    """Daily abnormal returns over the dates both series have."""
    df = pd.concat([ret_i.rename("i"), ret_m.rename("m")], axis=1, sort=True).dropna()
    return df["i"] - (mm.alpha + mm.beta * df["m"])


def car(ret_i: pd.Series, ret_m: pd.Series, mm: MarketModel, start: date, k: int) -> Optional[tuple]:
    """(CAR, standard error) over the k sessions starting at `start` (inclusive); None if the series
    does not cover k sessions from there."""
    ab = abnormal(ret_i, ret_m, mm)
    ab.index = pd.to_datetime(ab.index)
    pos = ab.index.searchsorted(pd.Timestamp(start), side="left")
    w = ab.iloc[pos: pos + k]
    if len(w) < k:
        return None
    return float(w.sum()), float(mm.sigma * np.sqrt(k))


def reactions(events: pd.DataFrame, ret_wide: pd.DataFrame, ret_m: pd.Series,
              horizons: Sequence[int] = (1, 5, 21)) -> pd.DataFrame:
    """Per event, the CAR over each horizon, starting at the first session on or after
    `usable_from` (the first session the market could have reacted).

    events: columns isin, usable_from (date), flag. ret_wide: sessions x ISIN daily returns.
    Events with no fit, or whose horizon runs past the data, are listed with NaN, never dropped."""
    rows = []
    for e in events.itertuples(index=False):
        ev_date = pd.Timestamp(e.usable_from).date()
        row = {"isin": e.isin, "flag": e.flag, "usable_from": ev_date}
        mm = fit(ret_wide[e.isin], ret_m, ev_date) if e.isin in ret_wide.columns else None
        row["beta"] = mm.beta if mm else np.nan
        for h in horizons:
            c = car(ret_wide[e.isin], ret_m, mm, ev_date, h) if mm else None
            row[f"car_{h}"] = c[0] if c else np.nan
            row[f"se_{h}"] = c[1] if c else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def summarise(r: pd.DataFrame, horizons: Sequence[int] = (1, 5, 21)) -> pd.DataFrame:
    """Per flag and horizon: events, mean, median, share negative, 10th and 90th percentile of CAR.
    Descriptive: it shows what happened before, with the count, and says nothing about the next one."""
    out = []
    for flag, g in r.groupby("flag"):
        for h in horizons:
            v = g[f"car_{h}"].dropna()
            if v.empty:
                continue
            out.append({"flag": flag, "horizon": h, "n": len(v), "mean": float(v.mean()), "median": float(v.median()),
                        "share_negative": float((v < 0).mean()), "p10": float(v.quantile(0.1)),
                        "p90": float(v.quantile(0.9))})
    return pd.DataFrame(out, columns=["flag", "horizon", "n", "mean", "median", "share_negative", "p10", "p90"])
