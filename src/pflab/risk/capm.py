"""CAPM on monthly excess returns (S64 Phase 2b). Layer: tool (code only); the agents read its numbers, never make them.

    r_stock - rf  =  alpha + beta * (r_market - rf) + e          monthly, the last `window` months, OLS

Market = the Nifty 500 TRI; rf = the monthly cash rate (data/riskfree.py: futures carry, else assumed 6.5%), the rate
known at the start of each month. Standard errors are Newey-West (HAC), maxlags = floor(4 * (n / 100) ** (2 / 9)).
Point in time: a fit at `asof` uses only months that ended on or before it. A DESCRIPTION: an alpha that is not
different from zero (|t| < 2) is reported as such, and no edge acts unless a pre-registered study passed it
(CLAUDE.md rule 12).
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from pflab.data import data_dir

MIN_MONTHS, WINDOW = 36, 60
ERP_PERIOD = ("2005-01-01", "2021-12-31")
ERP_LABEL = "estimate (Nifty 500 TRI excess over the cash rate, 2005-2021)"


def hac_lags(n: int) -> int:
    return int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0)))


def month_end_levels(level: pd.Series) -> pd.Series:
    """Last observation of each calendar month, indexed by the month's period end."""
    s = level.dropna().sort_index()
    s.index = pd.DatetimeIndex(s.index)
    m = s.groupby(s.index.to_period("M")).last()
    m.index = m.index.to_timestamp("M").normalize()
    return m


def monthly_returns(level: pd.Series) -> pd.Series:
    m = month_end_levels(level)
    return (m / m.shift(1) - 1.0).dropna()


def monthly_rf(table: pd.DataFrame, months: pd.DatetimeIndex) -> pd.Series:
    """The monthly cash return for each month: the annual rate known at the previous month-end, over 12."""
    from pflab.data import riskfree
    out = {}
    for m in months:
        prev = (m - pd.offsets.MonthEnd(1)).date()
        out[m] = riskfree.at(table, prev)[0] / 12.0
    return pd.Series(out, dtype=float)


def fit(stock_r: pd.Series, market_r: pd.Series, rf: pd.Series, min_months: int = MIN_MONTHS, window: int = WINDOW) -> dict:
    """dict(beta, beta_se, alpha_ann, alpha_t, r2, n, resid_vol). All None (with a note) under `min_months`."""
    import statsmodels.api as sm
    j = pd.concat([stock_r.rename("s"), market_r.rename("m"), rf.rename("f")], axis=1, join="inner").dropna().iloc[-window:]
    n = len(j)
    none = {"beta": None, "beta_se": None, "alpha_ann": None, "alpha_t": None, "r2": None, "n": n, "resid_vol": None}
    if n < min_months:
        return {**none, "note": f"only {n} months of history, {min_months} needed"}
    y, x = j["s"] - j["f"], j["m"] - j["f"]
    if float(x.std()) == 0.0:
        return {**none, "note": "the market did not move"}
    res = sm.OLS(y.to_numpy(), sm.add_constant(x.to_numpy())).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags(n)})
    a, b = float(res.params[0]), float(res.params[1])
    return {"beta": b, "beta_se": float(res.bse[1]), "alpha_ann": a * 12.0, "alpha_t": float(res.tvalues[0]),
            "r2": float(res.rsquared), "n": n, "resid_vol": float(np.std(res.resid, ddof=2) * math.sqrt(12.0))}


def erp(root: Optional[Path] = None, table: Optional[pd.DataFrame] = None) -> float:
    """The market's excess mean over cash, annualised, Nifty 500 TRI over ERP_PERIOD (computed, labelled ERP_LABEL)."""
    from pflab.data import indices, riskfree
    root = root or data_dir()
    table = riskfree.monthly_table(root) if table is None else table
    mr = monthly_returns(_series(indices.load("NIFTY500_TRI", root)))
    mr = mr[(mr.index >= pd.Timestamp(ERP_PERIOD[0])) & (mr.index <= pd.Timestamp(ERP_PERIOD[1]))]
    ex = mr - monthly_rf(table, mr.index)
    return float(ex.mean() * 12.0)


def expected_return(beta: float, rf_now: float, erp_value: float) -> float:
    """CAPM expected annual return: rf + beta * ERP (an estimate; never a forecast of a month)."""
    return float(rf_now + beta * erp_value)


def _series(df: pd.DataFrame) -> pd.Series:
    return df.assign(date=pd.to_datetime(df["date"])).set_index("date")["close"].sort_index()


def market_returns(root: Path, asof: date) -> pd.Series:
    from pflab.data import indices
    r = monthly_returns(_series(indices.load("NIFTY500_TRI", root)))
    return r[r.index <= pd.Timestamp(asof)]


