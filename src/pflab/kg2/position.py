"""The position layer (S81 B7): what the system's book holds, each holding with its lots, cost, days to 12 months, unrealised gain, the exemption used this
financial year, its exit plan and the storylines that touch it. Functions take the connection and a day; all read from the book's tables, none writes.

The book is the paper book (`paper_lots`, the system's own); `book="ledger"` reads `lots` (the system's ledger account). The exemption limit comes from the tax
engine's dated rows (`tax.rules.exemption`); the amount used from the year's realised long-term equity gains (`paper.book.year_gains`).
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Dict, List, Optional

from dateutil.relativedelta import relativedelta


def _exists(con, table: str) -> bool:
    return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [table]).fetchone()[0])


def fy_of(day: date) -> int:
    """The financial year's label (the year it ends)."""
    return day.year + 1 if day.month >= 4 else day.year


def lots(con, day: date, book: str = "paper") -> List[dict]:
    if book == "ledger":
        rows = con.execute("SELECT isin, acq_date, qty, cost_per_unit, tax_class, lot_id FROM lots WHERE acq_date <= ? AND qty > 0 ORDER BY isin, acq_date, lot_id", [day]).fetchall()
    else:
        if not _exists(con, "paper_lots"):
            return []
        rows = con.execute("SELECT isin, acq_date, qty, cost_per_unit, tax_class, lot_id FROM paper_lots WHERE acq_date <= ? AND qty > 0 ORDER BY isin, acq_date, lot_id", [day]).fetchall()
    return [{"isin": r[0], "acq_date": r[1], "qty": float(r[2]), "cost_per_unit": float(r[3]), "tax_class": r[4], "lot_id": r[5]} for r in rows]


def price_on(con, isin: str, day: date) -> Optional[float]:
    r = con.execute("SELECT close FROM prices WHERE isin=? AND date <= ? AND close > 0 ORDER BY date DESC LIMIT 1", [isin, day]).fetchone()
    if r:
        return float(r[0])
    if _exists(con, "navs"):
        r = con.execute("SELECT nav FROM navs WHERE isin=? AND date <= ? ORDER BY date DESC LIMIT 1", [isin, day]).fetchone()
        return float(r[0]) if r else None
    return None


def long_term_from(lot: dict, day: date) -> date:
    """The first day a sale of this lot is long-term: the tax engine's rule for its class when it has one, else more than 12 months."""
    from pflab.tax import plan, rules
    try:
        rule = plan.rule_of(lot["tax_class"] or "EQUITY", lot["acq_date"], day)
        ltf = plan.long_term_from(rule, lot["acq_date"])
        if ltf:
            return ltf
    except Exception:
        pass
    return lot["acq_date"] + relativedelta(months=12) + timedelta(days=1)


def exemption(con, day: date) -> dict:
    """This financial year's long-term equity gains exemption: the limit (tax engine), the amount used so far (realised long-term gains, paper book) and what is left."""
    fy = fy_of(day)
    try:
        from pflab.tax import rules
        limit = float(rules.exemption(fy))
        src = "tax engine (dated rows)"
    except Exception:
        from pflab.paper import book
        limit, src = float(book.LT_EXEMPT), "paper.book.LT_EXEMPT (tax engine had no row)"
    used = 0.0
    if _exists(con, "paper_trades"):
        from pflab.paper import book
        used = max(0.0, float(book.year_gains(con, book._fy(day)).get("lt_eq", 0.0)))   # (the paper book labels a FY by the year it starts)
    return {"fy": fy, "limit": limit, "used": round(used, 2), "left": round(max(0.0, limit - used), 2), "source": src}


def exit_plan(con, isin: str, day: date) -> Optional[dict]:
    """The open exit plan of this holding (table `exit_plans_s81`, written by the exit manager); None when there is none or the table does not exist."""
    if not _exists(con, "exit_plans_s81"):
        return None
    try:
        cur = con.execute("SELECT * FROM exit_plans_s81 WHERE isin = ?", [isin])
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception:
        return None
    live = [r for r in rows if str(r.get("status", "open")).lower() in ("open", "active")]
    pick = (live or rows or [None])[-1]
    return None if pick is None else {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in pick.items()}


