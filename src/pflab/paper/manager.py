"""The paper portfolio's manager (S76): the system runs a copy of his portfolio by itself (his decision 2026-11-01; PLAN amendment A35).

Who does what. The team of S68-S75 works on it with no approval step: the coordinator plans, research and quant work with the web, data and code, the quant
records each DECISION with `paper_decide` (direction, reasons, alternatives; code sizes it against the book and the rails), the independent reviewer judges the work,
and code here executes what the review approved: orders that fill at the close (`paper/book.py`). A decision the review did not approve is kept and never executed.

When it looks. Every round and every night, by code (free): its money in and out, fills, the day's value, the rails, decisions scored when due. The team (paid, inside
`[paper] monthly_rupees`, default Rs 500, under his cap): the first review on the first morning; a weekly review; a holding that moved 8% in a session or 15% since
the last review; cash below zero; and whatever he asks it to look into (one input it may overrule: it must say so and why). One piece of team work at a time.

How it is judged. Every decision states a claim the day it is made, scored after 7, 28, 84 and 182 days against the Nifty 500 (beta-adjusted, as the scorecard), or,
for keeping cash, against what cash earned. The gate to his real money (his choice: about two months): after GATE_SESSIONS sessions, if the paper portfolio's
time-weighted return beats the Nifty 500 total return over the same days and its worst fall was smaller, its new decisions also become proposals for his real portfolio,
each waiting for his yes. The gate is re-checked every night and closes again when that stops being true.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

ACTIONS = ("BUY", "ADD", "REDUCE", "SELL", "HOLD", "WAIT")
KIND = {"BUY": "add", "ADD": "add", "REDUCE": "trim", "SELL": "trim", "HOLD": "hold", "WAIT": "wait"}
HORIZONS = (7, 28, 84, 182)
GATE_SESSIONS = 40                     # about two months of sessions (his choice, 2026-11-01)
MONTHLY_RUPEES = 500.0                 # the team's money for the paper portfolio a month (his choice: the cap raised to Rs 1,500 for it)
MISSION_RUPEES = 100.0                 # one piece of the team's work on the paper portfolio at most (a standard investigation measured Rs 50-80)
REVIEW_EVERY_DAYS = 7
MOVE_DAY, MOVE_SINCE, MOVE_LIVE = 0.08, 0.15, 0.03            # a close-to-close move, a move since the last review, a move today on the live quote
CASH_PA = 0.07                         # what cash is taken to earn when keeping cash is scored (an assumption, stated)
ACTIVE = ("planning", "awaiting_approval", "working", "reviewing", "synthesising")


# --- settings and money -------------------------------------------------------------------------------------------------------------

def settings() -> dict:
    try:
        from pflab.agents import analyst as an
        p = an.config().get("paper") or {}
    except Exception:
        p = {}
    return {"on": str(p.get("on", "on")).lower() != "off", "monthly_rupees": float(p.get("monthly_rupees", MONTHLY_RUPEES)),
            "mission_rupees": float(p.get("mission_rupees", MISSION_RUPEES)), "start": p.get("start")}


def spend_month(con, now: datetime) -> float:
    from pflab.agents import analyst as an
    return float(con.execute(
        "SELECT coalesce(sum(a.cost_inr), 0) FROM api_calls a WHERE a.created_at >= ? AND a.status IN ('done','refused','submitted','queued','sending') "
        "AND a.task_id IN (SELECT t.task_id FROM hq_tasks t JOIN hq_missions m ON m.case_id = t.case_id WHERE m.origin='paper')", [an.month_start(now)]).fetchone()[0])


def open_case(con) -> Optional[int]:
    r = con.execute(f"SELECT case_id FROM hq_missions WHERE origin='paper' AND state IN ({','.join(repr(s) for s in ACTIVE)}) ORDER BY mission_id DESC LIMIT 1").fetchone()
    return int(r[0]) if r else None


def is_paper(con, cid: Optional[int]) -> bool:
    if not cid:
        return False
    r = con.execute("SELECT origin FROM hq_missions WHERE case_id=?", [cid]).fetchone()
    return bool(r and r[0] == "paper")


def _index(root) -> Optional[pd.Series]:
    try:
        from pflab.hq import stocks
        return stocks.index_series(root)
    except Exception:
        return None


# --- what the team is handed --------------------------------------------------------------------------------------------------------

def book_view(con, day: date) -> dict:
    from pflab.paper import book, rails
    h = book.holdings(con, day)
    unknown = {r[0] for r in con.execute("SELECT DISTINCT isin FROM events WHERE kind='buy' AND ref LIKE '%:cost_unknown'").fetchall()}   # inherited holdings: no purchase price
    dec = [{"id": r[0], "at": str(r[1])[:16], "action": r[2], "symbol": r[3], "status": r[4], "reason": (r[5] or "")[:200], "case_id": r[6], "amount": r[7], "fraction": r[8]}
           for r in con.execute("SELECT decision_id, made_at, action, symbol, status, reason, case_id, amount, fraction FROM paper_decisions ORDER BY decision_id DESC LIMIT 12").fetchall()]
    return {"started": str(book.started(con)) if book.started(con) else None, "as_of": str(day), "value": round(h["value"], 2), "cash": round(h["cash"], 2), "bank": round(h.get("bank", 0.0), 2),
            "holdings": [{"symbol": r["symbol"], "isin": r["isin"], "sector": r["sector"], "kind": r["asset_class"], "qty": round(r["qty"], 4), "price": r["price"],
                          "price_date": r["price_date"], "value": round(r["value"] or 0.0, 2), "weight": round(r["weight"], 4),
                          "gain": round((r["value"] or 0.0) - r["cost"], 2), "cost": round(r["cost"], 2), "cost_known": r["isin"] not in unknown} for r in h["rows"]],
            "rails": rails.describe(), "over_rails": rails.flags(con, day), "returns": book.returns(con), "recent_decisions": dec,
            "open_orders": [{"id": r[0], "symbol": r[1], "side": r[2], "qty": r[3], "amount": r[4]} for r in con.execute(
                "SELECT order_id, symbol, side, qty, amount FROM paper_orders WHERE status='open' ORDER BY order_id").fetchall()],
            "record": record(con)}


def dossier_text(con, cid: int, now: datetime, role: Optional[str] = None) -> str:
    """The paper block every worker of a paper mission reads first."""
    v = book_view(con, now.date())
    top = "; ".join(f"{h['symbol']} {h['weight']:.1%}" for h in v["holdings"][:12])
    ins = con.execute("SELECT input_id, text FROM paper_inputs WHERE case_id=? ORDER BY input_id", [cid]).fetchall()
    rec = v["record"]
    lines = ["THE PAPER PORTFOLIO (autonomous; this mission manages it, nothing waits for the investor). It started as a copy of his portfolio without FDs; the system "
             "now decides alone, and every decision is executed on paper at the close and scored later against the Nifty 500. The aim is the LONG TERM (3+ years): "
             "beat the Nifty 500 after tax and charges with a smaller worst fall. Doing nothing is a decision too; never trade to have something to show.",
             f"NOW ({v['as_of']}): value Rs {v['value']:,.0f}, broker cash Rs {v['cash']:,.0f}" + (f", bank Rs {v['bank']:,.0f} (moves to the broker by itself when a buy needs it; top-ups of at most Rs 50,000 a month are possible)" if v.get("bank") is not None and v.get("bank") >= 0 and v["bank"] > -1 and __import__("pflab.ledger.system", fromlist=["x"]).active() else "") + f"; holdings: {top or 'none'}",
             "RAILS (code holds them; a buy is cut to fit): " + "; ".join(f"{k}: {x}" for k, x in v["rails"].items()),
             ("OVER A RAIL NOW: " + "; ".join(v["over_rails"])) if v["over_rails"] else "No holding is over a rail.",
             f"ITS RECORD SO FAR: {rec['summary']}"]
    from pflab.paper import cadence
    les = cadence.lessons_text(con)
    if les:
        lines.append(les)
    from pflab.paper import watch as _watch
    wl = _watch.listing(con, now)
    if wl:
        lines.append("ITS WATCHLIST (ideas it waits on; the point is from its own calculation; a TRIGGERED one is why you are looking): " + " | ".join(
            f"{w['symbol']} {w['status'].upper()}: " + (f"zone Rs {w['zone_low'] or 0:,.0f}-{w['zone_high']:,.0f}" if w["kind"] == "zone" else f"{w['fall_pct']:g}% below its high" if w["kind"] == "fall_from_high" else f"market {w['fall_pct']:g}% below its high")
            + (f", price Rs {w['price']:,.2f}" if w.get("price") else "") + f" ({w['reason'][:90]})" for w in wl[:10]))
    br = cadence.breaker(con)
    if br["on"]:
        lines.append(f"CIRCUIT BREAKER IS ON: the account is {-br['drawdown']:.1%} below its high; BUY and ADD are refused by code until it recovers. Look for what went wrong first.")
    if ins:
        lines.append("WHAT THE INVESTOR ASKED IT TO LOOK INTO (one input, not an order: weigh it like any evidence, and if you go against him say so plainly and why): "
                     + " | ".join(f"#{i} {t[:400]}" for i, t in ins))
    lines.append("TOOLS AND THE PAPER BOOK: `paper_book` is the paper portfolio. The measuring tools (stocks_overview, exposure_shock, scenario, simulation, policy_scenarios, "
                 "portfolio, picture) read HIS real record, whose holdings are the same names but whose cash is not the paper cash: say so on any result you use, and when a figure "
                 "must be for the paper book, compute it with case_calculate from paper_book's holdings, weights and cash. A label must match what was computed.")
    if role in ("quant", "coordinator", None):
        lines.append("HOW TO DECIDE: read `paper_book`; for each holding or idea that deserves a decision call `paper_decide` with BUY, ADD, REDUCE, SELL, HOLD or WAIT, the "
                     "reasons and the alternatives (an amount in rupees or a target weight for a buy; a fraction for a reduce). Code sizes it against the cash and the rails and "
                     "tells you the numbers. Nothing is executed until the independent review approves the mission. Do NOT use make_proposal here: that is for his real money.")
    if role == "review":
        lines.append("REVIEW: the decisions below are executed on paper only if you approve. Check each against the evidence, the alternatives, the rails and the long-term aim; "
                     "approve, ask for a revision, or reject. A decision that goes against what he asked must say why.")
    for r in con.execute("SELECT decision_id, action, symbol, amount, fraction, reason, alternatives, his_view, note FROM paper_decisions WHERE case_id=? ORDER BY decision_id",
                         [cid]).fetchall():
        lines.append(f"PAPER DECISION #{r[0]} {r[1]} {r[2] or 'cash'}" + (f" Rs {r[3]:,.0f}" if r[3] else "") + (f" {r[4]:.0%} of the holding" if r[4] else "")
                     + f": {(r[5] or '')[:300]} | alternatives: {(r[6] or '')[:160]}" + (f" | his view: {r[7][:160]}" if r[7] else "") + (f" | sized: {r[8][:200]}" if r[8] else ""))
    return "\n".join(lines)


# --- a decision ---------------------------------------------------------------------------------------------------------------------

def decide(con, now: datetime, cid: int, a: dict, index: Optional[pd.Series] = None) -> dict:
    """Record one decision of a paper mission, sized by code. Returns the numbers, or the problem (nothing stored)."""
    from pflab.hq import scorecard
    from pflab.paper import book, rails
    if not is_paper(con, cid):
        return {"stored": False, "problem": "paper_decide is only for a paper-portfolio mission"}
    action = str(a.get("action", "")).upper()
    if action not in ACTIONS:
        return {"stored": False, "problem": f"action must be one of {ACTIONS}"}
    reason, alts = " ".join(str(a.get("reason", "")).split()), " ".join(str(a.get("alternatives", "")).split())
    cond = " ".join(str(a.get("review_condition", "")).split())
    if len(reason) < 20:
        return {"stored": False, "problem": "give the evidence and the reason in a few sentences"}
    if len(alts) < 10:
        return {"stored": False, "problem": "name the alternatives considered"}
    if action in ("HOLD", "WAIT") and len(cond) < 8:
        return {"stored": False, "problem": f"{action} needs a concrete condition for looking again"}
    sym = str(a.get("symbol") or "").strip().upper()
    isin = (str(a.get("isin") or "").strip().upper() or (book.isin_of(con, sym) if sym else None))
    if action != "WAIT" and not isin:
        return {"stored": False, "problem": f"{action} needs a symbol the record knows"}
    day = now.date()
    if action in ("BUY", "ADD"):
        from pflab.paper import cadence
        b = cadence.breaker(con)
        if b["on"]:
            return {"stored": False, "problem": f"circuit breaker: the account is {-b['drawdown']:.1%} below its own high (limit {-b['limit']:.0%}); no new buying until it recovers. Selling, holding and waiting stay open."}
    h = book.holdings(con, day)
    held = book.positions(con).get(isin, 0.0) if isin else 0.0
    px = book.close_on(con, isin, day) if isin else None
    if isin and px is None:
        return {"stored": False, "problem": f"no stored close for {sym or isin}"}
    amount = fraction = None
    note = ""
    if action in ("BUY", "ADD"):
        if a.get("amount_rupees"):
            amount = float(a["amount_rupees"])
        elif a.get("target_weight_pct"):
            mine = held * px[1]
            amount = max(0.0, float(a["target_weight_pct"]) / 100 * h["value"] - mine)
        if not amount or amount <= 0:
            return {"stored": False, "problem": "a BUY or ADD needs amount_rupees or target_weight_pct"}
        room = rails.buy_room(con, isin, day)
        if room <= 0:
            return {"stored": False, "problem": f"{sym or isin} may not be bought: it is not a listed share or ETF with a close, or it is at its rail"}
        pending_sells = sum(float(r[0] or 0) for r in con.execute(
            "SELECT d.fraction * coalesce((SELECT sum(qty) FROM paper_lots l WHERE l.isin = d.isin), 0) * coalesce(d.ref_close, 0) FROM paper_decisions d "
            "WHERE d.case_id=? AND d.action IN ('REDUCE','SELL') AND d.status='proposed'", [cid]).fetchall())
        pending_buys = float(con.execute("SELECT coalesce(sum(amount), 0) FROM paper_decisions WHERE case_id=? AND action IN ('BUY','ADD') AND status='proposed'",
                                         [cid]).fetchone()[0])
        avail = max(0.0, h["cash"] + pending_sells - pending_buys)
        cut = min(amount, room, avail)
        if cut < px[1]:
            return {"stored": False, "problem": f"no room: rails allow Rs {room:,.0f}, cash after this mission's other decisions Rs {avail:,.0f}"}
        if cut < amount:
            note = f"cut from Rs {amount:,.0f} to Rs {cut:,.0f} (" + ("the rails" if room < amount else "the cash") + ")"
            amount = cut
        note = (note + "; " if note else "") + f"about {int(amount // px[1])} at Rs {px[1]:,.2f} (close of {px[0]}), weight after about {(held * px[1] + amount) / h['value']:.1%}"
    elif action == "HOLD" and held <= 0:
        return {"stored": False, "problem": f"HOLD is for a holding; the paper portfolio holds no {sym or isin} (use WAIT for a name to buy later)"}
    elif action in ("REDUCE", "SELL"):
        if held <= 0:
            return {"stored": False, "problem": f"the paper portfolio holds no {sym or isin}"}
        fraction = 1.0 if action == "SELL" else float(a.get("fraction") or 0)
        if not 0 < fraction <= 1:
            return {"stored": False, "problem": "a REDUCE needs a fraction of the holding between 0 and 1"}
        note = f"{held * fraction:g} of {held:g} at about Rs {px[1]:,.2f} (close of {px[0]}), about Rs {held * fraction * px[1]:,.0f} before charges and tax"
    from pflab.pm.store import next_id
    did = next_id(con, "paper_decisions", "decision_id")
    known = index[index.index <= pd.Timestamp(day)] if index is not None and len(index) else None      # point in time: the level known on the day
    ref = px or ((known.index[-1].date(), float(known.iloc[-1])) if known is not None and len(known) else None)
    con.execute("INSERT INTO paper_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [did, now, cid, action, isin, book.inst(con, isin)["symbol"] if isin else None, amount, fraction, reason[:1500], alts[:800], cond[:300] or None,
                 str(a.get("his_view") or "")[:400] or None, "proposed", note[:400], ref[0] if ref else None, ref[1] if ref else None,
                 scorecard.state_at(index, day), None])
    return {"stored": True, "decision_id": did, "action": action, "symbol": sym or None, "amount_rupees": round(amount, 2) if amount else None, "fraction": fraction,
            "sized": note, "executes": "only if the independent review approves this mission; then at the close"}


def decisions_of(con, cid: int) -> List[dict]:
    return [{"id": r[0], "action": r[1], "symbol": r[2], "amount_rupees": r[3], "fraction": r[4], "status": r[5], "reason": (r[6] or "")[:400], "sized": r[7]}
            for r in con.execute("SELECT decision_id, action, symbol, amount, fraction, status, reason, note FROM paper_decisions WHERE case_id=? ORDER BY decision_id", [cid]).fetchall()]


def execute(con, now: datetime, cid: int, root=None) -> dict:
    """A finished paper mission. APPROVED: its decisions become orders (HOLD and WAIT are simply adopted). REVISE (the review still objects after its revision round):
    HOLD and WAIT, which move no money and are the book's default, are adopted with the objections on record; a trade is not executed. REJECTED or no verdict: nothing is.
    Every decision, executed or refused, is scored later, so the record also shows whether the review was right to refuse. Idempotent."""
    from pflab.hq import missions
    from pflab.paper import book
    todo = con.execute("SELECT decision_id, action, isin, amount, fraction FROM paper_decisions WHERE case_id=? AND status='proposed' ORDER BY "
                       "CASE WHEN action IN ('SELL','REDUCE') THEN 0 ELSE 1 END, decision_id", [cid]).fetchall()
    if not todo:
        return {"orders": 0}
    r = con.execute("SELECT outcome, note FROM hq_case_reviews WHERE case_id=? AND outcome IS NOT NULL ORDER BY review_id DESC LIMIT 1", [cid]).fetchone()
    verdict = missions.verdict_of(r[0]) if r else "none"
    n, adopted, refused = 0, 0, 0
    gate_open = gate(con, root)["open"] if verdict == "approve" else False
    for did, action, isin, amount, fraction in todo:
        stays = action in ("HOLD", "WAIT")
        if verdict == "approve" or (stays and verdict == "revise"):
            if action in ("BUY", "ADD"):
                book.place(con, now, did, isin, "buy", amount=amount, note=f"decision #{did}")
                n += 1
            elif action in ("REDUCE", "SELL"):
                qty = book.positions(con).get(isin, 0.0) * float(fraction or 1.0)
                book.place(con, now, did, isin, "sell", qty=qty, note=f"decision #{did}")
                n += 1
            else:
                adopted += 1
            note = "" if verdict == "approve" else " | adopted without the review's approval: it moves no money; the review's objections are in the case"
            con.execute("UPDATE paper_decisions SET status='executed', decided_at=?, note=coalesce(note,'') || ? WHERE decision_id=?", [now, note, did])
            try:
                from pflab.paper import watch as _w
                _w.handled(con, now, isin, action, did)               # S78: the look the watchlist asked for happened: a buy closes the item, a wait or hold re-arms it
            except Exception:
                pass                                                  # the watchlist never stops a decision from being recorded
            if gate_open:
                _to_real(con, now, cid, did)
        else:
            con.execute("UPDATE paper_decisions SET status='not_approved', decided_at=?, note=coalesce(note,'') || ? WHERE decision_id=?",
                        [now, f" | the review did not approve ({verdict}): not executed (still scored, to see whether refusing was right)", did])
            refused += 1
        register(con, did)
    return {"orders": n, "adopted": adopted, "not_approved": refused}


def sweep_stays(con, now: datetime) -> int:
    """A HOLD or WAIT refused before 2026-11-02's rule (a revise verdict adopts what moves no money) is adopted and scored now. Idempotent."""
    from pflab.hq import missions
    n = 0
    for did, cid in con.execute("SELECT decision_id, case_id FROM paper_decisions WHERE status='not_approved' AND action IN ('HOLD','WAIT') "
                                "AND decision_id NOT IN (SELECT decision_id FROM paper_claims)").fetchall():
        r = con.execute("SELECT outcome FROM hq_case_reviews WHERE case_id=? AND outcome IS NOT NULL ORDER BY review_id DESC LIMIT 1", [cid]).fetchone()
        if r and missions.verdict_of(r[0]) == "revise":
            con.execute("UPDATE paper_decisions SET status='executed', decided_at=?, note=coalesce(note,'') || ' | adopted afterwards: it moves no money' WHERE decision_id=?", [now, did])
            register(con, did)
            n += 1
    return n


