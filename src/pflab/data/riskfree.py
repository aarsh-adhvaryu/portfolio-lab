"""The risk-free (cash) rate, from the market itself (S64 Phase 2a). Layer: tool (code only).

No Indian short-rate series is on FRED any more, so the cash rate is read from the near-month NIFTY future at each
month-end (the S39 method): a future prices spot grown at the cash rate less the dividends paid until it expires,

    F = S * exp((r - q) * T)      so      r  ~=  (F / S - 1) / T  +  q

with T in years from the future's days to expiry and q the Nifty 50 dividend yield that day (data/indices valuation
file, a percent). Each month is labelled "estimate (futures carry)". A month with no usable future, or an implausible
rate (outside 0-15%), falls back to ASSUMED (6.5%) and is labelled "assumed". Point in time: a month-end uses its own
file, the spot close and the dividend yield dated on or before it.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

from pflab.data import data_dir

ASSUMED = 0.065
ESTIMATE_LABEL = "estimate (futures carry)"
ASSUMED_LABEL = "assumed"
MIN_DAYS = 5                    # a contract about to expire carries almost no premium and a noisy one
BOUNDS = (0.0, 0.15)
MAX_STALE_DAYS = 7              # the dividend yield / spot may be this old at a month-end


def implied_rate(futures: pd.DataFrame, spot: float, div_yield_pct: float, on: date, min_days: int = MIN_DAYS) -> Optional[float]:
    """The cash rate one day's NIFTY futures rows imply, or None. `futures`: expiry, close (index futures, symbol NIFTY)."""
    f = futures.copy()
    f["days"] = (pd.to_datetime(f["expiry"]) - pd.Timestamp(on)).dt.days
    f = f[(f["days"] >= min_days) & (f["close"] > 0)].sort_values("days")
    if f.empty or not spot or spot <= 0:
        return None
    row = f.iloc[0]
    t = row["days"] / 365.0
    return float((row["close"] / spot - 1.0) / t + div_yield_pct / 100.0)


def _asof(s: pd.Series, d: date) -> Optional[float]:
    s = s[s.index <= pd.Timestamp(d)]
    if s.empty or (pd.Timestamp(d) - s.index[-1]).days > MAX_STALE_DAYS:
        return None
    return float(s.iloc[-1])


def monthly_table(root: Optional[Path] = None) -> pd.DataFrame:
    """Per month-end (index: date): rate (annual, decimal) and label."""
    from pflab.data import fo_bhavcopy, indices
    root = root or data_dir()
    fo = fo_bhavcopy.load(root)
    if fo.empty:
        return pd.DataFrame(columns=["rate", "label"])
    fo = fo[(fo["kind"] == "index") & (fo["symbol"] == "NIFTY")]
    px = indices.load("NIFTY50_PRICE", root)
    spot = px.assign(date=pd.to_datetime(px["date"])).set_index("date")["close"].sort_index()
    val = indices.load("NIFTY50_VALUATION", root)
    dy = val.assign(date=pd.to_datetime(val["date"])).set_index("date")["div_yield"].sort_index()
    rows = {}
    for d, g in fo.groupby("date"):
        r = None
        s, q = _asof(spot, d), _asof(dy, d)
        if s is not None:
            r = implied_rate(g, s, q if q is not None else 0.0, d)
        if r is not None and BOUNDS[0] <= r <= BOUNDS[1]:
            rows[d] = (r, ESTIMATE_LABEL)
        else:
            rows[d] = (ASSUMED, ASSUMED_LABEL)
    out = pd.DataFrame.from_dict(rows, orient="index", columns=["rate", "label"]).sort_index()
    out.index = pd.to_datetime(out.index)
    return out


def monthly(root: Optional[Path] = None) -> pd.Series:
    """The annual cash rate at each month-end (decimal), index = month-end dates."""
    return monthly_table(root)["rate"].rename("rf")


def at(table: pd.DataFrame, d: date) -> tuple:
    """(rate, label) as known on `d`: the median of the last three month-ends on or before it (one month's basis is
    noisy: 5% to 10% in neighbouring months); ASSUMED when there is none. The label is the latest month's."""
    t = table[table.index <= pd.Timestamp(d)]
    if t.empty:
        return ASSUMED, ASSUMED_LABEL
    return float(t["rate"].iloc[-3:].median()), str(t["label"].iloc[-1])
