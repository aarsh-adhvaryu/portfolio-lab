"""Forward test F5: the stress-gauge futures hedge, on paper (protocol docs/protocols/s65_hedge_forward_protocol.md, committed before the first forward session).

The gauge (ported from the investor's Q_Alpha_Research `regime/fragility.py`, its STRESS composite) is the mean of causal percentile ranks of eight cross-asset
stress measures, each computed only from data up to that day; US-market series are lagged a session because the US closes after India. While the gauge holds
>= 0.70 for 5 sessions a paper short of Nifty futures worth half the book is held (entered at the close after the gauge's day), with costs and F&O tax. The book is
Nifty 50 TRI. Kept daily from 2026-10-29; decided once (24 months and 2 completed episodes). The gauge is COINCIDENT: it describes stress, it does not forecast.
Nothing is traded. Layer: tool (numbers by code); the brain sees the gauge and the paper state as information only.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

START = date(2026, 10, 29)
TAU, PERSIST, H, LAG = 0.70, 5, 0.5, 2          # LAG: the first return the position earns is two sessions after the gauge's day
PCT_WINDOW, PCT_MIN, MOM, DD, CORR = 1000, 252, 21, 252, 63
COST_EVENT, COST_ROLL, FNO_TAX = 0.0003, 0.0005, 0.30
MIN_MONTHS, MIN_EPISODES, MAX_MONTHS = 24, 2, 60
DD_BETTER, RET_GIVE = 0.05, 0.01
NOTE = "information: a forward paper test (F5), not a recommendation; the gauge describes stress as it happens, it does not forecast"


def _series(df: pd.DataFrame, col: str) -> pd.Series:
    return df.assign(date=pd.to_datetime(df["date"])).set_index("date")[col].astype(float).sort_index()


def inputs(root: Path) -> pd.DataFrame:
    """The eight measures' raw series on Nifty 50 sessions; US-market series lagged one session (a value dated d is used after d)."""
    from pflab.data import global_markets as gm, indices, macro
    nifty = _series(indices.load("NIFTY50_PRICE", root), "close")
    idx = nifty.index
    out = pd.DataFrame(index=idx)
    out["nifty"] = nifty
    out["india_vix"] = _series(indices.load("INDIA_VIX", root), "close").reindex(idx, method="ffill")
    us = {"us_vix": ("global", "US_VIX", "close"), "move": ("global", "US_MOVE", "close"), "hyg": ("global", "US_HIGH_YIELD_HYG", "adj_close"),
          "lqd": ("global", "US_IG_CREDIT_LQD", "adj_close"), "dxy": ("global", "DOLLAR_INDEX", "close"), "sp500": ("global", "US_SP500", "close"),
          "usdinr": ("macro", "USDINR", "value")}
    for name, (where, key, col) in us.items():
        try:
            s = _series(gm.load(key, root) if where == "global" else macro.load(key, root), col).dropna()
        except Exception:
            continue
        s.index = s.index + pd.Timedelta(days=1)                       # usable from the next calendar day: never the same Indian session
        out[name] = s[~s.index.duplicated(keep="last")].reindex(idx, method="ffill")
    return out


def _pct(s: pd.Series) -> pd.Series:
    return s.rolling(PCT_WINDOW, min_periods=PCT_MIN).apply(lambda a: float((a <= a[-1]).mean()), raw=True)


def _dd(s: pd.Series) -> pd.Series:
    return s / s.rolling(DD, min_periods=1).max() - 1.0


def gauge(p: pd.DataFrame) -> pd.Series:
    """The STRESS composite in [0, 1]: the mean of whichever measures have history that day."""
    f = {}
    for c in ("us_vix", "move", "india_vix"):
        if c in p:
            f[c] = _pct(p[c])
    if "hyg" in p and "lqd" in p:
        f["credit"] = _pct(-_dd(p["hyg"] / p["lqd"]))
    for c in ("usdinr", "dxy"):
        if c in p:
            f[c] = _pct(p[c].pct_change(MOM, fill_method=None))
    f["drawdown"] = _pct(-_dd(p["nifty"]))
    if "sp500" in p:
        f["contagion"] = _pct(p["nifty"].pct_change(fill_method=None).rolling(CORR).corr(p["sp500"].pct_change(fill_method=None)))
    return pd.DataFrame(f).mean(axis=1, skipna=True).rename("gauge")


def state(g: pd.Series, tau: float = TAU, persist: int = PERSIST) -> pd.Series:
    """On after `persist` sessions at or above `tau`; off on the first session below. Uses only past and present values."""
    above = (g >= tau).fillna(False)
    streak = above.rolling(persist, min_periods=persist).sum() == persist
    on, out = False, []
    for ab, st in zip(above.to_numpy(), streak.to_numpy()):
        on = False if not ab else (True if st else on)
        out.append(on)
    return pd.Series(out, index=g.index, name="on")


