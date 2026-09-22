"""Split/bonus factors from the bhavcopy's adjusted PREVCLOSE (sprint step 3).

SUPERSEDED -- charter §15, 2026-09-16. NSE does not publish an adjusted
PREVCLOSE, so this method recovers no factors at all: on 450 of 451 large
corporate-action gaps in 2012-2020, prev_close(t) equals close(t-1) exactly
and the formula below evaluates to 1.000. Use `pflab.data.nse_corporate_actions`
instead, which parses exact factors from the NSE corporate-actions feed.

This module is kept for the record and for `verify_known_events`, which is the
gate that caught the failure and which the feed-based factors still have to
pass. `tests/test_adjustment_known_events.py` asserts that `candidates()`
finds nothing, so the finding cannot quietly regress into looking correct.
Evidence: docs/data/adjustment_method_finding.md.

Contract
--------
candidates(panel) -> DataFrame(isin, ex_date, raw_ratio, snapped_factor, volume_ratio)
    raw_ratio = prev_close(t) / close(t-1) on rows where |raw_ratio - 1| > 0.02
    and the name traded on both sessions.
    snapped_factor = nearest of COMMON_RATIOS when within 1%, else raw_ratio.

adjustment_factors(candidates) -> DataFrame(isin, ex_date, factor)
    factor multiplies all prices strictly BEFORE ex_date. panel.py takes the
    cumulative product backwards in time.

verify_known_events(candidates) -> list[str] of failures
    Must include at least one 1:1 bonus, one 10->2 split, one 1:2 bonus.
    Lives in tests/test_adjustment_known_events.py once real data exists.

Fallback only if verification fails: NSE corporate-actions archive scraper.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

COMMON_RATIOS = [1/2, 1/3, 1/4, 1/5, 1/10, 2/3, 3/4, 1/1.5, 5/10, 1/2.5, 2/5, 1/1.25, 4/5]

# Sprint step 3: flag when PREVCLOSE and the previous close differ by more than
# 2%, and snap to a common ratio when within 1% of one.
THRESHOLD = 0.02
SNAP_TOL = 0.01

CANDIDATE_COLUMNS = ["isin", "ex_date", "raw_ratio", "snapped_factor", "volume_ratio"]


def snap(ratio: float) -> float:
    """Nearest common ratio within SNAP_TOL (relative), else the raw ratio."""
    if not ratio or ratio <= 0:
        return ratio
    best = min(COMMON_RATIOS, key=lambda c: abs(ratio / c - 1.0))
    return best if abs(ratio / best - 1.0) <= SNAP_TOL else ratio


def candidates(panel: pd.DataFrame, key: str = "isin") -> pd.DataFrame:
    """Corporate-action candidates implied by the adjusted PREVCLOSE.

    On an ex-date NSE publishes PREVCLOSE already adjusted for the action, so
    `prev_close(t) / close(t-1)` is the price factor: 0.5 for a 1:1 bonus,
    0.2 for a 10->2 split. `key` is the security key; pre-2012 bhavcopies
    carry no ISIN, so panel.py passes "symbol" for those rows until the
    symbol->ISIN map (sprint step 4) is built.
    """
    need = {key, "date", "close", "prev_close", "volume"}
    missing = need - set(panel.columns)
    if missing:
        raise ValueError(f"panel is missing {sorted(missing)}")

    df = panel.loc[panel[key].notna(), sorted(need)].copy()
    df = df.sort_values([key, "date"], kind="mergesort")
    g = df.groupby(key, sort=False)
    # The previous row for this security, which is the session PREVCLOSE
    # refers to -- not the previous calendar day, since illiquid names skip
    # sessions entirely.
    df["last_close"] = g["close"].shift(1)
    df["last_volume"] = g["volume"].shift(1)

    traded_both = (df["volume"].fillna(0) > 0) & (df["last_volume"].fillna(0) > 0)
    priced = (df["last_close"] > 0) & (df["prev_close"] > 0)
    df = df[traded_both & priced].copy()

    df["raw_ratio"] = df["prev_close"] / df["last_close"]
    out = df[(df["raw_ratio"] - 1.0).abs() > THRESHOLD].copy()
    out["snapped_factor"] = out["raw_ratio"].map(snap)
    # A split multiplies the share count, so volume usually jumps by roughly
    # the inverse of the factor. A reviewer uses this to tell a real action
    # from a bad print.
    out["volume_ratio"] = out["volume"] / out["last_volume"]
    out = out.rename(columns={"date": "ex_date", key: "isin"})
    return (out[CANDIDATE_COLUMNS]
            .sort_values(["isin", "ex_date"], kind="mergesort")
            .reset_index(drop=True))


def adjustment_factors(cands: pd.DataFrame) -> pd.DataFrame:
    """The factor to multiply into every price strictly before ex_date."""
    if cands.empty:
        return pd.DataFrame(columns=["isin", "ex_date", "factor"])
    out = cands[["isin", "ex_date", "snapped_factor"]].rename(
        columns={"snapped_factor": "factor"})
    # Two actions can share an ex-date (a bonus and a split together); the
    # price factor is their product.
    out = (out.groupby(["isin", "ex_date"], as_index=False)["factor"].prod())
    return out.sort_values(["isin", "ex_date"], kind="mergesort").reset_index(drop=True)


# Real events read off the backfilled bhavcopy, covering the three types the
# sprint requires. ex_date is the first session at the new price.
KNOWN_EVENTS = [
    ("INE009A01021", "INFY", "2015-06-15", 1 / 2, "1:1 bonus"),
    ("INE002A01018", "RELIANCE", "2017-09-07", 1 / 2, "1:1 bonus"),
    ("INE090A01013", "ICICIBANK", "2014-12-04", 1 / 5, "face value 10 -> 2 split"),
    ("INE018A01030", "LT", "2017-07-13", 2 / 3, "1:2 bonus"),
]


def verify_known_events(cands: pd.DataFrame, tol: float = 0.01) -> list[str]:
    """Failures among KNOWN_EVENTS. Empty list means the method is trustworthy.

    The sprint requires this to pass before any factor is believed. It does
    NOT pass for the PREVCLOSE method -- see
    docs/data/adjustment_method_finding.md.
    """
    failures = []
    for isin, sym, ex, want, what in KNOWN_EVENTS:
        ex_date = pd.Timestamp(ex).date()
        hit = cands[(cands["isin"] == isin)
                    & (pd.to_datetime(cands["ex_date"]).dt.date == ex_date)]
        if hit.empty:
            failures.append(f"{sym} {ex} ({what}): no candidate detected")
            continue
        got = float(hit["snapped_factor"].iloc[0])
        if abs(got / want - 1.0) > tol:
            failures.append(f"{sym} {ex} ({what}): factor {got:.4f}, expected {want:.4f}")
    return failures


def snapped(cands: pd.DataFrame) -> pd.DataFrame:
    """Candidates that landed on a common ratio."""
    return cands[cands["raw_ratio"].ne(cands["snapped_factor"])]


def unsnapped(cands: pd.DataFrame) -> pd.DataFrame:
    """Candidates that did NOT snap -- the ones Aarsh reviews (sprint step 7).

    These are large dividends, reverse splits, thin-trade prints and genuine
    data errors, mixed together. Nothing here is trusted as a factor without
    a look.
    """
    return cands[cands["raw_ratio"].eq(cands["snapped_factor"])]


def write_candidates(cands: pd.DataFrame, root: Optional[object] = None):
    """data/panel/adjustment_candidates.parquet (sprint step 3)."""
    from pflab.data import data_dir
    from pathlib import Path
    root = Path(root) if root is not None else data_dir()
    p = root / "panel" / "adjustment_candidates.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    cands.to_parquet(p, index=False)
    return p
