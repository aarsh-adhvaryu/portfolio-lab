"""S85 replay3: choose the three episodes BY CODE from the stored data (workshop data folder, read only), and write down which and why.

    python tools/replays_s85_select.py            # prints the choices as JSON and writes S85_REPLAY_OUT/selection.json

(1) ROTATION: from the stored NSE bars (the panel) and the stored industry of the Nifty 500 members (index_membership/sector_map): equal-weight industry baskets (at least 6 members that traded through the
    window); the window is a run of 10 sessions in which one basket FELL at least 5 points and another ROSE at least 5 points, both against the Nifty 500 total return index flat (within 1.5 points); the
    pick is the window with the largest min(fall, rise). Feb to Jun 2020 is left out (it is the third replay). The name the wide watch should notice is the basket's member with the largest 5-session
    gain against the index inside the rising basket.
(2) GOVERNANCE: from the stored red-flag events (`red_flag_events`: FRAUD, FORENSIC_AUDIT, REGULATORY_ACTION, AUDITOR_RESIGNATION with a headline and a usable_from time): the event followed by the largest fall of
    the name over the next 5 stored sessions (no gap of more than 9 calendar days in them) among names with a large daily traded value (the median over the 60 sessions before it) and at least 250 sessions of history; the kind is the stored flag.
(3) MARCH 2020: the Nifty 500 total return index's 20-session fall first beyond 10% (the watch's market line) from the stored index; the window runs from 20 sessions before to the 25th session after.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(os.environ.get("S85_REAL_DATA", r"D:\portfolio_lab\data"))
OUT = Path(os.environ.get("S85_REPLAY_OUT", r"D:\s85_scratch\replay3\out"))


def _panel(isins=None, lo="2009-06-01", hi="2026-11-06") -> pd.DataFrame:
    filt = [("date", ">=", pd.Timestamp(lo).date()), ("date", "<=", pd.Timestamp(hi).date())]
    if isins is not None:
        filt.append(("isin", "in", list(isins)))
    p = pd.read_parquet(DATA / "panel" / "prices.parquet", columns=["date", "isin", "symbol", "series", "close", "adj_close", "turnover"], filters=filt)
    p = p[p["series"].isin(["EQ", "BE", "SM"]) | p["series"].isna()] if "series" in p else p
    p["date"] = pd.to_datetime(p["date"])
    return p


def _index() -> pd.Series:
    ix = pd.read_parquet(DATA / "indices" / "NIFTY500_TRI.parquet")
    ix["date"] = pd.to_datetime(ix["date"])
    return ix.set_index("date")["close"].sort_index()


def select_rotation(min_members: int = 6) -> dict:
    sm = pd.read_parquet(DATA / "index_membership" / "sector_map.parquet")
    sm = sm[sm["index"].isin(["NIFTY500", "NIFTY200", "NIFTY100"])].sort_values("capture_date")
    ind = sm.drop_duplicates("isin", keep="last").set_index("isin")["industry"]
    p = _panel(list(ind.index), lo="2012-01-01")
    px = p.pivot_table(index="date", columns="isin", values="adj_close", aggfunc="last").sort_index()
    ix = _index().reindex(px.index).ffill()
    best = None
    h = 10
    ret = px / px.shift(h) - 1.0
    rix = ix / ix.shift(h) - 1.0
    liquid = p.groupby("isin")["turnover"].median()
    for d in ret.index[h::5]:
        if date(2020, 2, 1) <= d.date() <= date(2020, 6, 30) or pd.isna(rix.loc[d]) or abs(rix.loc[d]) > 0.015:
            continue
        r = ret.loc[d].dropna()
        g = pd.DataFrame({"r": r, "ind": ind.reindex(r.index)}).dropna()
        b = g.groupby("ind")["r"].agg(["mean", "count"])
        b = b[b["count"] >= min_members]
        if len(b) < 2:
            continue
        fall, rise = b["mean"].idxmin(), b["mean"].idxmax()
        f, u = float(b.loc[fall, "mean"]), float(b.loc[rise, "mean"])
        if f <= -0.05 and u >= 0.05:
            score = min(-f, u)
            if best is None or score > best["score"]:
                best = {"score": score, "end": d, "fall": fall, "rise": rise, "fall_pct": f, "rise_pct": u, "n_fall": int(b.loc[fall, "count"]), "n_rise": int(b.loc[rise, "count"]), "index_10d": float(rix.loc[d])}
    if best is None:
        return {}
    end = best["end"]
    i_end = list(px.index).index(end)
    start = px.index[i_end - h]
    mem = lambda name: [i for i in ind.index[ind == name] if i in px.columns and px[i].iloc[i_end - h:i_end + 1].notna().all()]  # noqa: E731
    rise_m, fall_m = mem(best["rise"]), mem(best["fall"])
    r5 = (px.iloc[i_end] / px.iloc[i_end - 5] - 1.0) - float(ix.iloc[i_end] / ix.iloc[i_end - 5] - 1.0)
    win = p[(p["date"] >= start) & (p["date"] <= end)]
    liq = win.groupby("isin")["turnover"].median()                         # the liquid names of each basket: a replay of thinly traded names would prove nothing about the loop
    rise_m = list(liq.reindex(rise_m).dropna().sort_values(ascending=False).head(6).index)
    fall_m = list(liq.reindex(fall_m).dropna().sort_values(ascending=False).head(6).index)
    pick = r5.reindex(rise_m).dropna().sort_values(ascending=False)
    syms = p.drop_duplicates("isin", keep="last").set_index("isin")["symbol"]
    falls = (px.iloc[i_end] / px.iloc[i_end - h] - 1.0).reindex(fall_m).dropna().sort_values()
    return {"window_start": str(start.date()), "window_end": str(end.date()), "sessions": h, "falling_industry": best["fall"], "falling_pct": round(100 * best["fall_pct"], 1), "falling_members": best["n_fall"],
            "rising_industry": best["rise"], "rising_pct": round(100 * best["rise_pct"], 1), "rising_members": best["n_rise"], "nifty500_tri_10d_pct": round(100 * best["index_10d"], 2),
            "why": "the largest min(fall, rise) among 10-session windows with the index flat (within 1.5 points), baskets of at least 6 members, Feb-Jun 2020 left out; the names are the six most liquid of each basket, the wide target the one of them with the largest 5-session gain against the index",
            "wide_target": {"isin": pick.index[0], "symbol": str(syms.get(pick.index[0])), "rel_5d_pct": round(100 * float(pick.iloc[0]), 1)},
            "rising_names": [{"isin": i, "symbol": str(syms.get(i)), "rel_5d_pct": round(100 * float(v), 1)} for i, v in pick.head(6).items()],
            "falling_names": [{"isin": i, "symbol": str(syms.get(i)), "pct_10d": round(100 * float(v), 1)} for i, v in falls.head(6).items()]}


def select_governance() -> dict:
    ev = pd.read_parquet(DATA / "red_flag_events" / "events.parquet")
    ev = ev[ev["flag"].isin(["FRAUD", "FORENSIC_AUDIT", "REGULATORY_ACTION", "AUDITOR_RESIGNATION"]) & ev["isin"].notna() & ev["usable_from"].notna()].copy()
    ev["usable_from"] = pd.to_datetime(ev["usable_from"])
    ev = ev[(ev["usable_from"] >= "2012-01-01") & (ev["usable_from"] <= "2026-06-30")]
    p = _panel(list(ev["isin"].unique()), lo="2011-01-01")
    px = p.pivot_table(index="date", columns="isin", values="close", aggfunc="last").sort_index()
    tv = p.pivot_table(index="date", columns="isin", values="turnover", aggfunc="last").sort_index()
    rows = []
    for e in ev.itertuples(index=False):
        if e.isin not in px.columns:
            continue
        s = px[e.isin].dropna()
        if len(s) < 250:
            continue
        pos = s.index.searchsorted(pd.Timestamp(e.usable_from).normalize(), side="right")          # the first close AFTER the event time: the first session the event can act on
        if pos < 60 or pos + 5 >= len(s):
            continue
        if (s.index[pos + 4] - s.index[pos - 1]).days > 9 or (pd.Timestamp(e.usable_from).normalize() - s.index[pos - 1]).days > 4:      # the stored closes must run through the five sessions after the event (a name that left the feed would otherwise count weeks as five sessions)
            continue
        base = float(s.iloc[pos - 1])
        fall5 = float(s.iloc[pos + 4] / base - 1.0)
        med_tv = float(tv[e.isin].dropna().iloc[max(0, pos - 60):pos].median()) if e.isin in tv.columns else 0.0
        rows.append({"isin": e.isin, "company": e.company, "flag": e.flag, "usable_from": str(e.usable_from), "headline": str(e.headline)[:200], "category": e.category, "fall_5": fall5, "median_turnover": med_tv, "day0": str(s.index[pos - 1].date()), "key_source": e.key_source})
    df = pd.DataFrame(rows)
    big = df[df["median_turnover"] >= df["median_turnover"].quantile(0.5)]
    top = big.sort_values("fall_5").head(8)
    pick = top.iloc[0].to_dict()
    return {"event": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in pick.items()}, "why": "the stored governance/regulatory flag event with the largest 5-session fall after it among names with above-median traded value and 250 sessions of history",
            "runners_up": [{"company": r.company, "flag": r.flag, "usable_from": r.usable_from, "fall_5": round(r.fall_5, 3)} for r in top.iloc[1:].itertuples()]}


def select_march2020() -> dict:
    ix = _index()
    r20 = ix / ix.shift(20) - 1.0
    hit = r20[(r20 <= -0.10) & (r20.index >= "2020-01-01")].index[0]
    i = list(ix.index).index(hit)
    return {"first_line_crossed": str(hit.date()), "fall_20d_pct": round(100 * float(r20.loc[hit]), 1), "window_start": str(ix.index[i - 20].date()), "window_end": str(ix.index[min(i + 25, len(ix) - 1)].date()),
            "trough_close_day": str(ix.loc["2020-03-01":"2020-04-30"].idxmin().date()), "why": "the first session the 20-session fall of the stored Nifty 500 TRI passes the watch's 10% line"}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"rotation": select_rotation(), "governance": select_governance(), "march2020": select_march2020()}
    (OUT / "selection.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    print(json.dumps(res, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
