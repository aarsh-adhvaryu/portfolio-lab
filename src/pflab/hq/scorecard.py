"""The scorecard (S73): did each recommendation turn out right, claim by claim, and which kind of decision works when.

Reinforcement learning was considered and not adopted (a handful of decisions a month, a market that changes, a spent 2022-2025: it would learn noise). What learns here is the
record: every proposal (BUY, ADD, REDUCE, SELL, HOLD, WAIT) states a claim the day it is made, the claim is scored when 5, 20 and 60 sessions have passed (7, 28 and 84 calendar
days), and the scores accumulate by kind of decision and by the state the market was in, with the count beside every rate.

    claim     BUY/ADD: the stock beats the market (its return less beta times the Nifty 500 total return) over the horizon. REDUCE/SELL: it lags. HOLD: it does not lag by more
              than a round trip's charges. WAIT: its price is lower at the horizon (waiting was a better entry). DIVERSIFY is not priced (no single price tells).
    outcome   good / bad per horizon (the same judge and beta as the brain's old suggestion ledger, `hq/suggestions.judge`). A proposal whose horizons disagree is PARTLY right;
              that is written as such, not rounded to a verdict.
    table     per decision kind and market state (near its high / a pullback / deep): n, good, the plain rate, and a skeptical rate (the 20th percentile of Beta(1+good, 1+bad)).
              Under 20 claims: the count and no conclusion (small-numbers rule). The scorecard describes; it never raises a limit and never retires a kind of decision.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

HORIZONS = (7, 28, 84)                     # calendar days: about 5, 20 and 60 sessions
KIND = {"BUY": "add", "ADD": "add", "REDUCE": "trim", "SELL": "trim", "HOLD": "hold", "WAIT": "wait"}
MIN_N = 20


def state_at(index: Optional[pd.Series], day: date) -> str:
    from pflab.plan import envelope
    d = envelope.drawdown(index, day)
    if d is None:
        return "unknown"
    return "near_high" if d["below_high_pct"] < 5 else "pullback" if d["below_high_pct"] < 15 else "deep"


def register(con, now: datetime, proposal_id: int, index: Optional[pd.Series] = None) -> int:
    """State the claim of a proposal at each horizon (idempotent). Needs the price the proposal rested on; without one nothing is claimed."""
    from pflab.pm.store import next_id
    p = con.execute("SELECT created_at, case_id, action, isin, symbol, payload_json FROM hq_proposals WHERE proposal_id = ?", [proposal_id]).fetchone()
    if p is None or p[2] not in KIND or not p[3]:
        return 0
    try:
        pay = json.loads(p[5])
    except ValueError:
        return 0
    px = pay.get("price") or {}
    if not px.get("value") or not px.get("as_of"):
        return 0
    ref_date = date.fromisoformat(str(px["as_of"])[:10])
    st = state_at(index, ref_date)
    n = 0
    for h in HORIZONS:
        if con.execute("SELECT 1 FROM hq_claims WHERE proposal_id = ? AND horizon_days = ?", [proposal_id, h]).fetchone():
            continue
        con.execute("INSERT INTO hq_claims (claim_id, proposal_id, case_id, isin, symbol, action, kind, made_at, ref_date, ref_close, state, horizon_days, due_on) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [next_id(con, "hq_claims", "claim_id"), proposal_id, p[1], p[3], p[4], p[2], KIND[p[2]], p[0], ref_date, float(px["value"]), st, h, ref_date + timedelta(days=h)])
        n += 1
    return n


def register_missing(con, now: datetime, index: Optional[pd.Series] = None) -> int:
    return sum(register(con, now, pid, index) for (pid,) in con.execute(
        "SELECT proposal_id FROM hq_proposals WHERE status NOT IN ('withdrawn') AND proposal_id NOT IN (SELECT DISTINCT proposal_id FROM hq_claims)").fetchall())


def score_due(con, now: datetime, index: Optional[pd.Series]) -> int:
    """Score every claim past its horizon: outcomes after the day it was made, never before. A claim with no close or index near its horizon for 10 days is void."""
    from pflab.hq import stocks, suggestions as sg
    n = 0
    for cid, isin, kind, ref_date, ref_close, due in con.execute(
            "SELECT claim_id, isin, kind, ref_date, ref_close, due_on FROM hq_claims WHERE scored_at IS NULL AND due_on <= ?", [now.date()]).fetchall():
        end = sg._close_on(con, isin, due)
        i0 = sg._index_on(index, ref_date) if index is not None else None
        i1 = sg._index_on(index, due) if index is not None else None
        if end is None or end[0] <= ref_date or i0 is None or i1 is None:
            if (now.date() - due).days > 10:
                con.execute("UPDATE hq_claims SET outcome = 'void', outcome_json = ?, scored_at = ? WHERE claim_id = ?", [json.dumps({"why": "no close or index level near the horizon"}), now, cid])
                n += 1
            continue
        sp, ip = (end[1] / ref_close - 1) * 100, (i1 / i0 - 1) * 100
        beta = sg.beta_at(isin, ref_date)
        adj = sp - (beta if beta is not None else 1.0) * ip
        out = sg.judge(kind, sp, adj, stocks.round_trip_pct(stocks.DEFAULT_ORDER))
        con.execute("UPDATE hq_claims SET outcome = ?, outcome_json = ?, scored_at = ? WHERE claim_id = ?",
                    [out, json.dumps({"to": str(end[0]), "stock_pct": round(sp, 2), "nifty500_pct": round(ip, 2), "market_adjusted_pct": round(adj, 2),
                                       "beta": None if beta is None else round(beta, 2)}), now, cid])
        n += 1
    return n


def verdict_of(outcomes: List[Optional[str]]) -> str:
    """One proposal across its scored horizons: held / did not hold / partly held / not yet."""
    got = [o for o in outcomes if o in ("good", "bad")]
    if not got:
        return "not yet scored"
    if len(got) < len(outcomes) and all(o == "good" for o in got):
        return "holding so far"
    if all(o == "good" for o in got):
        return "held"
    if all(o == "bad" for o in got):
        return "did not hold"
    return "partly held"


def proposal_view(con, proposal_id: int) -> dict:
    rows = con.execute("SELECT horizon_days, outcome, outcome_json FROM hq_claims WHERE proposal_id = ? ORDER BY horizon_days", [proposal_id]).fetchall()
    return {"proposal_id": proposal_id, "verdict": verdict_of([r[1] for r in rows]) if rows else "no claim stated",
            "horizons": [{"days": r[0], "outcome": r[1] or "pending", **(json.loads(r[2]) if r[2] else {})} for r in rows]}


def skeptical(good: int, bad: int, q: float = 0.20) -> Optional[float]:
    """The q-quantile of Beta(1 + good, 1 + bad): what the rate is probably at least, given only this record."""
    try:
        from scipy.stats import beta
        return round(float(beta.ppf(q, 1 + good, 1 + bad)), 3)
    except Exception:
        return None


def table(con) -> List[dict]:
    """Per kind of decision and market state: n, good, plain rate and skeptical rate; under MIN_N claims: the count only."""
    out = []
    for action, state, good, bad in con.execute(
            "SELECT action, state, count(*) FILTER (WHERE outcome = 'good'), count(*) FILTER (WHERE outcome = 'bad') FROM hq_claims WHERE outcome IN ('good', 'bad') GROUP BY 1, 2 ORDER BY 1, 2").fetchall():
        n = int(good + bad)
        row = {"action": action, "market_state": state, "n": n, "good": int(good)}
        if n >= MIN_N:
            row.update({"rate": round(good / n, 3), "skeptical_rate": skeptical(int(good), int(bad))})
        else:
            row["note"] = f"only {n} scored claim(s): a count, not a conclusion"
        out.append(row)
    return out
