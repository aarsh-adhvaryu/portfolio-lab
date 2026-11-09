"""Exemption and loss harvesting as a plain function (S81 B5, protocol `docs/protocols/s81_selling_swing_protocol.md` section 5).

SELF-CONTAINED (standard library only): the same file runs in the Docker sandbox beside `swing.py` and on the host. The exit manager (`core/exits.py`, B4) may call
`harvest_step` with the same arguments; the exits module was not available when this was written, so this is the minimal rule from the A51 brief:

* Window: the last quarter of the financial year (1 January to 31 March).
* Exemption harvest: book long-term gains up to the yearly long-term exemption (the room left after the year's gains so far) by selling lots held more than 12 months, and buy the
  same quantity back next session (the caller does that: a same-day round trip in a name is not allowed). The cost price is thereby reset.
* Loss harvest: when the year has taxable gains, sell lots at a loss to offset them (and buy back next session).
* Lots are taken OLDEST FIRST per name (the book is FIFO: a lot cannot be picked out of order); a winner not yet long-term is never sold here (the 12-month guard).
* Each sale must pay for its round trip: the tax saved must exceed `round_trip_cost` of the proceeds.

Rates and the exemption are NOT typed here: the caller passes them (`params["tax"]`, read from the tax engine's dated rows).
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from dateutil.relativedelta import relativedelta

DEFAULT_RULE = {"window_months": [1, 2, 3], "fill_fraction": 0.98, "round_trip_cost": 0.004, "guard_days": 30, "lt_months": 12, "min_room": 2000.0}


def is_long_term(acquired: date, day: date, months: int = 12) -> bool:
    """Held for MORE than `months` calendar months (the tax engine's rule: selling on the anniversary is short-term)."""
    return day > acquired + relativedelta(months=months)


def in_window(day: date, rule: Optional[dict] = None) -> bool:
    return day.month in tuple((rule or DEFAULT_RULE)["window_months"])


def harvest_step(day: date, lots: Dict[str, list], prices: Dict[str, float], gains_ytd: Dict[str, float], params: dict, blocked=()) -> List[dict]:
    """The sales to make today. `lots`: {key: [[acquired, qty, cost_per_unit], ...]} oldest first; `prices`: {key: price}; `gains_ytd`: the financial year's realised gains by bucket
    ({"st_eq","lt_eq","lt_other","slab"}); `params`: {"tax": {"lt_exempt","lt_rate","st_rate"}, optional rule overrides}; `blocked`: names not to touch today (traded today).
    Returns [{"key","qty","kind":"harvest","reason", "buy_back": True, "expected_gain"}]; the caller sells them at today's close and buys the same quantity back at the next
    session's close."""
    rule = {**DEFAULT_RULE, **{k: v for k, v in params.items() if k in DEFAULT_RULE}}
    tax = params["tax"]
    if not in_window(day, rule):
        return []
    exempt, lt_rate, st_rate = float(tax["lt_exempt"]), float(tax["lt_rate"]), float(tax["st_rate"])
    st, lt = float(gains_ytd.get("st_eq", 0.0)), float(gains_ytd.get("lt_eq", 0.0))
    lt_net = lt + min(0.0, st)                                                  # a short-term loss sets off a long-term gain
    st_net = max(0.0, st)
    room = max(0.0, exempt - max(0.0, lt_net))
    out: List[dict] = []
    months = int(rule["lt_months"])
    # 1. the exemption: oldest long-term lots with a gain, the key with the biggest unrealised long-term gain first
    if room >= rule["min_room"]:
        cand = []
        for k, ls in lots.items():
            if k in blocked or k not in prices:
                continue
            g = sum(q * (prices[k] - c) for a, q, c in ls if is_long_term(a, day, months) and prices[k] > c)
            if g > 0:
                cand.append((-g, k))
        remaining = room * rule["fill_fraction"]
        for _, k in sorted(cand):
            if remaining <= 0:
                break
            px, take, gain = prices[k], 0.0, 0.0
            for a, q, c in ls_of(lots, k):
                if not is_long_term(a, day, months) or px <= c:               # FIFO: the walk ends at the first lot that is not a long-term winner
                    break
                ug = px - c
                tq = min(q, (remaining - gain) / ug)
                if tq <= 0:
                    break
                take += tq
                gain += tq * ug
                if tq < q - 1e-9:
                    break
            if take > 0 and lt_rate * gain > rule["round_trip_cost"] * take * px:
                out.append({"key": k, "qty": take, "kind": "harvest", "buy_back": True, "expected_gain": gain,
                            "reason": f"harvest Rs {gain:,.0f} of long-term gain inside the yearly exemption (room Rs {room:,.0f}); buy back next session at a reset cost"})
                remaining -= gain
    # 2. losses against taxable gains
    taxable = st_net + max(0.0, lt_net - exempt)
    if taxable > 0:
        rate = st_rate if st_net > 0 else lt_rate
        left = taxable
        done = {o["key"] for o in out}
        for k in sorted(lots):
            if left <= 0:
                break
            if k in blocked or k in done or k not in prices:
                continue
            px, take, loss = prices[k], 0.0, 0.0
            for a, q, c in ls_of(lots, k):
                if px >= c:
                    break
                ul = c - px
                tq = min(q, (left - loss) / ul)
                if tq <= 0:
                    break
                take += tq
                loss += tq * ul
                if tq < q - 1e-9:
                    break
            if take > 0 and rate * loss > rule["round_trip_cost"] * take * px:
                out.append({"key": k, "qty": take, "kind": "harvest", "buy_back": True, "expected_gain": -loss,
                            "reason": f"harvest a loss of Rs {loss:,.0f} against this year's taxable gains; buy back next session at a lower cost"})
                left -= loss
    return out


def ls_of(lots: Dict[str, list], k: str) -> list:
    return lots.get(k, [])