def _to_real(con, now: datetime, cid: int, did: int) -> None:
    """Past the gate: the same decision as a proposal for his real money (sized by `hq/proposals` from HIS record; it waits for his yes)."""
    from pflab.hq import proposals
    from pflab.paper import book
    action, isin, sym, amount, fraction, reason, alts, cond = con.execute(
        "SELECT action, isin, symbol, amount, fraction, reason, alternatives, review_condition FROM paper_decisions WHERE decision_id=?", [did]).fetchone()
    inputs = {"action": action, "isin": isin, "symbol": sym, "reason": f"(from the paper portfolio, decision #{did}, past its gate) {reason}", "alternatives": alts,
              "review_condition": cond}
    try:
        if action in ("BUY", "ADD") and amount:
            from pflab.app import views
            real = float(views.holdings(con, now.date())["investable"] or 0.0)
            paper = book.holdings(con, now.date())["value"]
            if real > 0 and paper > 0:
                inputs["amount_rupees"] = round(amount / paper * real, -2)
        elif action == "REDUCE" and fraction:
            from pflab.app import views
            row = next((r for r in views.holdings(con, now.date())["rows"] if r["isin"] == isin), None)
            if row is None:
                return
            inputs["qty"] = max(1.0, float(int(row["qty"] * fraction)))
        proposals.create(con, now, inputs, case_id=cid, by="the paper portfolio")
    except Exception:
        pass


