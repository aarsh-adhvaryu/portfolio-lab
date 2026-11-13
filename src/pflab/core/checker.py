"""The checker (S80 phase 3): Sonnet's one-line pass or veto on a big trade. Whether a big trade is a mistake is a judgement code cannot make from the numbers alone (a stale price, a
corporate event, a thesis that has just broken); so before orders of `[checker] big_trade_share` of the book or more are placed, ONE Sonnet call reads the book card and the big
orders and answers pass or veto with a reason for each. It never sizes or invents a trade; a veto only removes an order from today (the policy tries again tomorrow).

It runs through the one door (`llm/gateway.py`, S85) as the agent `checker` (priced first, egress-checked, inside its 20% share of the cap, logged). If there is no client, no room in the budget, or the
call fails for any reason, the trades PASS and the record says `unchecked` and why: a missing check never stops the book (the rails are the hard limits).
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Callable, Dict, List, Optional

from pflab import core

SYSTEM = ("You are the CHECKER of a small personal paper portfolio of Indian shares and ETFs. A rule-based policy wants to place the BIG orders listed below. For each, answer 'pass' unless "
          "you can name a concrete reason the order is a mistake today (a data error, a stale or missing price, a known event, a position that would become too concentrated, a trade that "
          "contradicts the book's own stated risk). Do not second-guess the strategy. Reply with the JSON object only: {\"verdicts\": [{\"symbol\": \"...\", \"verdict\": \"pass\" or \"veto\", "
          "\"reason\": \"one short line\"}]}.")


def schema() -> dict:
    return {"type": "object", "properties": {"verdicts": {"type": "array", "maxItems": 12, "items": {"type": "object", "properties": {
        "symbol": {"type": "string"}, "verdict": {"enum": ["pass", "veto"]}, "reason": {"type": "string", "maxLength": 240}}, "required": ["symbol", "verdict", "reason"]}}},
        "required": ["verdicts"]}


def big(orders: List[dict], total: float) -> List[dict]:
    share = float(core.settings()["checker"]["big_trade_share"])
    return [o for o in orders if total > 0 and o["value"] >= share * total]


def _log(con, now: datetime, day: date, kind: str, subject: str, order: dict, verdict: str, reason: str, cost: float, model: str) -> None:
    from pflab.pm.store import next_id
    con.execute("INSERT INTO core_checks_s80 VALUES (?,?,?,?,?,?,?,?,?,?)", [next_id(con, "core_checks_s80", "check_id"), day, now, kind, subject, json.dumps({k: order.get(k) for k in ("symbol", "side", "value", "from_w", "to_w")}, default=str),
                                                                            verdict, reason[:300], cost, model])


def review(con, now: datetime, day: date, state: dict, orders: List[dict], client_fn: Optional[Callable] = None, gate=None, cfg: Optional[dict] = None, policy_id: str = "baseline_v1") -> dict:
    """-> {"orders": the orders that stand, "checked": n, "vetoed": [...], "unchecked": why or None}."""
    st = core.settings()["checker"]
    bigs = big(orders, state["value"])
    if not st["on"] or not bigs:
        return {"orders": orders, "checked": 0, "vetoed": [], "unchecked": None}
    model = st["model"]
    why = None
    verdicts: Dict[str, dict] = {}
    cost = 0.0
    if client_fn is None:
        why = "no cloud client (not allowed here, or no key)"
    else:
        try:
            from pflab.agents import analyst as an
            from pflab.core import card
            from pflab.hq import egress
            from pflab.llm import gateway
            lines = [f"- {o['side'].upper()} {o['symbol']}: Rs {o['value']:,.0f} ({o['value'] / state['value']:.1%} of the book), weight {o['from_w']:.1%} to {o['to_w']:.1%}"
                     + (f"; note: {o['note']}" if o.get("note") else "") for o in bigs]
            text = f"POLICY: {policy_id}\nTHE BIG ORDERS:\n" + "\n".join(lines) + "\n\nTHE BOOK CARD (the last close):\n" + (card.latest(con) or "(none yet)")[:9000]
            # S85: through the one door (role `quick`, agent `checker`): the engine in use decides which model answers; the egress gate, the governor and his cap are the door's, unchanged
            s = gateway.call(con, "quick", [{"type": "text", "text": SYSTEM}], [{"role": "user", "content": [{"type": "text", "text": text}]}], agent="checker", purpose="big-trade check",
                             max_tokens=700, schema=schema(), now=now, cfg=cfg or an.config(), gate=gate or egress.load(con), private_text=text, client=client_fn(), topic="big-trade check",
                             question=f"{day}: {len(bigs)} big order(s)")
            cost = float(s["cost_rupees"])
            from pflab.llm import constrained
            obj = s["json"] if s["json"] else {}
            if s.get("json_error"):
                raise ValueError(s["json_error"])
            bad = constrained.check(obj, schema())
            if bad:
                raise ValueError(f"the checker's answer did not fit: {bad}")
            verdicts = {v["symbol"]: v for v in obj["verdicts"]}
        except Exception as e:
            why = f"{type(e).__name__}: {str(e)[:200]}"
    vetoed, keep = [], []
    for o in orders:
        if o not in bigs:
            keep.append(o)
            continue
        v = verdicts.get(o["symbol"])
        if v and v["verdict"] == "veto":
            vetoed.append({"symbol": o["symbol"], "side": o["side"], "rupees": round(o["value"]), "reason": v["reason"]})
            _log(con, now, day, "big_trade", o["symbol"], o, "veto", v["reason"], cost / len(bigs), model)
        else:
            keep.append(o)
            _log(con, now, day, "big_trade", o["symbol"], o, "pass" if v else "unchecked", (v["reason"] if v else (why or "no verdict for this order")), cost / len(bigs), model)
    return {"orders": keep, "checked": len(bigs) if not why else 0, "vetoed": vetoed, "unchecked": why}
