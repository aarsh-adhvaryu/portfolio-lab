"""S79 item 2 (A45): the system's own allocation target. `system_allocation` reads it (target, reasons, drift, review dates); `propose_allocation` is how the paper team
proposes it (coordinator and quant of a PAPER mission only; code checks the rails; the independent review must approve before it is active)."""
from __future__ import annotations

import json

from pflab.hq.tools import Ctx, Tool, _n, _s


def system_allocation(ctx: Ctx, a: dict) -> dict:
    """Read: the active allocation target of the system's book, its reasons, the drift of the book from it, what waits for review and when the next re-examination is due."""
    try:
        from pflab.paper import allocation
        market = str(a.get("market") or "IN").upper()
        out = allocation.status(ctx.con, ctx.now.date(), market)
        out["history"] = [{"target_id": t["target_id"], "status": t["status"], "verdict": t["verdict"], "proposed_at": str(t["proposed_at"])[:16], "classes": t["classes"]}
                          for t in allocation.history(ctx.con, market, 5)]
        out["how"] = "the target is the SYSTEM's book only (not the investor's targets); weights are percent of the book; the close loop's sizing and the rails decide every amount."
        return out
    except Exception as e:                                     # a probe or a store without the table must get a harmless answer
        return {"active": None, "note": f"the allocation record is not readable now ({type(e).__name__})"}


def _sectors(text: str) -> dict:
    """'IT:15, Banks:20' or a JSON object -> {sector: pct}. A malformed piece is an error the team is told."""
    t = (text or "").strip()
    if not t:
        return {}
    if t.startswith("{"):
        return {str(k): float(v) for k, v in json.loads(t).items()}
    out = {}
    for piece in t.split(","):
        if not piece.strip():
            continue
        name, _, val = piece.rpartition(":")
        out[name.strip()] = float(val.strip().rstrip("%"))
    return out


TOOLS = [
    Tool("system_allocation", "read", "The system's OWN allocation target for its book (not the investor's): percent in equity, gold, international and cash, the sector split, the team's reasons, "
         "how far the book is from it now (drift and the gap per class and sector), what waits for the independent review and when the weekly re-examination is due.",
         {"market": _s("IN or US", 4)}, (), system_allocation),
]