# --- scoring ------------------------------------------------------------------------------------------------------------------------

def register(con, did: int) -> int:
    from pflab.pm.store import next_id
    action, isin, ref_date, ref_close, state = con.execute("SELECT action, coalesce(isin, 'CASH'), ref_date, ref_close, state FROM paper_decisions WHERE decision_id=?",
                                                           [did]).fetchone()
    if ref_date is None or ref_close is None:
        return 0
    n = 0
    for h in HORIZONS:
        if con.execute("SELECT 1 FROM paper_claims WHERE decision_id=? AND horizon_days=?", [did, h]).fetchone():
            continue
        con.execute("INSERT INTO paper_claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [next_id(con, "paper_claims", "claim_id"), did, isin, action, KIND[action], ref_date,
                                                                                    float(ref_close), state, h, ref_date + timedelta(days=h), None, None, None])
        n += 1
    return n


def score_due(con, now: datetime, index: Optional[pd.Series]) -> int:
    from pflab.hq import stocks, suggestions as sg
    n = 0
    for clid, isin, kind, ref_date, ref_close, due in con.execute(
            "SELECT claim_id, isin, kind, ref_date, ref_close, due_on FROM paper_claims WHERE scored_at IS NULL AND due_on <= ?", [now.date()]).fetchall():
        i0 = sg._index_on(index, ref_date) if index is not None else None
        i1 = sg._index_on(index, due) if index is not None else None
        end = (due, i1) if isin == "CASH" else sg._close_on(con, isin, due)
        if end is None or end[1] is None or i0 is None or i1 is None or (isin != "CASH" and end[0] <= ref_date):
            if (now.date() - due).days > 10:
                con.execute("UPDATE paper_claims SET outcome='void', outcome_json=?, scored_at=? WHERE claim_id=?", [json.dumps({"why": "no close or index level near the horizon"}), now, clid])
                n += 1
            continue
        ip = (i1 / i0 - 1) * 100
        if isin == "CASH":                                        # keeping cash: right when the market earned less than cash did
            cash_pct = CASH_PA * (due - ref_date).days / 365 * 100
            out = "good" if ip < cash_pct else "bad"
            detail = {"nifty500_pct": round(ip, 2), "cash_pct": round(cash_pct, 2)}
        else:
            sp = (end[1] / ref_close - 1) * 100
            beta = sg.beta_at(isin, ref_date)
            adj = sp - (beta if beta is not None else 1.0) * ip
            out = sg.judge(kind, sp, adj, stocks.round_trip_pct(stocks.DEFAULT_ORDER))
            detail = {"to": str(end[0]), "stock_pct": round(sp, 2), "nifty500_pct": round(ip, 2), "market_adjusted_pct": round(adj, 2), "beta": None if beta is None else round(beta, 2)}
        con.execute("UPDATE paper_claims SET outcome=?, outcome_json=?, scored_at=? WHERE claim_id=?", [out, json.dumps(detail), now, clid])
        n += 1
    return n


