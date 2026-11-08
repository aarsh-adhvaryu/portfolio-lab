"""The constrained optimiser of `construct` (S79b item 18A): mean-variance utility with the rails as hard constraints, trading costs and tax in the objective.

Variables are the purchases b and sales s of each name as fractions of the book (w = w0 + b - s, so a cost can be linear in each: |trade| without a kink).

    maximise   mu'w - (a/2) w'Sigma w - buy_cost'b - sell_cost's - turnover (sum b + sum s) - lam * sum_k max(0, |v_k - t_k| - band)^2

    subject to 0 <= s <= w0                      (no short sale)
               0 <= b <= ub - w0                 (a company at most 10%, one ETF 35%, a holding already over its rail is never forced out but not added to;
                                                  a name that may not be bought, or any name when the circuit breaker is on, has ub = w0)
               sum_i w_i <= 1                    (cash >= 0: no leverage, no borrowing)
               group_g' w <= cap_g               (a sector at most 25%, or what it already is when it is over)

`v` are the class and sector weights of the book (equity, gold, international, cash; sectors), `t` the system's own allocation target (`paper/allocation.py`): a soft
band, so a gap smaller than the band costs nothing. The solver is scipy's SLSQP from the current book (b = s = 0): deterministic, no random numbers. When it fails
or returns a point that breaks a constraint, `solve` says so and returns the current weights unchanged, and the caller falls back to the current sizing rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import minimize

EPS = 1e-6


@dataclass
class Problem:
    names: List[str]
    w0: np.ndarray                                 # current weights, fractions of the book's value (cash is the rest)
    mu: np.ndarray                                 # expected excess return per year over cash
    cov: np.ndarray                                # annual covariance
    ub: np.ndarray                                 # upper bound of each weight after trading (>= w0 by construction in `fix_bounds`)
    buy_cost: np.ndarray                           # per unit of weight bought (charges)
    sell_cost: np.ndarray                          # per unit of weight sold (charges + estimated tax)
    risk_aversion: float = 2.5
    turnover_penalty: float = 0.0                  # extra, per unit traded either way
    groups: Dict[str, Tuple[np.ndarray, float]] = field(default_factory=dict)      # name -> (0/1 mask, cap as a fraction of the book)
    target_A: Optional[np.ndarray] = None          # (m, n) maps weights to class/sector weights v = A w + target_b
    target_b: Optional[np.ndarray] = None
    target_t: Optional[np.ndarray] = None          # (m,) target fractions; NaN = no target for that row
    target_labels: List[str] = field(default_factory=list)
    target_band: float = 0.02
    target_lambda: float = 0.0
    frozen: Optional[np.ndarray] = None            # bool: cannot trade at all
    no_buy: Optional[np.ndarray] = None            # bool: may be sold, not bought (breaker, not listed, not a buyable class)
    no_sell: Optional[np.ndarray] = None           # bool: may be bought, not sold (the team asked to ADD it)
    budget: float = 1.0


def fix_bounds(p: Problem) -> np.ndarray:
    """Per-name purchase room: ub - w0 (never negative; zero when frozen or no-buy)."""
    room = np.maximum(p.ub - p.w0, 0.0)
    if p.no_buy is not None:
        room = np.where(p.no_buy, 0.0, room)
    if p.frozen is not None:
        room = np.where(p.frozen, 0.0, room)
    return room


def _target_pen(p: Problem, w: np.ndarray):
    if p.target_A is None or p.target_lambda <= 0:
        return 0.0, np.zeros_like(w)
    v = p.target_A @ w + p.target_b
    gap = v - p.target_t
    ok = np.isfinite(gap)
    ex = np.where(ok, np.maximum(np.abs(np.where(ok, gap, 0.0)) - p.target_band, 0.0), 0.0)
    pen = p.target_lambda * float(np.sum(ex ** 2))
    g = p.target_lambda * (p.target_A.T @ (2.0 * ex * np.sign(np.where(ok, gap, 0.0))))
    return pen, g


def objective_parts(p: Problem, w: np.ndarray, b: np.ndarray, s: np.ndarray) -> Dict[str, float]:
    pen, _ = _target_pen(p, w)
    return {"expected_excess": float(p.mu @ w), "risk_penalty": float(0.5 * p.risk_aversion * w @ p.cov @ w),
            "costs": float(p.buy_cost @ b + p.sell_cost @ s), "turnover_penalty": float(p.turnover_penalty * (b.sum() + s.sum())), "target_penalty": float(pen)}


def utility(p: Problem, w: np.ndarray, b: Optional[np.ndarray] = None, s: Optional[np.ndarray] = None) -> float:
    """The objective at weights w (b and s default to the trades from w0). Higher is better."""
    d = w - p.w0
    b = np.maximum(d, 0.0) if b is None else b
    s = np.maximum(-d, 0.0) if s is None else s
    o = objective_parts(p, w, b, s)
    return o["expected_excess"] - o["risk_penalty"] - o["costs"] - o["turnover_penalty"] - o["target_penalty"]


def solve(p: Problem, max_iter: int = 400) -> dict:
    """Solve. Returns {ok, weights, b, s, converged, message, binding, parts, utility, utility_now}; ok False means nothing here may be used."""
    n = len(p.names)
    w0 = np.asarray(p.w0, float)
    out = {"ok": False, "weights": w0.copy(), "converged": False, "message": "", "binding": [], "parts": {}, "utility": None, "utility_now": None}
    try:
        if n == 0:
            out["message"] = "no candidates"
            return out
        if not (np.all(np.isfinite(p.cov)) and np.all(np.isfinite(p.mu)) and np.all(np.isfinite(w0))):
            out["message"] = "non-finite inputs"
            return out
        room = fix_bounds(p)
        s_hi = w0.copy()
        if p.frozen is not None:
            s_hi = np.where(p.frozen, 0.0, s_hi)
        if p.no_sell is not None:
            s_hi = np.where(p.no_sell, 0.0, s_hi)
        budget = max(float(p.budget), 0.0)
        # a book that is over its budget (cash below zero) must be able to sell down to it: the budget row is then the binding rule
        scale = 100.0
        gcaps = {k: (np.asarray(m, float), float(c)) for k, (m, c) in p.groups.items()}

        def f(x):
            b, s = x[:n], x[n:]
            w = w0 + b - s
            cw = p.cov @ w
            pen, gpen = _target_pen(p, w)
            val = -(p.mu @ w) + 0.5 * p.risk_aversion * (w @ cw) + p.buy_cost @ b + p.sell_cost @ s + p.turnover_penalty * (b.sum() + s.sum()) + pen
            gw = -p.mu + p.risk_aversion * cw + gpen
            return scale * val, scale * np.concatenate([gw + p.buy_cost + p.turnover_penalty, -gw + p.sell_cost + p.turnover_penalty])

        cons = [{"type": "ineq", "fun": lambda x: budget - (w0 + x[:n] - x[n:]).sum(), "jac": lambda x: np.concatenate([-np.ones(n), np.ones(n)])}]
        for k, (m, c) in gcaps.items():
            cons.append({"type": "ineq", "fun": (lambda x, m=m, c=c: c - m @ (w0 + x[:n] - x[n:])), "jac": (lambda x, m=m: np.concatenate([-m, m]))})
        bounds = [(0.0, float(r)) for r in room] + [(0.0, float(h)) for h in s_hi]
        x0 = np.zeros(2 * n)
        res = minimize(f, x0, jac=True, bounds=bounds, constraints=cons, method="SLSQP", options={"maxiter": max_iter, "ftol": 1e-12})
        x = np.clip(res.x, [lo for lo, _ in bounds], [hi for _, hi in bounds])
        b, s = x[:n], x[n:]
        d = b - s
        d = np.where(np.abs(d) < EPS, 0.0, d)                       # dust is no trade
        w = w0 + d
        b, s = np.maximum(d, 0.0), np.maximum(-d, 0.0)
        # hard checks: the rails must hold on the result whatever the solver said
        bad = []
        if np.any(w < -1e-9):
            bad.append("a weight below zero")
        if np.any(b > room + 1e-7):
            bad.append("a purchase over its room")
        if w.sum() > budget + 1e-7:
            bad.append("cash would go below zero")
        for k, (m, c) in gcaps.items():
            if m @ w > c + 1e-7 and (m @ w) > (m @ w0) + 1e-9:
                bad.append(f"group {k} over its cap")
        if not np.all(np.isfinite(w)):
            bad.append("non-finite weights")
        u_now, u_new = utility(p, w0), utility(p, w, b, s)
        out.update(converged=bool(res.success), message=str(res.message)[:120], utility_now=float(u_now))
        if bad:
            out["message"] = "; ".join(bad)
            return out
        if u_new < u_now - 1e-9:                                    # a worse point than doing nothing is never returned
            out.update(ok=True, weights=w0.copy(), b=np.zeros(n), s=np.zeros(n), utility=float(u_now), message="no trade beats doing nothing after costs and tax",
                       parts=objective_parts(p, w0, np.zeros(n), np.zeros(n)), binding=binding(p, w0, room, gcaps, budget))
            return out
        out.update(ok=True, weights=w, b=b, s=s, utility=float(u_new), parts=objective_parts(p, w, b, s), binding=binding(p, w, room, gcaps, budget))
        return out
    except Exception as e:                                          # the caller falls back to the current rules
        out["message"] = f"optimiser failed: {type(e).__name__}: {str(e)[:100]}"
        return out


def binding(p: Problem, w: np.ndarray, room: np.ndarray, gcaps: Dict[str, Tuple[np.ndarray, float]], budget: float) -> List[str]:
    """Which constraints are tight at w (within a hundredth of a point), in plain words."""
    out = []
    tol = 1e-4
    for i, nm in enumerate(p.names):
        top = p.w0[i] + room[i]
        if p.frozen is not None and p.frozen[i]:
            continue
        if room[i] <= 1e-9 and p.no_buy is not None and p.no_buy[i] and p.w0[i] > 0:
            out.append(f"{nm}: no new buying allowed")
        elif w[i] >= top - tol and top > 0 and room[i] > 1e-9:
            out.append(f"{nm}: at its cap {top:.1%}")
        if w[i] <= tol and p.w0[i] > tol:
            out.append(f"{nm}: sold out")
    for k, (m, c) in gcaps.items():
        if m @ w >= c - tol:
            out.append(f"group {k}: at its cap {c:.1%}")
    if w.sum() >= budget - tol:
        out.append("fully invested (cash at zero)")
    return out
