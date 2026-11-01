"""Buy, add, hold, reduce, sell, diversify and wait as distinct, reviewable proposals (S69).

A proposal is a recommendation the investor can discuss, amend, accept, reject or withdraw, and that the system withdraws or refreshes when its evidence or the
portfolio changes. It is NEVER an order: the system has no trading path, a GTT is an order, and accepting a proposal records his decision, nothing more. Trades
stay manual; a genuine confirmation he later supplies is matched to an accepted proposal by `reconcile`.

Maths decides: the model proposes the DIRECTION and the reasons; every number in a proposal is computed here from the record (prices with their dates, the cash,
the holding, the charges, the tax engine) and carries where it came from. Nothing is made up to fill a field:

    BUY / ADD        quantity (or the amount), price and its date, the cost of the trade, cash available and what is left, the weight before and after, and the
                     comparison with WAITING and with HOLDING what he has
    REDUCE / SELL    partial or full exit, quantity (never more than he holds), price and date, estimated proceeds after charges, and the tax effect from the
                     lots when the acquisition cost is on record; if it is not, the tax is UNKNOWN (never a cost of zero) and the comparison with holding stays
    HOLD / WAIT / DIVERSIFY   why this is preferable, the constraints, the alternatives considered, and a concrete condition for looking again (a wait with no
                     condition is refused)

Every proposal carries its missing inputs and assumptions, the record snapshot and the strategy version it used, and its review status (the independent reviewer's
verdict). When the ledger is incomplete a proposal still carries its direction and evidence but gives NO personalised size and NO tax figure.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Dict, List, Optional

ACTIONS = ("BUY", "ADD", "HOLD", "REDUCE", "SELL", "DIVERSIFY", "WAIT")
BUYING, SELLING, STAYING = ("BUY", "ADD"), ("REDUCE", "SELL"), ("HOLD", "DIVERSIFY", "WAIT")
OPEN = ("proposed", "accepted")
STATUSES = ("proposed", "accepted", "rejected", "withdrawn", "executed", "partly_executed", "superseded")
REVIEW = ("unreviewed", "approved", "revise", "rejected")
COLS = ["proposal_id", "created_at", "updated_at", "case_id", "action", "isin", "symbol", "status", "review_status", "version", "snapshot_id", "strategy_version",
        "payload_json", "missing_json", "executed_event_ids", "plan_version"]


# --- the strategy version: what the proposals were made under --------------------------------------------------------------------------------

def strategy_version(con) -> str:
    """The active strategy (policy) version. A proposed change to the strategy is a separate row until he approves it; nothing here activates one."""
    r = con.execute("SELECT version FROM hq_policy WHERE status='active' ORDER BY version DESC LIMIT 1").fetchone()
    return f"policy-v{r[0]}" if r else "policy-v0 (his targets file as it stands; no strategy change approved)"


def propose_strategy_change(con, now: datetime, body: dict, source: str = "the system") -> int:
    """A strategy change is written as `proposed` and sits beside the active version until he approves it (`activate`, from his own press)."""
    from pflab.pm.store import next_id
    v = next_id(con, "hq_policy", "version")
    con.execute("INSERT INTO hq_policy VALUES (?,?,?,?,?,?,?,?)", [v, now, "proposed", json.dumps(body), source, None, None, None])
    return v


def activate_strategy(con, now: datetime, version: int, by: str = "the investor") -> dict:
    r = con.execute("SELECT status FROM hq_policy WHERE version=?", [version]).fetchone()
    if not r or r[0] != "proposed":
        return {"activated": False, "why": "no such proposed strategy version"}
    con.execute("UPDATE hq_policy SET status='superseded' WHERE status='active'")
    con.execute("UPDATE hq_policy SET status='active', decided_at=?, decided_by=? WHERE version=?", [now, by, version])
    return {"activated": True, "version": version}


# --- the facts a proposal rests on (all from the record) -------------------------------------------------------------------------------------

def _facts(con, isin: str, asof: date) -> dict:
    from pflab.app import views
    h = views.holdings(con, asof)
    row = next((r for r in h["rows"] if r["isin"] == isin), None)
    inst = con.execute("SELECT symbol, name, asset_class, tax_class FROM instruments WHERE isin=?", [isin]).fetchone()
    pr = con.execute("SELECT date, close FROM prices WHERE isin=? AND close IS NOT NULL ORDER BY date DESC LIMIT 1", [isin]).fetchone()
    unknown_cost = bool(con.execute("SELECT 1 FROM events WHERE kind='buy' AND isin=? AND ref LIKE '%:cost_unknown' LIMIT 1", [isin]).fetchone())
    total = float(h["net_worth"] or 0) or float(h["investable"] or 0)
    top = sorted(h["rows"], key=lambda r: -(r["value"] or 0))
    return {"holdings": h, "row": row, "inst": inst, "price_date": str(pr[0])[:10] if pr else None, "price": float(pr[1]) if pr else None,
            "cost_unknown": unknown_cost, "total": total, "cash": float(h["cash"] or 0), "top": top}


def ledger_supports_sizing(con) -> Dict[str, object]:
    """Personalised sizing and tax figures need a ledger that is whole: holdings on record and no open difference the record cannot explain. Anything else
    is general research only, and the proposal says so. The test is deliberately simple and says why."""
    reasons = []
    n_events = con.execute("SELECT count(*) FROM events").fetchone()[0]
    if not n_events:
        reasons.append("the ledger has no events yet")
    try:
        gaps = con.execute("SELECT count(*) FROM known_gaps WHERE status='open'").fetchone()[0]
    except Exception:
        gaps = 0
    if gaps:
        reasons.append(f"{gaps} known gap(s) in the record are open")
    try:
        breaks = con.execute("SELECT count(*) FROM recon_breaks WHERE status='open'").fetchone()[0]
    except Exception:
        breaks = 0
    if breaks:
        reasons.append(f"{breaks} difference(s) from the broker are unexplained")
    return {"ok": not reasons, "reasons": reasons}


def _charges(row_asset: str, side: str, notional: float) -> Optional[float]:
    from pflab.pm import costs
    try:
        c, _known = costs.estimate(costs.segment_of(row_asset or "equity"), side, notional)
        return float(c)
    except Exception:
        return None


def _tax_effect(con, isin: str, qty: float, price: float, today: date, facts: dict) -> dict:
    """What the sale would add to this year's tax, replayed through the tax engine on the lots. Unknown when the acquisition cost is not on record."""
    if facts["cost_unknown"]:
        return {"status": "unknown", "why": "the purchase record (acquisition cost) for this holding is not in the ledger; no gain or tax is claimed",
                "extra_tax": None, "lots": []}
    try:
        from pflab.tax import plan as tp
        from pflab.tax import proposed as pr
        eng = tp.Engine(con)
        led_acc = con.execute("SELECT account_id FROM events WHERE isin=? AND kind='buy' GROUP BY account_id ORDER BY sum(qty) DESC LIMIT 1", [isin]).fetchone()
        if not led_acc:
            return {"status": "unknown", "why": "no purchase of this holding is on record", "extra_tax": None, "lots": []}
        from pflab.tax.india_lots import fy_of
        out = pr.proposed_sale(eng.log, led_acc[0], isin, qty, price, today, eng.tcl, **eng.kw(fy_of(today)))
        lots = out["lots"]
        rows = [] if lots is None or len(lots) == 0 else [{"bought": str(r.buy_date)[:10], "qty": float(r.qty), "gain": float(r.gain), "term": str(getattr(r, "term", ""))}
                                                           for r in lots.itertuples()] if {"buy_date", "qty", "gain"} <= set(lots.columns) else []
        return {"status": "estimate", "extra_tax": float(out["extra_tax_cheaper_regime"]), "by_regime": {k: float(out[k]["extra_tax"]) for k in ("new", "old")},
                "lots": rows[:8], "label": "estimate at the latest close, from the lots by FIFO, before charges; the tax engine's own figure replaces it on the day",
                "fy": out["fy"]}
    except Exception as e:                                        # said, never hidden and never zero
        return {"status": "unknown", "why": f"not computed ({type(e).__name__}: {str(e)[:120]})", "extra_tax": None, "lots": []}