def record(con) -> dict:
    """How its judgement has held up: by kind of decision, the count, the plain rate (from 20) and the skeptical rate; and, apart, the decisions the review refused
    (scored the same way, so it shows whether refusing was right)."""
    from pflab.hq import scorecard
    rows, refused = [], []
    for action, status, good, bad in con.execute(
            "SELECT c.action, d.status, count(*) FILTER (WHERE c.outcome='good'), count(*) FILTER (WHERE c.outcome='bad') FROM paper_claims c JOIN paper_decisions d "
            "ON d.decision_id = c.decision_id WHERE c.outcome IN ('good','bad') GROUP BY 1, 2 ORDER BY 1, 2").fetchall():
        n = int(good + bad)
        row = {"action": action, "n": n, "good": int(good)}
        if n >= scorecard.MIN_N:
            row.update({"rate": round(good / n, 3), "skeptical_rate": scorecard.skeptical(int(good), int(bad))})
        (refused if status == "not_approved" else rows).append(row)
    made = con.execute("SELECT count(*), count(*) FILTER (WHERE status='executed'), count(*) FILTER (WHERE status='not_approved') FROM paper_decisions").fetchone()
    tot, good = sum(r["n"] for r in rows), sum(r["good"] for r in rows)
    rtot, rgood = sum(r["n"] for r in refused), sum(r["good"] for r in refused)
    summary = (f"{made[0]} decision(s), {made[1]} executed, {made[2]} refused by the review; {tot} executed claim(s) scored"
               + (f", {good} held ({scorecard.skeptical(good, tot - good):.0%} is what the rate probably is at least)" if tot else " (none due yet)")
               + (f"; of {rtot} refused claim(s) scored, {rgood} would have held" if rtot else ""))
    return {"by_action": rows, "refused": refused, "summary": summary}


