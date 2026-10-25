"""Event-study template (S46): how stocks moved after a kind of exchange filing, against the Nifty 500.

An event is a BSE filing, dated by its dissemination time: before 15:30 the event session is that day, after it the
next session (point in time). The abnormal return of a session is the stock's return minus the Nifty 500 TRI's; the
cumulative abnormal return CAR[0, k] adds sessions 0..k. Results are history, never a forecast, and a template run is
exploratory: a rule built on one needs its own pre-registration.
"""
from __future__ import annotations

import glob
import re
from datetime import datetime, time
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from pflab import _duck
import numpy as np
import pandas as pd

WINDOWS = (1, 5, 20)
CLOSE = time(15, 30)


def events(root: Path, start: str, end: str, subcategories: Sequence[str] = (), headline_regex: str = "",
           isins: Optional[Sequence[str]] = None) -> pd.DataFrame:
    """Filings in [start, end] matching the subcategories or the headline pattern: isin, t (dissemination), headline."""
    from pflab.data import bse_scrip_isin
    from pflab.monitor.filings import resolve_isins
    fs = glob.glob(str(root / "bse_announcements" / "**" / "*.parquet"), recursive=True)
    if not fs:
        return pd.DataFrame(columns=["isin", "t", "headline", "subcategory"])
    conds = []
    if subcategories:
        conds.append("subcategory in (" + ",".join("'" + s.replace("'", "''") + "'" for s in subcategories) + ")")
    if headline_regex:
        conds.append("regexp_matches(lower(headline), '" + headline_regex.lower().replace("'", "''") + "')")
    where = " or ".join(conds) or "true"
    df = _duck.sql(f"""select scrip_code, headline, subcategory, coalesce(dissem_dt, news_dt) t
                        from read_parquet({fs!r}, union_by_name=true)
                        where coalesce(dissem_dt, news_dt) between TIMESTAMP '{start}' and TIMESTAMP '{end} 23:59:59'
                          and ({where})""").df()
    if df.empty:
        return pd.DataFrame(columns=["isin", "t", "headline", "subcategory"])
    df["isin"] = resolve_isins(df.rename(columns={"t": "t"}), bse_scrip_isin.load(root))
    df = df.dropna(subset=["isin"])
    if isins is not None:
        df = df[df["isin"].isin(set(isins))]
    return df.drop_duplicates(["isin", "t"])[["isin", "t", "headline", "subcategory"]].reset_index(drop=True)


def returns(root: Path, isins: Sequence[str], start: str, end: str) -> pd.DataFrame:
    """Wide daily total returns (adjusted, dividends added) for `isins`, sessions in [start, end]."""
    px = _duck.sql(f"""select date, isin, close, adj_close, dividend from '{root}/panel/prices.parquet'
                        where isin in ({','.join(repr(i) for i in isins) or "''"})
                          and date between DATE '{start}' - INTERVAL 10 DAY and DATE '{end}' + INTERVAL 60 DAY""").df()
    if px.empty:
        return pd.DataFrame()
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values(["isin", "date"])
    r = px.groupby("isin")["adj_close"].pct_change()
    px["r"] = (1 + r) * (1 + (px["dividend"].fillna(0.0) / px["close"]).where(px["close"] > 0, 0.0)) - 1
    return px.pivot(index="date", columns="isin", values="r")


def cars(ev: pd.DataFrame, rets: pd.DataFrame, market: pd.Series, windows: Sequence[int] = WINDOWS) -> pd.DataFrame:
    """CAR[0, k] per event (market-adjusted). Events without enough sessions after them are dropped."""
    sessions = rets.index
    m = market.reindex(sessions)
    rows = []
    for e in ev.itertuples():
        t = pd.Timestamp(e.t)
        day = t.normalize() if t.time() < CLOSE else t.normalize() + pd.Timedelta(days=1)
        i = sessions.searchsorted(day)
        if e.isin not in rets.columns or i + max(windows) >= len(sessions):
            continue
        ar = (rets[e.isin].iloc[i:i + max(windows) + 1] - m.iloc[i:i + max(windows) + 1]).to_numpy()
        if np.isnan(ar).any():
            continue
        rows.append({"isin": e.isin, "t": t, "headline": e.headline,
                     **{f"car_{k}": float(ar[:k + 1].sum()) for k in windows}})
    return pd.DataFrame(rows)


def summary(c: pd.DataFrame, windows: Sequence[int] = WINDOWS) -> Dict[str, dict]:
    out = {}
    for k in windows:
        x = c[f"car_{k}"].dropna() if len(c) else pd.Series(dtype=float)
        sd = x.std(ddof=1) if len(x) > 1 else float("nan")
        out[f"CAR[0,{k}]"] = {"n": int(len(x)), "mean": float(x.mean()) if len(x) else float("nan"),
                              "median": float(x.median()) if len(x) else float("nan"),
                              "t": float(x.mean() / (sd / np.sqrt(len(x)))) if len(x) > 1 and sd > 0 else float("nan"),
                              "share_up": float((x > 0).mean()) if len(x) else float("nan")}
    return out


def market(root: Path) -> pd.Series:
    from pflab.data import indices
    df = indices.load("NIFTY500_TRI", root)
    return df.assign(date=pd.to_datetime(df["date"])).set_index("date")["close"].sort_index().pct_change()


def run(root: Path, start: str, end: str, subcategories: Sequence[str] = (), headline_regex: str = "",
        isins: Optional[Sequence[str]] = None) -> dict:
    ev = events(root, start, end, subcategories, headline_regex, isins)
    if ev.empty:
        return {"events": 0, "summary": summary(pd.DataFrame()), "cars": pd.DataFrame()}
    rets = returns(root, sorted(set(ev["isin"])), start, end)
    c = cars(ev, rets, market(root)) if len(rets) else pd.DataFrame()
    return {"events": int(len(ev)), "summary": summary(c), "cars": c}


def render(res: dict, label: str) -> str:
    L = [f"{label}: {res['events']} filing(s) found; market-adjusted moves after them (history, not a forecast):"]
    for k, s in res["summary"].items():
        if s["n"]:
            L.append(f"  {k}: mean {s['mean']:+.2%}, median {s['median']:+.2%}, up in {s['share_up']:.0%} of {s['n']} "
                     f"(t {s['t']:.1f})")
    if len(L) == 1:
        L.append("  too few usable events")
    return "\n".join(L)