def paper(book_ret: pd.Series, idx_ret: pd.Series, on: pd.Series, h: float = H, lag: int = LAG) -> dict:
    """Hedged and unhedged equity (1.0 at the start), with costs at entry, exit and month-end rolls and F&O tax on each episode's net gain."""
    idx = book_ret.index
    pos = on.reindex(idx).fillna(False).astype(bool).shift(lag).fillna(False).astype(bool)
    ir, br = idx_ret.reindex(idx).fillna(0.0), book_ret.fillna(0.0)
    month_end = idx.to_series().groupby(idx.to_period("M")).transform("max") == idx.to_series()
    pv, pu, prev, ep_pnl = 1.0, 1.0, False, 0.0
    hedged, plain = [], []
    cost = tax = 0.0
    started = completed = 0
    for t in idx:
        p_on = bool(pos.loc[t])
        hr = -h * float(ir.loc[t]) if p_on else 0.0
        before = pv
        pv *= 1.0 + float(br.loc[t]) + hr
        pu *= 1.0 + float(br.loc[t])
        ep_pnl += hr * before
        notional = h * pv
        if p_on != prev:
            c = COST_EVENT * notional
            pv -= c
            cost += c
            started += p_on
        if p_on and bool(month_end.loc[t]):
            pv -= COST_ROLL * notional
            cost += COST_ROLL * notional
        if prev and not p_on:
            t_ = FNO_TAX * max(0.0, ep_pnl)
            pv -= t_
            tax += t_
            ep_pnl = 0.0
            completed += 1
        prev = p_on
        hedged.append(pv)
        plain.append(pu)
    return {"hedged": pd.Series(hedged, index=idx), "plain": pd.Series(plain, index=idx), "episodes": started, "completed": completed,
            "cost": cost, "tax": tax, "on_now": bool(pos.iloc[-1]) if len(pos) else False}


def _max_dd(eq: pd.Series) -> float:
    return float((eq / eq.cummax() - 1.0).min()) if len(eq) else 0.0


def _ann(eq: pd.Series) -> float:
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25 if len(eq) > 1 else 0.0
    return float(eq.iloc[-1] ** (1 / yrs) - 1) if yrs > 0 else 0.0


def forward(root: Path, upto: Optional[date] = None) -> dict:
    """The paper record from START: gauge and state for every session (the state needs the gauge's history before START), equity from START."""
    from pflab.data import indices
    p = inputs(root)
    g = gauge(p)
    s = state(g)
    tri = _series(indices.load("NIFTY50_TRI", root), "close").reindex(p.index).ffill()
    if upto is not None:
        g, s, tri, p = g[g.index <= pd.Timestamp(upto)], s[s.index <= pd.Timestamp(upto)], tri[tri.index <= pd.Timestamp(upto)], p[p.index <= pd.Timestamp(upto)]
    keep = tri.index >= pd.Timestamp(START)
    out = {"gauge_now": None if g.dropna().empty else round(float(g.dropna().iloc[-1]), 3), "state_now": bool(s.iloc[-1]) if len(s) else False,
           "asof": str(g.index[-1].date()) if len(g) else None}
    if keep.sum() < 2:
        out.update(sessions=int(keep.sum()), note=NOTE)
        return out
    rec = paper(tri.pct_change(fill_method=None)[keep], p["nifty"].pct_change(fill_method=None)[keep], s[keep])
    out.update(sessions=int(keep.sum()), episodes=rec["episodes"], completed=rec["completed"], on_paper=rec["on_now"],
               hedged=round(float(rec["hedged"].iloc[-1]), 4), plain=round(float(rec["plain"].iloc[-1]), 4),
               max_dd_hedged=round(_max_dd(rec["hedged"]), 4), max_dd_plain=round(_max_dd(rec["plain"]), 4),
               ann_hedged=round(_ann(rec["hedged"]), 4), ann_plain=round(_ann(rec["plain"]), 4), note=NOTE)
    return out


def _months(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month)


def cycle(con, root: Path, now: datetime) -> dict:
    """Nightly: count F5 in the learner's counter (once); decide once when the protocol's conditions hold at a month-end; else report the state."""
    from pflab.learner import counter, live
    if not con.execute("SELECT 1 FROM learn_tests WHERE note='forward:F5'").fetchone():
        counter.record(con, now, "study", "forward_stress_hedge", {"claim": "F5", "tau": TAU, "persist": PERSIST, "h": H}, note="forward:F5")
    row = con.execute("SELECT test_id, passed, t_dev FROM learn_tests WHERE note='forward:F5'").fetchone()
    last_me = (pd.Timestamp(now.date()).to_period("M").start_time - pd.Timedelta(days=1)).date()        # the last month-end before today
    months = _months(START, last_me)
    if row[1] is not None or months < MIN_MONTHS:
        return {"decided": row[1] is not None, "months": max(months, 0)}
    rec = forward(root, upto=last_me)
    if rec.get("completed", 0) < MIN_EPISODES:
        if months < MAX_MONTHS:
            return {"decided": False, "months": months, "waiting_for": "a second completed hedge episode"}
        con.execute("UPDATE learn_tests SET passed=false, n_dev=?, note='forward:F5' WHERE test_id=?", [rec.get("completed", 0), row[0]])
        return {"decided": True, "passed": False, "why": "not enough stress to judge within 60 months"}
    ok = rec["max_dd_hedged"] >= rec["max_dd_plain"] + DD_BETTER and rec["ann_hedged"] >= rec["ann_plain"] - RET_GIVE
    con.execute("UPDATE learn_tests SET passed=?, n_dev=? WHERE test_id=?", [ok, rec["completed"], row[0]])
    if ok:
        live.put(con, "finding", "forward:F5",
                 f"The stress-gauge hedge held forward on paper: worst fall {rec['max_dd_hedged']:.0%} hedged vs {rec['max_dd_plain']:.0%} unhedged, "
                 f"{rec['ann_hedged']:.1%} vs {rec['ann_plain']:.1%} a year, {rec['completed']} episodes since {START} (protocol s65_hedge_forward). "
                 "A hedge plan may be proposed for his yes; nothing is traded.", json.dumps({"claim": "F5"}), "forward F5", now)
    return {"decided": True, "passed": ok, **{k: rec[k] for k in ("max_dd_hedged", "max_dd_plain", "ann_hedged", "ann_plain", "completed")}}