def build(con, now: datetime, inputs: dict) -> dict:
    """Compute a proposal's facts from `inputs` (the model's direction and reasons plus optional quantity or amount). Returns {"payload", "missing", "problem"}.
    `problem` means it cannot be made as stated (more than held, no condition for a wait, ...) and nothing is stored."""
    action = str(inputs.get("action", "")).upper()
    if action not in ACTIONS:
        return {"problem": f"action must be one of {ACTIONS}"}
    reason = " ".join(str(inputs.get("reason", "")).split())
    alts = " ".join(str(inputs.get("alternatives", "")).split())
    if len(reason) < 20:
        return {"problem": "give the evidence and reason in a few sentences"}
    if len(alts) < 10:
        return {"problem": "name the alternatives considered (waiting, holding, doing less)"}
    cond = " ".join(str(inputs.get("review_condition", "")).split())
    if action in STAYING and len(cond) < 8:
        return {"problem": f"{action} needs a concrete condition for looking again (a price, a date, a document, an amount of cash)"}
    isin = str(inputs.get("isin") or "").strip().upper() or None
    symbol = str(inputs.get("symbol") or "").strip().upper() or None
    if not isin and symbol:
        r = con.execute("SELECT isin FROM instruments WHERE upper(symbol)=? ORDER BY listed DESC NULLS LAST LIMIT 1", [symbol]).fetchone()
        isin = r[0] if r else None
    if action != "WAIT" and action != "DIVERSIFY" and not isin:
        return {"problem": f"{action} names one company: give its symbol or isin as the record knows it"}
    asof = now.date()
    missing: List[str] = []
    facts = _facts(con, isin, asof) if isin else None
    sizing = ledger_supports_sizing(con)
    payload: Dict[str, object] = {"action": action, "reason": reason[:1500], "alternatives": alts[:1200], "assumptions": str(inputs.get("assumptions", ""))[:800],
                                  "evidence": [int(x) for x in (inputs.get("evidence_ids") or []) if str(x).isdigit()][:20], "review_condition": cond[:400] or None,
                                  "sizing_supported": sizing["ok"], "sizing_unsupported_because": sizing["reasons"], "made_on": str(asof)}
    if not sizing["ok"]:
        missing.append("a whole ledger: " + "; ".join(sizing["reasons"]) + " (so no personalised size and no tax figure is given)")
    if facts:
        payload["company"] = {"isin": isin, "symbol": (facts["inst"] or (symbol,))[0] or symbol, "name": (facts["inst"] or (None, None))[1]}
        if facts["price"] is None:
            missing.append("a price on record for this company")
        payload["price"] = {"value": facts["price"], "as_of": facts["price_date"], "source": "the stored close (prices table); not a live quote"} if facts["price"] else None
        row = facts["row"]
        held = float(row["qty"]) if row else 0.0
        payload["holding_now"] = {"qty": held, "value": row["value"] if row else 0.0, "weight": row["weight"] if row else 0.0,
                                  "cost_known": bool(row) and not row["cost_unknown"]} if row else {"qty": 0.0, "value": 0.0, "weight": 0.0, "cost_known": None}
        if row and row["cost_unknown"]:
            missing.append("the purchase cost of this holding (not on record: gain and tax are unknown, not zero)")
        asset = (facts["inst"] or (None, None, "equity", None))[2]
        px, total, cash = facts["price"], facts["total"], facts["cash"]
        payload["portfolio"] = {"total_rupees": round(total, 2), "cash_rupees": round(cash, 2), "snapshot": None, "price_note": "valued at stored closes"}
        qty = inputs.get("qty")
        amount = inputs.get("amount_rupees")
        if action in BUYING:
            if not sizing["ok"] or px is None:
                payload["size"] = None
            else:
                q = float(qty) if qty else (math.floor(float(amount) / px) if amount else 0.0)
                if q <= 0:
                    return {"problem": "a BUY or ADD needs a quantity or an amount in rupees"}
                notional = q * px
                fee = _charges(asset, "buy", notional)
                short = max(0.0, notional + (fee or 0) - cash)
                payload["size"] = {"qty": q, "notional": round(notional, 2), "charges_estimate": round(fee, 2) if fee is not None else None,
                                   "cash_after": round(cash - notional - (fee or 0), 2), "cash_shortfall": round(short, 2) or None}
                if short > 0:
                    missing.append(f"cash: the buy needs about Rs {short:,.0f} more than the cash on record")
                w0 = (row["value"] if row and row["value"] else 0.0) / total if total else 0.0
                w1 = ((row["value"] if row and row["value"] else 0.0) + notional) / total if total else 0.0
                payload["portfolio_effect"] = {"weight_before": round(w0, 4), "weight_after": round(w1, 4),
                                               "largest_holdings": [{"symbol": r["symbol"], "weight": round(r["weight"], 4)} for r in facts["top"][:4]]}
        elif action in SELLING:
            if held <= 0:
                return {"problem": f"nothing is held in this company on record, so there is nothing to {action.lower()}"}
            full = bool(inputs.get("full_exit")) or action == "SELL" and not qty
            q = held if full else (float(qty) if qty else (math.floor(float(amount) / px) if (amount and px) else 0.0))
            if q <= 0:
                return {"problem": "a REDUCE needs a quantity (or an amount) smaller than the holding"}
            if q > held + 1e-6:
                return {"problem": f"cannot propose selling {q:g}: only {held:g} are on record"}
            payload["exit"] = "full" if abs(q - held) < 1e-6 else "partial"
            if not sizing["ok"] or px is None:
                payload["size"] = None
            else:
                notional = q * px
                fee = _charges(asset, "sell", notional)
                payload["size"] = {"qty": q, "notional": round(notional, 2), "charges_estimate": round(fee, 2) if fee is not None else None,
                                   "proceeds_estimate": round(notional - (fee or 0), 2), "fraction_of_holding": round(q / held, 4)}
                payload["tax_effect"] = _tax_effect(con, isin, q, px, asof, facts)
                if payload["tax_effect"]["status"] == "unknown":
                    missing.append("tax effect: " + payload["tax_effect"]["why"])
                w0 = (row["value"] or 0.0) / total if total else 0.0
                payload["portfolio_effect"] = {"weight_before": round(w0, 4), "weight_after": round(max(0.0, ((row["value"] or 0.0) - notional)) / total, 4) if total else None}
            payload["hold_comparison"] = ("Continuing to hold keeps the whole position at market risk and defers any tax; selling converts it to cash "
                                          "(proceeds above) and realises the gain or loss. " + alts[:300])
        else:
            payload["portfolio_effect"] = {"weight_now": round(row["weight"], 4) if row else 0.0}
    elif action == "DIVERSIFY":
        h = _all_holdings(con, asof)
        payload["portfolio_effect"] = h
    if action in STAYING:
        payload["why_not_act"] = reason[:600]
    payload["not_an_order"] = "this proposal is advice for him to consider; the system places no order, and a trade is entered by him"
    return {"payload": payload, "missing": missing, "isin": isin, "symbol": (payload.get("company") or {}).get("symbol") or symbol}


