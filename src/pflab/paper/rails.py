"""The paper portfolio's safety rails (S76, his choice 2026-11-01: free inside rails). Code holds them; no model can pass them.

    one company       at most 10% of the paper portfolio after a buy
    one sector        at most 25% after a buy (companies only; the sector as the record names it)
    one ETF           at most 35% after a buy (an index or gold fund is a basket, not one company)
    what it may buy   listed shares and ETFs with a stored close; no F&O, no borrowing (a buy never spends more than the cash), no short sales
A holding already over a rail (his own concentration on the first day) is not sold by force: it is flagged, and the team decides.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List

MAX_STOCK, MAX_SECTOR, MAX_ETF = 0.10, 0.25, 0.35


def buy_room(con, isin: str, day: date) -> float:
    """Rupees that may still be bought of `isin` on `day` without passing a rail (0 when it may not be bought at all)."""
    from pflab.paper import book
    meta = book.inst(con, isin)
    if (meta["asset_class"] or "") not in book.BUYABLE or book.close_on(con, isin, day) is None:
        return 0.0
    h = book.holdings(con, day)
    total = h["value"]
    if total <= 0:
        return 0.0
    mine = sum(r["value"] or 0.0 for r in h["rows"] if r["isin"] == isin)
    if meta["asset_class"] == "etf":
        return max(0.0, MAX_ETF * total - mine)
    room = MAX_STOCK * total - mine
    if meta["sector"]:
        sec = sum(r["value"] or 0.0 for r in h["rows"] if r["sector"] == meta["sector"] and r["asset_class"] != "etf")
        room = min(room, MAX_SECTOR * total - sec)
    return max(0.0, room)


def flags(con, day: date) -> List[str]:
    """The holdings over a rail today, in plain words."""
    from pflab.paper import book
    h = book.holdings(con, day)
    out, sectors = [], {}
    for r in h["rows"]:
        lim = MAX_ETF if r["asset_class"] == "etf" else MAX_STOCK
        if r["asset_class"] in book.BUYABLE and r["weight"] > lim:
            out.append(f"{r['symbol']} is {r['weight']:.1%} of the paper portfolio, over its {lim:.0%} rail (no more may be bought)")
        if r["sector"] and r["asset_class"] != "etf":
            sectors[r["sector"]] = sectors.get(r["sector"], 0.0) + r["weight"]
    out += [f"the {s} sector is {w:.1%}, over the {MAX_SECTOR:.0%} rail" for s, w in sorted(sectors.items()) if w > MAX_SECTOR]
    if h["cash"] < 0:
        out.append(f"cash is below zero (Rs {h['cash']:,.0f}) after a withdrawal: something must be sold")
    return out


def describe() -> Dict[str, str]:
    return {"one company": f"at most {MAX_STOCK:.0%} after a buy", "one sector": f"at most {MAX_SECTOR:.0%} after a buy",
            "one ETF": f"at most {MAX_ETF:.0%} after a buy", "never": "F&O, borrowing, short sales; buying funds, SGBs or physical gold (they may be sold)"}
