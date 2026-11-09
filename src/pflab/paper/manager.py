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


# --- a decision ---------------------------------------------------------------------------------------------------------------------

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
    from pflab.hq import stocks
    from pflab.quant import marks
    n = 0
    for clid, isin, kind, ref_date, ref_close, due in con.execute(
            "SELECT claim_id, isin, kind, ref_date, ref_close, due_on FROM paper_claims WHERE scored_at IS NULL AND due_on <= ?", [now.date()]).fetchall():
        i0 = marks.index_on(index, ref_date) if index is not None else None
        i1 = marks.index_on(index, due) if index is not None else None
        end = (due, i1) if isin == "CASH" else marks.close_on(con, isin, due)
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
            beta = marks.beta_at(isin, ref_date)
            adj = sp - (beta if beta is not None else 1.0) * ip
            out = marks.judge(kind, sp, adj, stocks.round_trip_pct(stocks.DEFAULT_ORDER))
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

# --- the loop -----------------------------------------------------------------------------------------------------------------------

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
    out["scored"] = score_due(con, now, index)
    return out


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
    v["working_on"] = None
    v["money"] = {"this_month": round(spend_month(con, datetime.now()), 2), "monthly": settings()["monthly_rupees"]}
    try:                                                                   # the whole system's API money against his monthly cap (the paper team's share is the part above)
        from pflab.agents import analyst as _an
        v["money"]["total"] = round(float(_an.month_spend_inr(con, datetime.now())), 2)
        v["money"]["cap"] = float(_an.config().get("cap") or 0)
    except Exception:
        pass
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
