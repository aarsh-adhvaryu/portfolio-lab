"""The system's OWN allocation target (S79, A45): how the system's book should be split between asset classes (equity, gold, international, cash) and between sectors.

Who decides what. The paper team (direction and reasons) proposes the target with `propose_allocation`; the independent reviewer of the paper mission judges it (the same
verdict `hq_case_reviews` that gates the mission's trades); only then does it become ACTIVE. CODE only checks it against the hard rails, never invents it, measures how far
the book is from it (`drift`) and hands the manager the gap (`trade_toward`); the manager's own sizing and the rails still decide every amount. A weekly review re-examines
the target (`review_due`). His `targets.toml` is never read or changed here: this target is the system's book only.

Weights are PERCENT of the book's value (the cash of the fake broker and bank counts as `cash`). Sector weights are percent of the whole book, companies only (as the rail).
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from pflab.paper import rails

CLASSES = ("equity", "gold", "international", "cash")
TOL = 0.05                                           # percentage points: weights are typed with decimals
BAND_PCT = 2.0                                       # a gap smaller than this (points of the book) is "in band": no trade is asked for
REVIEW_EVERY_DAYS = 7
DONE_STATES = ("done", "blocked", "declined")
_FORBIDDEN = re.compile(r"f&o|fno|future|option|derivativ|margin|borrow|loan|leverag|short|credit|pledg|swap", re.I)
_INTL = re.compile(r"nasdaq|s&p ?500|\bsp ?500\b|hang ?seng|\bfang|overseas|international|global|world|\bus ?(?:equity|tech)|\bnyse|msci (?:world|em|emerging|eafe|china|us)|china|japan|europe", re.I)
_GOLD = re.compile(r"\bgold|silver|sovereign gold|\bsgb\b", re.I)
_CASHLIKE = re.compile(r"liquid|overnight|gilt|g-?sec|\bsdl\b|treasury|money market|\bbond\b|debt|t-?bill|ultra short|low duration", re.I)


# --- the rails, in code -----------------------------------------------------------------------------------------------------------------

def validate_target(weights: dict, sectors: Optional[dict] = None) -> dict:
    """Check a target against the hard rails. `weights`: class -> percent (equity, gold, international, cash), summing to 100, each at or above zero (no borrowing: cash
    is never negative; no short sales: no weight is negative; no F&O: only these four classes exist). `sectors`: sector -> percent of the whole book, each at most the
    25% sector rail and together at most the equity weight. A single company stays at 10% and a single ETF at 35% whatever the target says: those are applied on every
    buy (`paper/rails.py`), and the target may not ask for a higher cap. Returns {ok, problems, classes, sectors}; nothing is changed."""
    problems: List[str] = []
    raw = dict(weights or {})
    if "sectors" in raw and sectors is None and isinstance(raw["sectors"], dict):
        sectors = raw.pop("sectors")
    raw.pop("sectors", None)
    classes: Dict[str, float] = {c: 0.0 for c in CLASSES}
    for k, v in raw.items():
        key = str(k).strip().lower()
        if _FORBIDDEN.search(key):
            problems.append(f"'{k}' is not allowed: no F&O, no borrowing, no short sales")
            continue
        if key not in CLASSES:
            problems.append(f"unknown asset class '{k}': use {', '.join(CLASSES)}")
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            problems.append(f"{k} is not a number")
            continue
        if not math.isfinite(x):
            problems.append(f"{k} is not a finite number")
            continue
        if x < 0:
            problems.append(f"{k} is below zero ({x:g}%): no short sales and no borrowing")
        classes[key] = x
    total = sum(classes.values())
    if abs(total - 100.0) > TOL and not any("is not" in p for p in problems):
        problems.append(f"the class weights sum to {total:g}%, not 100% (percent of the book; leverage is not allowed)")
    secs: Dict[str, float] = {}
    for k, v in (sectors or {}).items():
        name = " ".join(str(k).split())
        if not name:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            problems.append(f"sector {k} is not a number")
            continue
        if not math.isfinite(x) or x < 0:
            problems.append(f"sector {k} must be zero or more")
            continue
        if x > rails.MAX_SECTOR * 100 + TOL:
            problems.append(f"sector {k} at {x:g}% is over the {rails.MAX_SECTOR:.0%} sector rail")
        secs[name] = x
    if secs and sum(secs.values()) > classes["equity"] + TOL:
        problems.append(f"the sectors add up to {sum(secs.values()):g}% but equity is {classes['equity']:g}%: sectors are companies, which are equity")
    return {"ok": not problems, "problems": problems, "classes": {k: round(v, 4) for k, v in classes.items()}, "sectors": {k: round(v, 4) for k, v in secs.items()},
            "rails": {"one company": f"{rails.MAX_STOCK:.0%}", "one sector": f"{rails.MAX_SECTOR:.0%}", "one ETF": f"{rails.MAX_ETF:.0%}"}}


def class_of(asset_class: Optional[str], name: Optional[str] = None, symbol: Optional[str] = None, isin: Optional[str] = None) -> str:
    """The target class a holding counts in. Gold (ETF, SGB, physical) -> gold; an ETF or fund on foreign markets (by name; a pseudo-ISIN ZZ.. or US:..) -> international;
    liquid, overnight, gilt and other debt funds or bonds -> cash; everything else (shares, index ETFs) -> equity. By the instrument's own words, no model."""
    ac = (asset_class or "").lower()
    text = f"{name or ''} {symbol or ''}"
    if str(isin or "").startswith(("ZZ", "US:")):
        return "international"
    if ac in ("sgb", "gold_physical") or (ac in ("etf", "mutual_fund", "") and _GOLD.search(text)):
        return "gold"
    if ac in ("bond", "mutual_fund") and _CASHLIKE.search(text) or ac == "bond":
        return "cash"
    if ac == "etf":
        if _CASHLIKE.search(text):
            return "cash"
        if _INTL.search(text):
            return "international"
    return "equity"


