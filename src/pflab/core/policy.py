"""The champion policy. Phase 1 ships the BASELINE (`baseline_v1`), which needs no proven edge and acts from the first close:

    1. hold the system's own allocation target by class (equity, gold, international); with no active target, hold the class mix the book has now;
    2. inside a class, size each holding by its risk (weight proportional to 1 / volatility, the shrunk-covariance volatility), capped at the position rails;
    3. when the fall gauge fires, cut the equity class by `gauge_cut` and keep the difference in cash;
    4. rebalance a name only when it is more than `band_pts` points of the book from its target (the loop applies the band).

`decide(state)` is the whole interface a later, AI-written policy must keep: it returns the target weights (fractions of the book) of the holdings the book may trade, and
a note per decision. It never touches the rails, the data, the scoring or its own promotion (those are code outside it). Funds, SGBs and other holdings the book may not buy
are left where they are. Phase 1 trades only names already held: choosing new names is for the strategist's policies (phase 2), through the lab.
"""
from __future__ import annotations

import hashlib
import inspect
from typing import Dict, List

from pflab.paper import rails as hard

POLICY_ID = "baseline_v1"
TRADED_CLASSES = ("equity", "gold", "international")


def code_hash() -> str:
    return hashlib.sha256(inspect.getsource(__import__(__name__, fromlist=["x"])).encode("utf-8")).hexdigest()[:16]


def cap_of(row: dict) -> float:
    return hard.MAX_ETF if (row["asset_class"] or "") == "etf" else hard.MAX_STOCK


def risk_weights(budget: float, inv_vol: Dict[str, float], caps: Dict[str, float]) -> Dict[str, float]:
    """Split `budget` (a fraction of the book) in proportion to `inv_vol`, no name above its cap; what a cap leaves over is NOT given to others (it stays in cash)."""
    out: Dict[str, float] = {}
    live = dict(inv_vol)
    left = budget
    while live and left > 1e-12:
        tot = sum(live.values())
        over = {k: caps[k] for k, v in live.items() if left * v / tot > caps[k] + 1e-12}
        if not over:
            out.update({k: left * v / tot for k, v in live.items()})
            break
        for k, c in over.items():
            out[k] = c
            left -= c
            live.pop(k)
    return out


def decide(state: dict) -> dict:
    """-> {'weights': {isin: target fraction of the book}, 'notes': [...], 'classes': {class: fraction}}"""
    cfg = state["cfg"]["baseline"]
    total = float(state["value"])
    rows = state["rows"]
    notes: List[str] = []
    if total <= 0:
        return {"weights": {}, "notes": ["the book has no value"], "classes": {}}
    frac = {c: 0.0 for c in TRADED_CLASSES}
    fixed = {c: 0.0 for c in TRADED_CLASSES}                          # what the book holds in a class but may not trade (funds, SGBs, unpriced names)
    for r in rows:
        c = r["klass"]
        if c in frac:
            frac[c] += r["value"] / total
            if not r["buyable"]:
                fixed[c] += r["value"] / total
    if state["target"]:
        want = {c: float(state["target"]["classes"].get(c, 0.0)) / 100.0 for c in TRADED_CLASSES}
        notes.append(f"holding the system's allocation target #{state['target']['id']}")
    else:
        want = dict(frac)
        notes.append("no allocation target is active: holding the class mix the book has")
    if state["gauge"]["fired"] and want["equity"] > 0:
        cut = float(cfg["gauge_cut"])
        notes.append(f"fall gauge fired ({state['gauge']['why']}): equity cut by {cut:.0%}, the difference kept in cash")
        want["equity"] *= 1 - cut
    weights: Dict[str, float] = {}
    for c in TRADED_CLASSES:
        members = [r for r in rows if r["klass"] == c and r["buyable"]]
        if not members:
            continue
        budget = max(0.0, want[c] - fixed[c])
        inv = {r["isin"]: 1.0 / max(state["vol"].get(r["isin"], 0.30), 0.05) for r in members}
        caps = {r["isin"]: cap_of(r) for r in members}
        weights.update({k: 0.0 for k in inv})
        weights.update(risk_weights(budget, inv, caps))
    return {"weights": weights, "notes": notes, "classes": want}


# --- S81 (A48): which baseline decides -----------------------------------------------------------------------------------------------------------------------------------------------
# `decide` above is baseline_v1 and stays as it was (the safe fallback and the S80 tests). The loop asks `active_id()` / `decide_active()`: `[baseline_v2] version` picks v2 (default) or v1.
BASELINES = ("baseline_v1", "baseline_v2")


def active_id() -> str:
    from pflab import core
    return "baseline_v2" if core.baseline_version() == "v2" else POLICY_ID


def decide_active(state: dict) -> dict:
    """The baseline's decision for this close: v2 (core ETFs and the longterm names) unless the config falls back to v1."""
    if active_id() == "baseline_v2":
        from pflab.core import baseline_v2
        return baseline_v2.decide(state)
    return decide(state)


def universe(con, day=None, cfg=None) -> list:
    """Securities the active baseline may want that the book does not hold (they enter the state as rows with no quantity): the core ETFs under v2, none under v1."""
    if active_id() != "baseline_v2":
        return []
    from pflab import core
    from pflab.core import baseline_v2
    try:
        return baseline_v2.core_isins(con, cfg or core.settings())
    except Exception:
        return []


def registered() -> list:
    """(policy_id, code hash, note) of the baselines the store should list; the active one is the champion, the other 'previous'."""
    from pflab.core import baseline_v2
    return [(POLICY_ID, code_hash(), "the S80 baseline: hold the allocation target, size by risk, rebalance in a band, cut equity when the fall gauge fires"),
            (baseline_v2.POLICY_ID, baseline_v2.code_hash(), baseline_v2.NOTE)]
