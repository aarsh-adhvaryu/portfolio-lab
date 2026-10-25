"""S52: TimesFM done properly (docs/research/timesfm2_protocol.md, amendments in the same file).

Main-venv side: market data and the daily variance proxy, targets, baselines, losses, pooled tests and the registered
decision rules. TimesFM runs in `.venv-train` (tools/timesfm2_forecast.py, tools/timesfm2_finetune.py) and hands back
decile arrays aligned to the forecast dates written here. Point in time throughout: a value at index t uses rows up to
t; a target at t uses t+1.. only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from pflab.quant import vol_study as vs

H = 10
DECILES = np.round(np.arange(1, 10) / 10, 1)
SEED = 20261020
FLOOR = 1e-10
LOG_FLOOR = 1e-8
MIN_HISTORY = 512                        # sessions before a market's first forecast date
PERIODS = {"dev": ("2005-01-01", "2014-12-31"), "val": ("2015-01-01", "2019-12-31"),
           "desc": ("2020-01-01", "2021-12-31"), "holdout": ("2026-01-01", "2099-12-31")}
SPENT = ("2022-01-01", "2025-12-31")     # CLAUDE.md rule 2: never scored
FOLD_A = ("US_SP500", "DE_DAX", "JP_NIKKEI225", "HK_HANGSENG", "AU_ASX200")
FOLD_B = ("UK_FTSE100", "KR_KOSPI", "TW_TAIEX", "CN_SHANGHAI", "BR_BOVESPA")
MARKETS = FOLD_A + FOLD_B
VIX_SAME_DAY = ("US_SP500", "BR_BOVESPA")  # close with or after New York: same session's US VIX; others: the previous
RANGE_H = (63, 126, 252)
RANGE_STEP = 5


def fold_of(market: str) -> str:
    return "A" if market in FOLD_A else "B" if market in FOLD_B else "-"


# --- data ------------------------------------------------------------------------------------------------------------

def market_frame(path: Path) -> pd.DataFrame:
    """date, open, high, low, close; sessions with a missing or non-positive close dropped."""
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df[np.isfinite(df["close"]) & (df["close"] > 0)].sort_values("date").drop_duplicates("date", keep="last")
    return df[["date", "open", "high", "low", "close"]].reset_index(drop=True)


def variance_proxy(df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:
    """(r, v): close-to-close log returns and the daily variance proxy. v = Garman-Klass (intraday) plus the overnight
    term where the bar is coherent (H > L, H >= max(O, C), L <= min(O, C), O > 0), else r^2. Row 0 is NaN."""
    o, h, l, c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    r = np.full(len(c), np.nan)
    r[1:] = np.log(c[1:] / c[:-1])
    with np.errstate(divide="ignore", invalid="ignore"):
        ok = (h > l) & (h >= np.maximum(o, c)) & (l <= np.minimum(o, c)) & (o > 0) & np.isfinite(o + h + l)
        gk = 0.5 * np.log(h / l) ** 2 - (2 * np.log(2) - 1) * np.log(c / o) ** 2
        on = np.full(len(c), np.nan)
        on[1:] = np.log(o[1:] / c[:-1]) ** 2
        v = np.where(ok & np.isfinite(on), gk + on, r ** 2)
    v[0] = np.nan
    return r, v


def input_series(v: np.ndarray, kind: str) -> np.ndarray:
    """'log': ln v_t; 'log5': ln of the 5-session trailing mean of v (smoother). Floored before the log."""
    if kind == "log":
        x = v
    elif kind == "log5":
        x = pd.Series(v).rolling(5, min_periods=5).mean().to_numpy()
    else:
        raise ValueError(kind)
    return np.log(np.maximum(x, LOG_FLOOR))


def period_of(d) -> Optional[str]:
    s = str(d)[:10]
    if SPENT[0] <= s <= SPENT[1]:
        return None
    for k, (a, b) in PERIODS.items():
        if a <= s <= b:
            return k
    return None


def forecast_index(dates: Sequence, h: int, step: int = 1, min_history: int = MIN_HISTORY) -> np.ndarray:
    """Forecast dates: in a scored or described period (never the spent years), at least `min_history` sessions of
    history, a full horizon after. `step` thins the dates (every 5th session for the long ranges)."""
    n = len(dates)
    idx = [t for t in range(min_history, n - h) if period_of(dates[t]) is not None]
    return np.asarray(idx[::step], dtype=int)


def aligned_vix(dates: Sequence, vix: pd.DataFrame, same_day: bool) -> np.ndarray:
    """ln US VIX known at each market close: the last VIX close dated on or before (same_day) or strictly before
    (otherwise) the market's session date."""
    vd = pd.to_datetime(pd.Series(vix["date"])).to_numpy()
    vc = np.log(vix["close"].to_numpy(float))
    md = pd.to_datetime(pd.Series(list(dates))).to_numpy()
    pos = np.searchsorted(vd, md, side="right" if same_day else "left") - 1
    out = np.where(pos >= 0, vc[np.clip(pos, 0, None)], np.nan)
    return out


