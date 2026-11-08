"""fall_risk (S79 item 8): the probability that the benchmark closes at least 5% under today's close at some session within the next 20. A probability scored by
Brier against that fixed definition; never a crash date, never a call to sell.

Raw: zero-drift reflection, p = min(1, 2 * Phi(-d / sigma_20)), d = ln(1 / 0.95); Calibrated: a logit shift
fitted so that the mean probability equals the observed fall rate over the outcomes resolved so far (replay outcomes are the prior). Below 20 resolved
outcomes the raw figure is shown with n and "no conclusion".
"""
from __future__ import annotations

import math
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

from pflab.fcast import protocol as P
from pflab.fcast.forecasters import _sigma_h, _vol_parts


def raw_frame(close: pd.Series) -> pd.DataFrame:
    """Point in time at every row t: p_raw, the reference close, the threshold; `event` is the outcome over t+1..t+20 (NaN until known; for the replay/score only)."""
    lc, r, sig, ew = _vol_parts(close)
    s20 = _sigma_h(sig, ew, P.FALL_H, False)
    ref = close.where(sig.notna())                                    # the level the fall is measured from: the forecast date's close
    thr = ref * (1.0 - P.FALL_X)
    d = np.log(close / thr)                                           # = ln(1 / 0.95), the same every day
    p = np.where(d <= 0, 1.0, np.minimum(1.0, 2.0 * norm.cdf(-d / s20)))
    p = pd.Series(np.where(s20.notna() & ref.notna(), p, np.nan), index=close.index)
    fwd_min = close.iloc[::-1].rolling(P.FALL_H, min_periods=P.FALL_H).min().iloc[::-1].shift(-1)
    ev = (fwd_min <= thr).astype(float).where(fwd_min.notna() & thr.notna())
    return pd.DataFrame({"p_raw": p, "ref_high": ref, "threshold": thr, "event": ev})


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def fit_shift(p: np.ndarray, y: np.ndarray) -> float:
    """The logit shift a with mean(sigmoid(logit(p) + a)) = mean(y) (calibration in the large; one parameter, safe on small samples)."""
    z, target = _logit(p), float(np.mean(y))
    lo, hi = -10.0, 10.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if float(np.mean(1 / (1 + np.exp(-(z + mid))))) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def apply_shift(p, a: float):
    return 1 / (1 + np.exp(-(_logit(p) + a)))


