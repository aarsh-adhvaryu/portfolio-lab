"""The registered baselines the live system keeps (S64 Phase 3; from the S52 study, docs/STUDIES.md):
tools only, no model. Turnover (trader tickets' size check) and results (ranges before results) are served by these,
exactly as they were when they were the baseline beside TimesFM; and the EWMA the volatility chance uses.

    turnover   ln of the mean daily turnover over the next 5 sessions: HAR on ln turnover (1, 5, 22 sessions) with the
               calendar of the next 5 sessions, fitted on the stock's own matured history; else the 20-session mean
    results    next quarter's ln revenue: same quarter last year times the trailing four-quarter YoY growth; net margin:
               the same quarter last year
"""
from __future__ import annotations

from typing import Dict, Sequence

import numpy as np
import pandas as pd

FLOOR = 1e-10
USABLE_AFTER_DAYS = 60


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


def expiry_week_flags(dates: Sequence) -> np.ndarray:
    """1 on the sessions of the week holding the month's F&O expiry (the last Thursday, or the session before it when
    that Thursday is shut), else 0. Computed from the session list itself (known ahead from the exchange calendar)."""
    d = pd.to_datetime(pd.Series(list(dates)))
    flags = np.zeros(len(d))
    for _, g in d.groupby([d.dt.year, d.dt.month]):
        last = pd.Timestamp(g.iloc[-1].year, g.iloc[-1].month, 1) + pd.offsets.MonthEnd(0)
        while last.weekday() != 3:
            last -= pd.Timedelta(days=1)
        if not (g <= last).any():
            continue
        exp = g[g <= last].max()
        wk = exp - pd.Timedelta(days=exp.weekday())
        flags[g[(g >= wk) & (g <= exp)].index] = 1
    return flags


def calendar_covariates(dates: Sequence) -> np.ndarray:
    """(3, n): day of week (0-4), last session of the month (0/1), expiry week (0/1)."""
    d = pd.to_datetime(pd.Series(list(dates)))
    month_end = (d.dt.month != d.shift(-1).dt.month).astype(float).to_numpy(copy=True)
    month_end[-1] = 0.0                   # unknown at the end of the series; never inside a scored horizon's last row
    return np.vstack([d.dt.weekday.to_numpy(float), month_end, expiry_week_flags(dates)])


def turnover_target(lt: np.ndarray, idx: np.ndarray, h: int = 5) -> np.ndarray:
    """ln of the mean daily turnover over t+1..t+h (sessions without trade skipped)."""
    lev = np.exp(np.asarray(lt, float))
    return np.array([np.log(np.nanmean(lev[t + 1:t + 1 + h])) if np.isfinite(lev[t + 1:t + 1 + h]).any() else np.nan
                     for t in idx])


def turnover_baselines(lt: np.ndarray, cov: np.ndarray, idx: np.ndarray, dev_mask_idx: np.ndarray,
                       h: int = 5) -> Dict[str, np.ndarray]:
    """20-session mean of ln turnover; HAR on ln turnover (1, 5, 22) with the calendar of the next h sessions."""
    s = pd.Series(lt).ffill()
    m20 = s.rolling(20, min_periods=15).mean().to_numpy()
    fut_dow = np.array([np.mean(cov[0, t + 1:t + 1 + h]) for t in idx])
    fut_me = np.array([np.max(cov[1, t + 1:t + 1 + h]) for t in idx])
    fut_ex = np.array([np.mean(cov[2, t + 1:t + 1 + h]) for t in idx])
    X = np.column_stack([np.ones(len(idx)), s.to_numpy()[idx], s.rolling(5).mean().to_numpy()[idx],
                         s.rolling(22).mean().to_numpy()[idx], fut_dow, fut_me, fut_ex])
    y = turnover_target(lt, idx, h)
    ok = dev_mask_idx & np.isfinite(y) & np.isfinite(X).all(axis=1)
    beta, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
    return {"mean20": m20[idx], "har_cal": X @ beta}


def quarter_series(q: pd.DataFrame) -> pd.DataFrame:
    """One company's quarters -> quarter_end, ln_revenue, margin, usable_from (quarter end + 60 days); duplicates and
    non-positive revenue dropped."""
    d = q.dropna(subset=["revenue"]).copy()
    d = d[d["revenue"] > 0].sort_values("quarter_end").drop_duplicates("quarter_end", keep="last")
    d["ln_revenue"] = np.log(d["revenue"].astype(float))
    d["margin"] = d["net_profit"].astype(float) / d["revenue"].astype(float)
    d["usable_from"] = pd.to_datetime(d["quarter_end"]) + pd.Timedelta(days=USABLE_AFTER_DAYS)
    return d[["quarter_end", "ln_revenue", "margin", "usable_from"]].reset_index(drop=True)


def consecutive_tail(qe: Sequence, upto: int) -> int:
    """Start index of the unbroken run of quarters ending at position `upto` (quarters 3 months apart)."""
    qe = pd.to_datetime(pd.Series(list(qe)))
    s = upto
    while s > 0 and 80 <= (qe.iloc[s] - qe.iloc[s - 1]).days <= 100:
        s -= 1
    return s


def results_baselines(series: np.ndarray, qe: Sequence, target: str) -> Dict[str, np.ndarray]:
    """For each quarter i (with i-4 .. i-1 present and consecutive): same quarter last year; and, for ln revenue, that
    times the trailing four-quarter YoY growth (in logs: + mean of the last four YoY log changes)."""
    x = np.asarray(series, float)
    n = len(x)
    naive = np.full(n, np.nan)
    grow = np.full(n, np.nan)
    qd = pd.to_datetime(pd.Series(list(qe)))
    for i in range(1, n):
        if not 80 <= (qd.iloc[i] - qd.iloc[i - 1]).days <= 100:
            continue                                  # quarter i does not follow i-1: no forecast for it
        s = consecutive_tail(qe, i - 1)
        if i - 4 < s:
            continue
        naive[i] = x[i - 4]
        if i - 8 >= s:
            yoy = x[i - 4:i] - x[i - 8:i - 4]
            grow[i] = x[i - 4] + (yoy.mean() if target == "ln_revenue" else 0.0)
    return {"same_q_last_year": naive, "with_trailing_growth": grow}