def _all_holdings(con, asof: date) -> dict:
    from pflab.app import views
    h = views.holdings(con, asof)
    rows = sorted(h["rows"], key=lambda r: -(r["value"] or 0))
    return {"largest_holdings": [{"symbol": r["symbol"], "weight": round(r["weight"], 4), "sector": r["sector"]} for r in rows[:6]],
            "top3_share": round(sum(r["weight"] for r in rows[:3]), 4), "cash_rupees": round(float(h["cash"] or 0), 2), "holdings": len(rows)}


# --- storing, discussing, deciding -----------------------------------------------------------------------------------------------------------

def _log(con, pid: int, now: datetime, event: str, by: str, version: int, note: str = "") -> None:
    from pflab.pm.store import next_id
    con.execute("INSERT INTO hq_proposal_log VALUES (?,?,?,?,?,?,?)", [next_id(con, "hq_proposal_log", "log_id"), pid, now, event, by, version, note[:600]])


def create(con, now: datetime, inputs: dict, *, pm_dir=None, case_id: Optional[int] = None, by: str = "the system") -> dict:
    """Build and store a proposal. The same action on the same company in the same case supersedes the earlier open one (it is not duplicated)."""
    from pflab.hq import missions, plans
    from pflab.pm.store import next_id
    b = build(con, now, inputs)
    if "problem" in b:
        return {"stored": False, "problem": b["problem"]}
    from pflab.hq import rules
    from pflab.plan import envelope
    banned = rules.violation(con, b["payload"]["action"], b["isin"])
    if banned:                                             # S72: a house rule he made binds the proposals too; a WAIT or HOLD with the reason is still open to the system
        return {"stored": False, "problem": banned + ". Make this a WAIT or HOLD with the reason instead, or ask him whether he wants the rule undone."}
    eff = b["payload"].get("portfolio_effect") or {}
    for r in rules.active(con):
        if r["kind"] == "max_position" and b["payload"]["action"] in ("BUY", "ADD") and eff.get("weight_after") and eff["weight_after"] * 100 > float(r["machine"]["max_weight_pct"]):
            b["missing"].append(f"house rule '{r['name']}': this would take the holding to {eff['weight_after']:.1%}, above the {r['machine']['max_weight_pct']:g}% ceiling he set; reduce the size")
    size = b["payload"].get("size") or {}
    if b["payload"]["action"] in ("BUY", "ADD") and size.get("notional"):
        env = envelope.status(con, now.date())
        if env.get("active"):
            b["payload"]["envelope"] = {"available_now": env["available_now"], "this_buy": size["notional"], "carry_over": env["carry_over"]}
            if size["notional"] > env["available_now"] + 1e-6:
                b["missing"].append(f"the monthly envelope: this buy is Rs {size['notional']:,.0f}, above the Rs {env['available_now']:,.0f} available now (a dip tranche, if triggered, is counted by the daily review)")
    snap = missions.snapshot_id(con, pm_dir) if pm_dir else "unknown"
    b["payload"]["portfolio"] = {**(b["payload"].get("portfolio") or {}), "snapshot": snap}
    prev = con.execute("SELECT proposal_id, version FROM hq_proposals WHERE coalesce(case_id, 0)=? AND coalesce(isin, '')=? AND action=? AND status IN ('proposed') "
                       "ORDER BY proposal_id DESC LIMIT 1", [case_id or 0, b["isin"] or "", b["payload"]["action"]]).fetchone()
    if prev:
        return amend_stored(con, now, int(prev[0]), b, snap, by, why="the same proposal made again")
    pid = next_id(con, "hq_proposals", "proposal_id")
    con.execute("INSERT INTO hq_proposals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [pid, now, now, case_id, b["payload"]["action"], b["isin"], b["symbol"], "proposed", "unreviewed", 1, snap, strategy_version(con),
                 json.dumps(b["payload"], default=str), json.dumps(b["missing"]), None, plans.active_number(con, case_id) if case_id else None])
    _log(con, pid, now, "created", by, 1, b["payload"]["reason"][:200])
    return {"stored": True, "proposal_id": pid, "version": 1, "missing": b["missing"], "review_status": "unreviewed", "snapshot": snap}