# --- the gate to his real money -----------------------------------------------------------------------------------------------------

def gate(con, root=None, index: Optional[pd.Series] = None) -> dict:
    from pflab.paper import book
    r = book.returns(con)
    if r is None or r["sessions"] < GATE_SESSIONS:
        return {"open": False, "status": f"{0 if r is None else r['sessions']} of {GATE_SESSIONS} sessions: too early to judge (about two months, his choice)"}
    index = index if index is not None else _index(root)
    if index is None or not len(index):
        return {"open": False, "status": "no Nifty 500 series to compare with"}
    s = index[(index.index >= pd.Timestamp(r["since"])) & (index.index <= pd.Timestamp(r["to"]))]
    if len(s) < 2:
        return {"open": False, "status": "the Nifty 500 series does not cover the paper days"}
    n_ret = float(s.iloc[-1] / s.iloc[0] - 1)
    n_worst = float((s / s.cummax() - 1).min())
    ok = r["twr"] > n_ret and r["worst_fall"] > n_worst
    return {"open": ok, "paper_return": round(r["twr"], 4), "nifty500_return": round(n_ret, 4), "paper_worst_fall": round(r["worst_fall"], 4),
            "nifty500_worst_fall": round(n_worst, 4), "sessions": r["sessions"],
            "status": ("open: its new decisions also come to you as proposals for your real money, each waiting for your yes" if ok else
                       "closed: it has not beaten the Nifty 500 after tax with a smaller worst fall over these days")}


