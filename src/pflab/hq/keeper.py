"""The memory keeper (S59): the system's memory and journal stay correct.

    decisions     every decision in memory about a company is followed up: what its price did since ("we decided X; the
                  stock then fell 8%; what now"), for the journal screen
    outcomes      a decision followed for 30 days gets its outcome written back as an `outcome` row (S60)
    memory        the analyst's notes: one current note per company (an older one still open is ended); a decision whose
                  subject the system does not know is listed for the investor
    predictions   (S82) only READ: the brain's old predictions and their scores stay on the record and on the Agent HQ screen (`scorecard`); nothing
                  writes or scores one any more (the brain's passes are gone), so the writer and the scorer were deleted

All code, no model, nothing leaves the PC.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

HISTORY_DAYS = 3 * 365


def closes(con, isin: str, upto: date, days: int = HISTORY_DAYS) -> pd.Series:
    df = con.execute("SELECT date, close, source FROM prices WHERE isin=? AND date<=? AND date>=? ORDER BY date, "
                     "(source = 'nse_bhavcopy') DESC", [isin, upto, upto - timedelta(days=days)]).df()
    if df.empty:
        return pd.Series(dtype=float)
    df = df.drop_duplicates("date", keep="first")
    return pd.Series(df["close"].values, index=pd.to_datetime(df["date"]))


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
    fu = followups(con, now.date())
    from pflab.kg import hypotheses as hy
    try:
        hyp = hy.check_due(con, root, now) if root is not None else {}
    except Exception as e:                                   # a hypothesis check never stops the keeper
        hyp = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    from pflab.hq import board, cases
    return {"held_expired": board.expire_held(con, now), "case_outcomes": cases.link_outcomes(con, now),
            "hypotheses": hyp,
            "notes_ended": tidy_notes(con, now), "outcomes_written": write_outcomes(con, now, fu),
            "decisions_followed": sum(1 for f in fu if f["since"]), "unknown_subjects": sum(1 for f in fu if f.get("unknown_subject"))}