def amend_stored(con, now: datetime, pid: int, b: dict, snap: str, by: str, why: str = "") -> dict:
    r = con.execute("SELECT version FROM hq_proposals WHERE proposal_id=?", [pid]).fetchone()
    v = int(r[0]) + 1
    con.execute("UPDATE hq_proposals SET updated_at=?, version=?, snapshot_id=?, strategy_version=?, payload_json=?, missing_json=?, review_status='unreviewed', symbol=? WHERE proposal_id=?",
                [now, v, snap, strategy_version(con), json.dumps(b["payload"], default=str), json.dumps(b["missing"]), b["symbol"], pid])
    _log(con, pid, now, "amended", by, v, why or "amended")
    return {"stored": True, "proposal_id": pid, "version": v, "missing": b["missing"], "review_status": "unreviewed", "snapshot": snap}


def get(con, pid: int) -> Optional[dict]:
    r = con.execute("SELECT " + ", ".join(COLS) + " FROM hq_proposals WHERE proposal_id=?", [pid]).fetchone()
    if not r:
        return None
    d = dict(zip(COLS, r))
    d["payload"], d["missing"] = json.loads(d.pop("payload_json")), json.loads(d.pop("missing_json") or "[]")
    d["log"] = [{"at": str(a)[:16], "event": e, "by": b, "version": v, "note": n} for a, e, b, v, n in con.execute(
        "SELECT logged_at, event, actor, version, note FROM hq_proposal_log WHERE proposal_id=? ORDER BY log_id", [pid]).fetchall()]
    for k in ("created_at", "updated_at"):
        d[k] = str(d[k])[:19]
    return d


