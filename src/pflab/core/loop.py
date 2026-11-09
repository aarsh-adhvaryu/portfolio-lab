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
    """Both baselines are listed in the policy store; while no lab policy is champion the one `[baseline_v2] version` names is (S81), the other is 'previous' (the safe fallback)."""
    active = policy.active_id()
    for pid, h, note in policy.registered():
        r = con.execute("SELECT code_hash FROM core_policies_s80 WHERE policy_id=?", [pid]).fetchone()
        if r is None:
            con.execute("INSERT INTO core_policies_s80 (policy_id, status, code_hash, created_at, note) VALUES (?,?,?,?,?)", [pid, "previous", h, now, note])
        elif r[0] != h:
            con.execute("UPDATE core_policies_s80 SET code_hash=? WHERE policy_id=?", [h, pid])
    if not con.execute("SELECT 1 FROM core_policies_s80 WHERE status='champion' AND policy_id NOT IN ('baseline_v1','baseline_v2') AND code IS NOT NULL").fetchone():
        con.execute("UPDATE core_policies_s80 SET status='previous' WHERE policy_id IN ('baseline_v1','baseline_v2') AND policy_id <> ? AND status='champion'", [active])
        con.execute("UPDATE core_policies_s80 SET status='champion', promoted_at=coalesce(promoted_at, ?) WHERE policy_id=? AND status <> 'champion'", [now, active])


def _lab_champion(con) -> Optional[dict]:
    """The champion when it is a lab policy (code in the store); None while the baseline is champion."""
    r = con.execute("SELECT policy_id FROM core_policies_s80 WHERE status='champion' AND policy_id NOT IN ('baseline_v1','baseline_v2') AND code IS NOT NULL ORDER BY promoted_at DESC NULLS LAST LIMIT 1").fetchone()
    if not r:
        return None
    from pflab.lab import service
    return service.get(con, r[0])


def _decision(con, now, o: dict, index: Optional[pd.Series], day, pid: str = policy.POLICY_ID) -> int:
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
    why = (f"{pid}: weight {o['from_w']:.1%} now, target {o['to_w']:.1%} " + ("(risk-sized inside the allocation target)" if pid in policy.BASELINES else "(the champion policy's target)")
           + ("; risk cut by the fall gauge" if o["risk_cut"] else "") + (f"; {o['note']}" if o["note"] else ""))
    if o["side"] == "sell" and (o["charges"] or o["tax"]):
        why += f"; estimated charges Rs {o['charges']:,.0f} and tax Rs {o['tax']:,.0f}"
    did = next_id(con, "paper_decisions", "decision_id")
    con.execute("INSERT INTO paper_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [did, now, None, action, o["isin"], o["symbol"], o["amount"], fraction, why[:1500], "hold as it is (inside the band, the cheaper alternative)", None, None, "executed",
                 "placed by the close loop; fills at the next close", px[0] if px else None, px[1] if px else None, scorecard.state_at(index, day), now])
    return did


