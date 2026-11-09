"""Small pricing helpers the scoring code shares (closes near a date, index levels, the verdict of a priced call, a stock's beta then).

They lived in `hq/suggestions.py` (S60) until that layer was cut (S80 phase 4); the paper book's claims and the opportunity pot use them.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd

SLACK_DAYS = 6                           # a close or index level this many days before the day is still "the level on that day"


def close_on(con, isin: str, day: date) -> Optional[tuple]:
    """(date, close) of the last session at or before `day` within SLACK_DAYS; None when there is none."""
    from pflab.hq import keeper
    s = keeper.closes(con, isin, day, days=SLACK_DAYS + 5)
    s = s[s.index.date >= day - timedelta(days=SLACK_DAYS)] if len(s) else s
    return (s.index[-1].date(), float(s.iloc[-1])) if len(s) else None


def index_on(index: pd.Series, day: date) -> Optional[float]:
    s = index[(index.index <= pd.Timestamp(day)) & (index.index >= pd.Timestamp(day - timedelta(days=SLACK_DAYS)))]
    return float(s.iloc[-1]) if len(s) else None


def judge(kind: str, stock_pct: float, excess_pct: float, cost_pct: float) -> str:
    """good / bad / n/a for a priced call: add good if it beat the index; trim good if it lagged; hold good if it did not lag by more than a
    round trip's charges; wait good if the price fell."""
    if kind == "add":
        return "good" if excess_pct > 0 else "bad"
    if kind == "trim":
        return "good" if excess_pct < 0 else "bad"
    if kind == "hold":
        return "good" if excess_pct > -cost_pct else "bad"
    if kind == "wait":
        return "good" if stock_pct < 0 else "bad"
    return "n/a"


def beta_at(isin: str, day: date) -> Optional[float]:
    """The stock's CAPM beta as known on `day`; None when it has no fit."""
    try:
        from pflab.data import data_dir
        from pflab.risk import capm
        return capm.for_isin(data_dir(), isin, day)["beta"]
    except Exception:
        return None
