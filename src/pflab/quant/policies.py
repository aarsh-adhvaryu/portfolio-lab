"""Deployment policies across market paths (S68): a HYPOTHETICAL SCENARIO study, trusted code, deterministic and reproducible.

The question it answers is the investor's: "I have a sum to put into shares (an FD maturing, a monthly amount). Should I put it in now, in
equal monthly tranches (his current approach), in phased tranches with explicit rules, or keep it in cash until a fall? What happens to each
across a sharp fall, a prolonged decline, a fall and a recovery, and no crash?"

What this is, and is not (kept in every result):
    - the PATHS are assumptions he can see (the size and speed of the fall, the decline, the recovery, the drift): they are not forecasts and
      carry no probability unless the caller supplies weights, which are then labelled assumptions, not estimates;
    - the POLICIES are rules written down here with their parameters; nothing is tuned on the paths;
    - money in waiting earns `cash_rate_pa` (a debt/FD rate, an assumption);
    - transaction costs are `cost_bps` per rupee invested (an assumption); tax is not modelled (the numbers are pre-tax);
    - it says nothing about whether a crash will happen. Options-implied probabilities, if ever used, are risk-neutral and belong elsewhere.

`run(**params)` returns the whole study as a dict; with the same parameters it returns the same numbers (the noise uses a fixed seed).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

SHAPES = ("sharp_fall", "prolonged_decline", "fall_and_recovery", "no_crash")
POLICIES = ("lump_now", "current_staged", "phased_rules", "cash_until_fall")
VERSION = "policies-1"


def levels(shape: str, horizon: int, *, fall_pct: float = 20.0, fall_months: int = 2, decline_pct: float = 30.0, decline_months: int = 18,
           recover_months: int = 10, drift_pa: float = 0.10) -> np.ndarray:
    """The index level at the end of each month 0..horizon (level[0] = 1.0), as a piecewise-linear path in log terms."""
    drift_m = (1 + drift_pa) ** (1 / 12) - 1
    lv = np.ones(horizon + 1)
    if shape == "no_crash":
        for t in range(1, horizon + 1):
            lv[t] = lv[t - 1] * (1 + drift_m)
    elif shape in ("sharp_fall", "fall_and_recovery"):
        low = 1 - fall_pct / 100.0
        for t in range(1, horizon + 1):
            if t <= fall_months:
                lv[t] = np.exp(np.log(1.0) + (np.log(low) - 0.0) * t / fall_months)
            elif shape == "fall_and_recovery" and t <= fall_months + recover_months:
                k = (t - fall_months) / recover_months
                lv[t] = np.exp(np.log(low) * (1 - k))                              # back to the pre-fall level
            elif shape == "fall_and_recovery":
                lv[t] = lv[t - 1] * (1 + drift_m)
            else:
                lv[t] = lv[t - 1]                                                   # a sharp fall that does not recover within the horizon
    elif shape == "prolonged_decline":
        low = 1 - decline_pct / 100.0
        for t in range(1, horizon + 1):
            lv[t] = np.exp(np.log(low) * min(t, decline_months) / decline_months)
    else:
        raise ValueError(f"shape must be one of {SHAPES}")
    return lv


def _noisy(lv: np.ndarray, vol_pa: float, rng: np.random.Generator) -> np.ndarray:
    """The same path with month-to-month noise that returns to the path (a bridge), so the shape stays what was stated."""
    h = len(lv) - 1
    if vol_pa <= 0 or h <= 1:
        return lv
    eps = rng.normal(0.0, vol_pa / np.sqrt(12), h)
    walk = np.cumsum(eps)
    bridge = walk - (np.arange(1, h + 1) / h) * walk[-1]
    out = lv.copy()
    out[1:] = lv[1:] * np.exp(bridge)
    return out


def simulate(policy: str, lv: np.ndarray, amount: float, *, cash_rate_pa: float = 0.07, cost_bps: float = 10.0, staged_months: int = 10,
             base_months: int = 6, reserve_share: float = 0.4, dip_trigger: float = 0.10, wait_trigger: float = 0.15, max_wait: int = 12) -> dict:
    """One policy on one path. Decisions are made at the START of month t from levels up to t (lv[t]); the return of month t accrues to
    what is held during it. Returns the value path and its summary."""
    h = len(lv) - 1
    cm = (1 + cash_rate_pa) ** (1 / 12) - 1
    cash, units, spent, paid_cost = amount, 0.0, 0.0, 0.0
    values = np.zeros(h + 1)
    reserve = amount * reserve_share if policy == "phased_rules" else 0.0
    peak = lv[0]
    for t in range(h):
        peak = max(peak, lv[t])
        buy = 0.0
        if policy == "lump_now":
            buy = cash if t == 0 else 0.0
        elif policy == "current_staged":
            buy = min(cash, amount / staged_months) if t < staged_months else 0.0
        elif policy == "phased_rules":
            base = (amount - reserve_total(amount, reserve_share)) / base_months
            buy = min(max(cash - reserve, 0.0), base) if t < base_months else 0.0
            if reserve > 0 and (lv[t] <= peak * (1 - dip_trigger) or t == base_months):
                buy += reserve
                reserve = 0.0
            buy = min(buy, cash)
        elif policy == "cash_until_fall":
            if lv[t] <= lv[0] * (1 - wait_trigger) or t >= max_wait:
                buy = cash
        else:
            raise ValueError(f"policy must be one of {POLICIES}")
        if buy > 0:
            c = buy * cost_bps / 1e4
            paid_cost += c
            units += (buy - c) / lv[t]
            cash -= buy
            spent += buy
        values[t] = units * lv[t] + cash
        cash *= 1 + cm                                                              # what waits earns the cash rate during the month
    values[h] = units * lv[h] + cash
    v = values
    run_peak = np.maximum.accumulate(v)
    dd = float(np.min(v / run_peak - 1)) * 100
    under = int(np.sum(v < amount * 0.9999))
    first_back = next((t for t in range(1, h + 1) if v[t] >= amount * 0.9999 and np.any(v[:t] < amount * 0.9999)), None)
    return {"policy": policy, "terminal": float(v[h]), "return_pct": float(v[h] / amount - 1) * 100, "worst_value_vs_amount_pct": float(np.min(v) / amount - 1) * 100,
            "max_drawdown_pct": dd, "months_below_amount": under, "back_to_amount_month": first_back, "costs": float(paid_cost),
            "invested_by_end_pct": min(100.0, float(spent / amount) * 100)}       # (interest earned while waiting is reinvested; the principal is 100%)


def reserve_total(amount: float, share: float) -> float:
    return amount * share


def run(amount: float = 1_000_000.0, horizon_months: int = 24, *, fall_pct: float = 20.0, fall_months: int = 2, decline_pct: float = 30.0,
        decline_months: int = 18, recover_months: int = 10, drift_pa: float = 0.10, vol_pa: float = 0.15, n_noise: int = 300, seed: int = 20261031,
        cash_rate_pa: float = 0.07, cost_bps: float = 10.0, staged_months: int = 10, base_months: int = 6, reserve_share: float = 0.4,
        dip_trigger: float = 0.10, wait_trigger: float = 0.15, max_wait: int = 12, weights: Optional[Dict[str, float]] = None,
        sensitivity: bool = True, label: str = "") -> dict:
    """The study. `amount` is an ASSUMPTION unless the caller took it from his plan: it only scales the rupee columns; the percentages do not
    depend on it."""
    pol = dict(cash_rate_pa=cash_rate_pa, cost_bps=cost_bps, staged_months=staged_months, base_months=base_months, reserve_share=reserve_share,
               dip_trigger=dip_trigger, wait_trigger=wait_trigger, max_wait=max_wait)
    shape_kw = dict(fall_pct=fall_pct, fall_months=fall_months, decline_pct=decline_pct, decline_months=decline_months, recover_months=recover_months, drift_pa=drift_pa)
    table, rng = [], np.random.default_rng(seed)
    for shape in SHAPES:
        lv = levels(shape, horizon_months, **shape_kw)
        clean = {p: simulate(p, lv, amount, **pol) for p in POLICIES}
        noisy = {p: [] for p in POLICIES}
        for _ in range(n_noise):
            path = _noisy(lv, vol_pa, rng)
            for p in POLICIES:
                noisy[p].append(simulate(p, path, amount, **pol))
        for p in POLICIES:
            ret = np.array([r["return_pct"] for r in noisy[p]])
            dd = np.array([r["max_drawdown_pct"] for r in noisy[p]])
            table.append({"path": shape, **clean[p], "noisy": {"n": n_noise, "return_pct_mean": float(ret.mean()), "return_pct_p5": float(np.percentile(ret, 5)),
                                                                "return_pct_p95": float(np.percentile(ret, 95)), "max_drawdown_pct_mean": float(dd.mean())}})
    best = {s: max((r for r in table if r["path"] == s), key=lambda r: r["terminal"])["policy"] for s in SHAPES}
    out = {"kind": "scenario", "version": VERSION, "label": label, "assumptions": {
        "amount_rupees": amount, "horizon_months": horizon_months, **shape_kw, "vol_pa": vol_pa, "noise_paths": n_noise, "seed": seed, **pol,
        "note": "every one of these is an assumption, not an estimate: the paths are stated shapes, not forecasts; no tax; costs and the cash rate as stated"},
        "policies": {"lump_now": "all in at the start", "current_staged": f"equal tranches over {staged_months} months (his current FD approach)",
                     "phased_rules": f"{base_months} monthly base tranches of {(1 - reserve_share):.0%} plus a reserve of {reserve_share:.0%} bought on a {dip_trigger:.0%} fall from the "
                                     f"peak seen, or after {base_months} months",
                     "cash_until_fall": f"all in cash until the level is {wait_trigger:.0%} below the start, or {max_wait} months"},
        "table": table, "best_terminal_by_path": best}
    if weights:
        tot = sum(weights.values())
        out["weighted"] = {"weights_are": "assumptions supplied by the caller, not estimated", "by_policy": {
            p: sum(weights.get(s, 0) / tot * next(r for r in table if r["path"] == s and r["policy"] == p)["return_pct"] for s in SHAPES) for p in POLICIES}}
    if sensitivity:
        grid = []
        for fp in (10.0, 20.0, 35.0):
            lv = levels("fall_and_recovery", horizon_months, **{**shape_kw, "fall_pct": fp})
            lp = levels("prolonged_decline", horizon_months, **{**shape_kw, "decline_pct": fp})
            for dt in (0.05, 0.10, 0.15, 0.20):
                for sm in (6, 10, 12):
                    a = simulate("phased_rules", lv, amount, **{**pol, "dip_trigger": dt})["return_pct"]
                    b = simulate("current_staged", lv, amount, **{**pol, "staged_months": sm})["return_pct"]
                    c = simulate("lump_now", lv, amount, **pol)["return_pct"]
                    d = simulate("cash_until_fall", lp, amount, **{**pol, "wait_trigger": dt})["return_pct"]
                    e = simulate("lump_now", lp, amount, **pol)["return_pct"]
                    grid.append({"fall_or_decline_pct": fp, "dip_or_wait_trigger": dt, "staged_months": sm, "recovery: phased_rules_return_pct": a,
                                 "recovery: current_staged_return_pct": b, "recovery: lump_now_return_pct": c, "decline: cash_until_fall_return_pct": d,
                                 "decline: lump_now_return_pct": e})
        out["sensitivity"] = grid
    return out


def summary_lines(res: dict, top: int = 16) -> List[str]:
    """A compact reading of a study for a model or a card: one line per path and policy, with its assumptions named."""
    out = [f"SCENARIO STUDY ({res['version']}): amount Rs {res['assumptions']['amount_rupees']:,.0f} (assumed), horizon {res['assumptions']['horizon_months']} months; "
           "paths are stated shapes, not forecasts."]
    for r in res["table"][:top]:
        out.append(f"{r['path']:<18} {r['policy']:<16} return {r['return_pct']:+6.1f}%  worst value vs amount {r['worst_value_vs_amount_pct']:+6.1f}%  "
                   f"max drawdown {r['max_drawdown_pct']:6.1f}%  invested by end {r['invested_by_end_pct']:.0f}%")
    return out
