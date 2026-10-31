"""A provisional tax figure for shares Kite shows and the statements do not yet (S68; his request 2026-10-31).

A new allotment appears in Kite the day it is credited; the tradebook and the depository statement follow weeks later. Until they do, the ledger has no lot
for it and the tax engine cannot work. This module takes what Kite says (the extra quantity and its average price) as an ESTIMATE, never as the record:

    quantity     Kite's quantity above the ledger's, for the same ISIN (`pm/today` differences)
    cost         Kite's average price per share (what Kite calls average_price); an IPO's is the issue price. Brokerage and charges are not in it.
    date held    unknown: taken as recent (under a year), so the short-term rate applies. If it is older the real tax is lower; a statement settles it.
    rate         `stcg_rate` of configs/tax_policy_in.toml (the sourced, dated table), applied to a gain only; a loss gives 0 tax and no refund is implied
    price        today's price in the record (or Kite's last price)

Every line says `estimate, from Kite`, what it assumes, and what replaces it (the contract note, the tradebook or the depository statement).
It never writes to the ledger and is never a lot: when the statements arrive the engine's own figure replaces it.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import List, Optional

LABEL = "estimate, from Kite"


def stcg_rate() -> Optional[float]:
    try:
        from pflab import _toml
        return float(_toml.load(Path(__file__).resolve().parents[3] / "configs" / "tax_policy_in.toml")["stcg_rate"])
    except Exception:
        return None


def estimates(con, asof: date, rate: Optional[float] = None) -> List[dict]:
    """One estimate per holding Kite shows beyond the ledger. Empty when Kite has no snapshot newer than the statements or nothing differs."""
    from pflab.calc import valuation as val
    from pflab.pm import today
    rate = stcg_rate() if rate is None else rate
    info = today.build(con, asof).get("today") or {}
    if info.get("source") != "kite":
        return []
    price_fn = val.store_price_fn(con)
    out = []
    for d in info.get("diffs") or []:
        extra = float(d["kite"]) - float(d["ledger"])
        if extra <= 0:                                           # Kite shows fewer than the ledger: a sale, not a new holding
            continue
        cost = float(d.get("price_used") or 0.0)
        p = price_fn(d["isin"], asof)
        px = float(p.value) if p is not None else cost
        gain = (px - cost) * extra
        tax = max(gain, 0.0) * rate if rate is not None else None
        out.append({"isin": d["isin"], "symbol": d.get("symbol"), "label": LABEL, "quantity": extra, "average_price": cost, "price_now": px,
                    "price_date": str(getattr(p, "date", "") or "")[:10], "cost_total": cost * extra, "value_now": px * extra,
                    "unrealised_gain": gain, "short_term_rate": rate, "tax_if_sold_now": tax,
                    "assumes": ["the shares were bought within the last year (short-term rate); if older the real tax is lower",
                                "Kite's average price is the cost (brokerage and statutory charges are not in it)",
                                "a loss gives no tax and none is refunded or carried forward here"],
                    "replaced_by": "the tradebook or contract note and the depository statement: the tax engine then works from the real lot",
                    "not_a_lot": True})
    return out


def lines(est: List[dict]) -> List[str]:
    return [f"{e['symbol'] or e['isin']}: {e['quantity']:g} share(s), cost Rs {e['average_price']:,.2f} each ({LABEL}), now Rs {e['price_now']:,.2f}: gain Rs "
            f"{e['unrealised_gain']:,.0f}, tax if sold now about Rs {e['tax_if_sold_now']:,.0f} at {e['short_term_rate']:.0%} (ESTIMATE: the statements have not caught up)"
            for e in est if e["tax_if_sold_now"] is not None]