# --- his inputs ---------------------------------------------------------------------------------------------------------------------

def add_input(con, now: datetime, text: str) -> dict:
    from pflab.pm.store import next_id
    text = " ".join(str(text).split())[:1200]
    if len(text) < 6:
        return {"stored": False, "problem": "say what to look into"}
    iid = next_id(con, "paper_inputs", "input_id")
    con.execute("INSERT INTO paper_inputs VALUES (?,?,?,?,?,?)", [iid, now, text, "new", None, None])
    return {"stored": True, "input_id": iid, "next": "the paper team takes it up at its next look (at once if nothing else is running); it decides, and may go against it with reasons"}


# --- the loop -----------------------------------------------------------------------------------------------------------------------

def _start_mission(rt, con, now: datetime, goal: str, why: str, key: str) -> Optional[int]:
    from pflab.hq import missions
    out = missions.create(con, now, goal, pm_dir=rt.pm_dir, origin="paper", why=why, revisit="the next weekly review", key=key, budget="standard")
    return int(out["case_id"])


def reasons_to_look(con, now: datetime) -> List[str]:
    from pflab.paper import book, rails
    day = now.date()
    out = []
    last = con.execute("SELECT max(created_at) FROM hq_missions WHERE origin='paper'").fetchone()[0]
    if last is None:
        return ["the first review: the paper portfolio starts today as a copy of his portfolio"]
    if (now - last).days >= REVIEW_EVERY_DAYS:
        out.append("the weekly review")
    h = book.holdings(con, day)
    if h["cash"] < 0:
        out.append("cash is below zero after a withdrawal")
    from pflab.paper import watch
    out += watch.reasons(con)
    since = last.date()
    for r in h["rows"]:
        if r["price"] is None or r["weight"] < 0.02:
            continue
        live = book.live_prices(con, now, [r["isin"]], max_age_min=30).get(r["isin"])
        last_close = con.execute("SELECT close FROM prices WHERE isin=? AND date < ? ORDER BY date DESC LIMIT 1", [r["isin"], day]).fetchone()
        if live and last_close and last_close[0] and abs(live / last_close[0] - 1) >= MOVE_LIVE:
            out.append(f"{r['symbol']} is {live / last_close[0] - 1:+.1%} on the day at the live quote")
            continue
        p0 = book.close_on(con, r["isin"], since)
        prev = con.execute("SELECT close FROM prices WHERE isin=? AND date < ? ORDER BY date DESC LIMIT 1", [r["isin"], r["price_date"]]).fetchone()
        if prev and prev[0] and abs(r["price"] / prev[0] - 1) >= MOVE_DAY:
            out.append(f"{r['symbol']} moved {r['price'] / prev[0] - 1:+.1%} in a session")
        elif p0 and abs(r["price"] / p0[1] - 1) >= MOVE_SINCE:
            out.append(f"{r['symbol']} moved {r['price'] / p0[1] - 1:+.1%} since the last review")
    return out


