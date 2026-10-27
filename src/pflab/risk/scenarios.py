"""Scenario chains on the investor's portfolio (S64 Phase 5 item 6): oil, the rupee, a US crash.

A shock is the change of one factor in one month. Each holding responds through its own history: its 60-month beta to the factor
(direct), or factor -> Nifty 500 TRI -> holding through the CAPM beta (via_market). The result is a rupee impact per holding and
in total, with a range of +-2 standard errors (the holdings' errors added, which assumes they err together: the wide side).
Stock holdings use their own betas; index funds count as the Nifty 500. Gold, debt and cash are listed as not modelled.
"A description from historical betas, not a forecast": a beta is an average of calm and rough months and shocks of this size are
rare. Nothing here decides or places anything.
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from pflab import _toml

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "scenarios.toml"
WINDOW, MIN_MONTHS = 60, 36
LABEL = "from historical betas; a description, not a forecast"


def config(path: Optional[Path] = None) -> dict:
    return _toml.load(path or CONFIG)["scenario"]


def factor_returns(root, factor: str, asof: date) -> pd.Series:
    """Monthly percentage changes of the factor, months ended on or before `asof`."""
    from pflab.risk import capm
    if factor == "US_SP500":
        from pflab.data import global_markets
        d = global_markets.load("US_SP500", root)
        lvl = pd.Series(d["close"].to_numpy(float), index=pd.to_datetime(d["date"]))
    else:
        from pflab.data import macro
        d = macro.load(factor, root)
        lvl = pd.Series(d["value"].to_numpy(float), index=pd.to_datetime(d["date"]))
    lvl = lvl[lvl > 0]
    r = capm.monthly_returns(lvl)
    last_full = (pd.Timestamp(asof) + pd.offsets.MonthEnd(0)).normalize()
    if pd.Timestamp(asof).normalize() != last_full:
        r = r[r.index < last_full]
    return r[r.index <= pd.Timestamp(asof)]


def beta_se(y: pd.Series, x: pd.Series, window: int = WINDOW, min_months: int = MIN_MONTHS) -> Optional[tuple]:
    """(beta, standard error, months) of y on x over the last `window` common months, Newey-West; None under `min_months`."""
    import statsmodels.api as sm
    from pflab.risk.capm import hac_lags
    j = pd.concat([y.rename("y"), x.rename("x")], axis=1, join="inner").dropna().iloc[-window:]
    if len(j) < min_months or float(j["x"].std()) == 0.0:
        return None
    r = sm.OLS(j["y"].to_numpy(), sm.add_constant(j["x"].to_numpy())).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags(len(j))})
    return float(r.params[1]), float(r.bse[1]), int(len(j))


def holdings(con, asof: date) -> list:
    from pflab.pm import today
    pos = today.build(con, asof)["positions"]
    pos = pos[pos["value"].notna() & (pos["qty"] > 0)]
    return [{"isin": r.isin, "symbol": r.symbol, "bucket": r.bucket, "value": float(r.value)} for r in pos.itertuples()]


def run(con, root, asof: date, name: str, hold: Optional[list] = None, cfg: Optional[dict] = None) -> dict:
    from pflab.risk import capm
    sc = (cfg or config())[name]
    root = Path(root)
    f = factor_returns(root, sc["factor"], asof)
    shock = float(sc["shock"])
    hold = hold if hold is not None else holdings(con, asof)
    from pflab.data import indices
    mkt = capm.monthly_returns(capm._series(indices.load("NIFTY500_TRI", root)))
    mkt = mkt[mkt.index <= pd.Timestamp(asof)]
    mb = beta_se(mkt, f)                                   # the Nifty 500's own beta to the factor
    via = sc["path"] == "via_market"
    if via and mb is None:
        return {"scenario": name, "label": sc["label"], "error": "the Nifty 500 has too little history against this factor"}
    mshock = mb[0] * shock if mb else None
    rows, skipped = [], []
    for h in hold:
        if h["bucket"] not in ("equity", "equity_fund"):
            skipped.append({"symbol": h["symbol"], "bucket": h["bucket"], "value": h["value"]})
            continue
        if h["bucket"] == "equity_fund":                   # treated as the Nifty 500
            b, se, n, how = (1.0, 0.0, None, "index fund = Nifty 500") if via else (*(mb[:2] if mb else (None, None)), mb[2] if mb else None, "index fund = Nifty 500")
        elif via:
            c = capm.for_isin(root, h["isin"], asof)
            b, se, n, how = c.get("beta"), c.get("beta_se"), c.get("n"), "CAPM beta"
        else:
            got = beta_se(capm.stock_returns(root, h["isin"], asof), f)
            b, se, n, how = (got[0], got[1], got[2], f"60-month beta to {sc['factor']}") if got else (None, None, None, "too little history")
        if b is None:
            skipped.append({"symbol": h["symbol"], "bucket": h["bucket"], "value": h["value"], "why": how})
            continue
        if via:
            impact = h["value"] * b * mshock
            err = h["value"] * abs(b) * mb[1] * abs(shock)                 # the market leg's error; the stock's CAPM beta error is not added
        else:
            impact = h["value"] * b * shock
            err = h["value"] * (se or 0.0) * abs(shock)
        rows.append({"symbol": h["symbol"], "value": h["value"], "beta": b, "beta_se": se, "months": n, "how": how,
                     "impact": impact, "plus_minus": 2 * err})
    total = sum(r["impact"] for r in rows)
    spread = sum(r["plus_minus"] for r in rows)
    value = sum(r["value"] for r in rows)
    chain = (f"{sc['factor']} {shock:+.0%} -> Nifty 500 {mshock:+.1%} (its beta {mb[0]:.2f} +- {mb[1]:.2f}) -> each holding by its CAPM beta"
             if via else f"{sc['factor']} {shock:+.0%} -> each holding by its 60-month beta to it")
    return {"scenario": name, "label": sc["label"], "chain": chain, "asof": str(asof), "rows": sorted(rows, key=lambda r: r["impact"]),
            "total": total, "total_range": [total - spread, total + spread], "modelled_value": value,
            "total_pct_of_modelled": total / value if value else None,
            "not_modelled": skipped, "note": LABEL}


def run_all(con, root, asof: date) -> Dict[str, dict]:
    hold = holdings(con, asof)
    out = {}
    for name in config():
        try:
            out[name] = run(con, root, asof, name, hold)
        except Exception as e:                              # one missing series never hides the others
            out[name] = {"scenario": name, "error": f"{type(e).__name__}: {str(e)[:120]}"}
    return out