# --- measuring the book against it -------------------------------------------------------------------------------------------------------

def drift(book: dict, target: dict) -> dict:
    """How far the book is from the target. `book`: `paper.book.holdings(con, day)`; `target`: {'classes': {...pct}, 'sectors': {...pct}}. A gap is target minus actual in
    points of the book (positive: the book holds too little, negative: too much) and in rupees at today's value."""
    total = float(book.get("value") or 0.0)
    cls_val = {c: 0.0 for c in CLASSES}
    sec_val: Dict[str, float] = {}
    members: Dict[str, List[dict]] = {c: [] for c in CLASSES}
    for r in book.get("rows", []):
        v = float(r.get("value") or 0.0)
        c = class_of(r.get("asset_class"), r.get("name"), r.get("symbol"), r.get("isin"))
        cls_val[c] += v
        members[c].append({"symbol": r.get("symbol"), "isin": r.get("isin"), "weight_pct": round((r.get("weight") or 0.0) * 100, 2)})
        if r.get("sector") and (r.get("asset_class") or "") != "etf":
            sec_val[r["sector"]] = sec_val.get(r["sector"], 0.0) + v
    cls_val["cash"] += float(book.get("cash") or 0.0) + float(book.get("bank") or 0.0)
    tc, ts = (target or {}).get("classes") or {}, (target or {}).get("sectors") or {}

    def line(name: str, want: Optional[float], have_v: float) -> dict:
        have = 100.0 * have_v / total if total > 0 else 0.0
        gap = None if want is None else float(want) - have
        return {"name": name, "target_pct": None if want is None else round(float(want), 2), "actual_pct": round(have, 2), "gap_pct": None if gap is None else round(gap, 2),
                "gap_rupees": None if gap is None else round(gap / 100.0 * total, 2), "in_band": gap is None or abs(gap) < BAND_PCT}
    classes = [dict(line(c, tc.get(c, 0.0), cls_val[c]), holdings=members[c][:8]) for c in CLASSES]
    sectors = [line(s, ts.get(s, None), sec_val.get(s, 0.0)) for s in sorted(set(ts) | set(sec_val))]
    gaps = [abs(x["gap_pct"]) for x in classes + sectors if x["gap_pct"] is not None]
    return {"total": round(total, 2), "classes": classes, "sectors": sectors, "max_abs_gap_pct": round(max(gaps), 2) if gaps else 0.0,
            "in_band": all(x["in_band"] for x in classes + sectors), "band_pct": BAND_PCT}


def trade_toward(book: dict, target: dict) -> dict:
    """The gap the paper manager works from, per class and per sector, beyond the band: what to add and what to trim, in points and rupees. It names no security and no
    amount to trade: the team picks the names, and the manager's sizing and the rails (10% company, 25% sector, 35% ETF, cash, circuit breaker) cut every order."""
    d = drift(book, target)
    add = [x for x in d["classes"] + d["sectors"] if x["gap_pct"] is not None and x["gap_pct"] >= BAND_PCT]
    trim = [x for x in d["classes"] + d["sectors"] if x["gap_pct"] is not None and x["gap_pct"] <= -BAND_PCT]
    add.sort(key=lambda x: -x["gap_pct"])
    trim.sort(key=lambda x: x["gap_pct"])
    return {"in_band": d["in_band"], "add": add, "trim": trim, "total": d["total"], "max_abs_gap_pct": d["max_abs_gap_pct"],
            "note": "a direction only: the manager's sizing and the rails decide every amount; doing nothing while the book is in band is a decision too"}


