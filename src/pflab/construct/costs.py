"""Charges and tax for `construct` (S79b item 18A). Everything here is an ESTIMATE and is labelled so wherever it is shown.

Charges   Zerodha's, from `configs/costs_zerodha_pm.toml` through `pm/costs.py` (the same numbers the paper book charges at a fill).
Tax       what a sale adds to the year's tax, by first-in-first-out lots: the paper book's own rules (`paper/book.py`: short-term equity 20%, long-term equity 12.5% above
          Rs 1.25 lakh a year, listed non-equity 12.5% after a year, else a 30% slab; set-off as the law allows). Cess and surcharge are not added.
In the optimiser's objective a sale costs `sell_rate + tax_rate` per rupee sold and a purchase `buy_rate` per rupee (a linear cost; `tax_rate` is the whole holding's blended
FIFO tax per rupee sold, today). After the optimiser has chosen, the exact FIFO charges and tax of each trade are computed again with `trade_cost` and reported.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

REF_NOTIONAL = 50_000.0            # a typical order, to turn the flat per-scrip charge into a per-rupee rate


def charge(asset_class: Optional[str], side: str, notional: float) -> float:
    """Rupees of Zerodha charges for one order (the paper book's own estimate, so the cost here is the cost the fill will take)."""
    if notional <= 0:
        return 0.0
    from pflab.paper import book
    return float(book._charges(asset_class, side, notional))


def rate(asset_class: Optional[str], side: str, ref: float = REF_NOTIONAL) -> float:
    """Charges as a fraction of the order's value, at a typical order size."""
    return charge(asset_class, side, ref) / ref


def lots_tax(lots: List[Tuple[date, float, float, Optional[str]]], px: float, qty: float, day: date, asset_class: Optional[str], tax_class: Optional[str] = None,
             fee: float = 0.0, year_gains: Optional[Dict[str, float]] = None) -> Tuple[float, Dict[str, float]]:
    """(the tax a sale of `qty` at `px` adds to the year, the gains by bucket) by FIFO over `lots` = [(acq_date, qty, cost_per_unit, tax_class)] oldest first."""
    from pflab.paper import book
    left, gains = qty, {}
    for acq, lq, cpu, tc in lots:
        if left <= 1e-12:
            break
        take = min(lq, left)
        b = book._bucket(tc or tax_class, asset_class, acq, day)
        gains[b] = gains.get(b, 0.0) + take * (px - cpu) - (fee * take / qty if qty > 0 else 0.0)
        left -= take
    before = dict(year_gains or {})
    after = dict(before)
    for k, v in gains.items():
        after[k] = after.get(k, 0.0) + v
    return float(book.tax_of(after) - book.tax_of(before)), gains


def tax_rate(lots, px: float, day: date, asset_class: Optional[str], tax_class: Optional[str] = None) -> float:
    """The blended tax per rupee sold if the whole holding were sold today by FIFO (the objective's linear tax cost; 0 for a holding at a loss: a loss is not a cost, and
    its set-off value is not claimed)."""
    qty = sum(l[1] for l in lots)
    if qty <= 0 or px <= 0:
        return 0.0
    t, _ = lots_tax(lots, px, qty, day, asset_class, tax_class)
    return max(0.0, t) / (qty * px)


def trade_cost(lots, px: float, qty: float, side: str, day: date, asset_class: Optional[str], tax_class: Optional[str] = None,
               year_gains: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """The exact estimate for one trade: {'charges', 'tax', 'notional'}. A buy has charges only."""
    notional = abs(qty) * px
    fee = charge(asset_class, side, notional)
    if side == "buy":
        return {"notional": notional, "charges": fee, "tax": 0.0}
    t, _ = lots_tax(lots, px, qty, day, asset_class, tax_class, fee, year_gains)
    return {"notional": notional, "charges": fee, "tax": max(0.0, t)}