def listing(con, status: Optional[str] = None, case_id: Optional[int] = None, limit: int = 30) -> List[dict]:
    q, a = "SELECT proposal_id FROM hq_proposals WHERE 1=1", []
    if status:
        q += " AND status=?"
        a.append(status)
    if case_id:
        q += " AND case_id=?"
        a.append(case_id)
    return [get(con, r[0]) for r in con.execute(q + " ORDER BY proposal_id DESC LIMIT ?", [*a, limit]).fetchall()]


def stale_reason(con, p: dict, pm_dir=None) -> Optional[str]:
    """Why an open proposal no longer rests on the record: the portfolio snapshot moved on, or an executed trade changed the holding."""
    if p["status"] not in OPEN:
        return None
    from pflab.hq import missions
    now = missions.snapshot_id(con, pm_dir) if pm_dir else None
    if now and p["snapshot_id"] and now != p["snapshot_id"]:
        return f"made on snapshot {p['snapshot_id']}; the record is now {now}"
    return None


def discuss(con, now: datetime, pid: int, note: str, by: str = "the investor") -> dict:
    p = get(con, pid)
    if not p:
        return {"ok": False, "why": "no such proposal"}
    _log(con, pid, now, "discussed", by, p["version"], note)
    return {"ok": True, "proposal_id": pid}


