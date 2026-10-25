"""S52 inputs (docs/research/timesfm2_protocol.md): one .npz per market / stock and one table of quarters, written to
PFLAB_DATA_DIR/research/timesfm2/inputs for tools/timesfm2_forecast.py (.venv-train) and the evaluation. Point in time:
every array is indexed by session; forecast indices leave a full horizon after them.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from pflab.quant import tfm2 as tf

CONTEXT_FROM = "2000-01-01"
Q5_N, Q5_COVER = 200, 0.90
Q5_COVER_FROM, Q5_COVER_TO = "2008-01-01", "2019-12-31"
Q6_MIN_RUN = 8


def _str_dates(d) -> np.ndarray:
    return np.array([str(x)[:10] for x in d])


def q1_arrays(df: pd.DataFrame, vix: Optional[pd.DataFrame], same_day: bool, fold: str) -> Dict[str, np.ndarray]:
    df = df[df["date"].astype(str) >= CONTEXT_FROM].reset_index(drop=True)
    r, v = tf.variance_proxy(df)
    dates = df["date"].to_numpy()
    lnvix = tf.aligned_vix(dates, vix, same_day) if vix is not None else np.full(len(df), np.nan)
    return {"dates": _str_dates(dates), "r": r, "v": v, "x_log": tf.input_series(v, "log"),
            "x_log5": tf.input_series(v, "log5"), "lnvix": lnvix, "idx": tf.forecast_index(dates, tf.H),
            "fold": np.array(fold)}


def q3_arrays(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    df = df[df["date"].astype(str) >= CONTEXT_FROM].reset_index(drop=True)
    dates = df["date"].to_numpy()
    return {"dates": _str_dates(dates), "lnc": np.log(df["close"].to_numpy(float)),
            "idx": tf.forecast_index(dates, min(tf.RANGE_H), step=tf.RANGE_STEP)}


def q5_pick(turnover: pd.DataFrame, members: list, seed: int = tf.SEED) -> list:
    """`turnover`: date x isin (rupees). Members with turnover on >= 90% of 2008-2019 sessions; 200 drawn."""
    span = turnover.loc[(turnover.index.astype(str) >= Q5_COVER_FROM) & (turnover.index.astype(str) <= Q5_COVER_TO)]
    cover = (span[[m for m in members if m in span.columns]] > 0).mean()
    ok = sorted(cover[cover >= Q5_COVER].index)
    rng = np.random.default_rng(seed)
    return sorted(rng.choice(ok, size=min(Q5_N, len(ok)), replace=False).tolist())


def q5_arrays(series: pd.Series) -> Dict[str, np.ndarray]:
    """One stock's daily turnover (index: session dates, all market sessions; NaN or 0 where it did not trade)."""
    s = series.sort_index()
    dates = s.index.to_numpy()
    lt = np.log(s.where(s > 0).to_numpy(float))
    idx = tf.forecast_index(dates, 5, step=5)
    idx = idx[_str_dates(dates[idx]) >= "2008-01-01"]
    return {"dates": _str_dates(dates), "lt": lt, "cov": tf.calendar_covariates(dates), "idx": idx}


def q6_table(quarters: Dict[str, pd.DataFrame]) -> Dict[str, np.ndarray]:
    """`quarters`: scrip -> pit.load_history frame. Rows stacked by scrip, then quarter; for each row i, run_start is the
    first row of the unbroken run of quarters ending at i-1, and the row is forecastable when that run has at least 8
    quarters and quarter i follows i-1."""
    parts = []
    for sc, q in sorted(quarters.items()):
        s = tf.quarter_series(q)
        if len(s) < Q6_MIN_RUN + 1:
            continue
        s.insert(0, "scrip", str(sc))
        for target in ("ln_revenue", "margin"):
            b = tf.results_baselines(s[target].to_numpy(), s["quarter_end"], target)
            for k, v in b.items():
                s[f"base_{target}_{k}"] = v
        parts.append(s)
    t = pd.concat(parts, ignore_index=True)
    n = len(t)
    run_start = np.zeros(n, int)
    fc = np.zeros(n, bool)
    qe = pd.to_datetime(t["quarter_end"])
    for i in range(n):
        if i == 0 or t["scrip"].iat[i] != t["scrip"].iat[i - 1]:
            run_start[i] = i
            continue
        gap = (qe.iat[i] - qe.iat[i - 1]).days
        j = i - 1
        while j > 0 and t["scrip"].iat[j - 1] == t["scrip"].iat[i] and 80 <= (qe.iat[j] - qe.iat[j - 1]).days <= 100:
            j -= 1
        run_start[i] = j
        fc[i] = 80 <= gap <= 100 and (i - j) >= Q6_MIN_RUN and np.isfinite(t["ln_revenue"].iat[i])
    out = {"scrip": t["scrip"].to_numpy().astype(str), "quarter_end": _str_dates(t["quarter_end"]),
           "ln_revenue": t["ln_revenue"].to_numpy(float), "margin": t["margin"].to_numpy(float),
           "run_start": run_start, "forecastable": fc,
           "fold": np.array(["A" if int(s) % 2 == 0 else "B" for s in t["scrip"]])}
    for c in t.columns:
        if c.startswith("base_"):
            out[c] = t[c].to_numpy(float)
    return out
