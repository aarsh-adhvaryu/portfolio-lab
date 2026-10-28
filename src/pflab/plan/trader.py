"""The trader planner (S45, PLAN A7): how to place each proposed buy. It writes tickets for the investor to enter in Kite
himself; it has no order path (GTTs are orders: the system only prints their fields).

The plan follows the pre-registered split / limit study (docs/STUDIES.md,
data/research/split_study.json): if a plan was adopted it is used; otherwise, and before the study has run, the
advice is to buy at once with a limit at the last price. A measured impact note (S41 depth recordings) is added
when there is one, and a size check against the turnover expected over the next 5 sessions (S52 Q5, an ESTIMATE).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, List, Optional

from pflab.quant import execution_study as es


def decision(root: Optional[Path] = None) -> Optional[str]:
    """The adopted plan ('B5', 'L0.5', 'L1', 'L2'); '' when the study ran and adopted none; None before it has run."""
    from pflab.data import data_dir
    p = (root or data_dir()) / "research" / "split_study.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))["decision"].get("adopted") or ""


def tickets(symbol: str, qty: int, last_close: float, plan: Optional[str],
            impact: Optional[Callable[[str, float], Optional[str]]] = None, isin: Optional[str] = None,
            turnover: Optional[Callable[[str], Optional[tuple]]] = None,
            nudge: Optional[Callable[[str, float], List[str]]] = None) -> List[str]:
    """Lines the investor copies into Kite. Prices are rounded to the NSE tick of 0.05. `nudge` (plan/nudges.py) adds Kite-style
    pre-trade warnings for the stock, each its own line."""
    tick = lambda x: round(round(x / 0.05) * 0.05, 2)
    out: List[str] = []
    if plan and plan.startswith("L"):
        x = float(plan[1:]) / 100
        lim = tick(last_close * (1 - x))
        out.append(f"BUY {symbol} {qty} LIMIT {lim:,.2f} ({x:.1%} below the last close), good for {es.WINDOW} sessions "
                   f"(a GTT with trigger {lim:,.2f}); if not filled by session {es.WINDOW}, buy at the close that day")
    elif plan == "B5":
        parts = [qty // es.WINDOW + (1 if k < qty % es.WINDOW else 0) for k in range(es.WINDOW)]
        out.append(f"BUY {symbol} in {es.WINDOW} daily parts {parts} near each day's close (limit at that day's price)")
    else:
        why = "the split study has not run yet" if plan is None else "the split study found no reliably cheaper plan"
        out.append(f"BUY {symbol} {qty} LIMIT {tick(last_close):,.2f} (at the last price; {why})")
    note = impact(isin, qty * last_close) if impact and isin else None
    if note:
        out.append(note)
    if turnover and isin:
        from pflab.quant import forecast
        size = forecast.size_note(qty * last_close, turnover(isin))
        if size:
            out.append(size)
    if nudge and isin:
        out += nudge(isin, qty * last_close)
    return out


def plan_all(buys, root: Optional[Path] = None, impact=None, turnover=None, nudge=None) -> Dict[str, List[str]]:
    p = decision(root)
    return {b.symbol: tickets(b.symbol, b.qty, b.price, p, impact, b.isin, turnover, nudge) for b in buys}
