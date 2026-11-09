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