def decide(con, now: datetime, pid: int, decision: str, by: str = "the investor", note: str = "") -> dict:
    """accept | reject | withdraw. Only open proposals can be decided; accepting is his decision to act himself, not an order."""
    p = get(con, pid)
    if not p:
        return {"ok": False, "why": "no such proposal"}
    if decision not in ("accept", "reject", "withdraw"):
        return {"ok": False, "why": "accept, reject or withdraw"}
    if p["status"] not in OPEN:
        return {"ok": False, "why": f"the proposal is {p['status']}"}
    if decision in ("accept", "reject") and p["status"] != "proposed":
        return {"ok": False, "why": "already accepted: withdraw it if he has changed his mind" if p["status"] == "accepted" else f"the proposal is {p['status']}"}
    status = {"accept": "accepted", "reject": "rejected", "withdraw": "withdrawn"}[decision]
    extra = ""
    if decision == "accept" and p["review_status"] != "approved":
        extra = f" (accepted while the independent review is '{p['review_status']}')"
    con.execute("UPDATE hq_proposals SET status=?, updated_at=? WHERE proposal_id=?", [status, now, pid])
    _log(con, pid, now, status, by, p["version"], (note + extra).strip())
    return {"ok": True, "proposal_id": pid, "status": status, "note": extra.strip() or None,
            "reminder": "accepting does not place an order: you enter the trade yourself; when its confirmation arrives the record updates by itself" if decision == "accept" else None}