def run(con, now: datetime, root=None, index: Optional[pd.Series] = None, live_data: Optional[dict] = None, checker_client=None) -> dict:
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
    pid, dec = policy.active_id(), None
    champ = _lab_champion(con)
    if champ is not None:                                                 # a promoted lab policy decides; any failure falls back to the baseline for this close
        try:
            from pflab.lab import live
            w = live.decide(con, root, day, champ, {r["isin"]: r["weight"] for r in s["rows"] if r["weight"] > 0}, data=live_data)
            s = st.build(con, day, root, index, cfg, extra_isins=[i for i in w if i not in {r["isin"] for r in s["rows"]}])
            pid, dec = champ["policy_id"], {"weights": w, "notes": [f"champion {champ['policy_id']} (promoted lab policy)"], "classes": {}}
        except Exception as e:
            cadence.act(con, now, "core_loop", f"champion {champ['policy_id']} failed ({type(e).__name__}: {str(e)[:200]}): the baseline decides this close", False)
    if dec is None:
        dec = policy.decide_active(s)
    views_note = None
    if cfg["tactical"]["on"]:                                              # the tactical lane: active views adjust the target weights BEFORE the rails (every cap and limit still applies)
        try:
            from pflab.core import views
            views.score_due(con, now, day, root)
            held = {r["isin"]: r["weight"] for r in s["rows"] if r["weight"] > 0}
            merged = views.merge(con, day, dec["weights"], held)
            if merged != dec["weights"]:
                extra = [i for i in merged if i not in {r["isin"] for r in s["rows"]}]
                if extra:
                    s = st.build(con, day, root, index, cfg, extra_isins=extra)
                dec = {**dec, "weights": merged, "notes": list(dec["notes"]) + ["tactical views merged into the targets"]}
                views_note = "tactical views merged"
        except Exception as e:
            cadence.act(con, now, "core_loop", f"the tactical views could not be applied: {type(e).__name__}: {str(e)[:160]}", False)
    chk = rails.check(con, s, dec)
    checked = {"checked": 0, "vetoed": [], "unchecked": None}
    try:                                                                   # the big-trade check (Sonnet), never allowed to stop the book
        from pflab.core import checker
        checked = checker.review(con, now, day, s, chk["orders"], checker_client, policy_id=pid)
        chk = {**chk, "orders": checked["orders"]}
    except Exception as e:
        cadence.act(con, now, "core_loop", f"the big-trade check failed ({type(e).__name__}: {str(e)[:160]}): the trades stand", False)
    placed = []
    for o in chk["orders"]:
        did = _decision(con, now, o, index, day, pid)
        oid = book.place(con, now, did, o["isin"], o["side"], qty=o["qty"], amount=o["amount"], note=f"{pid} decision #{did}")
        manager.register(con, did)
        try:                                                              # S81: the position is tagged with its sleeve as the order is placed
            from pflab.core import sleeves
            sleeves.tag_order(con, o["isin"], day, pid)
        except Exception as e:
            cadence.act(con, now, "core_loop", f"the sleeve of {o['symbol']} could not be recorded: {type(e).__name__}: {str(e)[:120]}", False)
        placed.append({"decision_id": did, "order_id": oid, "symbol": o["symbol"], "side": o["side"], "rupees": round(o["value"], 2)})
    status = "traded" if placed else "held"
    brief = {"value": round(s["value"], 2), "gauge": s["gauge"], "breaker": s["breaker"], "target_id": (s["target"] or {}).get("id"), "classes_wanted": dec["classes"]}
    note = "; ".join(dec["notes"])
    con.execute("INSERT INTO core_runs_s80 VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [day, now, pid, status, round(time.time() - t0, 3), json.dumps(brief, default=str), json.dumps({k: round(v, 5) for k, v in dec["weights"].items()}),
                 json.dumps(chk["clipped"], default=str), json.dumps(placed), json.dumps(chk["skipped"], default=str), note[:900]])
    card_tokens = None
    try:                                                                  # the book card for the strategist: never allowed to fail the loop
        from pflab.core import card
        card_tokens = card.write(con, now, s, dec, placed)["tokens"]
    except Exception as e:
        cadence.act(con, now, "core_loop", f"the book card could not be written: {type(e).__name__}: {str(e)[:160]}", False)
    what = (f"close loop {day}: {len(placed)} order(s) placed" if placed else f"close loop {day}: held, nothing needed (the book is within its band and rails)") + f" [{note}]"
    if checked["vetoed"]:
        what += f"; the checker vetoed {len(checked['vetoed'])}: " + "; ".join(f"{v['symbol']} ({v['reason'][:60]})" for v in checked["vetoed"])
    cadence.act(con, now, "core_loop", what, True, {"orders": placed, "skipped": chk["skipped"][:8]})
    return {"day": str(day), "status": status, "orders": placed, "skipped": len(chk["skipped"]), "card_tokens": card_tokens, "vetoed": checked["vetoed"], "seconds": round(time.time() - t0, 3)}