# --- the record --------------------------------------------------------------------------------------------------------------------------

def _row(con, r) -> dict:
    keys = ("target_id", "market", "proposed_at", "proposed_by", "case_id", "classes_json", "sectors_json", "reasons", "status", "verdict", "verdict_notes", "reviewed_at",
            "activated_at", "review_due", "reexamined_at", "reexamined_notes", "superseded_by")
    d = dict(zip(keys, r))
    d["classes"] = json.loads(d.pop("classes_json") or "{}")
    d["sectors"] = json.loads(d.pop("sectors_json") or "{}")
    return d


def _select(con, where: str, params: list, order: str = "target_id DESC", limit: int = 20) -> List[dict]:
    cols = ("target_id, market, proposed_at, proposed_by, case_id, classes_json, sectors_json, reasons, status, verdict, verdict_notes, reviewed_at, activated_at, "
            "review_due, reexamined_at, reexamined_notes, superseded_by")
    return [_row(con, r) for r in con.execute(f"SELECT {cols} FROM system_allocation_s79 WHERE {where} ORDER BY {order} LIMIT {int(limit)}", params).fetchall()]


def active_target(con, market: str = "IN") -> Optional[dict]:
    r = _select(con, "status='active' AND market=?", [market], limit=1)
    return r[0] if r else None


def pending(con, market: str = "IN") -> List[dict]:
    return _select(con, "status='proposed' AND market=?", [market])


def history(con, market: str = "IN", limit: int = 10) -> List[dict]:
    return _select(con, "market=?", [market], limit=limit)


def _same(a: dict, b: dict) -> bool:
    return all(abs(float(a.get(k, 0.0)) - float(b.get(k, 0.0))) <= TOL for k in set(a) | set(b))


def propose_allocation(con, weights: dict, reasons: str, now: datetime, *, sectors: Optional[dict] = None, case_id: Optional[int] = None,
                       by: str = "the paper team", market: str = "IN", review_days: int = REVIEW_EVERY_DAYS) -> dict:
    """The team proposes the system's allocation target (direction and reasons are theirs; code checks the rails and stores). It waits for the independent review of the
    mission (`settle`) before it is active. The same target as the active one is a RE-EXAMINATION: it is recorded with the reasons and the review date moves a week on."""
    from pflab.pm.store import next_id
    reasons = " ".join(str(reasons or "").split())
    if len(reasons) < 40:
        return {"stored": False, "problem": "give the reasons for this split in a few sentences (what the book should hold and why, and what would change it)"}
    v = validate_target(weights, sectors)
    if not v["ok"]:
        return {"stored": False, "problem": "; ".join(v["problems"]), "rails": v["rails"]}
    act = active_target(con, market)
    if act and _same(act["classes"], v["classes"]) and _same(act["sectors"], v["sectors"]):
        due = now.date() + timedelta(days=review_days)
        con.execute("UPDATE system_allocation_s79 SET reexamined_at=?, reexamined_notes=?, review_due=? WHERE target_id=?", [now, reasons[:1500], due, act["target_id"]])
        return {"stored": True, "reaffirmed": True, "target_id": act["target_id"], "review_due": str(due), "note": "the active target stands; its next re-examination is due then"}
    tid = next_id(con, "system_allocation_s79", "target_id")
    con.execute("INSERT INTO system_allocation_s79 (target_id, market, proposed_at, proposed_by, case_id, classes_json, sectors_json, reasons, status, review_due) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                [tid, market, now, by, case_id, json.dumps(v["classes"], sort_keys=True), json.dumps(v["sectors"], sort_keys=True), reasons[:1500], "proposed",
                 now.date() + timedelta(days=review_days)])
    same_case = "case_id IS NULL" if case_id is None else "case_id = ?"
    con.execute(f"UPDATE system_allocation_s79 SET status='superseded', superseded_by=? WHERE status='proposed' AND market=? AND target_id <> ? AND {same_case}",
                [tid, market, tid] + ([] if case_id is None else [case_id]))
    return {"stored": True, "target_id": tid, "classes": v["classes"], "sectors": v["sectors"], "status": "proposed",
            "next": "the independent review of this mission judges it; it becomes the active target only if the review approves"}


