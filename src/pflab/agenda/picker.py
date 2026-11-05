"""Which item next. Score = expected value x the kind's yield multiplier / cost, inside what the clock's MODE and the money governor allow.

    session      the market is trading: only free, short, local items (the live watch has the machine)
    pre_open     rupees up to PRE_RUPEES and up to PRE_SECONDS an item
    post_close   the same as pre_open
    deep         anything the budget allows
Cost for the ratio is rupees plus time at SECOND_RUPEES a second (so a free 5-second item beats a free 5-minute one of the same value).
Work that is urgent (an open mission, an order he gave) pre-empts the agenda altogether: `urgent_pending`.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from pflab.agenda import items

SESSION_SECONDS = 20.0
PRE_RUPEES, PRE_SECONDS = 5.0, 120.0
SECOND_RUPEES = 0.01
MIN_COST = 0.05
URGENT_TASK_STATES = ("queued", "running", "retry")


def urgent_pending(con) -> bool:
    """True when something more urgent than the agenda is open: a task on the board that is queued, running or being retried (every open mission's work and every
    order he gave goes through it; a mission only waiting for a sandbox or for him has no such task). A question waiting FOR him is not urgent work: it waits on him."""
    try:
        return bool(con.execute("SELECT 1 FROM hq_tasks WHERE status IN ('queued','running','retry') LIMIT 1").fetchone())
    except Exception:
        return False


def cost_of(item: dict) -> float:
    return max(MIN_COST, float(item.get("cost_rupees") or 0.0) + float(item.get("cost_seconds") or 0.0) * SECOND_RUPEES)


def score(item: dict, mult: float) -> float:
    return float(item.get("expected_value") or 0.0) * mult / cost_of(item)


def mode_refusal(item: dict, mode: str) -> Optional[str]:
    """Why the MODE keeps this item for later, or None."""
    rup, sec = float(item.get("cost_rupees") or 0.0), float(item.get("cost_seconds") or 0.0)
    if mode == "session" and (rup > 0 or sec > SESSION_SECONDS):
        return f"held back while the market is trading (costs Rs {rup:.2f} and about {sec:.0f} s; only free items up to {SESSION_SECONDS:.0f} s)"
    if mode in ("pre_open", "post_close") and (rup > PRE_RUPEES or sec > PRE_SECONDS):
        return f"held back until the evening or night (costs Rs {rup:.2f} and about {sec:.0f} s)"
    return None


def budget_refusal(con, item: dict, now: datetime) -> Optional[str]:
    """Why the money governor would refuse this item, or None. A free (local) item is never refused here."""
    rup = float(item.get("cost_rupees") or 0.0)
    if rup <= 0:
        return None
    try:
        from pflab import guard
        why = guard.blocked("paid")
        if why:
            return why
        from pflab.hq import governor as gv
        sp = gv.spend(con, now)
        if sp["cap"] <= 0:
            return "no monthly cap is set: nothing paid is sent"
        if rup > sp["left"]:
            return f"over the monthly cap (Rs {sp['left']:.0f} left, this costs Rs {rup:.2f})"
        for lay in sp["layers"]:
            if lay["layer"] == "workers" and lay["today"] + rup > lay["day_cap"]:
                return f"over the workers' day limit (Rs {lay['today']:.0f} of Rs {lay['day_cap']:.0f} today)"
    except Exception as e:
        return f"the budget could not be checked ({type(e).__name__})"
    return None


def candidates(con, market: str, mode: str, now: datetime, mark: bool = True) -> Tuple[List[dict], List[dict]]:
    """(eligible items with their score, held items with the reason). With `mark`, stale and over-budget items are skipped for good (state 'skipped', reason kept)."""
    ok, held = [], []
    for it in items.queued(con, market):
        if now - it["created_at"] > timedelta(days=items.STALE_DAYS):
            if mark:
                items.skip(con, it["item_id"], now, f"stale: queued more than {items.STALE_DAYS} days ago")
            continue
        why = budget_refusal(con, it, now)
        if why:
            if mark:
                items.skip(con, it["item_id"], now, why)
            continue
        m = items.multiplier(con, market, it["kind"])
        it = {**it, "multiplier": m, "score": round(score(it, m), 4)}
        why = mode_refusal(it, mode)
        if why:
            held.append({**it, "held": why})
        else:
            ok.append(it)
    ok.sort(key=lambda i: (-i["score"], i["item_id"]))
    return ok, held


def next_item(con, market: str, mode: str, now: datetime) -> Optional[dict]:
    """The best eligible queued item of this market in this mode, or None. Stale and over-budget items met on the way are skipped with their reason."""
    ok, _held = candidates(con, market, mode, now, mark=True)
    return ok[0] if ok else None