def calibrate_series(fr: pd.DataFrame, prior: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Vectorised calibration for a whole series (replay): at row t the shift uses the outcomes whose 20 sessions have ended by t (origin <= t - 20)."""
    n = len(fr)
    p, y = fr["p_raw"].to_numpy(float), fr["event"].to_numpy(float)
    cal, ncal = np.full(n, np.nan), np.zeros(n, int)
    for t in range(n):
        k = t - P.FALL_H
        if k < 0 or not np.isfinite(p[t]):
            continue
        pp, yy = p[: k + 1], y[: k + 1]
        ok = np.isfinite(pp) & np.isfinite(yy)
        if ok.sum() < P.FALL_MIN_N:
            ncal[t] = int(ok.sum())
            continue
        a = fit_shift(pp[ok], yy[ok])
        cal[t], ncal[t] = float(apply_shift(p[t], a)), int(ok.sum())
    out = fr.copy()
    out["p"], out["n_cal"] = cal, ncal
    return out


def shown(p_raw, p) -> float:
    """What the forecast says: the calibrated figure when there is one, else the raw."""
    return float(p) if p is not None and not (isinstance(p, float) and math.isnan(p)) else float(p_raw)


# --- live ---------------------------------------------------------------------------------------------------------------------------
def make(con, market: str, close: pd.Series, as_of: date, source: str, now: datetime) -> Optional[dict]:
    """The fall risk made at the close of `as_of` from closes up to it (idempotent: one row per market, source, date)."""
    c = close[close.index <= pd.Timestamp(as_of)]
    if len(c) < P.SIGMA_MIN + 5 or c.index[-1].date() != as_of:
        return None
    ex = con.execute("SELECT p_raw, p, n_cal FROM fall_risk_s79 WHERE market=? AND source=? AND as_of=? AND horizon_sessions=?",
                     [market, source, as_of, P.FALL_H]).fetchone()
    if ex:
        return {"p_raw": ex[0], "p": ex[1], "n_cal": ex[2], "existing": True}
    fr = raw_frame(c).iloc[-1]
    if not np.isfinite(fr["p_raw"]):
        return None
    hist = con.execute("SELECT p_raw, outcome FROM fall_risk_s79 WHERE market=? AND outcome IS NOT NULL AND as_of<?", [market, as_of]).fetchall()
    n = len(hist)
    p = None
    if n >= P.FALL_MIN_N:
        a = fit_shift(np.array([h[0] for h in hist]), np.array([1.0 if h[1] else 0.0 for h in hist]))
        p = float(apply_shift(fr["p_raw"], a))
    con.execute("INSERT INTO fall_risk_s79 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [market, source, as_of, P.FALL_H, float(fr["p_raw"]), p, n, float(fr["ref_high"]), float(fr["threshold"]), None, None, now, None])
    return {"p_raw": float(fr["p_raw"]), "p": p, "n_cal": n, "existing": False}


def resolve(con, market: str, close: pd.Series, upto: date, source: str, now: datetime) -> int:
    """Resolve the fall risks whose 20 sessions have ended by `upto`: outcome 1 if any close in (as_of, end] was at or under the threshold; Brier of what was shown."""
    from pflab import markets
    mk = markets.get(market)
    rows = con.execute("SELECT as_of, p_raw, p, threshold FROM fall_risk_s79 WHERE market=? AND source=? AND outcome IS NULL AND horizon_sessions=? "
                       "ORDER BY as_of", [market, source, P.FALL_H]).fetchall()
    n = 0
    for as_of, p_raw, p, thr in rows:
        end = mk.session_after(as_of, P.FALL_H)
        if end > upto or close.index[-1] < pd.Timestamp(end):
            continue
        w = close[(close.index > pd.Timestamp(as_of)) & (close.index <= pd.Timestamp(end))]
        if len(w) < P.FALL_H - 2:
            continue
        y = bool(w.min() <= thr)
        con.execute("UPDATE fall_risk_s79 SET outcome=?, brier=?, scored_at=? WHERE market=? AND source=? AND as_of=? AND horizon_sessions=?",
                    [y, (shown(p_raw, p) - float(y)) ** 2, now, market, source, as_of, P.FALL_H])
        n += 1
    return n


def status(con, market: str, source: str = "live") -> dict:
    """The latest fall risk, how many outcomes calibrate it, its Brier against climatology, and the 60-live gate for a verdict."""
    last = con.execute("SELECT as_of, p_raw, p, n_cal, ref_high, threshold FROM fall_risk_s79 WHERE market=? AND source=? ORDER BY as_of DESC LIMIT 1",
                       [market, source]).fetchone()
    res = con.execute("SELECT p_raw, p, outcome, brier FROM fall_risk_s79 WHERE market=? AND source=? AND outcome IS NOT NULL", [market, source]).fetchall()
    n = len(res)
    out = {"market": market, "source": source, "definition": f"benchmark closes at least {P.FALL_X:.0%} under the forecast date's close within {P.FALL_H} sessions",
           "resolved": n, "need_for_verdict": P.MIN_LIVE}
    if last:
        shown_p = shown(last[1], last[2])
        out.update(as_of=str(last[0]), p_raw=round(last[1], 4), p_calibrated=(round(last[2], 4) if last[2] is not None else None),
                   shown=round(shown_p, 4), n_calibration=int(last[3]),
                   note=("calibrated on %d past outcomes" % last[3]) if last[2] is not None
                   else f"only {last[3]} resolved outcomes (need {P.FALL_MIN_N}): raw figure, no conclusion")
    else:
        out["note"] = "no fall risk made yet"
    if n:
        y = np.array([1.0 if r[2] else 0.0 for r in res])
        b = float(np.mean([r[3] for r in res]))
        c = float(np.mean((y.mean() - y) ** 2))
        out.update(brier=round(b, 5), brier_climatology=round(c, 5), fall_rate=round(float(y.mean()), 4))
    if source != "live":
        out["verdict"] = "refused: a replay is a development read"
    elif n < P.MIN_LIVE:
        out["verdict"] = f"not enough data ({n} of {P.MIN_LIVE} live resolved): no verdict"
    else:
        from pflab.fcast.score import dm_stat
        from pflab.learner import counter
        d = (y.mean() - y) ** 2 - np.array([r[3] for r in res])
        dm = dm_stat(d, P.FALL_H)
        bar = counter.t_needed(counter.n_tests(con))
        out["verdict"] = "PASS" if dm["t"] >= bar and dm["mean"] > 0 else "FAIL: not better than the base rate at the bar"
        out["t"], out["bar"] = dm["t"], bar
    return out