def review_target(con, target_id: int, verdict: str, notes: str, now: datetime) -> dict:
    """Record the independent reviewer's verdict on a proposed target. approve -> active (the one before it is superseded); revise or reject -> 'reviewed', never active."""
    from pflab.hq import missions
    v = missions.verdict_of(verdict)
    r = _select(con, "target_id=?", [int(target_id)], limit=1)
    if not r or r[0]["status"] != "proposed":
        return {"done": False, "why": "no proposed target with that id"}
    t = r[0]
    if v == "approve":
        con.execute("UPDATE system_allocation_s79 SET status='superseded', superseded_by=? WHERE status='active' AND market=?", [t["target_id"], t["market"]])
        con.execute("UPDATE system_allocation_s79 SET status='active', verdict=?, verdict_notes=?, reviewed_at=?, activated_at=?, review_due=? WHERE target_id=?",
                    [v, (notes or "")[:600], now, now, now.date() + timedelta(days=REVIEW_EVERY_DAYS), t["target_id"]])
    else:
        con.execute("UPDATE system_allocation_s79 SET status='reviewed', verdict=?, verdict_notes=?, reviewed_at=? WHERE target_id=?", [v or "none", (notes or "")[:600], now, t["target_id"]])
    return {"done": True, "target_id": t["target_id"], "verdict": v, "status": "active" if v == "approve" else "reviewed"}


def settle(con, now: datetime) -> List[dict]:
    """Every proposed target whose paper mission has finished takes the mission's review verdict (the review given after the proposal). Idempotent; the manager's nightly
    bookkeeping calls it. A target proposed with no mission waits for `review_target`."""
    out = []
    for t in pending(con):
        if t["case_id"] is None:
            continue
        m = con.execute("SELECT state FROM hq_missions WHERE case_id=?", [t["case_id"]]).fetchone()
        if not m or m[0] not in DONE_STATES:
            continue
        r = con.execute("SELECT outcome, note FROM hq_case_reviews WHERE case_id=? AND outcome IS NOT NULL AND reviewed_at >= ? ORDER BY review_id DESC LIMIT 1",
                        [t["case_id"], t["proposed_at"]]).fetchone()
        res = review_target(con, t["target_id"], r[0] if r else "none", (r[1] if r else "no review was given after the proposal"), now)
        out.append(res)
    return out


def review_due(con, now: datetime, market: str = "IN") -> dict:
    """Is a look at the allocation due? Yes when there is no target and none waits for its review (the team's FIRST review proposes the first one), or when the active
    target's review date has come (the weekly review re-examines it). The lead starts the paper mission on this."""
    act, wait = active_target(con, market), pending(con, market)
    if wait:
        return {"due": False, "why": f"target #{wait[0]['target_id']} waits for the independent review", "target_id": wait[0]["target_id"], "due_on": None, "first": act is None}
    if act is None:
        return {"due": True, "first": True, "why": "the system has no allocation target of its own yet: the team proposes the first one", "target_id": None, "due_on": None}
    due = act["review_due"]
    if due is not None and due <= now.date():
        return {"due": True, "first": False, "why": f"weekly re-examination of target #{act['target_id']} (due {due})", "target_id": act["target_id"], "due_on": str(due)}
    return {"due": False, "first": False, "why": "the active target was re-examined in the last week", "target_id": act["target_id"], "due_on": str(due) if due else None}


def reasons(con, now: datetime, market: str = "IN") -> List[str]:
    """For `paper.manager.reasons_to_look`: the allocation's reason to open the paper team's work, if any."""
    try:
        if not con.execute("SELECT 1 FROM reseed_s79 LIMIT 1").fetchone() and active_target(con, market) is None:      # before the A45 re-seed the book has no target to ask for
            return []
        d = review_due(con, now, market)
        last = con.execute("SELECT max(created_at) FROM hq_missions WHERE origin='paper'").fetchone()[0]
    except Exception:
        return []
    out: List[str] = []
    if not (last is not None and (now - last) < timedelta(days=1)) and d["due"]:      # a mission for it was opened today: one look a day at most (the team may re-affirm or hold the target)
        out.append(d["why"])
    try:                                                                                # S79b 18E: money added since the last look is a reason to deploy it under the target
        dep = deploy_reason(con, now, market)
        if dep:
            out.append(dep)
    except Exception:
        pass
    return out


