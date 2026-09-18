"""12-1 momentum (charter E1 §3) on a wide adjusted-close panel."""
from __future__ import annotations

import pandas as pd


def momentum_panel(adj_close: pd.DataFrame, lookback: int = 252, skip: int = 21) -> pd.DataFrame:
    """adj_close: rows = sessions (ascending), columns = ISIN.
    Returns close(t - skip) / close(t - lookback) - 1 for every session t.
    NaN where history is missing. No forward-looking access: only shifts."""
    if lookback <= skip:
        raise ValueError("lookback must exceed skip")
    return adj_close.shift(skip) / adj_close.shift(lookback) - 1.0


def rank_desc(scores: pd.Series) -> pd.Series:
    """Rank 1 = highest score. NaN scores are dropped (not eligible)."""
    s = scores.dropna()
    return s.rank(ascending=False, method="first").astype(int)