def stock_returns(root: Path, isin: str, asof: date, years: int = 12) -> pd.Series:
    """Monthly total returns of a stock (dividends in), up to the last full month ended on or before asof."""
    from pflab.learner import templates as tp
    start = str(pd.Timestamp(asof) - pd.Timedelta(days=int(365.25 * years)))[:10]
    w = tp.wide_panel(root, [isin], start, str(asof))
    if isin not in w["tr"].columns:
        return pd.Series(dtype=float)
    r = monthly_returns(w["tr"][isin])
    last_full = (pd.Timestamp(asof) + pd.offsets.MonthEnd(0)).normalize()
    if pd.Timestamp(asof).normalize() != last_full:           # a part month is not a month
        r = r[r.index < last_full]
    return r[r.index <= pd.Timestamp(asof)]


def for_isin(root: Path, isin: str, asof: date, table: Optional[pd.DataFrame] = None) -> dict:
    from pflab.data import riskfree
    table = riskfree.monthly_table(root) if table is None else table
    sr = stock_returns(root, isin, asof)
    mr = market_returns(root, asof)
    out = fit(sr, mr, monthly_rf(table, mr.index))
    rf_now, rf_label = riskfree.at(table, asof)
    out.update({"asof": str(asof), "rf_now": rf_now, "rf_label": rf_label, "market": "Nifty 500 TRI",
                "method": f"OLS on monthly excess returns, last {WINDOW} months, Newey-West"})
    return out


def rolling_beta(root: Path, isin: str, asof: date, window: int = 36, table: Optional[pd.DataFrame] = None) -> pd.Series:
    """The beta over each trailing `window` months (risk/shock_betas.rolling_betas on excess returns): a plot input."""
    from pflab.data import riskfree
    from pflab.risk import shock_betas
    table = riskfree.monthly_table(root) if table is None else table
    sr = stock_returns(root, isin, asof)
    mr = market_returns(root, asof)
    rf = monthly_rf(table, mr.index)
    j = pd.concat([sr.rename("s"), mr.rename("m"), rf.rename("f")], axis=1, join="inner").dropna()
    if len(j) < window:
        return pd.Series(dtype=float)
    b = shock_betas.rolling_betas((j[["s"]] - j[["f"]].to_numpy()), (j["m"] - j["f"]), window, min_obs=window)
    return b["s"].dropna()


def describe(f: dict) -> str:
    """One plain sentence from a fit (for the brain and the page)."""
    if f.get("beta") is None:
        return f.get("note", "no CAPM fit")
    s = f"beta {f['beta']:.2f} (se {f['beta_se']:.2f}) on {f['n']} months, R2 {f['r2']:.2f}; "
    if abs(f["alpha_t"]) < 2:
        return s + f"alpha {f['alpha_ann'] * 100:+.1f}% a year is not different from 0 (t {f['alpha_t']:+.1f})"
    return s + f"alpha {f['alpha_ann'] * 100:+.1f}% a year (t {f['alpha_t']:+.1f}): a description of the past, not a signal"


def portfolio(con, root: Path, asof: date, values: Optional[Dict[str, float]] = None) -> dict:
    """Holdings-weighted beta and alpha of the direct stocks. A name with no fit counts as market-like (beta 1, alpha 0)
    and is listed. `values`: isin -> rupees (default: today's equity positions from the ledger and prices)."""
    from pflab.data import riskfree
    if values is None:
        from pflab.pm import today
        pos = today.build(con, asof)["positions"]
        eq = {i for (i,) in con.execute("SELECT isin FROM instruments WHERE asset_class = 'equity'").fetchall()}
        pos = pos[pos["value"].notna() & (pos["qty"] > 0) & pos["isin"].isin(eq)]
        values = pos.groupby("isin")["value"].sum().to_dict()
    table = riskfree.monthly_table(root)
    tot = float(sum(v for v in values.values() if v > 0))
    if tot <= 0:
        return {"beta": None, "alpha_ann": None, "names": 0, "note": "no direct stock holdings"}
    beta = alpha = 0.0
    parts, unfit = [], []
    for isin, v in sorted(values.items(), key=lambda kv: -kv[1]):
        if v <= 0:
            continue
        f = for_isin(root, isin, asof, table)
        w = v / tot
        if f["beta"] is None:
            unfit.append(isin)
            beta += w
        else:
            beta += w * f["beta"]
            alpha += w * f["alpha_ann"]
        parts.append({"isin": isin, "weight": round(w, 4), "beta": f["beta"], "alpha_ann": f["alpha_ann"]})
    return {"beta": beta, "alpha_ann": alpha, "names": len(parts), "unfit": unfit, "parts": parts[:15],
            "label": "holdings-weighted CAPM description (Nifty 500 TRI, last 60 months); names without 36 months count as beta 1"}
