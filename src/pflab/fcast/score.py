"""Scoring of the forecasts (S79 item 8), by code only: pinball loss at each level, coverage of the 80% and 90% ranges, the scoreboard, and the verdict
the protocol allows. A verdict before 60 live sessions is refused here, and a replay is never a verdict.

Pinball loss at level tau for a quantile q and an outcome y: max(tau * (y - q), (tau - 1) * (y - q)); the score of a forecast is its mean over the levels.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from pflab.fcast import protocol as P

L = np.array(P.LEVELS)
I10, I90, I05, I95 = P.LEVELS.index(0.1), P.LEVELS.index(0.9), P.LEVELS.index(0.05), P.LEVELS.index(0.95)


def pinball(y, q) -> np.ndarray:
    """Pinball loss per level. `y` scalar or (n,), `q` (L,) or (n, L). Returns the same shape as q."""
    q = np.asarray(q, float)
    y = np.asarray(y, float)
    e = (y[..., None] if y.ndim else y) - q
    return np.maximum(L * e, (L - 1.0) * e)


def score_one(q: Dict[float, float], y: float) -> dict:
    qa = np.array([q[float(l)] for l in P.LEVELS], float)
    pb = pinball(y, qa)
    return {"pinball": pb.tolist(), "pinball_mean": float(pb.mean()),
            "covered_80": bool(qa[I10] <= y <= qa[I90]), "covered_90": bool(qa[I05] <= y <= qa[I95])}


def dm_stat(d: np.ndarray, h: int) -> dict:
    """Diebold-Mariano t of a loss difference series (Bartlett HAC, lags max(1, h-1)); positive when the first forecast is worse (d = L_naive - L_other)."""
    d = np.asarray(d, float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 3:
        return {"t": float("nan"), "n": n, "mean": float("nan")}
    lags = min(max(1, h - 1), n - 1)
    dc = d - d.mean()
    v = float(dc @ dc) / n
    for k in range(1, lags + 1):
        v += 2.0 * (1.0 - k / (lags + 1.0)) * float(dc[k:] @ dc[:-k]) / n
    se = math.sqrt(max(v, 1e-30) / n)
    return {"t": float(d.mean() / se), "n": n, "mean": float(d.mean())}


# --- persisting scores -----------------------------------------------------------------------------------------------------------------
PriceAt = Callable[[str, date], Optional[float]]


def score_pending(con, price_at: PriceAt, market: str, upto: date, source: str, now: datetime) -> pd.DataFrame:
    """Score every unscored forecast of (market, source) that matured on or before `upto`, in the order of maturity. `price_at(subject, d)` is the close on
    or just before d, or None when not known yet (the forecast stays pending). Returns the new scores (a frame) for the weights' update."""
    rows = con.execute(
        "SELECT f.forecast_id, f.as_of, f.matures, f.subject, f.horizon_sessions, f.forecaster, f.quantiles_json, f.base_price "
        "FROM forecasts_s79 f LEFT JOIN forecast_scores_s79 s ON s.forecast_id=f.forecast_id "
        "WHERE f.market=? AND f.source=? AND f.matures<=? AND s.forecast_id IS NULL ORDER BY f.matures, f.as_of, f.forecast_id",
        [market, source, upto]).fetchall()
    out: List[list] = []
    cache: Dict[tuple, Optional[float]] = {}
    for fid, as_of, mat, subj, h, fc, qj, base in rows:
        k = (subj, mat)
        if k not in cache:
            cache[k] = price_at(subj, mat)
        px = cache[k]
        if px is None or not base:
            continue
        y = float(px) / float(base) - 1.0
        sc = score_one({float(a): b for a, b in json.loads(qj).items()}, y)
        out.append([fid, market, source, as_of, mat, subj, h, fc, y, json.dumps([round(v, 8) for v in sc["pinball"]]), sc["pinball_mean"],
                    sc["covered_80"], sc["covered_90"], now])
    cols = ["forecast_id", "market", "source", "as_of", "matures", "subject", "horizon_sessions", "forecaster", "realised", "pinball_json",
            "pinball_mean", "covered_80", "covered_90", "scored_at"]
    df = pd.DataFrame(out, columns=cols)
    if len(df):
        con.register("_new_scores", df)
        try:
            con.execute("INSERT INTO forecast_scores_s79 SELECT * FROM _new_scores")
        finally:
            con.unregister("_new_scores")
    return df


# --- the scoreboard and the verdict ---------------------------------------------------------------------------------------------------
def _index(market: str) -> str:
    from pflab import markets
    return markets.get(market).index


