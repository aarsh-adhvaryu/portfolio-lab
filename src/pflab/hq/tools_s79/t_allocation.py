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
        out["how"] = ("the target is the SYSTEM's book only (not the investor's targets); weights are percent of the book; the manager's sizing and the rails decide every amount. "
                      "Propose a change with propose_allocation; the independent review decides.")
        if out.get("active") is None:
            out["playbook"] = allocation.playbook_text()
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


def propose_allocation(ctx: Ctx, a: dict) -> dict:
    """Action: the paper team proposes the system's own allocation target. Quant and coordinator of a paper mission only; the reviewer judges it with the mission."""
    from pflab.hq.tools import _SHADOW_CASE, _checked, note_artifact
    from pflab.paper import allocation, manager
    if ctx.shadow:
        return _SHADOW_CASE
    if ctx.role not in ("coordinator", "quant"):
        return {"stored": False, "problem": "only the coordinator and the quant of the paper team propose the allocation; the reviewer and research judge and inform it"}
    cid = int(a["case_id"]) if a.get("case_id") else None
    if cid is None:
        r = ctx.con.execute("SELECT case_id FROM hq_tasks WHERE task_id=?", [ctx.task_id]).fetchone() if ctx.task_id else None
        cid = int(r[0]) if r and r[0] else None
    if not manager.is_paper(ctx.con, cid):
        return {"stored": False, "problem": "propose_allocation is only for a paper-portfolio mission"}
    try:
        secs = _sectors(str(a.get("sectors") or ""))
    except Exception:
        return {"stored": False, "problem": "sectors must read like 'IT:15, Banks:20' (percent of the whole book) or a JSON object"}
    weights = {"equity": a.get("equity_pct"), "gold": a.get("gold_pct"), "international": a.get("international_pct"), "cash": a.get("cash_pct")}
    out = allocation.propose_allocation(ctx.con, weights, _checked(ctx, a.get("reasons", "")), ctx.now, sectors=secs, case_id=cid, by=f"the paper team ({ctx.role})")
    if out.get("stored") and not out.get("reaffirmed"):
        note_artifact(ctx, cid, "proposal", f"alloc:{out['target_id']}", "allocation target")
    return out


TOOLS = [
    Tool("system_allocation", "read", "The system's OWN allocation target for its book (not the investor's): percent in equity, gold, international and cash, the sector split, the team's reasons, "
         "how far the book is from it now (drift and the gap per class and sector), what waits for the independent review and when the weekly re-examination is due.",
         {"market": _s("IN or US", 4)}, (), system_allocation),
    Tool("propose_allocation", "action", "Propose the system's allocation target (paper missions; quant or coordinator): equity_pct, gold_pct, international_pct, cash_pct (percent of the book, "
         "each at least 0, together 100), the sector split of the companies (percent of the whole book, each at most 25), and the reasons including what would change it. Code refuses a split "
         "that breaks the rails (no F&O, no borrowing, no short sales, sector 25%, company 10%, one ETF 35%); the independent review must approve before it is active. The same split as "
         "the active one is a re-examination at the weekly review.",
         {"equity_pct": _n("percent of the book in shares and equity/index ETFs", 0, 100), "gold_pct": _n("percent in gold (gold ETFs, SGBs)", 0, 100),
          "international_pct": _n("percent in foreign-index ETFs listed in India (and US instruments when that leg opens)", 0, 100), "cash_pct": _n("percent in cash and liquid funds", 0, 100),
          "sectors": _s("sector split of the companies as 'IT:15, Banks:20' (percent of the whole book)", 600),
          "reasons": _s("why this split, the evidence you read, and what would make you change it", 1500)},
         ("equity_pct", "gold_pct", "international_pct", "cash_pct", "reasons"), propose_allocation),
]
