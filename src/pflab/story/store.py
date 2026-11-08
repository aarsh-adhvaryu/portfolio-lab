"""Storylines: the records (S80 phase 3). A storyline is a hypothesis about what is driving the market for days or weeks: a claim (the cause and what it should do to prices), signals
(measurable things tied to a series that would confirm or contradict it), dated evidence for and against (each with its source), a probability that CODE updates each close, an
exposure per holding, predictions at 5 and 20 sessions scored when due, and a status (open, confirmed, faded, broken) with its date.

Signals come from a menu of TEMPLATES (code-defined, so a model can choose a signal but never invent a threshold): see `TEMPLATES`. Everything numeric here is code's.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Dict, List, Optional

from pflab.story import series

STATUSES = ("open", "confirmed", "faded", "broken")
STANCES = ("for", "against")
STRENGTH = {"weak": 0.3, "moderate": 0.6, "strong": 1.0}
SUBJECTS = ("NIFTY500_TRI",)                      # the index a storyline's predictions are scored on (a sector index joins when one is collected)

# template -> (series, transform, op, threshold, stance when the condition holds, weight, label)
TEMPLATES: Dict[str, tuple] = {
    "fii_buying_strong": ("FII_NET_CR", "sum:5", ">", 15000.0, "confirm", 1.0, "foreign institutions bought more than Rs 15,000 crore net over 5 sessions"),
    "fii_selling_strong": ("FII_NET_CR", "sum:5", "<", -15000.0, "confirm", 1.0, "foreign institutions sold more than Rs 15,000 crore net over 5 sessions"),
    "fii_selling_contradicts": ("FII_NET_CR", "sum:5", "<", -5000.0, "contradict", 0.8, "foreign institutions sold net over 5 sessions"),
    "fii_buying_contradicts": ("FII_NET_CR", "sum:5", ">", 5000.0, "contradict", 0.8, "foreign institutions bought net over 5 sessions"),
    "asia_chip_weak": ("KOSPI", "relret:5:NIFTY500_TRI", "<", -0.03, "confirm", 0.8, "Korea's KOSPI trailed the Nifty 500 by more than 3 points over 5 sessions"),
    "taiex_weak": ("TAIEX", "relret:5:NIFTY500_TRI", "<", -0.03, "confirm", 0.6, "Taiwan's TAIEX trailed the Nifty 500 by more than 3 points over 5 sessions"),
    "chips_falling": ("SOX", "ret:5", "<", -0.05, "confirm", 0.6, "the US chip index fell more than 5% over 5 sessions"),
    "india_outperforms_asia": ("NIFTY500_TRI", "relret:5:KOSPI", ">", 0.03, "confirm", 0.8, "the Nifty 500 beat Korea's KOSPI by more than 3 points over 5 sessions"),
    "india_lags_asia": ("NIFTY500_TRI", "relret:5:KOSPI", "<", -0.03, "contradict", 0.8, "the Nifty 500 trailed Korea's KOSPI by more than 3 points over 5 sessions"),
    "crude_falling": ("BRENT", "ret:5", "<", -0.05, "confirm", 0.6, "Brent fell more than 5% over 5 sessions"),
    "crude_rising": ("BRENT", "ret:5", ">", 0.05, "confirm", 0.6, "Brent rose more than 5% over 5 sessions"),
    "rupee_weakening": ("USDINR", "ret:5", ">", 0.01, "confirm", 0.6, "the rupee weakened more than 1% over 5 sessions"),
    "dollar_strengthening": ("DOLLAR_INDEX", "ret:5", ">", 0.015, "confirm", 0.5, "the dollar index rose more than 1.5% over 5 sessions"),
    "nifty_up_strong": ("NIFTY500_TRI", "ret:5", ">", 0.03, "confirm", 0.5, "the Nifty 500 rose more than 3% over 5 sessions"),
    "nifty_down_strong": ("NIFTY500_TRI", "ret:5", "<", -0.03, "confirm", 0.5, "the Nifty 500 fell more than 3% over 5 sessions"),
}


def _id(con, table: str, col: str) -> int:
    from pflab.pm.store import next_id
    return next_id(con, table, col)


def open_storyline(con, now: datetime, claim: str, direction: int, opened_on: date, templates: List[str], *, kind: str = "market", subject: str = "NIFTY500_TRI", market: str = "IN",
                   prior: float = 0.5, created_by: str = "code") -> dict:
    """Open a storyline. `direction`: +1 the subject should rise, -1 fall. `templates`: names from `TEMPLATES` (at least one). Refused with the reason when something is off."""
    claim = " ".join((claim or "").split())
    if len(claim) < 25 or len(claim) > 300:
        return {"ok": False, "problem": "the claim is one sentence of 25 to 300 characters: the cause and what it should do to prices"}
    if direction not in (-1, 1):
        return {"ok": False, "problem": "direction is +1 (the subject should rise) or -1 (fall)"}
    if subject not in SUBJECTS:
        return {"ok": False, "problem": f"subject must be one of {SUBJECTS}"}
    bad = [t for t in templates if t not in TEMPLATES]
    if bad or not templates:
        return {"ok": False, "problem": f"choose signals from the menu: {', '.join(sorted(TEMPLATES))}" + (f" (not known: {bad})" if bad else "")}
    if not 0.05 <= prior <= 0.95:
        return {"ok": False, "problem": "prior must be between 0.05 and 0.95"}
    dup = con.execute("SELECT storyline_id FROM storylines_s80 WHERE market=? AND status='open' AND lower(claim)=lower(?)", [market, claim]).fetchone()
    if dup:
        return {"ok": False, "problem": f"an open storyline already says this (#{dup[0]})", "storyline_id": dup[0]}
    sid = _id(con, "storylines_s80", "storyline_id")
    con.execute("INSERT INTO storylines_s80 (storyline_id, market, claim, kind, direction, subject, opened_on, status, status_on, prior, probability, ai_adjust, influence, created_by, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [sid, market, claim, kind, direction, subject, opened_on, "open", opened_on, prior, prior, 0.0, 0.5, created_by, now])
    for t in templates:
        ser, tr, op, th, stance, w, label = TEMPLATES[t]
        con.execute("INSERT INTO storyline_signals_s80 VALUES (?,?,?,?,?,?,?,?,?,?)", [_id(con, "storyline_signals_s80", "signal_id"), sid, t, ser, tr, op, th, stance, w, label])
    return {"ok": True, "storyline_id": sid, "signals": templates}


def get(con, sid: int) -> Optional[dict]:
    r = con.execute("SELECT storyline_id, market, claim, kind, direction, subject, opened_on, status, status_on, prior, probability, ai_adjust, ai_reason, influence, created_by "
                    "FROM storylines_s80 WHERE storyline_id=?", [sid]).fetchone()
    if not r:
        return None
    d = dict(zip(("storyline_id", "market", "claim", "kind", "direction", "subject", "opened_on", "status", "status_on", "prior", "probability", "ai_adjust", "ai_reason", "influence", "created_by"), r))
    d["signals"] = [dict(zip(("template", "series", "transform", "op", "threshold", "stance", "weight", "label"), x)) for x in con.execute(
        "SELECT template, series, transform, op, threshold, stance, weight, label FROM storyline_signals_s80 WHERE storyline_id=? ORDER BY signal_id", [sid]).fetchall()]
    return d


def listing(con, statuses=("open",), market: str = "IN") -> List[dict]:
    ph = ",".join("?" for _ in statuses)
    rows = con.execute(f"SELECT storyline_id FROM storylines_s80 WHERE market=? AND status IN ({ph}) ORDER BY storyline_id", [market, *statuses]).fetchall()
    return [get(con, r[0]) for r in rows]


def add_evidence(con, now: datetime, sid: int, evidence_date: date, stance: str, text: str, source_kind: str, source_ref: str, strength: str = "moderate", added_by: str = "code") -> dict:
    """One dated item for or against, linked to its source (a tool result, a filing, a news cluster). Deduplicated by (storyline, source kind and ref, date)."""
    if stance not in STANCES or strength not in STRENGTH:
        return {"ok": False, "problem": f"stance is one of {STANCES}, strength one of {tuple(STRENGTH)}"}
    if not get(con, sid):
        return {"ok": False, "problem": "no such storyline"}
    text = " ".join((text or "").split())[:400]
    if len(text) < 10 or not source_ref:
        return {"ok": False, "problem": "evidence needs its words and its source"}
    key = f"{sid}|{source_kind}|{source_ref}|{evidence_date}"
    if con.execute("SELECT 1 FROM storyline_evidence_s80 WHERE dedup=?", [key]).fetchone():
        return {"ok": True, "duplicate": True}
    eid = _id(con, "storyline_evidence_s80", "evidence_id")
    con.execute("INSERT INTO storyline_evidence_s80 VALUES (?,?,?,?,?,?,?,?,?,?,?)", [eid, sid, evidence_date, stance, text, source_kind, source_ref, STRENGTH[strength], added_by, now, key])
    return {"ok": True, "evidence_id": eid}


def evidence(con, sid: int, limit: int = 12) -> List[dict]:
    return [{"date": str(a), "stance": b, "text": c, "source": f"{d}:{e}", "strength": f, "by": g} for a, b, c, d, e, f, g in con.execute(
        "SELECT evidence_date, stance, text, source_kind, source_ref, strength, added_by FROM storyline_evidence_s80 WHERE storyline_id=? ORDER BY evidence_date DESC, evidence_id DESC LIMIT ?",
        [sid, limit]).fetchall()]


def set_exposure(con, sid: int, exposures: Dict[str, float], source: str, as_of: date) -> int:
    """Per-holding exposure in [-1, 1] (how much a security's price should move with the storyline's claim: + with it, - against it)."""
    n = 0
    for isin, x in exposures.items():
        con.execute("INSERT OR REPLACE INTO storyline_exposure_s80 VALUES (?,?,?,?,?)", [sid, isin, max(-1.0, min(1.0, float(x))), source, as_of])
        n += 1
    return n


def exposure_by_sector(con, sid: int, sector_weights: Dict[str, float], isins: List[str], source: str, as_of: date) -> int:
    """Exposure from the sector the record names for each security (`paper/book.inst`): the first sector word that matches (case-insensitive) sets the exposure."""
    from pflab.paper import book
    out = {}
    for isin in isins:
        sec = (book.inst(con, isin).get("sector") or "").lower()
        for word, x in sector_weights.items():
            if word.lower() in sec:
                out[isin] = x
                break
    return set_exposure(con, sid, out, source, as_of)


def close(con, now: datetime, sid: int, status: str, on: date, reason: str = "") -> None:
    con.execute("UPDATE storylines_s80 SET status=?, status_on=?, updated_at=? WHERE storyline_id=?", [status, on, now, sid])
    refresh_record(con, now)


def refresh_record(con, now: datetime) -> None:
    """The record of which kinds of story hold: for each kind, how many are open, confirmed, faded, broken, and how long the finished ones lasted (sessions, by the calendar)."""
    con.execute("DELETE FROM storyline_record_s80")
    for kind, in con.execute("SELECT DISTINCT coalesce(kind, 'market') FROM storylines_s80").fetchall():
        rows = con.execute("SELECT status, opened_on, status_on FROM storylines_s80 WHERE coalesce(kind, 'market')=?", [kind]).fetchall()
        n = {s: sum(1 for r in rows if r[0] == s) for s in STATUSES}
        done = [(r[2] - r[1]).days * 5 / 7.0 for r in rows if r[0] != "open" and r[2] and r[1]]
        con.execute("INSERT INTO storyline_record_s80 VALUES (?,?,?,?,?,?,?)", [kind, n["open"], n["confirmed"], n["faded"], n["broken"], (sum(done) / len(done)) if done else None, now])


def record_text(con) -> str:
    rows = con.execute("SELECT kind, n_open, n_confirmed, n_faded, n_broken, mean_sessions FROM storyline_record_s80 ORDER BY kind").fetchall()
    return "; ".join(f"{k}: {c} confirmed, {f} faded, {b} broken, {o} open" + (f", finished ones lasted about {m:.0f} sessions" if m else "") for k, o, c, f, b, m in rows) or "no finished storylines yet"
