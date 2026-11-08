"""A storyline's probability, by code (S80 phase 3). Nothing a model says becomes a number: a model may CHOOSE a signal template and a strength WORD; this module turns them into log-odds.

    log-odds = logit(prior)
             + sum over signals whose condition holds today:  +weight (confirm) or -weight (contradict), times SIGNAL_SCALE
             + sum over evidence dated <= today:  +/- strength * EVIDENCE_SCALE, halved every EVIDENCE_HALF_LIFE_DAYS
             + the AI's adjustment (written reason required, never more than AI_LIMIT in log-odds)
    probability = 1 / (1 + exp(-log-odds)), kept in [0.02, 0.98]

The probability is stored each close (`storyline_prob_s80`) so it can be rebuilt for any past day: it reads only rows dated on or before that day (and the series' own lag rules).
Status changes by rule: broken at 0.15 or below, or after two bad predictions in a row; confirmed at 0.85 or above once a prediction scored good; faded after 20 days with no
evidence while it stays between 0.15 and 0.65.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Optional

from pflab.story import series, store

SIGNAL_SCALE = 0.8
EVIDENCE_SCALE = 0.35
EVIDENCE_HALF_LIFE_DAYS = 14.0
AI_LIMIT = 0.6                                  # log-odds: about +/- 15 points around 50%
CONFIRM_AT, BREAK_AT, FADE_AFTER_DAYS, FADE_BELOW = 0.85, 0.15, 20, 0.65


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


def _holds(v: Optional[float], op: str, th: float) -> bool:
    return v is not None and ((v > th) if op == ">" else (v < th))


def compute(con, sid: int, asof: date, root=None) -> dict:
    """{probability, logodds, parts} for `asof`, from rows known on that day."""
    s = store.get(con, sid)
    lo = _logit(min(max(s["prior"], 0.05), 0.95))
    parts = {"prior": round(lo, 3), "signals": [], "evidence": 0.0, "ai": 0.0}
    for g in s["signals"]:
        v = series.value(g["series"], g["transform"], asof, root)
        if _holds(v, g["op"], g["threshold"]):
            d = SIGNAL_SCALE * g["weight"] * (1 if g["stance"] == "confirm" else -1)
            lo += d
            parts["signals"].append({"label": g["label"], "value": round(v, 4), "effect": round(d, 3)})
    ev = 0.0
    for d_, stance, strength in con.execute("SELECT evidence_date, stance, strength FROM storyline_evidence_s80 WHERE storyline_id=? AND evidence_date <= ?", [sid, asof]).fetchall():
        age = max((asof - d_).days, 0)
        ev += (1 if stance == "for" else -1) * strength * EVIDENCE_SCALE * 0.5 ** (age / EVIDENCE_HALF_LIFE_DAYS)
    parts["evidence"] = round(ev, 3)
    lo += ev
    ai = max(-AI_LIMIT, min(AI_LIMIT, float(s["ai_adjust"] or 0.0)))
    parts["ai"] = round(ai, 3)
    lo += ai
    p = 1.0 / (1.0 + math.exp(-lo))
    p = min(max(p, 0.02), 0.98)
    return {"probability": p, "logodds": lo, "parts": parts}


def adjust(con, now: datetime, sid: int, delta: float, reason: str) -> dict:
    """The AI may move the probability, with a written reason, inside AI_LIMIT. The adjustment is on the record (`ai_adjust`, `ai_reason`) and shows in the parts of every later reading."""
    reason = " ".join((reason or "").split())
    if len(reason) < 20:
        return {"ok": False, "problem": "an adjustment needs a written reason (what the signals miss)"}
    if not store.get(con, sid):
        return {"ok": False, "problem": "no such storyline"}
    d = max(-AI_LIMIT, min(AI_LIMIT, float(delta)))
    con.execute("UPDATE storylines_s80 SET ai_adjust=?, ai_reason=?, updated_at=? WHERE storyline_id=?", [d, reason[:400], now, sid])
    return {"ok": True, "ai_adjust": d, "limit": AI_LIMIT}


def update(con, now: datetime, sid: int, asof: date, root=None) -> dict:
    """Recompute and store the day's probability; apply the status rules. Returns the reading."""
    s = store.get(con, sid)
    r = compute(con, sid, asof, root)
    con.execute("INSERT OR REPLACE INTO storyline_prob_s80 VALUES (?,?,?,?,?)", [sid, asof, r["probability"], r["logodds"], json.dumps(r["parts"])])
    con.execute("UPDATE storylines_s80 SET probability=?, updated_at=? WHERE storyline_id=?", [r["probability"], now, sid])
    if s["status"] == "open":
        why = _status_rule(con, s, r["probability"], asof)
        if why:
            store.close(con, now, sid, why, asof)
            r["status_change"] = why
    return r


def _status_rule(con, s: dict, p: float, asof: date) -> Optional[str]:
    sid = s["storyline_id"]
    last_two = [r[0] for r in con.execute("SELECT outcome FROM storyline_predictions_s80 WHERE storyline_id=? AND outcome IN ('good','bad') ORDER BY due_on DESC LIMIT 2", [sid]).fetchall()]
    if p <= BREAK_AT or (len(last_two) == 2 and all(o == "bad" for o in last_two)):
        return "broken"
    good = con.execute("SELECT count(*) FROM storyline_predictions_s80 WHERE storyline_id=? AND outcome='good'", [sid]).fetchone()[0]
    if p >= CONFIRM_AT and good >= 1:
        return "confirmed"
    last_ev = con.execute("SELECT max(evidence_date) FROM storyline_evidence_s80 WHERE storyline_id=? AND evidence_date <= ?", [sid, asof]).fetchone()[0]
    quiet_since = last_ev or s["opened_on"]
    if (asof - quiet_since).days >= FADE_AFTER_DAYS and BREAK_AT < p < FADE_BELOW:
        return "faded"
    return None


def update_all(con, now: datetime, asof: date, root=None, market: str = "IN") -> dict:
    out = {}
    for s in store.listing(con, ("open",), market):
        out[s["storyline_id"]] = round(update(con, now, s["storyline_id"], asof, root)["probability"], 4)
    return out


def history(con, sid: int) -> list:
    return [(str(d), round(p, 4)) for d, p in con.execute("SELECT prob_date, probability FROM storyline_prob_s80 WHERE storyline_id=? ORDER BY prob_date", [sid]).fetchall()]