def set_review(con, now: datetime, pid: int, verdict: str, note: str = "") -> None:
    rs = {"approve": "approved", "approved": "approved", "revise": "revise", "reject": "rejected", "rejected": "rejected"}.get(verdict)
    if not rs:
        return
    con.execute("UPDATE hq_proposals SET review_status=?, updated_at=? WHERE proposal_id=? AND status IN ('proposed','accepted')", [rs, now, pid])
    p = get(con, pid)
    if p:
        _log(con, pid, now, "reviewed", "independent reviewer", p["version"], f"{rs}: {note[:200]}")


def review_case(con, now: datetime, cid: int, verdict: str, note: str = "") -> List[int]:
    """The independent review of an investigation covers the proposals it made: each open one takes the verdict."""
    ids = [r[0] for r in con.execute("SELECT proposal_id FROM hq_proposals WHERE case_id=? AND status IN ('proposed','accepted')", [cid]).fetchall()]
    for pid in ids:
        set_review(con, now, pid, verdict, note)
    return ids


# --- the evidence changes: a proposal is withdrawn or refreshed -------------------------------------------------------------------------------

def evidence_changed(con, now: datetime, cid: int, why: str) -> List[int]:
    """New or contradicting evidence arrived for an investigation: its open proposals are marked for re-review (not silently kept as they were) and the
    log says why. The coordinator's follow-up decides whether to amend or withdraw."""
    ids = [r[0] for r in con.execute("SELECT proposal_id FROM hq_proposals WHERE case_id=? AND status='proposed'", [cid]).fetchall()]
    for pid in ids:
        con.execute("UPDATE hq_proposals SET review_status='unreviewed', updated_at=? WHERE proposal_id=?", [now, pid])
        p = get(con, pid)
        _log(con, pid, now, "evidence_changed", "the system", p["version"], why[:300])
    return ids


# --- his confirmation arrives: the record is rebuilt by the ledger; the accepted proposal is matched to what actually happened ---------------------

def _trade_keys(con, kind: str, isin: str, since: date) -> List[dict]:
    """The trades of this kind in this company since `since`, each with a STABLE key: the ledger is rebuilt from the documents and its event numbers are
    not kept from one build to the next, so a trade is known by what it is (account, day, company, side, quantity, price, the document's reference), with
    a counter for genuinely identical twins."""
    import hashlib
    rows = con.execute("SELECT account_id, trade_date, qty, price, ref, fees_json FROM events WHERE kind=? AND isin=? AND trade_date >= ? ORDER BY trade_date, event_id",
                       [kind, isin, since]).fetchall()
    seen: Dict[str, int] = {}
    out = []
    for acc, d, q, px, ref, fj in rows:
        base = hashlib.sha1(f"{acc}|{d}|{isin}|{kind}|{float(q or 0):.6f}|{float(px or 0):.6f}|{ref or ''}".encode()).hexdigest()[:16]
        seen[base] = seen.get(base, 0) + 1
        try:
            fees = sum(float(v) for v in json.loads(fj or "{}").values())
        except Exception:
            fees = 0.0
        out.append({"key": f"{base}#{seen[base]}", "date": str(d)[:10], "qty": float(q or 0), "price": float(px or 0), "fees": fees})
    return out


