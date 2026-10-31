"""Evaluation contracts for the bounded experiment loop (S68).

A historical STRATEGY EXPERIMENT is judged by one of these contracts, chosen when the question is registered and fixed by the protocol hash. A
contract fixes: what the candidate's `compute(data)` returns, what it is compared with (the baseline), how a period is scored, and the
rule that keeps or rejects it. The candidate (model-written code, run in the sandbox) never touches any of it. A hypothesis no contract fits is
recorded as `unsupported` with the reason; it is NEVER run through another contract's template.

    index_timing   "be invested or out each month" on one index series; baseline: always invested.            (the S67 evaluator, unchanged)
    deployment     "how much of a waiting sum to put in each month" on one index series; baseline: all in at the
                   start (lump sum). The score is the terminal value of a 12-month deployment started in every month; waiting
                   cash earns CASH_RATE_PA; costs per rupee invested. Start months overlap, so the t-statistic uses the number of
                   independent windows (months / horizon), not the number of months.

Another family (IPO sell or hold, FD deployment by maturity) is a calculation on its own data (`quant/ipo_policy.py`, `quant/policies.py`), not a
sandbox candidate; the experiment loop does not take it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

HORIZON = 12                      # months a deployment runs
CASH_RATE_PA = 0.06               # what waiting cash earns (an assumption, stated in the protocol)
COST_BPS = 10.0                   # per rupee put to work (an assumption, stated in the protocol)


@dataclass(frozen=True)
class Contract:
    name: str
    comparator: str
    metric: str
    writer_system: str
    min_text: str


INDEX_TIMING_WRITER = (
    "You write ONE small Python rule for a research experiment on a daily index series. Reply in exactly this form and nothing else:\n"
    "WHY: one sentence on why this rule might work\n"
    "```python\n<the code>\n```\n"
    "The code defines def compute(data) where data maps the dataset name to a pandas DataFrame with columns date and close, and returns "
    '{"signal": number}: above 0 means be invested for the next month, 0 or below means be out. compute is called once per month-end with ONLY the rows '
    "up to that date; use only those rows, never assume a length (check len first). Do not modify the input frame. Allowed imports: numpy, pandas, math. "
    "The frame holds DAILY rows (a month is about 21 rows, a year about 252). "
    "No files, no network. You are shown every earlier candidate and exactly how it scored: do not repeat one that failed; change one thing for a reason.")

DEPLOYMENT_WRITER = (
    "You write ONE small Python rule for a research experiment on how to put a waiting sum into a daily index series over twelve months. "
    "Reply in exactly this form and nothing else:\n"
    "WHY: one sentence on why this rule might work\n"
    "```python\n<the code>\n```\n"
    "The code defines def compute(data) where data maps the dataset name to a pandas DataFrame with columns date and close, and returns "
    '{"signal": number between 0 and 1}: the SHARE OF THE CASH STILL WAITING to put into the index at the next session. compute is called once per '
    "month-end with ONLY the rows up to that date; use only those rows, never assume a length (check len first). You do not know how much cash is "
    "left or when the deployment began: decide from the prices alone (for example: more when the index is below its own recent high, less when above). "
    "Do not modify the input frame. Allowed imports: numpy, pandas, math. The frame holds DAILY rows (a month is about 21 rows). No files, no network. "
    "The comparator is putting everything in at the start; a rule that only waits will lose in rising markets. You are shown every earlier candidate "
    "and exactly how it scored: do not repeat one that failed; change one thing for a reason.")

CONTRACTS: Dict[str, Contract] = {
    "index_timing": Contract("index_timing", "always invested", "paired monthly return difference net of switching cost; t-statistic",
                             INDEX_TIMING_WRITER, "months in each period"),
    "deployment": Contract("deployment", "all in at the start (lump sum)",
                           f"paired terminal-return difference of a {HORIZON}-month deployment started in every month, net of costs, waiting cash earning "
                           f"{CASH_RATE_PA:.0%} a year; t-statistic on independent windows (months / {HORIZON})",
                           DEPLOYMENT_WRITER, "start months in each period"),
}
DEFAULT = "index_timing"


class Unsupported(ValueError):
    """No contract fits the hypothesis: it is recorded as unsupported, not evaluated by another template."""


KEYWORDS = {
    "deployment": ("deploy", "phased", "lump", "stagger", "tranche", "dollar-cost", "dollar cost", "sip", "cash to equity", "buy in parts", "staged"),
    "index_timing": ("in and out", "in/out", "be invested", "market timing", "timing", "go to cash", "moving average", "trend filter", "switch"),
}


def infer(hypothesis: str) -> Optional[str]:
    """The contract a hypothesis names by its words, when exactly one fits; None when none or several do (the caller must say which)."""
    h = hypothesis.lower()
    hits = [c for c, words in KEYWORDS.items() if any(w in h for w in words)]
    return hits[0] if len(hits) == 1 else None


def resolve(hypothesis: str, contract: Optional[str]) -> str:
    if contract:
        if contract not in CONTRACTS:
            raise Unsupported(f"{contract!r} is not an evaluation contract of this system (supported: {', '.join(CONTRACTS)}); a strategy question of another kind "
                              "is a calculation or a scenario study, or needs a new contract written and reviewed first")
        return contract
    c = infer(hypothesis)
    if c is None:
        raise Unsupported("the hypothesis does not say which evaluation applies (supported contracts: " + "; ".join(f"{k}: {v.comparator}" for k, v in CONTRACTS.items())
                          + "). Name the contract, or ask for a calculation or a scenario instead.")
    return c


# --- deployment scoring -----------------------------------------------------------------------------------------------------------------------

def _exec_prices(df: pd.DataFrame, dates: List[date], days: List[date]) -> Dict[date, float]:
    """Execution price of a decision made at the close of d: the NEXT session's close (never d's own)."""
    import bisect
    px = dict(zip(df["date"], df["close"].astype(float)))
    out = {}
    for d in dates:
        i = bisect.bisect_right(days, d)
        if i < len(days):
            out[d] = px[days[i]]
    return out


def deployment_windows(df: pd.DataFrame, signals: Dict[str, float], dates: List[date]) -> List[dict]:
    """For each start month-end s with HORIZON later month-ends in `dates`: the terminal return of the candidate's deployment and of the lump
    sum, and the worst mark-to-market fall of each. Raises ValueError for a missing or non-finite signal."""
    days = sorted(df["date"])
    ex = _exec_prices(df, dates, days)
    cm = (1 + CASH_RATE_PA) ** (1 / 12) - 1
    rows = []
    for i in range(len(dates) - HORIZON):
        win = dates[i:i + HORIZON + 1]
        if any(d not in ex for d in win):
            continue
        cash, units, curve, cost = 1.0, 0.0, [], 0.0
        for k, d in enumerate(win[:-1]):
            s = signals.get(d.isoformat())
            if s is None or not math.isfinite(float(s)):
                raise ValueError(f"no signal for {d}")
            f = min(1.0, max(0.0, float(s)))
            buy = cash * f
            c = buy * COST_BPS / 1e4
            units += (buy - c) / ex[d]
            cost += c
            cash -= buy
            nxt = win[k + 1]
            curve.append(units * ex[nxt] + cash * (1 + cm))
            cash *= 1 + cm
        end = units * ex[win[-1]] + cash
        lump_units = (1.0 - COST_BPS / 1e4) / ex[win[0]]
        lump_curve = [lump_units * ex[d] for d in win[1:]]
        rows.append({"start": win[0], "cand": end - 1.0, "lump": lump_curve[-1] - 1.0, "cand_worst": min(curve) - 1.0 if curve else 0.0,
                     "lump_worst": min(lump_curve) - 1.0, "invested_share": 1.0 - cash / (cash + units * ex[win[-1]]) if (cash + units * ex[win[-1]]) else 0.0})
    return rows


def score_deployment(df: pd.DataFrame, signals: Dict[str, float], period: Tuple[str, str], month_ends: Callable) -> dict:
    dates = month_ends(df, *period)
    rows = deployment_windows(df, signals, dates)
    n = len(rows)
    diff = pd.Series([r["cand"] - r["lump"] for r in rows], dtype=float)
    eff = max(n / HORIZON, 1.0)                                    # overlapping windows: independent ones are about one in HORIZON
    sd = float(diff.std(ddof=1)) if n > 1 else 0.0
    t = float(diff.mean() / (sd / math.sqrt(eff))) if n > 1 and sd > 0 else 0.0
    return {"n_months": n, "mean_excess": float(diff.mean()) if n else 0.0, "t": round(t, 3), "effective_windows": round(eff, 1),
            "cand_mean": float(pd.Series([r["cand"] for r in rows]).mean()) if n else 0.0, "base_mean": float(pd.Series([r["lump"] for r in rows]).mean()) if n else 0.0,
            "cand_worst_fall_mean": float(pd.Series([r["cand_worst"] for r in rows]).mean()) if n else 0.0,
            "base_worst_fall_mean": float(pd.Series([r["lump_worst"] for r in rows]).mean()) if n else 0.0,
            "share_invested_at_end": round(float(pd.Series([r["invested_share"] for r in rows]).mean()), 3) if n else 0.0,
            "cand_max_drawdown": float(pd.Series([r["cand_worst"] for r in rows]).min()) if n else 0.0,
            "base_max_drawdown": float(pd.Series([r["lump_worst"] for r in rows]).min()) if n else 0.0, "exposure": 0.0}


def baseline_signals(contract: str, dates: List[date]) -> Dict[str, float]:
    """The comparator as signals: index_timing is always invested; the lump sum is everything at the first decision (the deployment scoring
    computes the lump sum itself, so these are only the recorded baseline's inputs)."""
    return {d.isoformat(): 1.0 for d in dates}