def deploy_reason(con, now: datetime, market: str = "IN") -> Optional[str]:
    """A top-up (the investor's or the system's own) reached the fake bank since the paper team last looked, and cash is above its target class weight by more than the band:
    the next review must see it and deploy it toward the active target. None otherwise (no target, no new top-up, or cash already within its band)."""
    act = active_target(con, market)
    if act is None:
        return None
    last = con.execute("SELECT max(created_at) FROM hq_missions WHERE origin='paper'").fetchone()[0]
    q = "SELECT coalesce(sum(amount), 0), max(trade_date) FROM events WHERE kind='deposit' AND account_id='SYSBANK' AND ref LIKE 'topup:%'" + (" AND ingested_at > ?" if last is not None else "")
    amt, when = con.execute(q, [last] if last is not None else []).fetchone()
    if not amt or amt <= 0:
        return None
    from pflab.paper import book as pb
    if not pb.started(con):
        return None
    line = next((x for x in drift(pb.holdings(con, now.date()), act)["classes"] if x["name"] == "cash"), None)
    if line is None or line["gap_pct"] is None or line["gap_pct"] > -BAND_PCT:
        return None
    return (f"a top-up of Rs {amt:,.0f} reached the bank (latest {when}) and cash is {line['actual_pct']:.1f}% of the book against a target of {line['target_pct']:.1f}%: "
            f"deploy it toward the target (the team picks the names; sizes and rails are code's)")


def status(con, day: date, market: str = "IN") -> dict:
    """What the tool and the team's dossier show: the active target, its reasons, the drift and the gaps, the review dates, and what waits."""
    from pflab.paper import book as pb
    act = active_target(con, market)
    out: dict = {"market": market, "active": act, "pending": pending(con, market), "review": review_due(con, datetime.combine(day, datetime.min.time()), market),
                 "rails": rails.describe(), "classes": list(CLASSES)}
    if act and pb.started(con):
        h = pb.holdings(con, day)
        out["drift"] = drift(h, act)
        out["gaps"] = trade_toward(h, act)
    return out


def dossier_text(con, day: date, market: str = "IN") -> str:
    """The block the paper team reads: its target and the gap to it, or the instruction to propose the first."""
    try:
        s = status(con, day, market)
    except Exception:
        return ""
    act = s["active"]
    if act is None:
        if s["pending"]:
            return f"ALLOCATION TARGET: #{s['pending'][0]['target_id']} is proposed and waits for the independent review; until it is active the book has no target to trade toward."
        return "ALLOCATION TARGET: the system has none yet. " + playbook_text()
    cl = ", ".join(f"{k} {v:g}%" for k, v in act["classes"].items())
    sec = ("; sectors: " + ", ".join(f"{k} {v:g}%" for k, v in act["sectors"].items())) if act["sectors"] else ""
    g = s.get("gaps") or {}
    gap = ("in band: no trade is needed for the allocation" if g.get("in_band") else
           "ADD " + ", ".join(f"{x['name']} {x['gap_pct']:+.1f} pts (about Rs {x['gap_rupees']:,.0f})" for x in g.get("add", []))
           + ("; " if g.get("add") and g.get("trim") else "") + ("TRIM " + ", ".join(f"{x['name']} {x['gap_pct']:+.1f} pts (about Rs {x['gap_rupees']:,.0f})" for x in g.get("trim", [])) if g.get("trim") else ""))
    return (f"ITS OWN ALLOCATION TARGET (#{act['target_id']}, active since {str(act['activated_at'])[:10]}, re-examined at the review due {act['review_due']}): {cl}{sec}. Reasons: {act['reasons'][:500]} "
            f"GAP TO IT NOW: {gap}. Trade toward it with paper_decide (names of your choice; sizes and rails are code's). If the reasons no longer hold, call propose_allocation with the new split; "
            "the independent review decides before it is active.")


def playbook_text() -> str:
    """One paragraph for the paper team's first review (and each weekly one): the lead includes it in the paper playbook's decision step."""
    return ("ALLOCATION: the system's book has its own target, not the investor's. Decide it yourselves, with reasons: how much to hold in equity (shares and index ETFs), gold (gold ETFs, "
            "SGBs), international (Nasdaq or other foreign-index ETFs listed in India) and cash, and the sector split of the companies. Read `system_allocation` for the current target and the "
            "gap to it, call `propose_allocation` with the percentages (they sum to 100; each at least zero) and the reasons, including what would make you change it. Code refuses a split "
            "that breaks the rails (a company 10%, a sector 25%, one ETF 35%, no F&O, no borrowing, no short sales); the independent reviewer must approve it before it is active. Re-examine "
            "it at every weekly review: say if it stands or propose the new split. Stocks and ETFs of any kind may be bought toward it.")
