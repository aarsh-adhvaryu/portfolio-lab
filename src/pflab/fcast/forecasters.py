"""The code forecasters (S79 item 8). Each turns a close series into QUANTILES of the simple return over h sessions, at `protocol.LEVELS`.

Everything is vectorised and point in time: row t of a frame uses closes dated <= t only (rolling windows end at t; nothing is shifted backwards), so the
same function serves the live forecast (the last row of the series up to the session) and the history replay (every row). The constants are the
protocol's. Quantiles are normal in the log return: q = exp(mu + z * sigma_h) - 1, non-decreasing in the level by construction.
"""
from __future__ import annotations

from datetime import date
from typing import Callable, Dict, Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

from pflab.fcast import protocol as P

Z = np.array([norm.ppf(q) for q in P.LEVELS])


def _vol_parts(close: pd.Series):
    lc = np.log(close.astype(float))
    r = lc.diff()
    sig = r.rolling(P.SIGMA_WINDOW, min_periods=P.SIGMA_MIN).std()
    ew = (r ** 2).ewm(alpha=1 - P.EWMA_LAMBDA, adjust=False, min_periods=P.SIGMA_MIN).mean()
    return lc, r, sig, ew


def _frame(mu: pd.Series, sigma: pd.Series) -> pd.DataFrame:
    m, s = mu.to_numpy(float)[:, None], sigma.to_numpy(float)[:, None]
    return pd.DataFrame(np.exp(m + Z[None, :] * s) - 1.0, index=mu.index, columns=list(P.LEVELS))


def _sigma_h(sig: pd.Series, ew: pd.Series, h: int, naive: bool) -> pd.Series:
    if naive:
        return sig * np.sqrt(h)
    w = float(h) ** -0.5
    return np.sqrt(h * (w * ew + (1 - w) * sig ** 2))


def naive(close: pd.Series, h: int, **_) -> pd.DataFrame:
    lc, r, sig, ew = _vol_parts(close)
    return _frame(sig * 0.0, _sigma_h(sig, ew, h, True))


def volatility(close: pd.Series, h: int, **_) -> pd.DataFrame:
    lc, r, sig, ew = _vol_parts(close)
    return _frame(sig * 0.0, _sigma_h(sig, ew, h, False))


def momentum(close: pd.Series, h: int, **_) -> pd.DataFrame:
    lc, r, sig, ew = _vol_parts(close)
    s = _sigma_h(sig, ew, h, False)
    z = r.rolling(P.MOM_WINDOW, min_periods=P.MOM_WINDOW).sum() / (sig * np.sqrt(P.MOM_WINDOW))
    return _frame(P.TILT * s * np.tanh(z), s)


def reversion(close: pd.Series, h: int, **_) -> pd.DataFrame:
    lc, r, sig, ew = _vol_parts(close)
    s = _sigma_h(sig, ew, h, False)
    z = (lc - lc.rolling(P.REV_WINDOW, min_periods=P.REV_WINDOW).mean()) / (sig * np.sqrt(P.REV_WINDOW))
    return _frame(-P.TILT * s * np.tanh(z), s)


def _fresh_driver(local_dates: pd.DatetimeIndex, prior_dates: pd.DatetimeIndex, drv: pd.Series) -> np.ndarray:
    """For each local session date t_k, the log return of the latest driver-market session dated STRICTLY before t_k, kept only if that session is dated on or
    after the local session before it (a driver session already used for the earlier day is stale: no news, the cell is NaN)."""
    out = np.full(len(local_dates), np.nan)
    right = pd.DataFrame({"du": pd.DatetimeIndex(drv.index).astype("datetime64[ns]"), "ru": drv.values}).dropna().sort_values("du")
    ok = ~pd.isna(local_dates)
    if right.empty or not ok.any():
        return out
    left = pd.DataFrame({"d": pd.DatetimeIndex(local_dates[ok]).astype("datetime64[ns]"), "k": np.flatnonzero(ok)}).sort_values("d")
    m = pd.merge_asof(left, right, left_on="d", right_on="du", allow_exact_matches=False).sort_values("k")
    prior = prior_dates[m["k"].to_numpy()]
    fresh = (m["du"].to_numpy() >= prior.to_numpy()) & m["ru"].notna().to_numpy()
    vals = np.where(fresh, m["ru"].to_numpy(float), np.nan)
    out[m["k"].to_numpy()] = vals
    return out


