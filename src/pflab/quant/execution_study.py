"""Split or limit-below-market vs buying at once (S45; docs/STUDIES.md).

For each month's first session t and each point-in-time Nifty 500 member, the price paid by each plan against the
benchmark A (all at the close of t), in basis points saved. Pure functions over a panel slice; `tools/split_study.py`
runs them on the real panel and applies the registered rule.
"""
from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

LIMITS = (0.005, 0.01, 0.02)
WINDOW = 5
PLANS = ("B5",) + tuple(f"L{x * 100:g}" for x in LIMITS)


def plan_prices(prev_close: float, o: Sequence[float], low: Sequence[float], c: Sequence[float]) -> Dict[str, float]:
    """Prices of every plan for one stock and one month: o/low/c are sessions t .. t+4 (adjusted)."""
    out = {"A": c[0], "B5": float(np.mean(c[:WINDOW]))}
    for x in LIMITS:
        lim = prev_close * (1 - x)
        px = c[WINDOW - 1]                                      # never filled: all at the close of t+4
        for k in range(WINDOW):
            if o[k] <= lim:
                px = o[k]
                break
            if low[k] <= lim:
                px = lim
                break
        out[f"L{x * 100:g}"] = px
    return out


def savings(panel: pd.DataFrame, members: pd.DataFrame, months: Sequence[pd.Timestamp]) -> pd.DataFrame:
    """One row per (month, isin): bps saved by each plan against A. `panel`: date, isin, open, low, close,
    adj_factor (one row per session); `members`: isin, from_date, to_date."""
    p = panel.sort_values(["isin", "date"]).copy()
    for k in ("open", "low", "close"):
        p[k] = p[k] * p["adj_factor"]
    p["prev"] = p.groupby("isin")["close"].shift(1)
    sessions = np.array(sorted(p["date"].unique()))
    rows: List[dict] = []
    for m in months:
        i = np.searchsorted(sessions, np.datetime64(m))
        if i + WINDOW > len(sessions):
            continue
        t, last = sessions[i], sessions[i + WINDOW - 1]
        live = set(members[(members["from_date"] <= t) & (members["to_date"] > t)]["isin"])
        w = p[(p["date"] >= t) & (p["date"] <= last) & p["isin"].isin(live)]
        for isin, g in w.groupby("isin"):
            if len(g) < WINDOW or g["date"].iloc[0] != t or not np.isfinite(g["prev"].iloc[0]) or g["prev"].iloc[0] <= 0:
                continue
            pp = plan_prices(g["prev"].iloc[0], g["open"].to_numpy(), g["low"].to_numpy(), g["close"].to_numpy())
            rows.append({"month": pd.Timestamp(t), "isin": isin,
                         **{k: (pp["A"] - pp[k]) / pp["A"] * 1e4 for k in PLANS}})
    return pd.DataFrame(rows, columns=["month", "isin", *PLANS])


def summarise(sv: pd.DataFrame) -> Dict[str, dict]:
    """Mean monthly saving (bps) and its t-statistic per plan."""
    mm = sv.groupby("month")[list(PLANS)].mean()
    out = {}
    for k in PLANS:
        x = mm[k].dropna()
        sd = x.std(ddof=1)
        out[k] = {"mean_bps": float(x.mean()), "t": float(x.mean() / (sd / np.sqrt(len(x)))) if len(x) > 1 and sd > 0
                  else 0.0, "months": int(len(x)), "share_better": float((sv[k] > 0).mean())}
    return out


def decide(dev: Dict[str, dict], val: Dict[str, dict], min_bps: float = 10.0, min_t: float = 2.0) -> dict:
    best = max(PLANS, key=lambda k: dev[k]["mean_bps"])
    ok = val[best]["mean_bps"] >= min_bps and val[best]["t"] >= min_t
    return {"chosen_on_dev": best, "validation": val[best], "adopted": best if ok else None}
