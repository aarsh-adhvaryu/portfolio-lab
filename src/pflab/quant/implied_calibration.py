"""S79 item 11: the option-implied probabilities of a fall against what happened (the variance / risk premium, point in time).

The options give a RISK-NEUTRAL chance that the index ends more than X% lower at the nearest expiry (`quant/implied.py`). Buyers pay
extra for protection, so that chance runs above the real frequency. This module keeps every day's chance next to the outcome in
`implied_calibration_s79` (market, asof, horizon in SESSIONS of the market's calendar, fall_pct, p_implied, outcome, resolved_at),
fills the outcome by code when the horizon has passed, and fits the simplest map from the options' chance to the observed frequency:

    p_calibrated = k * p_implied   (capped at 1),   k = sum(outcomes) / sum(p_implied) over the outcomes resolved on or before `asof`

Rules: under MIN_N (20) resolved observations the map is NOT used (n is reported and there is no conclusion); rows that share an expiry
share an outcome, so the distinct expiries are reported beside n and the reading says the sample is thinner than n suggests. The
2024-2026 years are spent: this describes how far the options ran from the real frequency, it is no signal (protocol:
docs/protocols/implied_calibration_protocol.md). Where there is no option data it returns the realised frequency of the index and says so.
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

LEVELS = (5.0, 10.0, 15.0, 20.0)              # falls kept, in percent below the day's index level
MIN_N = 20
INDEX_KEY = {"IN": "NIFTY50_PRICE"}           # the market's option index (the only market with option data on this PC)


def _market(code: str):
    from pflab import markets
    return markets.get(code)


def _index_close(root, market: str) -> Optional[pd.Series]:
    key = INDEX_KEY.get(market)
    if key is None:
        return None
    from pflab.data import indices
    try:
        px = indices.load(key, Path(root))
    except Exception:
        return None
    if px is None or not len(px):
        return None
    return pd.Series(px["close"].to_numpy(float), index=pd.to_datetime(px["date"])).sort_index()


def _implied_table(root) -> Optional[pd.DataFrame]:
    from pflab.quant import implied
    p = Path(root) / "derived" / implied.FILE
    if not p.exists():
        return None
    t = pd.read_parquet(p)
    return t if len(t) else None


def has_option_data(root, market: str = "IN") -> bool:
    return market in INDEX_KEY and _implied_table(root) is not None


def refresh(con, root, market: str = "IN", asof: Optional[date] = None) -> dict:
    """Record every kept day's implied chances not yet in the table, then resolve those whose horizon has passed (on or before `asof`)."""
    t = _implied_table(root)
    close = _index_close(root, market)
    if t is None or close is None:
        return {"added": 0, "resolved": 0, "note": "no option data on this PC" if t is None else f"no index series for market {market}"}
    mk = _market(market)
    have = {(a, int(h), float(f)) for a, h, f in con.execute(
        "SELECT \"asof\", horizon, fall_pct FROM implied_calibration_s79 WHERE market=?", [market]).fetchall()}
    rows = []
    for r in t.itertuples():
        d, e = pd.Timestamp(r.date).date(), pd.Timestamp(r.expiry).date()
        if asof is not None and d > asof:
            continue
        h = mk.session_count(d, e)
        for lv in LEVELS:
            col = f"p_below_{int(lv)}"
            if hasattr(r, col) and (d, h, lv) not in have and pd.notna(getattr(r, col)):
                rows.append([market, d, h, lv, float(getattr(r, col)), None, None, e, float(r.spot), None])
    if rows:
        con.executemany("INSERT INTO implied_calibration_s79 VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    last = close.index.max().date()
    todo = con.execute("SELECT \"asof\", horizon, fall_pct, spot FROM implied_calibration_s79 WHERE market=? AND outcome IS NULL", [market]).fetchall()
    upd, plan = [], {}
    for d, h, lv, spot in todo:
        key = (d, int(h))
        if key not in plan:
            plan[key] = mk.session_after(d, int(h))
        due = plan[key]
        if due > last or (asof is not None and due > asof):
            continue
        end = float(close[:pd.Timestamp(due)].iloc[-1])
        upd.append([int(end < spot * (1 - lv / 100.0)), due, end, market, d, int(h), lv])
    if upd:
        con.executemany("UPDATE implied_calibration_s79 SET outcome=?, resolved_at=?, end_level=? WHERE market=? AND \"asof\"=? AND horizon=? AND fall_pct=?", upd)
    return {"added": len(rows), "resolved": len(upd)}


def resolved(con, market: str, asof: date) -> pd.DataFrame:
    """The outcomes known on `asof` (resolved on or before it): point in time."""
    rows = con.execute("SELECT \"asof\", horizon, fall_pct, p_implied, outcome, resolved_at, expiry FROM implied_calibration_s79 "
                       "WHERE market=? AND outcome IS NOT NULL AND resolved_at <= ?", [market, asof]).fetchall()
    return pd.DataFrame(rows, columns=["asof", "horizon", "fall_pct", "p_implied", "outcome", "resolved_at", "expiry"])


def fit_map(df: pd.DataFrame) -> dict:
    """The scale map from resolved observations. `k` is None under MIN_N observations (no conclusion)."""
    n = int(len(df))
    out = {"n": n, "expiries": int(df["expiry"].nunique()) if n else 0, "min_n": MIN_N, "k": None, "by_level": {}}
    if n:
        out["implied_mean"] = round(float(df["p_implied"].mean()), 4)
        out["realised_frequency"] = round(float(df["outcome"].mean()), 4)
        for lv, g in df.groupby("fall_pct"):
            out["by_level"][f"{lv:g}%"] = {"n": int(len(g)), "options_said": round(float(g["p_implied"].mean()), 4), "happened": round(float(g["outcome"].mean()), 4)}
    if n >= MIN_N and float(df["p_implied"].sum()) > 0:
        out["k"] = float(df["outcome"].sum() / df["p_implied"].sum())
    return out


def apply_map(k: Optional[float], p: Optional[float]) -> Optional[float]:
    return None if k is None or p is None else float(min(1.0, max(0.0, k * p)))


def _stored_p(con, market: str, asof: date, fall_pct: float) -> Optional[dict]:
    """The latest kept day on or before `asof`: its chance for exactly this fall, else interpolated (in log p) between the two kept levels around it."""
    r = con.execute("SELECT max(\"asof\") FROM implied_calibration_s79 WHERE market=? AND \"asof\"<=?", [market, asof]).fetchone()
    if not r or r[0] is None:
        return None
    day = r[0]
    rows = con.execute("SELECT fall_pct, p_implied, horizon, expiry FROM implied_calibration_s79 WHERE market=? AND \"asof\"=? ORDER BY fall_pct", [market, day]).fetchall()
    if not rows:
        return None
    lv = np.array([x[0] for x in rows], float)
    p = np.array([x[1] for x in rows], float)
    exact = np.flatnonzero(np.isclose(lv, fall_pct))
    h, e = int(rows[0][2]), rows[0][3]
    if len(exact):
        return {"day": day, "p": float(p[exact[0]]), "horizon": h, "expiry": e, "how": "kept level"}
    if lv.min() < fall_pct < lv.max():
        lp = np.log(np.maximum(p, 1e-9))
        return {"day": day, "p": float(math.exp(np.interp(fall_pct, lv, lp))), "horizon": h, "expiry": e,
                "how": f"between the kept levels {lv[lv < fall_pct].max():g}% and {lv[lv > fall_pct].min():g}% (log scale)"}
    return {"day": day, "p": None, "horizon": h, "expiry": e, "how": f"{fall_pct:g}% is outside the kept levels {lv.min():g}% to {lv.max():g}%"}


def calibrated_fall_probability(con, market: str, asof: date, horizon: int, fall_pct: float, root=None) -> dict:
    """For the forecasting agent's `fall_risk`: {"p_implied","p_calibrated","n","note"}. p_implied is the options' (risk-neutral) chance
    from the latest kept day on or before `asof`; p_calibrated applies the map fitted on outcomes resolved by `asof`, and is None under
    MIN_N resolved observations (the note says n and gives no conclusion). With a `root` the table is refreshed first. Never invents:
    with no option data both are None and the note says so."""
    out = {"market": market, "asof": str(asof), "p_implied": None, "p_calibrated": None, "n": 0, "note": ""}
    if root is not None:
        try:
            refresh(con, root, market, asof)
        except Exception as e:
            out["note"] = f"refresh failed ({type(e).__name__}); "
    st = _stored_p(con, market, asof, float(fall_pct))
    if st is None:
        out["note"] += "no option data kept for this market on or before that date" + (": the options give nothing here" if market not in INDEX_KEY else "")
        return out
    fit = fit_map(resolved(con, market, asof))
    out.update({"n": fit["n"], "expiries": fit["expiries"], "option_day": str(st["day"]), "expiry": str(st["expiry"]), "horizon_sessions": st["horizon"],
                "k": None if fit["k"] is None else round(fit["k"], 3), "p_implied": None if st["p"] is None else round(st["p"], 4)})
    out["p_calibrated"] = None if fit["k"] is None or st["p"] is None else round(apply_map(fit["k"], st["p"]), 4)
    parts = []
    if st["p"] is None:
        parts.append(st["how"])
    if abs(int(horizon) - st["horizon"]) > 3:
        parts.append(f"the options' nearest usable expiry is {st['horizon']} sessions out, not {int(horizon)}: their chance is for that expiry")
    if fit["k"] is None:
        parts.append(f"{fit['n']} resolved observations ({fit['expiries']} distinct expiries) is under {MIN_N}: no calibration, no conclusion")
    else:
        parts.append(f"options said {fit['implied_mean']:.1%} on average, {fit['realised_frequency']:.1%} happened (n={fit['n']}, {fit['expiries']} distinct expiries: "
                     "rows on one expiry share their outcome, so the sample is thinner than n; 2024-2026 is spent: a description, not evidence)")
    if st["how"] != "kept level" and st["p"] is not None:
        parts.append(f"p_implied is {st['how']}")
    out["note"] += "; ".join(parts)
    return out


def baseline_frequency(root, market: str, asof: date, horizon: int, fall_pct: float) -> dict:
    """The realised frequency of the index ending more than `fall_pct` percent lower `horizon` sessions later, over every window whose end is on or
    before `asof` (point in time; overlapping windows, so the effective sample is smaller than n)."""
    close = _index_close(root, market)
    if close is None:
        return {"available": False, "note": f"no index series for market {market}"}
    s = close[close.index <= pd.Timestamp(asof)]
    h = int(horizon)
    if len(s) <= h + 20:
        return {"available": False, "note": "too little index history"}
    ret = (s.shift(-h) / s - 1).dropna()
    hit = ret < -fall_pct / 100.0
    return {"available": True, "frequency": round(float(hit.mean()), 4), "windows": int(len(ret)), "from": str(ret.index[0].date()), "to": str(ret.index[-1].date()),
            "note": "overlapping windows: far fewer independent observations than windows; includes the spent years"}
