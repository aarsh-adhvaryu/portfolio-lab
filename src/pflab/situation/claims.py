"""The shared situation, one typed claim at a time (S79b item 16).

Every agent and tool states what it found as a CLAIM, not prose: what (kind, subject, text), where (market), about whom (entities: ISINs or
symbols; themes), the evidence (call_ids: the tool-call ids the claim rests on), how sure (confidence 0..1, from code), and when (as_of, with a
life of `ttl_sessions` sessions on the market's calendar). The situation of a market at a date is the set of live claims dated on or before that
date (point-in-time): nothing dated later is ever read.

    claims.add(con, "IN", "regime", "nifty", "calm uptrend", value=0.3, themes=("banks",), call_ids=("c12",), confidence=0.7, as_of=date(2026, 11, 6))
    claims.active(con, "IN", as_of)            -> live claims, newest per (kind, subject, source)
    claims.by_kind(con, "IN", as_of)           -> {kind: [claim, ...]}

A claim with the same market, kind, subject, as_of and source replaces the earlier one (a rebuild is idempotent). Numbers in `value` come from
tools only (the synthesizer's citation check refuses a number without a call id).
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional

from pflab.pm.store import next_id

KINDS = (
    "regime",        # market regime (calm/stress, trend), from breadth / forecasts
    "wave",          # a wave flag (a theme/market-wide surge or unwind)
    "rotation",      # a rotation flag (money moving between sectors/themes)
    "macro",         # macro attribution (what part of the move is oil, USD, rates, FII ...)
    "sentiment",     # sentiment by theme
    "exposure",      # theme exposure of the book / the target
    "forecast",      # a forecast (distribution, probability, ensemble)
    "weights",       # ensemble weights
    "fall_risk",     # fall risk
    "event",         # a calendar event (results, policy, expiry ...)
    "book",          # the paper book / the system's account
    "allocation",    # the system's allocation target
    "move",          # an explained move (decompose_move, trajectory)
    "transmission",  # a transmission / lead-lag finding
    "implied",       # an implied distribution (options) or a cascade
    "scorecard",     # how the system's own parts have done (bear scorecard ...)
    "agenda",        # what the system is working on
    "state",         # state of the machinery (catch-up, data staleness)
    "question",      # an open question (the system's, or one for him)
    "observation",   # anything else a tool found
)
MAX_TEXT = 400


class ClaimError(ValueError):
    """A claim that is not typed properly (unknown kind, empty subject, non-finite value, confidence outside 0..1)."""


def _as_date(x, now: Optional[datetime] = None) -> date:
    if x is None:
        return (now or datetime.now()).date()
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def _jlist(x: Iterable) -> str:
    if x is None:
        return "[]"
    if isinstance(x, (str, int)):
        x = [x]
    return json.dumps([str(v) for v in x if v is not None and str(v) != ""])


def _unj(s) -> List[str]:
    try:
        return list(json.loads(s)) if s else []
    except ValueError:
        return []


def expiry(market: str, as_of: date, ttl_sessions: int) -> date:
    """The last date the claim is live: `ttl_sessions` sessions after as_of on the market's calendar (calendar days if the calendar is unavailable)."""
    try:
        from pflab import markets
        return markets.get(market).session_after(as_of, max(0, int(ttl_sessions)))
    except Exception:
        return as_of + timedelta(days=max(0, int(ttl_sessions)))


