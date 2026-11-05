"""History replay (S79 item 9): the code forecasters, scoring and Hedge run day by day, point in time, over 2012-2021 on the real index series.

Warms the weights and tests the loop on thousands of days. Rows go to the same tables with `source = 'replay'`, kept apart from live ones: the replay is
never counted in the 60 live sessions and never decides a verdict. 2022-2025 is spent: any start or end date in it is refused, and the series is cut at
the end date before anything is computed. Sessions are the days the index traded (the series' own dates), so the horizon is counted in sessions.
Vectorised: a frame per forecaster and horizon; only the Hedge's weight path is a loop (one step per day and horizon). No news or model-read feature.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd

from pflab import markets
from pflab.fcast import fall_risk, forecasters as F, protocol as P, score as S, weights as W

SOURCE = "replay"


def _pinball_matrix(y: np.ndarray, Q: np.ndarray) -> np.ndarray:
    e = y[:, None] - Q
    return np.maximum(S.L[None, :] * e, (S.L[None, :] - 1.0) * e)


def _hedge_path(Q: Dict[str, np.ndarray], pb: Dict[str, np.ndarray], valid: np.ndarray, h: int, i0: int, names: tuple):
    """Weights at every origin t (after the outcomes maturing at t), by Hedge steps. Returns (W (n,F), steps (n,) count of updates so far, updated (n,) bool)."""
    n, f = len(valid), len(names)
    Wm = np.full((n, f), 1.0 / f)
    steps = np.zeros(n, int)
    updated = np.zeros(n, bool)
    w, cnt = np.full(f, 1.0 / f), 0
    nl = pb[P.BENCHMARK]
    for t in range(i0, n):
        k = t - h
        if k >= i0 and valid[k] and np.isfinite(nl[k]):
            ls = np.array([pb[nm][k] if np.isfinite(pb[nm][k]) else nl[k] for nm in names])
            w = W.hedge_step(w, ls, float(nl[k]), h)
            cnt += 1
            updated[t] = True
        Wm[t], steps[t] = w, cnt
    return Wm, steps, updated


def replay(con, market: str = "IN", start: date = P.REPLAY_START, end: date = P.REPLAY_END, close: Optional[pd.Series] = None,
           us_close: Optional[pd.Series] = None, root=None, now: Optional[datetime] = None, write: bool = True) -> dict:
    """Run the loop over [start, end]; write to the tables (source 'replay') when `write`; return the scoreboard numbers."""
    P.refuse_spent(start)
    P.refuse_spent(end)
    if start > end:
        raise ValueError("start after end")
    now = now or datetime.now()
    if close is None:
        from pflab.fcast.run import load_series
        close = load_series(market, root)
    cut = pd.Timestamp(end)
    close = close[close.index <= cut]                         # nothing after the end (2022-2025 never read) enters any computation
    if us_close is None and market == "IN":
        from pflab.fcast.run import load_us
        try:
            us_close = load_us(root)
        except Exception:
            us_close = None
    if us_close is not None:
        us_close = us_close[us_close.index <= cut]
    names_all = F.names_for(market, True)
    if market == "IN" and us_close is None:
        names_all = tuple(n for n in names_all if n != "overnight")
    idx = close.index
    n = len(idx)
    i0 = int(np.searchsorted(idx.values, np.datetime64(pd.Timestamp(start)), side="left"))
    out: dict = {"market": market, "start": str(start), "end": str(end), "source": SOURCE, "sessions": int(n - i0), "horizons": {}}
    fc_rows, sc_rows, w_rows = [], [], []
    px = close.to_numpy(float)
    dates = [d.date() for d in idx]
    for h in P.HORIZONS:
        frames = F.all_frames(close, h, names_all, us_close=us_close, next_date=None)
        Q = {nm: fr.to_numpy(float) for nm, fr in frames.items()}
        y = np.full(n, np.nan)
        if n > h:
            y[: n - h] = px[h:] / px[: n - h] - 1.0
        pb = {nm: np.where(np.isfinite(Q[nm]).all(1) & np.isfinite(y), _pinball_matrix(y, Q[nm]).mean(1), np.nan) for nm in names_all}
        valid = np.isfinite(y)
        Wm, steps, updated = _hedge_path(Q, pb, valid, h, i0, names_all)
        num, den = np.zeros((n, len(P.LEVELS))), np.zeros((n, 1))
        for j, nm in enumerate(names_all):
            ok = np.isfinite(Q[nm]).all(1)[:, None]
            num += np.where(ok, Wm[:, [j]] * np.nan_to_num(Q[nm]), 0.0)
            den += np.where(ok, Wm[:, [j]], 0.0)
        with np.errstate(invalid="ignore", divide="ignore"):
            Qh = np.where(den > 0, num / den, np.nan)
        Q[P.COMBINED] = Qh
        pb[P.COMBINED] = np.where(np.isfinite(Qh).all(1) & np.isfinite(y), _pinball_matrix(y, Qh).mean(1), np.nan)
        cov80 = {nm: np.where(np.isfinite(pb[nm]), ((Q[nm][:, S.I10] <= y) & (y <= Q[nm][:, S.I90])).astype(float), np.nan) for nm in Q}
        cov90 = {nm: np.where(np.isfinite(pb[nm]), ((Q[nm][:, S.I05] <= y) & (y <= Q[nm][:, S.I95])).astype(float), np.nan) for nm in Q}
        # scoreboard over the origins in [start, end] with an outcome and every forecaster present
        allok = np.isfinite(np.vstack([pb[nm] for nm in Q])).all(0)
        allok[:i0] = False
        base = float(np.nanmean(pb[P.BENCHMARK][allok])) if allok.any() else float("nan")
        board = {}
        for nm in Q:
            board[nm] = {"n": int(allok.sum()), "pinball": float(np.mean(pb[nm][allok])) if allok.any() else None,
                         "vs_naive": float(np.mean(pb[nm][allok]) / base) if allok.any() else None,
                         "coverage_80": float(np.mean(cov80[nm][allok])) if allok.any() else None}
        dm = S.dm_stat((pb[P.BENCHMARK] - pb[P.COMBINED])[allok], h) if allok.any() else {}
        out["horizons"][str(h)] = {"forecasters": board, "hedge_vs_naive_dm_t": dm.get("t"), "hedge_mean_gain": dm.get("mean"),
                                   "final_weights": {nm: float(Wm[-1, j]) for j, nm in enumerate(names_all)}, "weight_steps": int(steps[-1])}
        if write:
            for t in np.flatnonzero(allok):                # forecasts that matured by the end; the last h origins have no outcome and are not stored
                mat = dates[t + h]
                for nm in Q:
                    qd = {str(float(l)): round(float(v), 8) for l, v in zip(P.LEVELS, np.sort(Q[nm][t]))}
                    fc_rows.append([None, market, SOURCE, dates[t], markets.get(market).index, None, h, nm, json.dumps(qd), float(px[t]), mat,
                                    json.dumps({}), now])
                    sc_rows.append([None, market, SOURCE, dates[t], mat, markets.get(market).index, h, nm, float(y[t]),
                                    json.dumps([round(float(v), 8) for v in _pinball_matrix(y[t:t + 1], np.sort(Q[nm][t])[None, :])[0]]),
                                    float(pb[nm][t]), bool(cov80[nm][t]), bool(cov90[nm][t]), now])
            for t in np.flatnonzero(updated):
                for j, nm in enumerate(names_all):
                    w_rows.append([market, SOURCE, h, nm, dates[t], float(Wm[t, j]), int(steps[t]), now])
    # fall risk: raw, calibrated on outcomes resolved by each date, Brier of what was shown against the base rate
    fr = fall_risk.calibrate_series(fall_risk.raw_frame(close))
    sel = np.zeros(n, bool)
    sel[i0:] = True
    fr_ok = sel & fr["p_raw"].notna().to_numpy() & fr["event"].notna().to_numpy()
    shown = np.where(fr["p"].notna(), fr["p"], fr["p_raw"]).astype(float)
    ev = fr["event"].to_numpy(float)
    calib = fr_ok & fr["p"].notna().to_numpy()
    if fr_ok.any():
        b = float(np.mean((shown[fr_ok] - ev[fr_ok]) ** 2))
        rate = float(np.mean(ev[fr_ok]))
        bc = float(np.mean((shown[calib] - ev[calib]) ** 2)) if calib.any() else None
        braw = float(np.mean((fr["p_raw"].to_numpy(float)[fr_ok] - ev[fr_ok]) ** 2))
        out["fall_risk"] = {"definition": f"{P.FALL_X:.0%} under the forecast date's close within {P.FALL_H} sessions", "n": int(fr_ok.sum()),
                            "fall_rate": rate, "brier_shown": b, "brier_raw": braw, "brier_climatology": float(np.mean((rate - ev[fr_ok]) ** 2)),
                            "brier_calibrated_only": bc, "n_calibrated": int(calib.sum())}
    else:
        out["fall_risk"] = {"note": "too little history"}
    if write:
        _write(con, market, fc_rows, sc_rows, w_rows, fr, shown, fr_ok, i0, dates, now)
        from pflab.pm.store import next_id
        rid = next_id(con, "replay_runs_s79", "run_id")
        con.execute("INSERT INTO replay_runs_s79 VALUES (?,?,?,?,?,?,?)", [rid, market, now, start, end, int(n - i0), json.dumps(out, default=float)])
    return out


def _write(con, market, fc_rows, sc_rows, w_rows, fr, shown, fr_ok, i0, dates, now) -> None:
    from pflab.pm.store import next_id
    from pflab.fcast.run import _insert
    con.execute("DELETE FROM forecast_scores_s79 WHERE market=? AND source=?", [market, SOURCE])
    con.execute("DELETE FROM forecasts_s79 WHERE market=? AND source=?", [market, SOURCE])
    con.execute("DELETE FROM forecaster_weights WHERE market=? AND source=?", [market, SOURCE])
    con.execute("DELETE FROM fall_risk_s79 WHERE market=? AND source=?", [market, SOURCE])
    n0 = next_id(con, "forecasts_s79", "forecast_id")
    for i, (a, b) in enumerate(zip(fc_rows, sc_rows)):
        a[0] = b[0] = n0 + i
    _insert(con, "forecasts_s79", pd.DataFrame(fc_rows, columns=["forecast_id", "market", "source", "as_of", "subject", "symbol", "horizon_sessions", "forecaster",
                                                                  "quantiles_json", "base_price", "matures", "meta_json", "made_at"]))
    _insert(con, "forecast_scores_s79", pd.DataFrame(sc_rows, columns=["forecast_id", "market", "source", "as_of", "matures", "subject", "horizon_sessions",
                                                                        "forecaster", "realised", "pinball_json", "pinball_mean", "covered_80", "covered_90",
                                                                        "scored_at"]))
    _insert(con, "forecaster_weights", pd.DataFrame(w_rows, columns=["market", "source", "horizon_sessions", "forecaster", "as_of", "weight", "n", "updated_at"]))
    rows = []
    ev = fr["event"].to_numpy(float)
    for t in np.flatnonzero(fr_ok):
        p = fr["p"].iloc[t]
        rows.append([market, SOURCE, dates[t], P.FALL_H, float(fr["p_raw"].iloc[t]), None if pd.isna(p) else float(p), int(fr["n_cal"].iloc[t]),
                     float(fr["ref_high"].iloc[t]), float(fr["threshold"].iloc[t]), bool(ev[t]), float((shown[t] - ev[t]) ** 2), now, now])
    _insert(con, "fall_risk_s79", pd.DataFrame(rows, columns=["market", "source", "as_of", "horizon_sessions", "p_raw", "p", "n_cal", "ref_high", "threshold",
                                                              "outcome", "brier", "made_at", "scored_at"]))
