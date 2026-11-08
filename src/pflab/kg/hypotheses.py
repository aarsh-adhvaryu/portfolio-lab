"""Cause hypotheses in the graph (S64 Phase 5 item 3; the investor: "it seems the war has caused fuel cost to inflate ...
I will check later; OK, this is the cause").

The brain records "this seems the cause" with its evidence and a date to check by (at most 90 days). Each hypothesis is a
row in `kg_hypotheses` and an edge `seems_caused_by` in the graph. The keeper checks the ones that are due:
- where the cause is a macro series (BRENT, USDINR, US_SP500) by code: the beta of the subject's daily returns to the
  series' returns over the last 500 sessions (series return known before the NSE session it is paired with),
  Newey-West t; |t| >= 2 confirms, else refutes;
- otherwise the hypothesis goes to the brain's next pass (status 'review') to decide with the evidence;
- 30 days past `check_by` an undecided one expires.
A refuted or expired hypothesis closes its graph edge. A confirmed one keeps it. The test says whether the stock has
moved with the series over the window, not that the series caused one day's move: the status text says so.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd

from pflab.kg import graph

REL = "seems_caused_by"
MAX_DAYS = 90
EXPIRE_AFTER = 30
SERIES = ("BRENT", "USDINR", "US_SP500")
WINDOW = 500                    # sessions
T_BAR = 2.0
MIN_OBS = 120


def _node(con, subject: str, now: datetime) -> str:
    r = con.execute("SELECT isin, symbol FROM instruments WHERE upper(symbol)=? LIMIT 1", [subject.strip().upper()]).fetchone()
    nid = f"company:{r[0]}" if r else f"topic:{subject.strip().lower()[:60]}"
    graph.node(con, nid, "company" if r else "topic", r[1] if r else subject.strip()[:60], now=now)
    return nid


def record(con, pass_id: Optional[int], subject: str, cause: str, effect: str, evidence: List[str], check_by: date,
           series: Optional[str], now: datetime) -> int:
    """Keep a hypothesis and its graph edge. `series` is one of SERIES when the cause is a macro series the keeper can test."""
    from pflab.kg import switch
    if not switch.on():
        raise RuntimeError(switch.WHY)
    if not now.date() < check_by <= now.date() + timedelta(days=MAX_DAYS):
        raise ValueError(f"check_by must be after today and at most {MAX_DAYS} days ahead")
    if series is not None and series not in SERIES:
        raise ValueError(f"series is one of {SERIES}")
    from pflab.pm.store import next_id
    hid = next_id(con, "kg_hypotheses", "hyp_id")
    con.execute("INSERT INTO kg_hypotheses (hyp_id, made_at, pass_id, subject, cause, effect, evidence_json, status, check_by) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                [hid, now, pass_id, subject.strip()[:80], cause[:300], effect[:300],
                 json.dumps({"ids": evidence[:10], "series": series}), "open", check_by])
    src = _node(con, subject, now)
    dst = f"cause:{cause.strip().lower()[:60]}"
    graph.node(con, dst, "cause", cause.strip()[:60], now=now)
    graph.edge(con, src, REL, dst, now, "brain", f"hyp:{hid}", {"hyp_id": hid, "check_by": str(check_by)}, now=now)
    return hid


def _edge_ends(con, hid: int):
    r = con.execute("SELECT src, dst FROM kg_edges WHERE rel=? AND source_ref=? AND valid_to IS NULL", [REL, f"hyp:{hid}"]).fetchone()
    return r


def decide(con, hid: int, status: str, why: str, now: datetime) -> None:
    """Close a hypothesis as confirmed, refuted or expired. Refuted and expired end the graph edge."""
    if status not in ("confirmed", "refuted", "expired"):
        raise ValueError("status is confirmed, refuted or expired")
    if not con.execute("SELECT 1 FROM kg_hypotheses WHERE hyp_id=? AND status IN ('open','review')", [hid]).fetchone():
        raise ValueError(f"hypothesis #{hid} is not open")
    ends = _edge_ends(con, hid)
    if status != "confirmed" and ends:
        graph.close(con, ends[0], REL, ends[1], now)
    con.execute("UPDATE kg_hypotheses SET status=?, decided_at=?, why=? WHERE hyp_id=?", [status, now, why[:500], hid])


def macro_returns(root, series: str) -> pd.Series:
    """Daily log returns of the series, indexed by the date they became known."""
    if series == "US_SP500":
        from pflab.data import global_markets
        df = global_markets.load("US_SP500", root)
        s = df.set_index(pd.to_datetime(df["date"]))["close"]
    else:
        from pflab.data import macro
        df = macro.load(series, root)
        s = df.set_index(pd.to_datetime(df["date"]))["value"]
    s = s.dropna()
    s = s[s > 0].sort_index()
    return np.log(s).diff().dropna()


def beta_test(stock_close: pd.Series, factor_ret: pd.Series, asof: date, window: int = WINDOW) -> dict:
    """OLS slope of the stock's daily log returns on the factor's, with a Newey-West t. A factor return is paired with the
    first NSE session AFTER its date (the US and the FRED series close after the NSE does)."""
    import statsmodels.api as sm
    c = stock_close[stock_close.index <= pd.Timestamp(asof)].dropna()
    y = np.log(c).diff().dropna().iloc[-window:]
    if len(y) < MIN_OBS:
        return {"n": int(len(y)), "error": "too few sessions"}
    f = factor_ret[factor_ret.index < y.index[-1]]
    pos = y.index.searchsorted(f.index, side="right")
    keep = pos < len(y)
    x = pd.Series(f.to_numpy()[keep], index=y.index[pos[keep]]).groupby(level=0).sum().reindex(y.index).fillna(0.0)
    fit = sm.OLS(y.to_numpy(), sm.add_constant(x.to_numpy())).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    return {"n": int(len(y)), "beta": float(fit.params[1]), "t": float(fit.tvalues[1])}


def check_due(con, root, now: datetime, closes_fn=None) -> dict:
    """Test or hand over every hypothesis whose check_by has come; expire the stale ones."""
    today = now.date()
    out = {"confirmed": 0, "refuted": 0, "review": 0, "expired": 0}
    for hid, subject, cause, ev, status, check_by in con.execute(
            "SELECT hyp_id, subject, cause, evidence_json, status, check_by FROM kg_hypotheses WHERE status IN ('open','review') "
            "AND check_by <= ? ORDER BY hyp_id", [today]).fetchall():
        if (today - check_by).days > EXPIRE_AFTER:
            decide(con, hid, "expired", "no decision within 30 days of the check date", now)
            out["expired"] += 1
            continue
        series = (json.loads(ev or "{}") or {}).get("series")
        r = con.execute("SELECT isin FROM instruments WHERE upper(symbol)=? LIMIT 1", [subject.upper()]).fetchone()
        if status == "review" or not series or not r:
            if status == "open":
                con.execute("UPDATE kg_hypotheses SET status='review' WHERE hyp_id=?", [hid])
                out["review"] += 1
            continue
        if closes_fn is None:
            from pflab.hq import stocks
            closes_fn = lambda isin, d: stocks.closes(con, root, isin, d)             # noqa: E731
        try:
            t = beta_test(closes_fn(r[0], today), macro_returns(root, series), today)
        except Exception as e:                       # data missing: the brain decides rather than a guess by code
            con.execute("UPDATE kg_hypotheses SET status='review', why=? WHERE hyp_id=?", [f"test not run: {type(e).__name__}", hid])
            out["review"] += 1
            continue
        if "t" not in t:
            con.execute("UPDATE kg_hypotheses SET status='review', why=? WHERE hyp_id=?", [t["error"], hid])
            out["review"] += 1
            continue
        ok = abs(t["t"]) >= T_BAR
        decide(con, hid, "confirmed" if ok else "refuted",
               f"{subject} moved {'with' if ok else 'not clearly with'} {series} over the last {t['n']} sessions: beta {t['beta']:+.2f}, "
               f"t {t['t']:+.1f} (bar {T_BAR:g}); a relation over the window, not proof of one day's cause", now)
        out["confirmed" if ok else "refuted"] += 1
    return out


def due_for_the_brain(con) -> List[dict]:
    return [{"hyp_id": h, "subject": s, "cause": c, "effect": e, "evidence": json.loads(ev or "{}").get("ids", []),
             "check_by": str(cb)} for h, s, c, e, ev, cb in con.execute(
        "SELECT hyp_id, subject, cause, effect, evidence_json, check_by FROM kg_hypotheses WHERE status='review' ORDER BY hyp_id").fetchall()]


def listing(con, status: Optional[str] = None, limit: int = 20) -> List[dict]:
    q = "SELECT hyp_id, made_at, subject, cause, effect, status, check_by, why FROM kg_hypotheses"
    q += " WHERE status=?" if status else ""
    q += " ORDER BY hyp_id DESC LIMIT ?"
    rows = con.execute(q, ([status] if status else []) + [limit]).fetchall()
    return [{"hyp_id": h, "made": str(m)[:10], "subject": s, "cause": c, "effect": e, "status": st, "check_by": str(cb),
             "why": w} for h, m, s, c, e, st, cb, w in rows]