def reconcile(con, now: datetime) -> List[dict]:
    """Match accepted BUY/ADD/REDUCE/SELL proposals to the trades the ledger now holds for that company on or after the day it was accepted. A trade is linked
    to ONE proposal, once (its stable key is kept on the proposal), so ingesting the same confirmation again cannot count it twice; the proposal becomes
    executed or partly executed with what was really traded (quantity, average price, charges) set beside what was proposed. The investigation that made it
    is told, and a finished one is reopened to look at the new position."""
    from pflab.hq import cases
    out = []
    taken = {k for (j,) in con.execute("SELECT executed_event_ids FROM hq_proposals WHERE executed_event_ids IS NOT NULL").fetchall() for k in json.loads(j)}
    for pid, cid, action, isin, accepted_at in con.execute(
            "SELECT p.proposal_id, p.case_id, p.action, p.isin, (SELECT max(logged_at) FROM hq_proposal_log l WHERE l.proposal_id=p.proposal_id AND l.event='accepted') "
            "FROM hq_proposals p WHERE p.status IN ('accepted','partly_executed') AND p.action IN ('BUY','ADD','REDUCE','SELL') ORDER BY p.proposal_id").fetchall():
        p = get(con, pid)
        kind = "buy" if action in BUYING else "sell"
        want = float(((p["payload"].get("size") or {}).get("qty")) or 0)
        mine = json.loads(con.execute("SELECT coalesce(executed_event_ids, '[]') FROM hq_proposals WHERE proposal_id=?", [pid]).fetchone()[0])
        trades = _trade_keys(con, kind, isin, (accepted_at or now).date())
        have = [t for t in trades if t["key"] in mine]
        filled = sum(t["qty"] for t in have)
        added = []
        for t in trades:
            if t["key"] in taken or t["key"] in mine:
                continue
            if want and filled >= want - 1e-6:
                break
            added.append(t)
            filled += t["qty"]
        if not added:
            continue
        used = have + added
        for t in added:
            taken.add(t["key"])
        q = sum(t["qty"] for t in used)
        avg = sum(t["qty"] * t["price"] for t in used) / q if q else None
        fees = sum(t["fees"] for t in used)
        status = "executed" if (not want or q >= want - 1e-6) else "partly_executed"
        con.execute("UPDATE hq_proposals SET status=?, executed_event_ids=?, updated_at=? WHERE proposal_id=?", [status, json.dumps([t["key"] for t in used]), now, pid])
        note = f"{q:g} @ about Rs {avg:,.2f} (charges Rs {fees:,.2f}) against {want:g} proposed; trades on {', '.join(sorted({t['date'] for t in used}))}"
        _log(con, pid, now, status, "the ledger", p["version"], note)
        if cid:
            cases.log(con, cid, now, "proposal executed", f"proposal #{pid} {action} {p['symbol']}: {note}")
        _refresh_case(con, now, cid, pid, p, note)
        out.append({"proposal_id": pid, "status": status, "qty": q, "avg_price": avg, "trades": [t["key"] for t in used]})
    return out


def _refresh_case(con, now: datetime, cid: int, pid: int, p: dict, note: str) -> None:
    """The portfolio changed because of a trade he made: the investigation that proposed it is told, the other open proposals on the same company are marked
    to be re-reviewed, and a finished investigation is reopened to look at the new position."""
    from pflab.hq import missions
    others = [r[0] for r in con.execute("SELECT proposal_id FROM hq_proposals WHERE isin=? AND proposal_id<>? AND status='proposed'", [p["isin"], pid]).fetchall()]
    for o in others:
        con.execute("UPDATE hq_proposals SET review_status='unreviewed', updated_at=? WHERE proposal_id=?", [now, o])
        _log(con, o, now, "evidence_changed", "the system", get(con, o)["version"], f"the holding changed: proposal #{pid} was executed")
    m = missions.mission_of(con, cid) if cid else None
    if m and m["state"] == "done":
        missions.reopen(con, now, cid, f"a trade he made changed the portfolio ({p['action']} {p['symbol']}: {note[:160]})")
    try:
        from pflab.app import assistant
        assistant.notify(con, now, f"Your {p['action'].lower()} of {p['symbol']} is in the record now: {note}. The holdings, cash and my related research are updated.",
                         f"proposal-executed:{pid}:{p['version']}")
    except Exception:
        pass
