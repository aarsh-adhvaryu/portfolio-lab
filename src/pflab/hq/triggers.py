"""Monitoring that executes (S69). "I will watch this" is not a monitor: a monitor is a row the system checks, by code, on every HQ round.

Supported kinds (anything else is refused with the reason, and the answer then says it has NO executable trigger for that wish):

    price_below   {isin|symbol, value}      the latest close is at or below value
    price_above   {isin|symbol, value}      the latest close is at or above value
    move_pct      {isin|symbol, pct}        the close has moved by pct (negative: a fall) from the close when the trigger was set
    new_document  {isin|symbol}             a document about the company, published after the trigger was set, entered the graph
    review_on     {date}                    that day comes (YYYY-MM-DD)

A trigger belongs to an investigation. When it fires it is marked fired once, said in the investigation's log and the conversation, and the investigation
is reopened if it was finished (the coordinator plans only what changed). Nothing here trades or moves money.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import List, Optional

KINDS = ("price_below", "price_above", "move_pct", "new_document", "review_on")


def _isin(con, p: dict) -> Optional[str]:
    if p.get("isin"):
        return str(p["isin"]).strip().upper()
    sym = str(p.get("symbol") or "").strip().upper()
    if not sym:
        return None
    r = con.execute("SELECT isin FROM instruments WHERE upper(symbol)=? ORDER BY listed DESC NULLS LAST LIMIT 1", [sym]).fetchone()
    return r[0] if r else None


def last_close(con, isin: str, asof: Optional[date] = None):
    q = "SELECT date, close FROM prices WHERE isin=? AND close IS NOT NULL" + (" AND date<=?" if asof else "") + " ORDER BY date DESC LIMIT 1"
    r = con.execute(q, [isin, *([asof] if asof else [])]).fetchone()
    return (r[0], float(r[1])) if r else (None, None)


def validate(con, item: dict, now: datetime) -> dict:
    """A supported, fully specified trigger (with the company resolved and the reference price taken), or {'problem': why}."""
    kind = str(item.get("kind") or "").strip()
    if kind not in KINDS:
        return {"problem": f"kind {kind!r} is not one the system can check; supported: {', '.join(KINDS)}"}
    p = {k: v for k, v in item.items() if k != "kind"}
    if kind == "review_on":
        try:
            d = date.fromisoformat(str(p.get("date"))[:10])
        except ValueError:
            return {"problem": "review_on needs date as YYYY-MM-DD"}
        if d < now.date():
            return {"problem": "review_on must be a day in the future"}
        return {"kind": kind, "params": {"date": str(d)}, "ref": None}
    isin = _isin(con, p)
    if not isin:
        return {"problem": f"{kind}: name a held or watched company by isin or a symbol the record knows"}
    out = {"kind": kind, "params": {"isin": isin}, "ref": None}
    if kind in ("price_below", "price_above"):
        try:
            v = float(p["value"])
        except (KeyError, TypeError, ValueError):
            return {"problem": f"{kind} needs a price in rupees as value"}
        if v <= 0:
            return {"problem": f"{kind} needs a positive price"}
        out["params"]["value"] = v
    elif kind == "move_pct":
        try:
            pct = float(p["pct"])
        except (KeyError, TypeError, ValueError):
            return {"problem": "move_pct needs pct (negative for a fall), e.g. -10"}
        if not 0 < abs(pct) <= 90:
            return {"problem": "move_pct must be between 0 and 90 in size"}
        d, c = last_close(con, isin)
        if c is None:
            return {"problem": "move_pct needs a price on record for that company to measure from"}
        out["params"]["pct"] = pct
        out["params"]["ref_date"] = str(d)
        out["ref"] = c
    return out


def add(con, now: datetime, cid: int, items: List[dict], text: str = "") -> dict:
    """Persist the supported triggers for a case; return {'stored': [ids], 'unsupported': [reasons]}. The same trigger twice is stored once."""
    from pflab.hq import cases
    from pflab.pm.store import next_id
    stored, bad = [], []
    for it in items or []:
        v = validate(con, it, now) if isinstance(it, dict) else {"problem": "each trigger is an object with a kind"}
        if "problem" in v:
            bad.append(v["problem"])
            continue
        pj = json.dumps(v["params"], sort_keys=True)
        r = con.execute("SELECT trigger_id FROM hq_triggers WHERE case_id=? AND kind=? AND params_json=? AND status='active'", [cid, v["kind"], pj]).fetchone()
        if r:
            stored.append(int(r[0]))
            continue
        tid = next_id(con, "hq_triggers", "trigger_id")
        con.execute("INSERT INTO hq_triggers VALUES (?,?,?,?,?,?,?,?,?,?,?)", [tid, cid, now, v["kind"], pj, "active", text[:300], v["ref"], None, None, None])
        stored.append(tid)
    if stored:
        cases.log(con, cid, now, "monitor", f"{len(stored)} trigger(s) set: " + "; ".join(describe(con, t) for t in stored))
    return {"stored": stored, "unsupported": bad}


def describe(con, tid: int) -> str:
    r = con.execute("SELECT kind, params_json, status FROM hq_triggers WHERE trigger_id=?", [tid]).fetchone()
    if not r:
        return f"#{tid}"
    p = json.loads(r[1])
    sym = ""
    if p.get("isin"):
        s = con.execute("SELECT symbol FROM instruments WHERE isin=?", [p["isin"]]).fetchone()
        sym = (s[0] if s and s[0] else p["isin"]) + " "
    body = {"price_below": f"{sym}closes at or below Rs {p.get('value', 0):,.2f}", "price_above": f"{sym}closes at or above Rs {p.get('value', 0):,.2f}",
            "move_pct": f"{sym}moves {p.get('pct', 0):+.0f}% from {p.get('ref_date', '')}", "new_document": f"{sym}has a new document",
            "review_on": f"the date {p.get('date', '')} comes"}[r[0]]
    return f"#{tid} {r[0]}: {body}"


def active(con, cid: Optional[int] = None) -> List[dict]:
    q = "SELECT trigger_id, case_id, kind, params_json, status, created_at, last_checked, fired_at, fire_note, text FROM hq_triggers"
    rows = con.execute(q + (" WHERE case_id=?" if cid else "") + " ORDER BY trigger_id", [cid] if cid else []).fetchall()
    return [{"id": r[0], "case_id": r[1], "kind": r[2], "params": json.loads(r[3]), "status": r[4], "created_at": str(r[5])[:16],
             "last_checked": str(r[6])[:16] if r[6] else None, "fired_at": str(r[7])[:16] if r[7] else None, "note": r[8], "text": r[9],
             "describe": describe(con, r[0])} for r in rows]


def _met(con, kind: str, p: dict, ref, created: datetime, now: datetime) -> Optional[str]:
    """The sentence saying why the trigger fires now, or None."""
    if kind == "review_on":
        return f"the review date {p['date']} has come" if date.fromisoformat(p["date"]) <= now.date() else None
    isin = p["isin"]
    if kind == "new_document":
        r = con.execute("SELECT d.doc_id, d.title FROM kg_docs d JOIN kg_edges e ON e.src = d.doc_id AND e.dst = ? WHERE d.published_at > ? AND d.dup_of IS NULL "
                        "ORDER BY d.published_at DESC LIMIT 1", [f"company:{isin}", created]).fetchone()
        return f"a new document about the company: {r[0]} {(r[1] or '')[:80]}" if r else None
    d, c = last_close(con, isin, now.date())
    if c is None:
        return None
    if kind == "price_below" and c <= p["value"]:
        return f"the close on {d} (Rs {c:,.2f}) is at or below Rs {p['value']:,.2f}"
    if kind == "price_above" and c >= p["value"]:
        return f"the close on {d} (Rs {c:,.2f}) is at or above Rs {p['value']:,.2f}"
    if kind == "move_pct" and ref:
        mv = (c / ref - 1) * 100
        if (p["pct"] < 0 and mv <= p["pct"]) or (p["pct"] > 0 and mv >= p["pct"]):
            return f"the close on {d} (Rs {c:,.2f}) is {mv:+.1f}% from Rs {ref:,.2f} on {p.get('ref_date')}"
    return None


def check(rt) -> List[int]:
    """Look at every active trigger (free, code only). A fired one is marked, told once, and its investigation is reopened if it was finished or the
    coordinator is told in the log if it is running. Returns the ids that fired."""
    from pflab.hq import cases, missions
    con, now = rt.cursor(), rt.clock()
    fired = []
    for (tid, cid, kind, pj, ref, created) in con.execute(
            "SELECT trigger_id, case_id, kind, params_json, ref_value, created_at FROM hq_triggers WHERE status='active' ORDER BY trigger_id").fetchall():
        why = _met(con, kind, json.loads(pj), ref, created, now)
        con.execute("UPDATE hq_triggers SET last_checked=? WHERE trigger_id=?", [now, tid])
        if not why:
            continue
        con.execute("UPDATE hq_triggers SET status='fired', fired_at=?, fire_note=? WHERE trigger_id=? AND status='active'", [now, why[:300], tid])
        cases.log(con, cid, now, "trigger fired", f"{describe(con, tid)}: {why}")
        fired.append(tid)
        try:
            from pflab.app import assistant
            assistant.notify(con, now, f"A watch I set has fired for \"{(missions.mission_of(con, cid) or {}).get('goal', '')[:100]}\": {why}.", f"trigger:{tid}")
        except Exception:
            pass
        m = missions.mission_of(con, cid)
        if m and m["state"] == "done":
            missions.reopen(con, now, cid, f"a monitoring trigger fired: {why}")
    return fired
