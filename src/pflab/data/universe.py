"""Eligibility filter (charter E1 §2) evaluated on a long panel truncated
at the decision date. Columns required: date, isin, close, turnover, series,
instrument_type."""
from __future__ import annotations

import pandas as pd

from pflab.data import instruments


def eligible(panel: pd.DataFrame, series=("EQ",), min_sessions: int = 250, top_n: int = 500,
             turnover_window: int = 126, min_price: float = 10.0,
             types=instruments.UNIVERSE_TYPES) -> pd.Index:
    df = panel[panel["series"].isin(series)]
    if types is not None:
        # §2 / §15 2026-09-16: STK only. ETFs trade under series EQ, so the
        # series filter alone does not exclude them, and a gold ETF would have
        # ranked top-25 on 12-1 momentum in 2020 and 2024-25.
        if "instrument_type" not in df.columns:
            raise ValueError("panel has no instrument_type column; rebuild it "
                             "(charter §2 requires the STK filter)")
        df = df[df["instrument_type"].isin(types)]
    df = df.sort_values(["isin", "date"])
    g = df.groupby("isin", sort=False)
    n = g.size()
    last_close = g["close"].last()
    mean_turnover = g["turnover"].apply(lambda s: s.tail(turnover_window).mean())
    ok = (n >= min_sessions) & (last_close > min_price)
    ranked = mean_turnover[ok].sort_values(ascending=False).head(top_n)
    return pd.Index(sorted(ranked.index))


def eligible_index_members(panel, membership, index: str, m,
                           min_sessions: int = 250, min_price: float = 10.0,
                           types=instruments.UNIVERSE_TYPES,
                           series=("EQ",), bound: str = "earliest") -> pd.Index:
    """Charter E1b §3: constituents of `index` as of month-end `m`.

    E1's §2 replaced wholesale. Everything else is identical: series EQ,
    instrument type STK, 250 sessions listed, close above the floor. There is
    NO turnover ranking -- membership is the universe, so a thin index member
    is eligible and a heavily traded non-member is not. That is the whole
    point of the experiment.
    """
    from pflab.data import index_membership as im
    # E1b §6 S12: "earliest" places every guessed start at the first date the
    # name could have joined, "latest" at the last. The two bracket the truth.
    members = im.members_at(im.with_bound(membership, bound), index, m)
    if not members:
        return pd.Index([])
    df = panel[panel["series"].isin(series) & panel["isin"].isin(members)]
    if types is not None:
        if "instrument_type" not in df.columns:
            raise ValueError("panel has no instrument_type column")
        df = df[df["instrument_type"].isin(types)]
    if df.empty:
        return pd.Index([])
    g = df.sort_values(["isin", "date"]).groupby("isin", sort=False)
    ok = (g.size() >= min_sessions) & (g["close"].last() > min_price)
    return pd.Index(sorted(ok[ok].index))


def eligible_top_n_by_turnover(panel, m=None, top_n: int = 200, **kw) -> pd.Index:
    """E1b sweep row S11: top N by trailing traded value.

    Separates "large" from "index member": S11 keeps E1's ranking mechanism
    but narrows it to N=200, so a difference between S11 and the base row is
    about index membership, not about size.
    """
    return eligible(panel, top_n=top_n, **kw)