def bookkeeping(rt) -> dict:
    """The free part, also run by the nightly `paper` job: the start, money in and out, fills, the day's value, claims scored, finished work executed."""
    from pflab.paper import book
    con, now = rt.cursor(), rt.clock()
    st = settings()
    if not st["on"]:
        return {"off": True}
    out: dict = {}
    if not book.started(con):
        if st["start"] and now.date() < date.fromisoformat(str(st["start"])[:10]):
            return {"waiting": f"starts on {st['start']}"}
        last = con.execute("SELECT max(date) FROM prices WHERE date <= ? AND source='nse_bhavcopy'", [now.date()]).fetchone()[0]
        if last is None:
            return {"waiting": "no exchange close on record yet"}
        out["seed"] = book.seed(con, last, now)
    out["book"] = book.catch_up(con, now.date(), now)
    out["live_fills"] = len(book.fill_live(con, now))                 # S77: open orders fill at the live Kite quote, inside a session only (S78)
    index = _index(rt.data_root)
    from pflab.paper import watch
    out["watch"] = watch.check(con, now, rt.data_root, index)         # S78: the watchlist: prices against the points the team's own calculations set
    out["adopted_late"] = sweep_stays(con, now)
    out["scored"] = score_due(con, now, index)
    for (cid,) in con.execute("SELECT DISTINCT d.case_id FROM paper_decisions d JOIN hq_missions m ON m.case_id = d.case_id WHERE d.status='proposed' "
                              "AND m.state IN ('done','blocked','declined')").fetchall():
        out.setdefault("executed", {})[cid] = execute(con, now, cid, rt.data_root)
    for (iid, cid) in con.execute("SELECT i.input_id, i.case_id FROM paper_inputs i JOIN hq_missions m ON m.case_id = i.case_id WHERE i.status='taken' AND m.state='done'").fetchall():
        ans = (missions_answer(con, cid) or "")[:1500]
        con.execute("UPDATE paper_inputs SET status='answered', answer=? WHERE input_id=?", [ans, iid])
    return out


