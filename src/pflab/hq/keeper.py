"""The memory keeper (S59): the system's memory and journal stay correct, and the brain is held to its word.

    predictions   each kept with the reference close and its base rate (how often the stock's own history made such a
                  move over the same number of sessions, the last three years, at least 250 windows); scored by code when
                  due on the close on or just before the due date (Brier score, the brain against its base rate)
    decisions     every decision in memory about a company is followed up: what its price did since ("we decided X; the
                  stock then fell 8%; what now"), for the journal screen and the brain's reflection
    suggestions   the suggestion ledger (S60, `hq/suggestions.py`) scored at each horizon against the Nifty 500
    outcomes      a decision followed for 30 days gets its outcome written back as an `outcome` row (S60)
    memory        the analyst's notes: one current note per company (an older one still open is ended); a decision whose
                  subject the system does not know is listed for the investor

All code, no model, nothing leaves the PC.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

HISTORY_DAYS = 3 * 365
MIN_WINDOWS = 250                    # PLAN A9 small numbers: fewer windows -> no base rate
SCORE_SLACK_DAYS = 6                 # the close used may be at most this many days before the due date
MIN_SCORED = 20                      # under this, the scorecard shows counts only


def closes(con, isin: str, upto: date, days: int = HISTORY_DAYS) -> pd.Series:
    df = con.execute("SELECT date, close, source FROM prices WHERE isin=? AND date<=? AND date>=? ORDER BY date, "
                     "(source = 'nse_bhavcopy') DESC", [isin, upto, upto - timedelta(days=days)]).df()
    if df.empty:
        return pd.Series(dtype=float)
    df = df.drop_duplicates("date", keep="first")
    return pd.Series(df["close"].values, index=pd.to_datetime(df["date"]))


def sessions_between(a: date, b: date) -> int:
    return max(1, int(np.busday_count(a, b)))


def hit(kind: str, change_pct: float, level: float) -> bool:
    return change_pct > level if kind == "return_above" else change_pct < level


def base_rate(s: pd.Series, h: int, kind: str, level: float) -> Optional[float]:
    if len(s) <= h:
        return None
    r = (s.shift(-h) / s - 1).dropna() * 100
    if len(r) < MIN_WINDOWS:
        return None
    return float(np.mean([hit(kind, x, level) for x in r.values]))


def add_prediction(con, pass_id: int, model: str, p: dict, now: datetime) -> Optional[int]:
    from pflab.pm.store import next_id
    s = closes(con, p["isin"], now.date())
    if s.empty:
        return None
    ref_date, ref = s.index[-1].date(), float(s.iloc[-1])
    br = base_rate(s, sessions_between(ref_date, p["due"]), p["kind"], p["level"])
    pid = next_id(con, "hq_predictions", "pred_id")
    check = {"isin": p["isin"], "symbol": p["symbol"], "kind": p["kind"], "level": p["level"], "ref_date": str(ref_date),
             "ref_close": ref}
    con.execute("INSERT INTO hq_predictions (pred_id, pass_id, model, made_at, claim, check_json, due, confidence, base_rate) "
                "VALUES (?,?,?,?,?,?,?,?,?)", [pid, pass_id, model, now, p["claim"] or f"{p['symbol']} {p['kind']} "
                                               f"{p['level']}% by {p['due']}", json.dumps(check), p["due"],
                                               p["confidence"], br])
    return pid


def score_due(con, now: datetime) -> int:
    """Score every open prediction whose due date has a close (outcomes made after the prediction, never before)."""
    n = 0
    for pid, check, due in con.execute("SELECT pred_id, check_json, due FROM hq_predictions WHERE outcome IS NULL AND due <= ?",
                                       [now.date()]).fetchall():
        c = json.loads(check)
        s = closes(con, c["isin"], due, days=SCORE_SLACK_DAYS + 5)
        s = s[s.index.date >= due - timedelta(days=SCORE_SLACK_DAYS)] if len(s) else s
        if s.empty or s.index[-1].date() <= date.fromisoformat(c["ref_date"]):
            if (now.date() - due).days > 10:                  # no close came: void, never guessed
                con.execute("UPDATE hq_predictions SET scored_at=?, detail=? WHERE pred_id=?",
                            [now, "void: no close near the due date", pid])
            continue
        ch = (float(s.iloc[-1]) / c["ref_close"] - 1) * 100
        con.execute("UPDATE hq_predictions SET outcome=?, scored_at=?, detail=? WHERE pred_id=?",
                    [hit(c["kind"], ch, c["level"]), now, f"{c['symbol']} {ch:+.2f}% from {c['ref_date']} to "
                                                          f"{s.index[-1].date()}", pid])
        n += 1
    return n


def scorecard(con, model: Optional[str] = None) -> dict:
    q = "SELECT model, confidence, base_rate, outcome FROM hq_predictions WHERE outcome IS NOT NULL"
    rows = con.execute(q + (" AND model=?" if model else ""), [model] if model else []).fetchall()
    out: Dict[str, dict] = {}
    for m in sorted({r[0] for r in rows}):
        rs = [r for r in rows if r[0] == m]
        y = np.array([float(r[3]) for r in rs])
        p = np.array([r[1] for r in rs])
        with_base = [r for r in rs if r[2] is not None]
        d = {"n": len(rs), "hits": int(y.sum()), "brier": float(np.mean((p - y) ** 2)) if len(rs) else None,
             "n_base": len(with_base)}
        if with_base:
            yb = np.array([float(r[3]) for r in with_base])
            d["brier_model_on_base"] = float(np.mean((np.array([r[1] for r in with_base]) - yb) ** 2))
            d["brier_base"] = float(np.mean((np.array([r[2] for r in with_base]) - yb) ** 2))
        out[m] = d
    open_ = dict(con.execute("SELECT model, count(*) FROM hq_predictions WHERE outcome IS NULL AND scored_at IS NULL "
                             "GROUP BY model").fetchall())
    return {"models": out, "open": open_}


def scorecard_text(con, model: str) -> str:
    sc = scorecard(con, model)["models"].get(model)
    if not sc or not sc["n"]:
        return "YOUR SCORECARD: nothing scored yet."
    if sc["n"] < MIN_SCORED:
        return f"YOUR SCORECARD: {sc['hits']} of {sc['n']} predictions came true (too few to score; {MIN_SCORED} needed)."
    s = f"YOUR SCORECARD: {sc['hits']} of {sc['n']} came true; Brier {sc['brier']:.3f} (lower is better)"
    if sc.get("brier_base") is not None:
        s += f"; on the {sc['n_base']} with a base rate: yours {sc['brier_model_on_base']:.3f}, base rate {sc['brier_base']:.3f}"
    return s + "."


# --- decisions followed up; memory kept tidy -------------------------------------------------------------------------------

def followups(con, asof: date, days: int = 120) -> List[dict]:
    """Decisions in memory about a company in the last `days`, with what its price did since."""
    sym = {s.upper(): i for i, s in con.execute("SELECT isin, symbol FROM instruments WHERE symbol IS NOT NULL").fetchall()}
    out = []
    for mid, at, subject, text in con.execute(
            "SELECT mem_id, created_at, subject, text FROM memory WHERE kind='decision' AND valid_to IS NULL AND created_at >= ? "
            "ORDER BY created_at DESC", [datetime.combine(asof - timedelta(days=days), datetime.min.time())]).fetchall():
        isin = sym.get((subject or "").strip().upper())
        d = {"id": mid, "at": at, "subject": subject, "text": text, "since": None}
        if isin:
            s = closes(con, isin, asof, days=days + 10)
            s0 = s[s.index.date <= at.date()]
            if len(s0) and len(s):
                d["since"] = {"from": str(s0.index[-1].date()), "to": str(s.index[-1].date()),
                              "change_pct": (float(s.iloc[-1]) / float(s0.iloc[-1]) - 1) * 100}
        else:
            d["unknown_subject"] = bool(subject)
        out.append(d)
    return out


def tidy_notes(con, now: datetime) -> int:
    """One current analyst note per company: an older one still open is ended (S57's rule, kept true)."""
    n = 0
    for (subject,) in con.execute("SELECT subject FROM memory WHERE kind='note' AND valid_to IS NULL AND source LIKE "
                                  "'analyst call #%' GROUP BY subject HAVING count(*) > 1").fetchall():
        keep = con.execute("SELECT max(mem_id) FROM memory WHERE kind='note' AND valid_to IS NULL AND subject=? AND source "
                           "LIKE 'analyst call #%'", [subject]).fetchone()[0]
        n += con.execute("SELECT count(*) FROM memory WHERE kind='note' AND valid_to IS NULL AND subject=? AND source LIKE "
                         "'analyst call #%' AND mem_id <> ?", [subject, keep]).fetchone()[0]
        con.execute("UPDATE memory SET valid_to=? WHERE kind='note' AND valid_to IS NULL AND subject=? AND source LIKE "
                    "'analyst call #%' AND mem_id <> ?", [now.date(), subject, keep])
    return int(n)


OUTCOME_DAYS = 30


def write_outcomes(con, now: datetime, fu: Optional[List[dict]] = None) -> int:
    """S60 memory that updates: a decision followed for OUTCOME_DAYS gets its outcome written back once, as an
    `outcome` row on the same subject (what the price did since)."""
    from pflab.agents import memory as mem
    n = 0
    for f in fu if fu is not None else followups(con, now.date()):
        if not f["since"] or (now.date() - f["at"].date()).days < OUTCOME_DAYS:
            continue
        tag = f"decision #{f['id']}"
        if con.execute("SELECT 1 FROM memory WHERE kind='outcome' AND source=?", [f"keeper ({tag})"]).fetchone():
            continue
        mem.remember(con, "outcome", f"{OUTCOME_DAYS}+ days after {tag} ({f['at']:%Y-%m-%d}): the price moved "
                                     f"{f['since']['change_pct']:+.1f}% from {f['since']['from']} to {f['since']['to']}",
                     subject=f["subject"], source=f"keeper ({tag})", now=now)
        n += 1
    return n


def run(con, now: datetime, root=None) -> dict:
    from pflab.hq import suggestions as sg
    fu = followups(con, now.date())
    index = None
    if root is not None:
        try:
            from pflab.hq import stocks
            index = stocks.index_series(root)
        except Exception:                                    # no index file: suggestions wait (void after 10 days)
            index = None
    from pflab.kg import hypotheses as hy
    try:
        hyp = hy.check_due(con, root, now) if root is not None else {}
    except Exception as e:                                   # a hypothesis check never stops the keeper
        hyp = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    return {"hypotheses": hyp, "scored": score_due(con, now), "suggestions_scored": sg.score_due(con, now, index),
            "notes_ended": tidy_notes(con, now), "outcomes_written": write_outcomes(con, now, fu),
            "decisions_followed": sum(1 for f in fu if f["since"]), "unknown_subjects": sum(1 for f in fu if f.get("unknown_subject"))}