def storylines(con, isin: str, day: date) -> List[dict]:
    if not (_exists(con, "storyline_exposure_s80") and _exists(con, "storylines_s80")):
        return []
    rows = con.execute("""SELECT s.storyline_id, s.claim, s.direction, s.status, e.exposure, e.as_of
                          FROM storyline_exposure_s80 e JOIN storylines_s80 s USING (storyline_id)
                          WHERE e.isin = ? AND s.opened_on <= ? AND s.status = 'open' ORDER BY s.storyline_id""", [isin, day]).fetchall()
    return [{"storyline_id": r[0], "claim": r[1], "direction": r[2], "status": r[3], "exposure": float(r[4]), "as_of": r[5].isoformat() if r[5] else None} for r in rows]


def recent_events(con, isin: str, day: date, days: int = 30, limit: int = 8) -> List[dict]:
    if not _exists(con, "kg2_event"):
        return []
    rows = con.execute("SELECT kind, severity, ts, headline, source, event_id FROM kg2_event WHERE isin=? AND event_date <= ? AND event_date > ? ORDER BY ts DESC, event_id LIMIT ?",
                       [isin, day, day - timedelta(days=days), limit]).fetchall()
    return [{"kind": r[0], "severity": r[1], "ts": r[2].isoformat(), "headline": r[3], "source": r[4], "event_id": r[5]} for r in rows]


def holding(con, isin: str, day: date, book: str = "paper", all_lots: Optional[List[dict]] = None) -> Optional[dict]:
    ls = [l for l in (all_lots if all_lots is not None else lots(con, day, book)) if l["isin"] == isin]
    if not ls:
        return None
    px = price_on(con, isin, day)
    qty = sum(l["qty"] for l in ls)
    cost = sum(l["qty"] * l["cost_per_unit"] for l in ls)
    out_lots, to_lt, gain_lt, gain_st = [], [], 0.0, 0.0
    for l in ls:
        ltf = long_term_from(l, day)
        d_to = (ltf - day).days
        g = None if px is None else l["qty"] * (px - l["cost_per_unit"])
        long_term = d_to <= 0
        if g is not None:
            gain_lt, gain_st = (gain_lt + g, gain_st) if long_term else (gain_lt, gain_st + g)
        if not long_term:
            to_lt.append(d_to)
        out_lots.append({"lot_id": l["lot_id"], "acq_date": l["acq_date"].isoformat(), "qty": l["qty"], "cost_per_unit": l["cost_per_unit"],
                         "days_held": (day - l["acq_date"]).days, "days_to_long_term": max(0, d_to), "long_term": long_term,
                         "unrealised": None if g is None else round(g, 2)})
    return {"isin": isin, "qty": qty, "cost": round(cost, 2), "price": px, "value": None if px is None else round(qty * px, 2),
            "unrealised": None if px is None else round(qty * px - cost, 2), "unrealised_long_term": round(gain_lt, 2), "unrealised_short_term": round(gain_st, 2),
            "days_to_next_long_term": min(to_lt) if to_lt else 0, "lots": out_lots, "exit_plan": exit_plan(con, isin, day),
            "storylines": storylines(con, isin, day), "events": recent_events(con, isin, day)}


def positions(con, day: date, book: str = "paper") -> dict:
    """{'day', 'exemption': {...}, 'holdings': [per holding, sorted by ISIN]}: the whole position layer at one day."""
    ls = lots(con, day, book)
    hs = [h for h in (holding(con, i, day, book, ls) for i in sorted({l["isin"] for l in ls})) if h]
    return {"day": day.isoformat(), "exemption": exemption(con, day), "holdings": hs}
