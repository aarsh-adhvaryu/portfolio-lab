"""Fill-cost calibration, automatic (S82 C8): the three numbers of the fill model `liquidity_v1` (`half_spread_liquid_bps`, `half_spread_illiquid_bps`, `impact_bps`) refitted from the
session's own REAL fills.

WHAT IS A REAL FILL: a row of `session_fills_s81` whose `source` is 'live' (the session loop priced it from a live Kite quote). Rows from tests, drills, replays and simulations carry another
source, and rows written before S82 carry none: none of them counts. A fill with no known liquidity (the unknown-liquidity assumption was charged) tells nothing about the spread or
the impact curve and is left out of the fit (it still counts toward "real fills so far").

THE FIT (the simplest robust method): each fill's observed cost is its price against its quote in basis points, signed against the order (a buy above the quote, a sell below it, is positive).
The model's own prediction for a fill is  hs_illiquid * (1 - x) + hs_liquid * x + max(min_slippage, impact * sqrt(participation))  where x in [0, 1] is the fill's place between the illiquid and
the liquid end of the log-ADV scale (exactly `fills.model`). A soft-L1 least squares (scipy, robust to odd fills) finds the three numbers, each held inside STATED BOUNDS (0.5x to 3x of the
configured default, never under 0.5 bp of spread or 5 bp of impact) by the optimiser itself. A number the fills cannot speak to (fewer than 5 fills near that end of the liquidity scale, or
fewer than 5 whose impact term is above the slippage floor) stays at its current value and the row says so. The row holds n, the residual and a 95% interval (Gauss-Newton, approximate).

CADENCE: the first fit when 30 real fills with known liquidity exist; then at most once in 30 days (a fit that could not be accepted is retried after 7 days). Until then the defaults
stand and the job says "waiting: N of 30 real fills".

HONEST LIMIT: today a paper fill's price is itself computed by this model, so the observed cost equals the model's prediction (plus the paisa rounding) and the fit mostly reproduces the
current numbers. The machinery is ready for the day a fill's price is not model-made (an executed price or a measured one); until then the fit is a consistency check and the defaults hold.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from typing import Dict, Optional

import numpy as np
import pandas as pd

from pflab.core import fills

COOLDOWN_ACCEPTED = timedelta(days=30)
COOLDOWN_REJECTED = timedelta(days=7)
MIN_SUPPORT = 5                                    # fills needed near an end of the liquidity scale (or above the slippage floor) for a number to be fitted


def real_fills(con, market: str = "IN") -> pd.DataFrame:
    """The real fills usable for the fit: source 'live', a valid quote and price, a known liquidity. Columns as stored."""
    return con.execute("SELECT fill_id, side, quote, price, adv_rupees, order_rupees, participation FROM session_fills_s81 "
                       "WHERE market=? AND source='live' AND quote > 0 AND price > 0 AND adv_rupees IS NOT NULL AND adv_rupees > 0 AND order_rupees IS NOT NULL ORDER BY fill_id",
                       [market]).fetchdf()


def observed_bps(df: pd.DataFrame) -> np.ndarray:
    sign = np.where(df["side"].astype(str).str.lower() == "buy", 1.0, -1.0)
    return sign * (df["price"].to_numpy(float) - df["quote"].to_numpy(float)) / df["quote"].to_numpy(float) * 1e4


def _x(adv: np.ndarray, base: dict) -> np.ndarray:
    hi, lo = float(base["liquid_adv_rupees"]), float(base["illiquid_adv_rupees"])
    return np.clip((np.log(adv) - math.log(lo)) / (math.log(hi) - math.log(lo)), 0.0, 1.0)


def fit(df: pd.DataFrame, base: Optional[dict] = None, current: Optional[dict] = None) -> dict:
    """Fit the three numbers on the fills in `df` (see the module docstring). Pure. -> {'ok', 'values', 'fitted': [names], 'frozen': {name: why}, 'n_used', 'residual_rms_bps',
    'residual_mad_bps', 'outliers', 'interval': {name: [lo, hi] | None}, 'reason'}. `base` is the configured defaults (the bounds' anchor), `current` the values in force (the start)."""
    from scipy.optimize import least_squares
    base = base or fills.settings()
    cur = {k: float(v) for k, v in (current or {k: base[k] for k in fills.FITTED}).items()}
    bd = fills.bounds(base)
    names = list(fills.FITTED)
    out = {"ok": False, "values": {k: min(bd[k][1], max(bd[k][0], cur[k])) for k in names}, "fitted": [], "frozen": {}, "n_used": int(len(df)), "residual_rms_bps": None,
           "residual_mad_bps": None, "outliers": 0, "interval": {k: None for k in names}, "reason": ""}
    if len(df) < fills.MIN_REAL_FILLS:
        out["reason"] = f"only {len(df)} usable real fills (need {fills.MIN_REAL_FILLS})"
        return out
    y = observed_bps(df)
    adv = df["adv_rupees"].to_numpy(float)
    part = np.maximum(df["order_rupees"].to_numpy(float) / adv, 0.0)
    x = _x(adv, base)
    floor = float(base["min_slippage_bps"])
    # which numbers the fills can speak to
    support = {"half_spread_illiquid_bps": int((1.0 - x >= 0.3).sum()), "half_spread_liquid_bps": int((x >= 0.3).sum()),
               "impact_bps": int((float(base["impact_bps"]) * np.sqrt(part) >= 1.5 * floor).sum())}
    free = [k for k in names if support[k] >= MIN_SUPPORT]
    out["frozen"] = {k: f"only {support[k]} fills speak to it (need {MIN_SUPPORT}): it keeps its current value" for k in names if k not in free}
    if not free:
        out["reason"] = "the fills do not cover the liquidity range or the impact range well enough to fit anything"
        return out

    def predict(p: np.ndarray) -> np.ndarray:
        v = dict(out["values"])
        v.update(dict(zip(free, p)))
        return v["half_spread_illiquid_bps"] * (1.0 - x) + v["half_spread_liquid_bps"] * x + np.maximum(floor, v["impact_bps"] * np.sqrt(part))

    x0 = np.array([out["values"][k] for k in free])
    lo, hi = np.array([bd[k][0] for k in free]), np.array([bd[k][1] for k in free])
    scale = max(0.5, 1.4826 * float(np.median(np.abs(y - predict(x0)))))               # the robust scale of the starting residuals, at least half a bp
    try:
        res = least_squares(lambda p: predict(p) - y, x0, bounds=(lo, hi), loss="soft_l1", f_scale=scale)
    except Exception as e:
        out["reason"] = f"the fit failed ({type(e).__name__}: {str(e)[:120]})"
        return out
    if not res.success:
        out["reason"] = f"the fit did not converge ({res.message})"
        return out
    for k, v in zip(free, res.x):
        out["values"][k] = float(min(bd[k][1], max(bd[k][0], v)))
    r = predict(res.x) - y
    out["fitted"] = free
    out["residual_rms_bps"] = float(np.sqrt(np.mean(r ** 2)))
    out["residual_mad_bps"] = float(np.median(np.abs(r - np.median(r))))
    out["outliers"] = int((np.abs(r) > 3 * scale).sum())
    dof = max(1, len(y) - len(free))
    try:
        cov = (float(np.sum(r ** 2)) / dof) * np.linalg.pinv(res.jac.T @ res.jac)
        se = np.sqrt(np.clip(np.diag(cov), 0.0, None))
        for k, v, s in zip(free, res.x, se):
            out["interval"][k] = [float(max(bd[k][0], v - 1.96 * s)), float(min(bd[k][1], v + 1.96 * s))]
    except Exception:
        pass
    out["ok"] = True
    return out


def run(con, now: datetime, market: str = "IN", force: bool = False) -> dict:
    """The job's body. Returns a small dict: {'waiting': 'waiting: N of 30 real fills'}, {'skipped': ...} (not due yet) or the recorded calibration."""
    from pflab.pm.store import next_id
    n_real = fills.real_fill_count(con, market)
    df = real_fills(con, market)
    if len(df) < fills.MIN_REAL_FILLS:
        why = f"waiting: {n_real} of {fills.MIN_REAL_FILLS} real fills" + (f" ({len(df)} with a known liquidity)" if n_real != len(df) else "")
        return {"waiting": why, "n_real_fills": n_real, "n_usable": int(len(df)), "source": "defaults"}
    if not force:
        last = con.execute("SELECT made_at, accepted FROM fills_calibration_s82 WHERE market=? ORDER BY cal_id DESC LIMIT 1", [market]).fetchone()
        if last and now - last[0] < (COOLDOWN_ACCEPTED if last[1] else COOLDOWN_REJECTED):
            due = last[0] + (COOLDOWN_ACCEPTED if last[1] else COOLDOWN_REJECTED)
            return {"skipped": f"the last fit was {str(last[0])[:10]}; the next is due {due:%Y-%m-%d}", "source": fills.calibration_status(con, market)["source"]}
    base = fills.settings()
    old = {k: float(fills.settings(con, market)[k]) for k in fills.FITTED}
    f = fit(df, base, old)
    cid = next_id(con, "fills_calibration_s82", "cal_id")
    new = {k: round(float(v), 4) for k, v in f["values"].items()}
    fit_json = {k: f[k] for k in ("fitted", "frozen", "n_used", "residual_rms_bps", "residual_mad_bps", "outliers", "interval")}
    fit_json["bounds"] = {k: list(v) for k, v in fills.bounds(base).items()}
    con.execute("INSERT INTO fills_calibration_s82 (cal_id, made_at, market, status, accepted, n_fills, n_used, old_json, new_json, fit_json, reason) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [cid, now, market, "accepted" if f["ok"] else "rejected", bool(f["ok"]), n_real, int(len(df)), json.dumps({k: round(v, 4) for k, v in old.items()}), json.dumps(new),
                 json.dumps(fit_json), f["reason"] or None])
    return {"cal_id": cid, "accepted": bool(f["ok"]), "n_real_fills": n_real, "n_used": int(len(df)), "old": old, "new": new, "fitted": f["fitted"], "frozen": list(f["frozen"]),
            "residual_rms_bps": f["residual_rms_bps"], "reason": f["reason"], "source": fills.calibration_status(con, market)["source"]}
