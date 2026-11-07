"""Positioning (S79b item 15b, spec (c)): FII cash flows (NSDL's daily FPI table), FII and DII index-futures positioning (NSE participant-wise open interest),
the open-interest build-up of stock futures (derived/fo_buildup.parquet) and breadth (advancers against decliners in the NSE daily files). By code, from the
exchanges' own numbers. IN only; the US has no such source on this PC (the frame is empty and says so by being NaN).

Breadth is computed from the bhavcopy files and cached in `derived/sentiment_breadth_s79b.parquet` (date, adv, dec, adv_share); names whose close is more than
-25%/+30% from the previous close are left out (a split or bonus, not a price move, since the circuit limit is 20%)."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from pflab import _duck
from pflab.sentiment import stale_align

BREADTH_CACHE = "sentiment_breadth_s79b.parquet"
BULL = ("long buildup", "short covering")
BEAR = ("short buildup", "long unwinding")


def fii_flow(root) -> Optional[pd.Series]:
    """FPI net investment in equity, Rs crore, by report date (macro/FPI_DAILY.parquet: asset Equity, route Sub-total). A report date's row is knowable at its end."""
    p = Path(root) / "macro" / "FPI_DAILY.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p, columns=["report_date", "asset", "route", "net_cr"])
    except Exception:
        return None
    df = df[(df["asset"] == "Equity") & (df["route"] == "Sub-total")]
    if df.empty:
        return None
    s = pd.Series(df["net_cr"].to_numpy(float), index=pd.to_datetime(df["report_date"])).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def participant_net(root, who: str = "FII") -> Optional[pd.Series]:
    """(long - short) / (long + short) of one participant's INDEX futures open interest, from fo_participant/*.parquet (2024 onward)."""
    base = Path(root) / "fo_participant"
    files = sorted(base.glob("*.parquet")) if base.exists() else []
    if not files:
        return None
    lst = ",".join("'" + f.as_posix() + "'" for f in files)
    try:
        df = _duck.sql(f"SELECT CAST(date AS DATE) AS d, \"Future Index Long\" AS l, \"Future Index Short\" AS s FROM read_parquet([{lst}], union_by_name=true) "
                       f"WHERE participant = '{who}'").df()
    except Exception:
        return None
    if df.empty:
        return None
    den = (df["l"] + df["s"]).astype(float).replace(0, np.nan)
    s = pd.Series(((df["l"] - df["s"]) / den).to_numpy(float), index=pd.to_datetime(df["d"])).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def oi_buildup(root) -> Optional[pd.Series]:
    """(bullish - bearish) / (bullish + bearish) over the stock futures of the day: long build-up and short covering against short build-up and long unwinding."""
    p = Path(root) / "derived" / "fo_buildup.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p, columns=["date", "class"])
    except Exception:
        return None
    c = df["class"].astype(str).str.lower()
    bull = df.assign(v=c.isin(BULL).astype(float)).groupby("date")["v"].sum()
    bear = df.assign(v=c.isin(BEAR).astype(float)).groupby("date")["v"].sum()
    tot = (bull + bear).replace(0, np.nan)
    s = ((bull - bear) / tot).dropna()
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def breadth_series(root, start: date, end: date, use_cache: bool = True) -> Optional[pd.Series]:
    """Share of advancers among advancers + decliners (NSE series EQ), by date in [start, end]. Missing dates are computed from the bhavcopy files and cached."""
    root = Path(root)
    cache = root / "derived" / BREADTH_CACHE
    have = pd.DataFrame(columns=["date", "adv", "dec", "adv_share"])
    if use_cache and cache.exists():
        try:
            have = pd.read_parquet(cache)
        except Exception:
            pass
    have["date"] = pd.to_datetime(have["date"])
    base = root / "bhavcopy"
    if not base.exists():
        return None
    files = {}
    for f in base.glob("*/*.parquet"):
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if start <= d <= end:
            files[d] = f
    done = set(have["date"].dt.date)
    todo = sorted(d for d in files if d not in done)
    if todo:
        new = []
        for k in range(0, len(todo), 400):
            chunk = todo[k:k + 400]
            lst = ",".join("'" + files[d].as_posix() + "'" for d in chunk)
            try:
                q = _duck.sql(f"SELECT CAST(date AS DATE) AS date, sum(CASE WHEN close > prev_close THEN 1 ELSE 0 END) AS adv, "
                              f"sum(CASE WHEN close < prev_close THEN 1 ELSE 0 END) AS dec FROM read_parquet([{lst}], union_by_name=true) "
                              "WHERE series = 'EQ' AND close > 0 AND prev_close > 0 AND close / prev_close BETWEEN 0.75 AND 1.30 GROUP BY 1").df()
            except Exception:
                continue
            new.append(q)
        if new:
            q = pd.concat(new, ignore_index=True)
            q["date"] = pd.to_datetime(q["date"])
            q["adv_share"] = q["adv"] / (q["adv"] + q["dec"]).replace(0, np.nan)
            have = pd.concat([have, q], ignore_index=True).drop_duplicates("date", keep="last").sort_values("date")
            if use_cache:
                try:
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    have.to_parquet(cache, index=False)
                except Exception:
                    pass
    s = have[(have["date"] >= pd.Timestamp(start)) & (have["date"] <= pd.Timestamp(end))]
    s = pd.Series(s["adv_share"].to_numpy(float), index=pd.DatetimeIndex(s["date"])).dropna()
    return s if len(s) else None