def pairs(con, market: str, horizon: int, source: str, forecaster: str = P.COMBINED, versus: str = P.BENCHMARK) -> pd.DataFrame:
    """Scored index forecasts of `forecaster` and `versus`, one row per forecast date (same outcome)."""
    df = con.execute(
        "SELECT as_of, forecaster, pinball_mean, covered_80, realised FROM forecast_scores_s79 WHERE market=? AND source=? AND subject=? "
        "AND horizon_sessions=? AND forecaster IN (?,?) ORDER BY as_of", [market, source, _index(market), horizon, forecaster, versus]).df()
    if df.empty:
        return pd.DataFrame(columns=["as_of", "a", "b", "cov_a"])
    a = df[df.forecaster == forecaster].set_index("as_of")
    b = df[df.forecaster == versus].set_index("as_of")
    j = pd.DataFrame({"a": a["pinball_mean"], "cov_a": a["covered_80"].astype(float), "b": b["pinball_mean"]}).dropna()
    return j.reset_index()


def n_live(con, market: str, horizon: int = 1, source: str = "live") -> int:
    """Live sessions scored so far (distinct forecast dates of the combined index forecast with an outcome)."""
    return int(con.execute("SELECT count(DISTINCT as_of) FROM forecast_scores_s79 WHERE market=? AND source=? AND subject=? AND horizon_sessions=? "
                           "AND forecaster=?", [market, source, _index(market), horizon, P.COMBINED]).fetchone()[0])


def verdict(con, market: str, horizon: int, source: str = "live") -> dict:
    """The protocol's decision for (market, horizon). Refused (decided False) below 60 live sessions, for a replay, or if the protocol file changed
    since it was registered. PASS: DM t of (naive - hedge) pinball >= counter.t_needed(N) with a positive mean, and the 80% range covers 75-85%."""
    out = {"market": market, "horizon": horizon, "source": source, "need": P.MIN_LIVE, "decided": False}
    if source != "live":
        return {**out, "status": "refused: only live sessions can decide (a replay is a development read)"}
    j = pairs(con, market, horizon, source)
    n = len(j)
    out["n"] = n
    if n < P.MIN_LIVE:
        return {**out, "status": f"not enough data ({n} of {P.MIN_LIVE} live sessions): no verdict"}
    reg = P.registered_sha(con, market)
    if reg is None or reg != P.protocol_sha():
        return {**out, "status": "refused: the protocol is not registered or changed after registration (amend with a date and re-register)"}
    from pflab.learner import counter
    bar = counter.t_needed(counter.n_tests(con))
    dm = dm_stat((j["b"] - j["a"]).to_numpy(), horizon)
    cov = float(j["cov_a"].mean())
    ok_t = bool(dm["t"] >= bar and dm["mean"] > 0)
    ok_c = bool(P.COVER_LO <= cov <= P.COVER_HI)
    return {**out, "decided": True, "t": dm["t"], "bar": bar, "mean_gain": dm["mean"], "coverage_80": cov, "beats_naive": ok_t, "covers": ok_c,
            "passed": ok_t and ok_c,
            "status": "PASS" if ok_t and ok_c else ("FAIL: not better than naive at the bar" if not ok_t else "FAIL: 80% range not calibrated")}


def scoreboard(con, market: str, source: str = "live") -> dict:
    """Per horizon and forecaster: n, mean pinball, ratio to naive, 80% coverage; the live count towards the 60; the verdicts (refused until 60)."""
    idx = _index(market)
    df = con.execute(
        "SELECT horizon_sessions h, forecaster, count(*) n, avg(pinball_mean) pb, avg(CASE WHEN covered_80 THEN 1.0 ELSE 0.0 END) cov80 "
        "FROM forecast_scores_s79 WHERE market=? AND source=? AND subject=? GROUP BY 1, 2 ORDER BY 1, 2", [market, source, idx]).df()
    hs = {}
    for h in P.HORIZONS:
        sub = df[df.h == h]
        base = sub[sub.forecaster == P.BENCHMARK]["pb"]
        base = float(base.iloc[0]) if len(base) else None
        fcs = {}
        for r in sub.itertuples():
            fcs[r.forecaster] = {"n": int(r.n), "pinball": round(float(r.pb), 6), "vs_naive": (round(float(r.pb) / base, 4) if base else None),
                                 "coverage_80": round(float(r.cov80), 3)}
        hs[str(h)] = {"forecasters": fcs, "live_sessions": n_live(con, market, h, source), "verdict": verdict(con, market, h, source)}
    return {"market": market, "source": source, "subject": idx, "live_sessions_h1": n_live(con, market, 1, source), "of": P.MIN_LIVE, "horizons": hs}
