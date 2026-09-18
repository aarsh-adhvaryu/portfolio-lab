"""Trend filter (charter E1 §6): RISK_OFF when the Nifty 50 month-end
close is below the simple mean of the last `months` month-end closes,
including the current one."""
from __future__ import annotations

import pandas as pd


def month_end_closes(daily_close: pd.Series) -> pd.Series:
    s = daily_close.dropna().copy()
    s.index = pd.to_datetime(s.index)
    return s.resample("ME").last().dropna()


def risk_off(month_end_close: pd.Series, months: int = 10) -> pd.Series:
    """Boolean series aligned to month-ends. False until `months` of history exist."""
    sma = month_end_close.rolling(months, min_periods=months).mean()
    out = month_end_close < sma
    return out.where(sma.notna(), False).astype(bool)
