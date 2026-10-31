"""IPO sell-or-hold policies on listing history (S68): a CALCULATION on historical data, trusted code, reproducible. Not a prediction about any one IPO.

For large main-board listings since 2016 (the panel's listing dates and prices; `plan/ipo.listing_table`), each policy's return per allotment from the
issue price, using only what is known at the moment of the decision:

    sell_open        sell at the listing-day open
    sell_close       sell at the listing-day close                      <- the baseline
    hold_5/20/60     hold from the listing-day close for that many sessions
    sell_half        sell half at the close, hold the rest 60 sessions
    rule_gain        sell at the close if the listing-day gain is above THRESHOLD, else hold 20 sessions (decided from the open and close only)

The history is split by listing date: development 2016-2019, validation 2020-2021. The period from 2022 is spent (the repo's rule) and is not loaded.
Under 20 listings in a period gives the count and no conclusion (the small-numbers rule). Returns are gross of costs and before tax; the short-term
gains tax is an estimate shown next to the result (rate from configs/tax_policy_in.toml). Listings are history of other companies: not a forecast of
this one, and the issue price is the exchange's listing base price.
"""
from __future__ import annotations

import math
from datetime import date
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

VERSION = "ipo_policy-1"
DEV = ("2016-01-01", "2019-12-31")
VAL = ("2020-01-01", "2021-12-31")
SPENT_FROM = date(2022, 1, 1)
MIN_N = 20
THRESHOLD = 0.15
POLICIES = ("sell_open", "sell_close", "hold_5", "hold_20", "hold_60", "sell_half", "rule_gain")
BASELINE = "sell_close"


def returns(t: pd.DataFrame) -> pd.DataFrame:
    """Per listing, each policy's return from the issue price. Needs gain_open, gain_close, r5, r20, r60 (from the listing-day close)."""
    out = pd.DataFrame({"isin": t["isin"], "date": pd.to_datetime(t["date"])})
    go, gc = t["gain_open"].astype(float), t["gain_close"].astype(float)
    hold = lambda k: (1 + gc) * (1 + t[f"r{k}"].astype(float)) - 1
    out["sell_open"], out["sell_close"] = go, gc
    for k in (5, 20, 60):
        out[f"hold_{k}"] = hold(k)
    out["sell_half"] = 0.5 * gc + 0.5 * hold(60)
    out["rule_gain"] = np.where(gc > THRESHOLD, gc, hold(20))
    return out


def _summ(x: pd.Series) -> dict:
    n = int(x.notna().sum())
    if n < MIN_N:
        return {"n": n, "note": f"only {n} listings: too few to say anything (need {MIN_N})"}
    return {"n": n, "mean": round(float(x.mean()), 4), "median": round(float(x.median()), 4), "share_positive": round(float((x > 0).mean()), 3),
            "p10": round(float(x.quantile(.1)), 4), "worst": round(float(x.min()), 4)}


def _vs_base(x: pd.Series, base: pd.Series) -> dict:
    d = (x - base).dropna()
    n = len(d)
    if n < MIN_N:
        return {"n": n}
    sd = float(d.std(ddof=1))
    return {"n": n, "mean_difference": round(float(d.mean()), 4), "t": round(float(d.mean() / (sd / math.sqrt(n))), 2) if sd > 0 else 0.0,
            "share_better": round(float((d > 0).mean()), 3)}


def run(t: pd.DataFrame, *, qty: Optional[int] = None, issue: Optional[float] = None, stcg: Optional[float] = None) -> dict:
    """The study over the listing table `t`. With an allotment (`qty`, `issue`) the rupee value of each policy's median outcome is added."""
    t = t.copy()
    t["date"] = pd.to_datetime(t["date"])
    t = t[t["date"] < pd.Timestamp(SPENT_FROM)]                      # the spent period is never read
    r = returns(t)
    periods = {"development": DEV, "validation": VAL}
    res: Dict[str, dict] = {}
    for name, (a, b) in periods.items():
        sub = r[(r["date"] >= a) & (r["date"] <= b)]
        res[name] = {"window": [a, b], "listings": int(len(sub)),
                     "policies": {p: {**_summ(sub[p]), "vs_baseline": _vs_base(sub[p], sub[BASELINE]) if p != BASELINE else None} for p in POLICIES}}
    verdict = []
    for p in POLICIES:
        if p == BASELINE:
            continue
        dv, vv = res["development"]["policies"][p]["vs_baseline"], res["validation"]["policies"][p]["vs_baseline"]
        if "t" not in dv or "t" not in vv:
            verdict.append({"policy": p, "reading": "too few listings in a period to say anything"})
        elif dv["mean_difference"] > 0 and vv["mean_difference"] > 0 and dv["t"] >= 2 and vv["t"] >= 1.65:
            verdict.append({"policy": p, "reading": f"ahead of {BASELINE} in both periods (t {dv['t']} / {vv['t']}); one study, not a rule",
                            "development": dv, "validation": vv})
        else:
            verdict.append({"policy": p, "reading": f"not reliably ahead of {BASELINE} (development {dv.get('mean_difference')}, validation {vv.get('mean_difference')})"})
    out = {"kind": "calculation", "version": VERSION, "baseline": BASELINE, "threshold_rule_gain": THRESHOLD, "periods": res, "verdict": verdict,
           "tests_in_this_study": len(POLICIES) - 1,
           "limits": ["large main-board listings since 2016 only; other companies' history, not a forecast of this one",
                      "gross of costs, before tax", f"the period from {SPENT_FROM:%Y} is spent and not used", "policy parameters were fixed before looking (no tuning)"]}
    if qty and issue:
        med = res["development"]["policies"]
        out["allotment_value_at_median_rs"] = {p: round(qty * issue * (1 + (med[p].get("median") or 0))) for p in POLICIES if "median" in med[p]}
        if stcg is not None:
            out["tax_note"] = f"a sale within a year is taxed as short-term gains at about {stcg:.0%} (estimate; configs/tax_policy_in.toml)"
    return out
