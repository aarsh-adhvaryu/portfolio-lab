"""The US sub-book's side of the picks sleeve (S83 L8, A62): the glue between `core/picks.py` (market "US") and `us/policy.py` / `us/adapter.py`. Thin: the sizing, the share and the rules are the
picks module's; the rails are the sub-book's own (a stock at most `[picks] us_stock_cap` = 10%, at most 12 stocks, SPY at least `us_spy_floor` = 30% of the sub-book).

    symbols(con)                   the symbols of the US picks the book holds or waits to hold (proposed, buying, held, withdrawn): their bars are loaded and they are rows of the state
    extra_weights(con, state)      -> {"extra": {symbol: weight}, "core_total": float, "notes": [...]}: the picks' target weights (code-sized, `picks.target_weights`), a withdrawn pick at 0 (sold at
                                   the next US open: the 12-month guard of the rupee book has no US counterpart yet, said in the order's reason), the picks' total held to `invested_share - SPY floor` so
                                   SPY's target is never under the floor, and the SPY share of the sub-book that is left (`core_total`)

A pick with no bar today is not bought or sold that session (the sub-book works from daily closes, A59).
"""
from __future__ import annotations

from typing import Dict, List

from pflab.core import picks, pick_share

LIVE = ("proposed", "buying", "held", "withdrawn")


def symbols(con) -> List[str]:
    """Symbols of the US picks in a live state (empty when the picks are off for the US or the table is unreadable)."""
    try:
        if not pick_share.on("US"):
            return []
        return [p["symbol"].upper() for p in picks.managed(con, "US")]
    except Exception:
        return []


def extra_weights(con, state: dict) -> dict:
    """The pick names' target weights for the US decision. `state` is `us.policy.build`'s state after `picks.attach(con, state, "US")`."""
    out: Dict[str, float] = {}
    notes: List[str] = []
    s = state["settings"]
    invested = float(s["invested_share"])
    pk = (state.get("picks") or {}).get("weights") or {}
    if not pk:
        return {"extra": {}, "core_total": invested, "notes": notes}
    c = pick_share.settings("US")
    floor = float(c["us_spy_floor"])
    by_key = {r["isin"]: r for r in state["rows"]}
    withdrawn = {p["isin"] for p in picks.managed(con, "US") if p["state"] == "withdrawn"}
    try:                                                                  # S84 (A65): a name under a thinking-loop freeze is not bought (its target is what the sub-book holds)
        from pflab.think import cases as _tcases
        frozen = set(_tcases.frozen_isins(con, state.get("day"), "US"))
    except Exception:
        frozen = set()
    total_v = float(state.get("value") or 0.0)
    for k, w in pk.items():
        r = by_key.get(k)
        if r is None or not r.get("buyable"):
            continue
        out[r["symbol"]] = 0.0 if k in withdrawn else float(w)
        if k in frozen and k not in withdrawn and total_v > 0:
            out[r["symbol"]] = min(out[r["symbol"]], float(r["value"]) / total_v)
            notes.append(f"{r['symbol']} is frozen (no new buying) by an open case")
    total = sum(out.values())
    room = max(0.0, invested - floor)                                   # SPY's target is at least the floor: the picks' total never passes what is left of the invested share
    if total > room + 1e-12 and total > 0:
        f = room / total
        out = {k: v * f for k, v in out.items()}
        notes.append(f"the picks' total {total:.0%} was brought to {room:.0%} so SPY keeps at least {floor:.0%} of the sub-book")
        total = room
    if any(v == 0.0 for v in out.values()):
        notes.append("a withdrawn pick is sold at the next US open (the rupee book's 12-month guard has no US counterpart yet; the order's reason carries the estimated tax)")
    return {"extra": out, "core_total": max(floor, invested - total), "notes": notes}