def overnight(close: pd.Series, h: int, us_close: Optional[pd.Series] = None, next_date: Optional[date] = None, **_) -> pd.DataFrame:
    """The home index's return from the driver market's (US) last session before the target session, times a rolling beta. A pre-open forecast: the
    driver's close is known before the home open. `next_date` is the target session of the LAST row (the replay knows the others from the series)."""
    idx = pd.DatetimeIndex(close.index)
    nan = pd.DataFrame(np.nan, index=idx, columns=list(P.LEVELS))
    if us_close is None or len(us_close) < 30:
        return nan
    lc, r, sig, ew = _vol_parts(close)
    drv = np.log(us_close.astype(float)).diff()
    prior_dates = pd.DatetimeIndex(idx)
    # driver value that applied to each home session day j (for the regression): the session dated before j and not before j's previous session
    dates_prev = pd.DatetimeIndex([pd.NaT]).append(idx[:-1])
    drv_on = pd.Series(_fresh_driver(idx, dates_prev, drv), index=idx)
    # driver value for the NEXT home session of each row t (the target of the forecast made at close t)
    nxt = idx[1:].append(pd.DatetimeIndex([pd.Timestamp(next_date) if next_date is not None else pd.NaT]))
    # stale rule: the driver session must be dated on or after t itself
    dn = _fresh_driver(nxt, idx, drv)
    mu_drv = pd.Series(dn, index=idx)
    pair = pd.DataFrame({"r": r, "u": drv_on})
    cov = pair["r"].rolling(P.BETA_WINDOW, min_periods=P.BETA_MIN).cov(pair["u"])
    var_u = pair["u"].rolling(P.BETA_WINDOW, min_periods=P.BETA_MIN).var()
    var_r = pair["r"].rolling(P.BETA_WINDOW, min_periods=P.BETA_MIN).var()
    beta = cov / var_u
    rho2 = (cov ** 2 / (var_u * var_r)).clip(0, 0.95)
    w = float(h) ** -0.5
    var_d = w * ew + (1 - w) * sig ** 2
    sigma_h = np.sqrt((var_d * (h - rho2)).clip(lower=1e-12))
    mu = (beta * mu_drv.fillna(0.0))
    mu = mu.where(beta.notna())
    return _frame(mu, sigma_h)


def last_driver(close: pd.Series, us_close: Optional[pd.Series], next_date: date) -> Optional[float]:
    """The driver return (log, US) the overnight forecast of the last row uses for `next_date`; None if the driver session has not happened yet."""
    if us_close is None or len(us_close) < 2 or len(close) == 0:
        return None
    drv = np.log(us_close.astype(float)).diff()
    v = _fresh_driver(pd.DatetimeIndex([pd.Timestamp(next_date)]), pd.DatetimeIndex([close.index[-1]]), drv)[0]
    return None if not np.isfinite(v) else float(v)


FORECASTERS: Dict[str, Callable[..., pd.DataFrame]] = {
    "naive": naive, "volatility": volatility, "momentum": momentum, "reversion": reversion, "overnight": overnight}
NEEDS_DRIVER = ("overnight",)


def names_for(market: str, index: bool) -> tuple:
    """The forecasters a subject has: names have no overnight; only the home market's index does (IN, from the US close)."""
    if index and market == "IN":
        return P.FORECASTERS
    return tuple(n for n in P.FORECASTERS if n not in NEEDS_DRIVER)


def all_frames(close: pd.Series, h: int, names: tuple, us_close=None, next_date=None) -> Dict[str, pd.DataFrame]:
    return {n: FORECASTERS[n](close, h, us_close=us_close, next_date=next_date) for n in names}


def last_row(frame: pd.DataFrame) -> Optional[Dict[float, float]]:
    """The last row as {level: return}, sorted non-decreasing; None when it could not be made (too little history)."""
    v = frame.iloc[-1].to_numpy(float)
    if not np.isfinite(v).all():
        return None
    v = np.sort(v)
    return {float(q): float(x) for q, x in zip(P.LEVELS, v)}


def external_gap(con, target: date, market: str, root=None):
    """HOOK: the transmission module's expected open gap for the morning of `target` (`quant.transmission.expected_open_gap`), recorded beside the
    overnight forecast and not used by it (a second transmission model enters only through its own registered comparison). None when it fails."""
    try:
        from pflab.quant import transmission
        v = transmission.expected_open_gap(con, target, market, root)
        if isinstance(v, dict):
            return {k: v.get(k) for k in ("expected_gap_pct", "sd_pct", "n", "note") if k in v}
        return v if isinstance(v, (int, float, str)) or v is None else str(v)
    except Exception:
        return None


EXTERNAL_GAP = external_gap
