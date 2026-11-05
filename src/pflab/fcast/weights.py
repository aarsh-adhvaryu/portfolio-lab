"""Hedge weights on pinball loss (S79 item 8): slow learning rate, a floor, code only. No model sets a weight.

w_i <- w_i * exp(-eta_h * l_i), l_i = L_i / (L_i + L_naive) in [0, 1], normalised, then floored (a weight under the floor is lifted to it, the rest scaled down).
Weights live in `forecaster_weights` (market, source, horizon, forecaster, as_of, weight, n); history is kept, the current row is the latest as_of.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Optional, Sequence

import numpy as np

from pflab.fcast import protocol as P


def relative_loss(losses: np.ndarray, naive_loss: float) -> np.ndarray:
    """Bounded loss in [0, 1]: a forecaster as bad as naive has 0.5; better, less."""
    L = np.asarray(losses, float)
    return L / np.maximum(L + naive_loss, 1e-18)


def mix_floor(w: np.ndarray, floor: float = P.FLOOR) -> np.ndarray:
    """Normalise, then lift every weight under the floor to the floor and scale the others down so the sum stays 1. A weight above the floor is not pulled
    towards uniform (a mixing floor applied every step would cancel the learning)."""
    w = np.asarray(w, float)
    w = w / w.sum()
    for _ in range(len(w)):
        low = w < floor
        if not low.any():
            break
        free = ~low
        w = np.where(low, floor, w * ((1.0 - low.sum() * floor) / w[free].sum()))
    return w


def hedge_step(w: np.ndarray, losses: np.ndarray, naive_loss: float, h: int, floor: float = P.FLOOR) -> np.ndarray:
    """One Hedge update of the weight vector `w` after a matured forecast with per-forecaster pinball `losses`."""
    w = np.asarray(w, float)
    l = relative_loss(losses, naive_loss)
    new = w * np.exp(-P.eta(h) * l)
    return mix_floor(new, floor)


def uniform(names: Sequence[str]) -> Dict[str, float]:
    return {n: 1.0 / len(names) for n in names}


def current(con, market: str, horizon: int, source: str, names: Sequence[str], upto: Optional[date] = None) -> Dict[str, float]:
    """The weights in force: the latest stored for (market, source, horizon) on or before `upto`; live starts from the replay's last weights, else uniform.
    A forecaster with no stored weight gets the mean of the others' floor-lifted share (then all are re-normalised)."""
    def latest(src):
        q = "SELECT forecaster, weight, as_of FROM forecaster_weights WHERE market=? AND source=? AND horizon_sessions=?"
        a = [market, src, horizon]
        if upto is not None:
            q += " AND as_of<=?"
            a.append(upto)
        rows = con.execute(q + " ORDER BY as_of DESC", a).fetchall()
        if not rows:
            return {}
        top = rows[0][2]
        return {f: w for f, w, d in rows if d == top}
    got = latest(source) or (latest("replay") if source == "live" else {})
    w = {n: got.get(n) for n in names}
    known = [v for v in w.values() if v is not None]
    if not known:
        return uniform(names)
    fill = 1.0 / len(names)
    w = {n: (v if v is not None else fill) for n, v in w.items()}
    s = sum(w.values())
    return {n: v / s for n, v in w.items()}


def n_updates(con, market: str, horizon: int, source: str) -> int:
    r = con.execute("SELECT max(n) FROM forecaster_weights WHERE market=? AND source=? AND horizon_sessions=?", [market, source, horizon]).fetchone()
    return int(r[0] or 0)


def store(con, market: str, source: str, horizon: int, as_of: date, w: Dict[str, float], n: int, now: datetime) -> None:
    con.execute("DELETE FROM forecaster_weights WHERE market=? AND source=? AND horizon_sessions=? AND as_of=?", [market, source, horizon, as_of])
    con.executemany("INSERT INTO forecaster_weights VALUES (?,?,?,?,?,?,?,?)",
                    [[market, source, horizon, f, as_of, float(v), int(n), now] for f, v in w.items()])


def combine(quantiles: Dict[str, Dict[float, float]], w: Dict[str, float]) -> Optional[Dict[float, float]]:
    """The hedge forecast: the weighted average of the forecasters' quantiles (a Vincentisation: it keeps the order). Only forecasters present count."""
    names = [n for n in quantiles if quantiles[n] is not None and n in w]
    if not names:
        return None
    tot = sum(w[n] for n in names)
    out = {}
    for q in P.LEVELS:
        out[float(q)] = sum(w[n] * quantiles[n][float(q)] for n in names) / tot
    return out