def tick(rt) -> dict:
    """Every HQ round: the bookkeeping (free); team work only when there is a reason, money in its share, and nothing else of its own running."""
    con, now = rt.cursor(), rt.clock()
    out = bookkeeping(rt)
    if out.get("off") or out.get("waiting"):
        return out
    st = settings()
    from pflab.paper import book, cadence
    if book.session_open(now) and not cadence.acted_since(con, "live_watch", now - timedelta(minutes=14)):
        w = reasons_to_look(con, now)
        cadence.act(con, now, "live_watch", "watched the holdings against the live quote" + (f"; {len(w)} reason(s): " + "; ".join(w)[:160] if w else "; nothing moved enough"), True)
    if open_case(con) is not None:
        out["working"] = open_case(con)
        return out
    room = st["monthly_rupees"] - spend_month(con, now)
    new = con.execute("SELECT input_id, text FROM paper_inputs WHERE status='new' ORDER BY input_id").fetchall()
    why = ([f"he asked it to look into: {t[:200]}" for _, t in new]) + reasons_to_look(con, now)
    if not why:
        return out
    if room < 20:
        out["held"] = f"the paper team's money this month is used (Rs {st['monthly_rupees']:,.0f}); it looks again next month: " + "; ".join(why)[:300]
        return out
    goal = ("Paper portfolio: " + ("; ".join(why))[:700] + ". Decide for the long term what to buy, add, reduce, sell, hold or wait on, and why; the system executes on "
            "paper what the review approves.")
    cid = _start_mission(rt, con, now, goal, why[0], f"paper:{now:%Y%m%d%H%M}:" + str(con.execute("SELECT count(*) FROM hq_missions WHERE origin='paper'").fetchone()[0]))
    for iid, _ in new:
        con.execute("UPDATE paper_inputs SET status='taken', case_id=? WHERE input_id=?", [cid, iid])
    out["started"] = cid
    cadence.act(con, now, "weekly_review", f"the team started a review (#{cid}): {why[0][:160]}", True)
    return out


def missions_answer(con, cid: int) -> Optional[str]:
    from pflab.hq import missions
    m = missions.mission_of(con, cid)
    return (m or {}).get("result", {}).get("answer")


def status(con, root=None) -> dict:
    """Everything the screen and the chat show."""
    from pflab.paper import book
    if not book.started(con):
        return {"started": False, "note": "the paper portfolio starts on the first run after the release: a copy of your portfolio without FDs"}
    day = con.execute("SELECT max(day) FROM paper_days").fetchone()[0]
    v = book_view(con, day)
    v["gate"] = gate(con, root)
    v["inputs"] = [{"id": r[0], "at": str(r[1])[:16], "text": r[2], "status": r[3], "case_id": r[4], "answer": r[5]}
                   for r in con.execute("SELECT input_id, logged_at, text, status, case_id, answer FROM paper_inputs ORDER BY input_id DESC LIMIT 10").fetchall()]
    v["trades"] = [{"day": str(r[0]), "symbol": r[1], "side": r[2], "qty": r[3], "price": r[4], "charges": r[5], "tax": r[6], "decision_id": r[7]}
                   for r in con.execute("SELECT day, symbol, side, qty, price, charges, tax, decision_id FROM paper_trades ORDER BY trade_id DESC LIMIT 20").fetchall()]
    from pflab.paper import cadence
    v["acts"], v["lessons"], v["breaker"] = cadence.last_acts(con), cadence.lessons(con), cadence.breaker(con)
    from pflab.paper import watch as _wt
    v["watchlist"] = _wt.listing(con, datetime.now())
    v["working_on"] = open_case(con)
    v["money"] = {"this_month": round(spend_month(con, datetime.now()), 2), "monthly": settings()["monthly_rupees"]}
    v["days"] = [{"day": str(r[0]), "value": round(r[1], 2)} for r in con.execute("SELECT day, value FROM paper_days ORDER BY day").fetchall()]
    idx = _index(root) if root is not None else None                       # S78: the Nifty 500 over the same days, rebased to the account's first value (for the chart on Today)
    if idx is not None and len(idx) and v["days"]:
        base = None
        v["nifty"] = []
        for d in v["days"]:
            s_ = idx[idx.index <= pd.Timestamp(d["day"])]
            if not len(s_):
                continue
            base = base or float(s_.iloc[-1])
            v["nifty"].append({"day": d["day"], "value": round(v["days"][0]["value"] * float(s_.iloc[-1]) / base, 2)})
    from pflab.paper import funds
    try:
        v["topup"] = {"room": funds.room_this_month(con, day), "max": float(__import__("pflab.ledger.system", fromlist=["x"]).settings().get("topup_month_max", 50000.0))}
        v["moves"] = [{"kind": "TOP-UP" if r[0].startswith("topup:") else "MOVE", "what": ("Added to the bank" if r[0].startswith("topup:") else "Bank to broker"), "by": r[0][6:] if r[0].startswith("topup:") else "",
                       "amount": r[1], "day": str(r[2])} for r in con.execute(
            "SELECT ref, amount, trade_date FROM events WHERE account_id='SYSBANK' AND (ref LIKE 'topup:%' OR kind='cash_transfer') ORDER BY event_id DESC LIMIT 8").fetchall() if r[0]]
    except Exception:
        v["topup"], v["moves"] = None, []
    r_ = book.returns(con)
    v["sessions"] = r_["sessions"] if r_ else 0
    return v