# --- Q1 volatility -------------------------------------------------------------------------------------------------

def rv_from_deciles(q: np.ndarray) -> np.ndarray:
    """q: (n, h, 9) deciles of the log-variance path -> E[mean variance over the horizon], approximated by the average
    of exp over the nine deciles (the mean of a right-skewed variable, not its median)."""
    q = np.asarray(q, float)
    return np.maximum(np.exp(q).mean(axis=2).mean(axis=1), FLOOR)


def fit_scale(rv: np.ndarray, f: np.ndarray, mask: np.ndarray) -> float:
    """QLIKE-optimal multiplier on development: mean(RV / F)."""
    ok = mask & np.isfinite(rv) & np.isfinite(f) & (f > 0)
    return float(np.mean(rv[ok] / f[ok]))


def _log_har_X(lv: np.ndarray, extra: Optional[List[np.ndarray]] = None) -> np.ndarray:
    s = pd.Series(lv)
    cols = [np.ones(len(lv)), lv, s.rolling(5).mean().to_numpy(), s.rolling(22).mean().to_numpy()]
    return np.column_stack(cols + list(extra or []))


def log_reg_fit(X: np.ndarray, y_level: np.ndarray, mask: np.ndarray) -> Tuple[np.ndarray, float]:
    """OLS of ln y on X over `mask`; returns (beta, residual variance) for the back-transform exp(fit + s2/2)."""
    y = np.log(np.maximum(y_level, FLOOR))
    ok = mask & np.isfinite(y) & np.isfinite(X).all(axis=1)
    beta, *_ = np.linalg.lstsq(X[ok], y[ok], rcond=None)
    res = y[ok] - X[ok] @ beta
    return beta, float(res.var(ddof=X.shape[1]))


def log_reg_forecast(X: np.ndarray, beta: np.ndarray, s2: float) -> np.ndarray:
    return np.maximum(np.exp(X @ beta + s2 / 2), FLOOR)


def har_log_v(v: np.ndarray, rv: np.ndarray, dev: np.ndarray) -> np.ndarray:
    """Baseline: HAR on ln v (1, 5, 22 sessions), fitted on development, back-transformed."""
    X = _log_har_X(np.log(np.maximum(v, LOG_FLOOR)))
    beta, s2 = log_reg_fit(X, rv, dev)
    return log_reg_forecast(X, beta, s2)


def combination(v: np.ndarray, f_tfm: np.ndarray, rv: np.ndarray, dev: np.ndarray,
                lnvix: Optional[np.ndarray] = None) -> np.ndarray:
    """Candidate C: HAR on ln v plus ln F (the fine-tuned model from the other fold) and ln VIX where there is one."""
    extra = [np.log(np.maximum(f_tfm, FLOOR))] + ([lnvix] if lnvix is not None else [])
    X = _log_har_X(np.log(np.maximum(v, LOG_FLOOR)), extra)
    beta, s2 = log_reg_fit(X, rv, dev)
    return log_reg_forecast(X, beta, s2)


def baselines_q1(r: np.ndarray, v: np.ndarray, dev: np.ndarray) -> Dict[str, np.ndarray]:
    rz = np.nan_to_num(r)                    # row 0 has no return; a NaN would spread through target_rv's cumulative sum
    rv = vs.target_rv(rz)
    return {"ewma094": vs.ewma(rz), "har_r2": vs.har_forecast(rz, vs.har_fit(rz, dev)), "har_logv": har_log_v(v, rv, dev)}


