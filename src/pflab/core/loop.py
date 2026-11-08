"""The close loop (S80): once per closed session, by code, in seconds, no paid call.

    perceive   the session's closes are stored and the book is marked for it (`paper` job: fills, corporate actions, the day's value)
    state      the book, the risk model, the allocation target, the fall gauge, the circuit breaker           (core/state.py)
    decide     the champion policy turns the state into target weights                                          (core/policy.py)
    check      the rails clip them and turn them into orders                                                    (core/rails.py)
    act        each order is a decision row (reasons written by code) and a paper order that fills at the next close (`paper/book.py`)
    score      each decision registers its claims at 7, 28, 84 and 182 days, scored by `paper/manager.score_due` as before

A session is run once (`core_runs_s80`, one row a day); a run that finds orders still open waits. Every run leaves an act, even "held": nothing is silent.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Optional

import pandas as pd

from pflab import core
from pflab.core import policy, rails, state as st


def ensure_policy(con, now: datetime) -> None:
    h = policy.code_hash()
    r = con.execute("SELECT code_hash FROM core_policies_s80 WHERE policy_id=?", [policy.POLICY_ID]).fetchone()
    if r is None:
        con.execute("INSERT INTO core_policies_s80 VALUES (?,?,?,?,?,?)",
                    [policy.POLICY_ID, "champion", h, now, now, "the baseline: hold the allocation target, size by risk, rebalance in a band, cut equity when the fall gauge fires"])
    elif r[0] != h:
        con.execute("UPDATE core_policies_s80 SET code_hash=? WHERE policy_id=?", [h, policy.POLICY_ID])


def _decision(con, now, o: dict, index: Optional[pd.Series], day) -> int:
    from pflab.hq import scorecard
    from pflab.paper import book
    from pflab.pm.store import next_id
    held = book.positions(con).get(o["isin"], 0.0)
    px = book.close_on(con, o["isin"], day)
    if o["side"] == "buy":
        action, fraction = ("ADD" if held > 0 else "BUY"), None
    else:
        fraction = min(1.0, o["qty"] / held) if held > 0 else 1.0
        action = "SELL" if fraction >= 0.999 else "REDUCE"
    why = (f"{policy.POLICY_ID}: weight {o['from_w']:.1%} now, target {o['to_w']:.1%} (risk-sized inside the allocation target)"
           + ("; risk cut by the fall gauge" if o["risk_cut"] else "") + (f"; {o['note']}" if o["note"] else ""))
    if o["side"] == "sell" and (o["charges"] or o["tax"]):
        why += f"; estimated charges Rs {o['charges']:,.0f} and tax Rs {o['tax']:,.0f}"
    did = next_id(con, "paper_decisions", "decision_id")
    con.execute("INSERT INTO paper_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [did, now, None, action, o["isin"], o["symbol"], o["amount"], fraction, why[:1500], "hold as it is (inside the band, the cheaper alternative)", None, None, "executed",
                 "placed by the close loop; fills at the next close", px[0] if px else None, px[1] if px else None, scorecard.state_at(index, day), now])
    return did


def run(con, now: datetime, root=None, index: Optional[pd.Series] = None) -> dict:
    """One pass for the latest closed session. Returns what happened (never raises for a missing input: it says what it is waiting for)."""
    from pflab import markets
    from pflab.paper import book, cadence, manager
    if not core.on():
        return {"off": True}
    if not book.started(con):
        return {"waiting": "the paper book has not started"}
    day = markets.get("IN").session_closed_by(now)
    if con.execute("SELECT 1 FROM core_runs_s80 WHERE day=?", [day]).fetchone():
        return {"skipped": f"session {day} already done"}
    marked = con.execute("SELECT max(day) FROM paper_days").fetchone()[0]
    if marked is None or marked < day:
        return {"waiting": f"the book is marked to {marked}, not yet to {day}"}
    if con.execute("SELECT count(*) FROM paper_orders WHERE status='open'").fetchone()[0]:
        return {"waiting": "orders from an earlier session have not filled yet"}
    t0 = time.time()
    ensure_policy(con, now)
    index = index if index is not None else manager._index(root)
    cfg = core.settings()
    s = st.build(con, day, root, index, cfg)
    dec = policy.decide(s)
    chk = rails.check(con, s, dec)
    placed = []
    for o in chk["orders"]:
        did = _decision(con, now, o, index, day)
        oid = book.place(con, now, did, o["isin"], o["side"], qty=o["qty"], amount=o["amount"], note=f"{policy.POLICY_ID} decision #{did}")
        manager.register(con, did)
        placed.append({"decision_id": did, "order_id": oid, "symbol": o["symbol"], "side": o["side"], "rupees": round(o["value"], 2)})
    status = "traded" if placed else "held"
    brief = {"value": round(s["value"], 2), "gauge": s["gauge"], "breaker": s["breaker"], "target_id": (s["target"] or {}).get("id"), "classes_wanted": dec["classes"]}
    note = "; ".join(dec["notes"])
    con.execute("INSERT INTO core_runs_s80 VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [day, now, policy.POLICY_ID, status, round(time.time() - t0, 3), json.dumps(brief, default=str), json.dumps({k: round(v, 5) for k, v in dec["weights"].items()}),
                 json.dumps(chk["clipped"], default=str), json.dumps(placed), json.dumps(chk["skipped"], default=str), note[:400]])
    card_tokens = None
    try:                                                                  # the book card for the strategist: never allowed to fail the loop
        from pflab.core import card
        card_tokens = card.write(con, now, s, dec, placed)["tokens"]
    except Exception as e:
        cadence.act(con, now, "core_loop", f"the book card could not be written: {type(e).__name__}: {str(e)[:160]}", False)
    what = (f"close loop {day}: {len(placed)} order(s) placed" if placed else f"close loop {day}: held, nothing needed (the book is within its band and rails)") + f" [{note}]"
    cadence.act(con, now, "core_loop", what, True, {"orders": placed, "skipped": chk["skipped"][:8]})
    return {"day": str(day), "status": status, "orders": placed, "skipped": len(chk["skipped"]), "card_tokens": card_tokens, "seconds": round(time.time() - t0, 3)}