def add(con, market: str, kind: str, subject: str, text: str, value: Optional[float] = None, entities: Iterable = (), themes: Iterable = (),
        call_ids: Iterable = (), confidence: Optional[float] = None, as_of=None, ttl_sessions: int = 5, source: str = "", run_id: Optional[int] = None,
        now: Optional[datetime] = None) -> int:
    """Store one typed claim and return its claim_id. Raises ClaimError when it is not typed properly."""
    if kind not in KINDS:
        raise ClaimError(f"unknown claim kind {kind!r}; kinds: {', '.join(KINDS)}")
    subject = str(subject or "").strip()
    if not subject:
        raise ClaimError("a claim needs a subject")
    if value is not None:
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ClaimError(f"value must be a number, got {value!r}")
        if not math.isfinite(value):
            raise ClaimError("value must be finite")
    if confidence is not None:
        confidence = float(confidence)
        if not (0.0 <= confidence <= 1.0):
            raise ClaimError("confidence must be between 0 and 1")
    d = _as_date(as_of, now)
    created = now or datetime.now()
    exp = expiry(market, d, ttl_sessions)
    old = con.execute("SELECT claim_id FROM situation_claim WHERE market=? AND kind=? AND subject=? AND as_of=? AND coalesce(source,'')=?", [market, kind, subject[:120], d, source or ""]).fetchone()
    if old:                                          # a rebuild updates the claim in place: its id stays valid for the reports that cite it
        con.execute("UPDATE situation_claim SET text=?, value=?, entities=?, themes=?, call_ids=?, confidence=?, created_at=?, ttl_sessions=?, expires_on=?, run_id=? WHERE claim_id=?",
                    [str(text or "")[:MAX_TEXT], value, _jlist(entities), _jlist(themes), _jlist(call_ids), confidence, created, int(ttl_sessions), exp, run_id, int(old[0])])
        return int(old[0])
    cid = next_id(con, "situation_claim", "claim_id")
    con.execute("INSERT INTO situation_claim (claim_id, market, kind, subject, text, value, entities, themes, call_ids, confidence, as_of, created_at, ttl_sessions, "
                "expires_on, source, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [cid, market, kind, subject[:120], str(text or "")[:MAX_TEXT], value, _jlist(entities), _jlist(themes), _jlist(call_ids), confidence, d, created,
                 int(ttl_sessions), exp, source or "", run_id])
    return cid


COLS = ("claim_id", "market", "kind", "subject", "text", "value", "entities", "themes", "call_ids", "confidence", "as_of", "created_at", "ttl_sessions",
        "expires_on", "source", "run_id")


def _row(r) -> dict:
    d = dict(zip(COLS, r))
    for k in ("entities", "themes", "call_ids"):
        d[k] = _unj(d[k])
    return d


def get(con, claim_id: int) -> Optional[dict]:
    r = con.execute(f"SELECT {', '.join(COLS)} FROM situation_claim WHERE claim_id=?", [int(claim_id)]).fetchone()
    return _row(r) if r else None


def active(con, market: str, as_of, kinds: Optional[Iterable[str]] = None) -> List[dict]:
    """The claims live at `as_of`: dated on or before it, not past their expiry; the newest per (kind, subject, source). Point-in-time by construction."""
    d = _as_date(as_of)
    q = (f"SELECT {', '.join(COLS)} FROM situation_claim WHERE market=? AND as_of<=? AND expires_on>=?")
    args: list = [market, d, d]
    if kinds:
        ks = list(kinds)
        q += f" AND kind IN ({','.join('?' * len(ks))})"
        args += ks
    q += " ORDER BY as_of DESC, claim_id DESC"
    seen, out = set(), []
    for r in con.execute(q, args).fetchall():
        c = _row(r)
        key = (c["kind"], c["subject"], c["source"] or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    out.sort(key=lambda c: (c["kind"], c["subject"], c["claim_id"]))
    return out


def by_kind(con, market: str, as_of, kinds: Optional[Iterable[str]] = None) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for c in active(con, market, as_of, kinds):
        out.setdefault(c["kind"], []).append(c)
    return out


def purge(con, market: str, before: date, keep_days: int = 120) -> int:
    """Delete claims whose expiry is more than keep_days before `before` (the table stays small); returns how many."""
    n = con.execute("SELECT count(*) FROM situation_claim WHERE market=? AND expires_on < ?", [market, before - timedelta(days=keep_days)]).fetchone()[0]
    con.execute("DELETE FROM situation_claim WHERE market=? AND expires_on < ?", [market, before - timedelta(days=keep_days)])
    return int(n)