def positioning_frame(root, market: str, index: pd.DatetimeIndex, max_age_days: int = 4, with_breadth: bool = True) -> pd.DataFrame:
    """Columns pos_flow, pos_fut, pos_dii, pos_oi, pos_breadth on `index` (IN). NaN where a series does not exist or its last print is older than max_age_days."""
    idx = pd.DatetimeIndex(index)
    out = pd.DataFrame(index=idx, columns=["pos_flow", "pos_fut", "pos_dii", "pos_oi", "pos_breadth"], dtype=float)
    if market != "IN" or not len(idx):
        return out
    for col, s in (("pos_flow", fii_flow(root)), ("pos_fut", participant_net(root, "FII")), ("pos_dii", participant_net(root, "DII")), ("pos_oi", oi_buildup(root))):
        out[col] = stale_align(s, idx, max_age_days) if s is not None else np.nan
    if with_breadth:
        b = breadth_series(root, (idx.min() - pd.Timedelta(days=500)).date(), idx.max().date())
        out["pos_breadth"] = stale_align(b, idx, max_age_days) if b is not None else np.nan
    return out


def native(root, market: str, start: date, end: date, with_breadth: bool = True) -> dict:
    """{component: native series (its own dates)} for the positioning components that exist on this PC (IN only)."""
    if market != "IN":
        return {}
    out = {"pos_flow": fii_flow(root), "pos_fut": participant_net(root, "FII"), "pos_dii": participant_net(root, "DII"), "pos_dii_cash": dii_cash(root), "pos_oi": oi_buildup(root)}
    if with_breadth:
        out["pos_breadth"] = breadth_series(root, start, end)
    return {k: v for k, v in out.items() if v is not None and len(v)}


def dii_cash(root) -> Optional[pd.Series]:
    """DII net cash-market buying, Rs crore, from flows/FII_DII_CASH.parquet (the exchange's end-of-day figure; a SHORT history, so its z-score uses the short minimum)."""
    p = Path(root) / "flows" / "FII_DII_CASH.parquet"
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p, columns=["date", "dii_net_cr"])
    except Exception:
        return None
    s = pd.Series(pd.to_numeric(df["dii_net_cr"], errors="coerce").to_numpy(float), index=pd.to_datetime(df["date"])).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index() if len(s) else None