def pooled_dm(rows: Iterable[Tuple[Sequence, np.ndarray, np.ndarray]], lag: int = H - 1) -> dict:
    """Diebold-Mariano on d_t = mean over the markets open on date t of (loss_b - loss_a); H1: a has the lower loss.
    `rows`: (dates, loss_a, loss_b) per market."""
    parts = []
    for dates, la, lb in rows:
        d = np.asarray(lb, float) - np.asarray(la, float)
        ok = np.isfinite(d)
        parts.append(pd.Series(d[ok], index=pd.to_datetime(pd.Series(list(dates))[ok].to_numpy())))
    if not parts:
        return {"mean_diff": float("nan"), "t": float("nan"), "p": float("nan"), "n": 0}
    s = pd.concat(parts).groupby(level=0).mean().sort_index()
    return vs.dm_one_sided(np.zeros(len(s)), s.to_numpy(), lag=lag)


# --- Q2 fall chance ---------------------------------------------------------------------------------------------------

def fall_chance(var_path: np.ndarray, threshold: float = vs.FALL) -> np.ndarray:
    """1 - prod_h (1 - Phi(threshold / s_h)) for a (n, h) path of daily variances."""
    from scipy.stats import norm
    s = np.sqrt(np.maximum(np.asarray(var_path, float), FLOOR))
    p = norm.cdf(threshold / s)
    return 1 - np.prod(1 - p, axis=1)


def var_path_from_deciles(q: np.ndarray, scale: float = 1.0) -> np.ndarray:
    """(n, h, 9) log-variance deciles -> (n, h) expected daily variance, times the development scale."""
    return np.exp(np.asarray(q, float)).mean(axis=2) * scale


def pooled_auc(scores: Sequence[np.ndarray], events: Sequence[np.ndarray]) -> float:
    s = np.concatenate([np.asarray(x, float) for x in scores])
    e = np.concatenate([np.asarray(x, float) for x in events])
    return vs.auc(s, e)


