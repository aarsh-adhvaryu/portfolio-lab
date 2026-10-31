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


def cess() -> float:
    try:
        from pflab import _toml
        return float(_toml.load(Path(__file__).resolve().parents[3] / "configs" / "tax_policy_in.toml")["tax"]["cess"])
    except Exception:
        return 0.0


def stcg_rate() -> Optional[float]:
    try:
        from pflab import _toml
        return float(_toml.load(Path(__file__).resolve().parents[3] / "configs" / "tax_policy_in.toml")["tax"]["stcg_rate"])
    except Exception:
        return None


def estimates(con, asof: date, rate: Optional[float] = None) -> List[dict]:
    """One estimate per holding Kite's LATEST snapshot shows beyond the record (all accounts). The snapshot may be older than the statements (the statements
    are dated to a day, a Kite login is not daily): its date is said on the line, and a holding the record now has is not estimated."""
    import pandas as pd
    from pflab.calc import networth as nw
    from pflab.calc import valuation as val
    from pflab.pm import today
    rate = stcg_rate() if rate is None else rate
    acc = today.broker(con)
    snap = today.latest(con, acc, asof) if acc else None
    if snap is None or snap.empty:
        return []
    taken = pd.Timestamp(snap["taken_at"].iloc[0]).to_pydatetime()
    kq, kpx, ksym, klast = {}, {}, {}, {}
    for r in snap[snap["kind"] != "cash"].itertuples():
        if not isinstance(r.isin, str) or not r.isin:
            continue
        kq[r.isin] = kq.get(r.isin, 0.0) + float(r.qty)
        ksym.setdefault(r.isin, r.symbol)
        if (r.kind == "today" and r.qty > 0) or (r.kind in ("holding", "fund") and r.isin not in kpx):
            kpx[r.isin] = float(r.avg_price or 0) or kpx.get(r.isin, 0.0)
    pos = nw.build(con, asof)["positions"]
    have = pos.groupby("isin")["qty"].sum().to_dict() if len(pos) else {}
    price_fn = val.store_price_fn(con)
    out = []
    for isin, q in kq.items():
        extra = q - float(have.get(isin, 0.0))
        if extra <= 1e-6:                                          # the record has it (or more): not a new holding
            continue
        cost = float(kpx.get(isin) or 0.0)
        p = price_fn(isin, asof)
        px = float(p.value) if p is not None else cost
        gain = (px - cost) * extra
        tax = max(gain, 0.0) * rate * (1 + cess()) if rate is not None else None          # the rate plus the health and education cess; surcharge (high incomes) is not in it
        out.append({"isin": isin, "symbol": ksym.get(isin), "label": LABEL, "kite_view_at": taken.isoformat(timespec="minutes"), "quantity": extra,
                    "average_price": cost, "price_now": px, "price_date": str(getattr(p, "date", "") or "")[:10], "cost_total": cost * extra,
                    "value_now": px * extra, "unrealised_gain": gain, "short_term_rate": rate, "tax_if_sold_now": tax,
                    "assumes": ["the shares were bought within the last year (short-term rate); if older the real tax is lower",
                                "Kite's average price is the cost (brokerage and statutory charges are not in it)",
                                f"Kite's view is from {taken:%Y-%m-%d %H:%M}; a later sale or purchase is not in it",
                                "a loss gives no tax and none is refunded or carried forward here",
                                "the rate includes the 4% cess; a surcharge, if your income is high, is not included"],
                    "replaced_by": "the tradebook or contract note and the depository statement: the tax engine then works from the real lot",
                    "not_a_lot": True})
    return out


def lines(est: List[dict]) -> List[str]:
    return [f"{e['symbol'] or e['isin']}: {e['quantity']:g} share(s), cost Rs {e['average_price']:,.2f} each ({LABEL}), now Rs {e['price_now']:,.2f}: gain Rs "
            f"{e['unrealised_gain']:,.0f}, tax if sold now about Rs {e['tax_if_sold_now']:,.0f} at {e['short_term_rate']:.0%} (ESTIMATE: the statements have not caught up; Kite's view of {e['kite_view_at']})"
            for e in est if e["tax_if_sold_now"] is not None]