def pooled_auc_diff_bootstrap(a: Sequence[np.ndarray], b: Sequence[np.ndarray], e: Sequence[np.ndarray],
                              block: int = 20, reps: int = 2000, seed: int = SEED) -> dict:
    """Pooled AUC(a) - AUC(b); one-sided p (H1: a better) from moving blocks drawn within each market."""
    rng = np.random.default_rng(seed)
    clean = []
    for x, y, z in zip(a, b, e):
        ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
        clean.append((np.asarray(x)[ok], np.asarray(y)[ok], np.asarray(z)[ok]))
    diff = pooled_auc([c[0] for c in clean], [c[2] for c in clean]) - pooled_auc([c[1] for c in clean], [c[2] for c in clean])
    out = []
    for _ in range(reps):
        sa, sb, se = [], [], []
        for x, y, z in clean:
            n = len(z)
            if n == 0:
                continue
            st = rng.integers(0, max(1, n - block + 1), size=n // block + 1)
            idx = np.concatenate([np.arange(s, min(s + block, n)) for s in st])[:n]
            sa.append(x[idx]), sb.append(y[idx]), se.append(z[idx])
        d = pooled_auc(sa, se) - pooled_auc(sb, se)
        if np.isfinite(d):
            out.append(d)
    out = np.asarray(out)
    return {"diff": float(diff), "p": float((out <= 0).mean()) if len(out) else float("nan"), "reps": int(len(out))}


# --- Q3/Q4 ranges and the 12-month return ---------------------------------------------------------------------------------

def target_cumret(lnc: np.ndarray, idx: np.ndarray, h: int) -> np.ndarray:
    return np.asarray(lnc, float)[idx + h] - np.asarray(lnc, float)[idx]


def pinball(y: np.ndarray, q: np.ndarray, levels: np.ndarray = DECILES) -> np.ndarray:
    """Mean pinball loss over the levels, per row. q: (n, len(levels))."""
    y = np.asarray(y, float)[:, None]
    u = y - np.asarray(q, float)
    return np.mean(np.maximum(levels * u, (levels - 1) * u), axis=1)


def coverage(y: np.ndarray, q: np.ndarray) -> float:
    """Share of outcomes inside the 10-90 band."""
    ok = np.isfinite(y) & np.isfinite(q).all(axis=1)
    return float(np.mean((y[ok] >= q[ok, 0]) & (y[ok] <= q[ok, -1])))


def range_bootstrap(lnc: np.ndarray, idx: np.ndarray, h: int) -> np.ndarray:
    """Baseline (a): deciles of the market's own past h-session log returns completed by t (the Monte Carlo's way)."""
    lnc = np.asarray(lnc, float)
    out = np.full((len(idx), 9), np.nan)
    for i, t in enumerate(idx):
        past = lnc[h:t + 1] - lnc[:t + 1 - h]
        if len(past) >= 2 * h:
            out[i] = np.quantile(past, DECILES)
    return out


def range_normal(r: np.ndarray, idx: np.ndarray, h: int, sd: str) -> np.ndarray:
    """Baselines (b) sd='ewma' and (c) sd='expanding': normal with the expanding mean daily log return x h."""
    from scipy.stats import norm
    rz = np.nan_to_num(np.asarray(r, float))
    mean = pd.Series(rz).expanding(min_periods=250).mean().to_numpy()
    if sd == "ewma":
        sig = np.sqrt(vs.ewma(rz))
    else:
        sig = pd.Series(rz).expanding(min_periods=250).std().to_numpy()
    z = norm.ppf(DECILES)
    return (mean[idx] * h)[:, None] + (sig[idx] * np.sqrt(h))[:, None] * z[None, :]


def oos_r2(y: np.ndarray, f: np.ndarray, bench: np.ndarray) -> float:
    ok = np.isfinite(y) & np.isfinite(f) & np.isfinite(bench)
    return float(1 - np.sum((y[ok] - f[ok]) ** 2) / np.sum((y[ok] - bench[ok]) ** 2))


def clark_west_pooled(rows: Iterable[Tuple[Sequence, np.ndarray, np.ndarray, np.ndarray]], lag: int) -> dict:
    """Clark-West adjusted MSPE test (H1: the model beats the benchmark), on the per-date mean over markets of
    f_t = (y - b)^2 - [(y - m)^2 - (b - m)^2]. `rows`: (dates, y, model, bench)."""
    import statsmodels.api as sm
    from scipy.stats import norm
    parts = []
    for dates, y, m, b in rows:
        f = (y - b) ** 2 - ((y - m) ** 2 - (b - m) ** 2)
        ok = np.isfinite(f)
        parts.append(pd.Series(f[ok], index=pd.to_datetime(pd.Series(list(dates))[ok].to_numpy())))
    s = pd.concat(parts).groupby(level=0).mean().sort_index().to_numpy()
    fit = sm.OLS(s, np.ones(len(s))).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    t = float(fit.tvalues[0])
    return {"t": t, "p": float(1 - norm.cdf(t)), "n": int(len(s))}


def expanding_mean_return(r: np.ndarray, idx: np.ndarray, h: int) -> np.ndarray:
    rz = np.nan_to_num(np.asarray(r, float))
    return pd.Series(rz).expanding(min_periods=250).mean().to_numpy()[idx] * h


# --- Q5 turnover ---------------------------------------------------------------------------------------------------------

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


def turnover_from_deciles(q: np.ndarray) -> np.ndarray:
    """(n, h, 9) deciles of daily ln turnover -> ln of the expected mean turnover over the horizon."""
    return np.log(np.exp(np.asarray(q, float)).mean(axis=2).mean(axis=1))


# --- Q6 results -----------------------------------------------------------------------------------------------------------

USABLE_AFTER_DAYS = 60


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


def company_t(diffs: Dict[str, np.ndarray]) -> dict:
    """One-sided t across companies of their mean loss difference (baseline - model; H1: model better)."""
    from scipy.stats import t as tdist
    m = np.array([np.nanmean(d) for d in diffs.values() if np.isfinite(d).any()])
    if len(m) < 3:
        return {"t": float("nan"), "p": float("nan"), "n": int(len(m)), "share_better": float("nan")}
    t = m.mean() / (m.std(ddof=1) / np.sqrt(len(m)))
    return {"t": float(t), "p": float(1 - tdist.cdf(t, len(m) - 1)), "n": int(len(m)),
            "share_better": float((m > 0).mean())}
