"""S54e: the Simulations screen. The current mix, the target mix and a what-if mix, each over 1-5 years by a circular
block bootstrap of the joint history (`risk.montecarlo`), up to 100,000 paths, every figure with its error:

    fan          the value of 1 rupee each month: p5, p25, p50, p75, p95
    fall         the chance of a fall beyond the 35% limit on any session (daily one-year blocks), its standard error,
                 shown under the small-numbers rule (`calc.smalln.tail`)
    medians      the median value at 1, 3 and 5 years with a batch-means standard error (10 batches of paths)
    stress       each mix replayed through dated episodes in the history (what it would have done then), and its own
                 worst fall in the whole history with the dates
    frontier     random mixes of the five investable assets: annual return, volatility, worst fall on any session

Two stock assets: "mine" is the investor's own stocks at today's names and weights (their total returns from the panel: adjusted
closes and dividends; before a stock listed, the equal-weight Nifty 500 stands in, and the share of the history that is
his stocks' own is shown); "stocks" is the equal-weight Nifty 500 (survivorship-free), kept as the comparison. Your mix
today and the stock part of the target mix use "mine" (The investor 2026-10-23). Estimates from one history, named beside them.
"""
from __future__ import annotations

import json
import math
import threading
from datetime import date
from typing import Dict, Optional

import numpy as np
import pandas as pd

PATHS = (10_000, 100_000)
CHUNK = 10_000
BATCHES = 10
FRONTIER_N = 3000
FRONTIER_SHOW = 1200
EPISODES = (("2008 global financial crisis", "2008-01-01", "2009-03-31"),
            ("2011 euro crisis", "2010-11-01", "2011-12-31"),
            ("2013 taper tantrum", "2013-05-15", "2013-08-31"),
            ("2015-16 slowdown", "2015-03-01", "2016-02-29"),
            ("2018-19 mid and small cap fall", "2018-01-01", "2019-08-31"),
            ("2020 Covid crash", "2020-01-15", "2020-03-31"),
            ("2024-25 correction", "2024-09-27", "2025-03-31"))
_RUN = threading.Lock()


ASSETS = ("mine", "stocks", "n500", "mom50", "gold", "debt", "cash")


def stock_weights(con, asof: date) -> Dict[str, float]:
    """Today's stocks (the equity bucket) by value, summing to 1."""
    from pflab.pm import today
    pos = today.build(con, asof)["positions"]
    eq = pos[(pos["bucket"] == "equity") & pos["value"].notna()].groupby("isin")["value"].sum()
    eq = eq[eq > 0]
    return (eq / eq.sum()).to_dict() if len(eq) else {}


def mine_daily(root, weights: Dict[str, float], proxy: pd.Series) -> tuple:
    """Daily total return of the stocks at fixed weights (rebalanced daily) on the proxy's sessions; a stock's own
    return where it has one, the proxy before it listed. Returns the series and the weighted share that is its own."""
    from pflab import _duck
    if not weights:
        return proxy.copy(), 0.0
    isins = ",".join(repr(i) for i in weights)
    px = _duck.sql(f"select date, isin, close, adj_close, dividend from '{root}/panel/prices.parquet' "
                    f"where isin in ({isins}) and date >= DATE '2006-12-01'").df()
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values(["isin", "date"])
    px["r"] = px.groupby("isin")["adj_close"].pct_change()
    px["r"] = (1 + px["r"]) * (1 + (px["dividend"].fillna(0.0) / px["close"]).where(px["close"] > 0, 0.0)) - 1
    r = px.dropna(subset=["r"]).pivot(index="date", columns="isin", values="r").reindex(proxy.index)
    out = pd.Series(0.0, index=proxy.index)
    own = 0.0
    for isin, w in weights.items():
        x = r[isin] if isin in r.columns else pd.Series(np.nan, index=proxy.index)
        first = x.first_valid_index()
        listed = proxy.index >= first if first is not None else np.zeros(len(proxy), bool)
        x = x.where(~listed | x.notna(), 0.0)                            # a listed day without a trade: no change
        out += w * x.where(listed, proxy).fillna(0.0)
        own += w * float(listed.mean())
    return out, own


def history(con, root, asof: date) -> tuple:
    """The simulator's monthly and daily histories with "mine" added, and what share of it is his stocks' own."""
    from pflab.risk import montecarlo as mc
    R, Rd = mc.history(root), mc.history_daily(root)
    weights = stock_weights(con, asof)
    d, own = mine_daily(root, weights, Rd["stocks"])
    Rd = Rd.assign(mine=d)[list(ASSETS)]
    m = (1 + d).groupby(d.index.to_period("M")).prod() - 1               # by calendar month, as R's month-ends
    R = R.assign(mine=m.reindex(R.index.to_period("M")).to_numpy())
    R["mine"] = R["mine"].fillna(R["stocks"])
    return R[list(ASSETS)], Rd, {"names": len(weights), "own_share": own}


def weights(mix: Dict[str, float]) -> np.ndarray:
    w = np.array([mix.get(a, 0.0) for a in ASSETS])
    if abs(w.sum() - 1) > 1e-9:
        raise ValueError(f"weights sum to {w.sum():.4f}")
    return w


def point(R: pd.DataFrame, Rd: pd.DataFrame, w: np.ndarray) -> dict:
    """Annual return, volatility and the worst fall on any session the mix actually had over the history."""
    port = R.values @ w
    v = np.concatenate([[1.0], np.cumprod(1 + Rd.values @ w)])
    return {"ret": float(np.prod(1 + port) ** (12 / len(port)) - 1), "vol": float(port.std(ddof=1) * np.sqrt(12)),
            "worst_fall_any_day": float((v / np.maximum.accumulate(v) - 1).min())}


def current_mix(con, asof: date) -> Dict[str, float]:
    """Today's holdings as the simulator's assets: stocks as "mine", funds as the Nifty 500, cash with debt."""
    from pflab.pm import today
    b = today.build(con, asof)["buckets"]
    from pflab.ledger import system
    if system.active():                                   # S77: the system's account holds no FDs and no debt: its cash is cash (the simulator's cash-like series carries it)
        b = {**b, "cash": b.get("cash", 0) + b.get("debt", 0), "debt": 0}
    inv = sum(v for k, v in b.items() if k in MAPPED) or 1.0     # (2026-10-31) a bucket the simulator has no series for (`review`) is left out and
    return {"mine": b.get("equity", 0) / inv, "stocks": 0.0, "n500": b.get("equity_fund", 0) / inv, "mom50": 0.0,     # named, never a crash
            "gold": b.get("gold", 0) / inv, "debt": (b.get("debt", 0) + (0 if system.active() else b.get("cash", 0))) / inv,
            "cash": (b.get("cash", 0) / inv) if system.active() else 0.0}


MAPPED = ("equity", "equity_fund", "gold", "debt", "cash")


def left_out(con, asof: date) -> Dict[str, float]:
    """Buckets the simulator cannot model (an instrument still to be classified, say), as rupees."""
    from pflab.pm import today
    return {k: float(v) for k, v in today.build(con, asof)["buckets"].items() if k not in MAPPED and v}


def invested(con, asof: date) -> float:
    from pflab.pm import today
    return float(sum(today.build(con, asof)["buckets"].values()))


def target_mix(con) -> Optional[Dict[str, float]]:
    from pflab.ledger import system
    if system.active():                                   # S77: no targets of his: the system's own limits are rails, not a target mix
        return None
    from pflab.plan import targets as tg
    from pflab.risk import montecarlo as mc
    try:
        t = tg.load()
        m = mc.target_mix(t, mc.fund_names(con, t))
    except Exception:
        return None
    m["mine"], m["stocks"] = m.get("stocks", 0.0), 0.0                  # the stock part held as his own names
    return m


def clean_mix(m: Dict[str, float]) -> Dict[str, float]:
    w = {a: max(0.0, float(m.get(a, 0) or 0)) for a in ASSETS}
    s = sum(w.values())
    if s <= 0:
        raise ValueError("the mix is empty")
    return {a: v / s for a, v in w.items()}


def fan(R: np.ndarray, w: np.ndarray, months: int, paths: int, rng: np.random.Generator) -> dict:
    """Monthly percentiles of the value of 1 rupee, and the 1/3/5-year medians with batch-means errors."""
    from pflab.risk import montecarlo as mc
    v = np.empty((paths, months))
    for s in range(0, paths, CHUNK):
        m = min(CHUNK, paths - s)
        v[s:s + m] = mc.mix_values(mc.block_paths(R, months, m, rng), w)
    q = np.percentile(v, [5, 25, 50, 75, 95], axis=0)
    out = {"months": months, "p5": q[0].tolist(), "p25": q[1].tolist(), "p50": q[2].tolist(), "p75": q[3].tolist(),
           "p95": q[4].tolist(), "p_loss_at_end": float(np.mean(v[:, -1] < 1)),
           "median_cagr": float(q[2][-1] ** (12 / months) - 1), "years": {}}
    for y in (1, 3, 5):
        if 12 * y <= months:
            x = v[:, 12 * y - 1]
            med = [float(np.median(b)) for b in np.array_split(x, BATCHES)]
            out["years"][str(y)] = {"p5": float(np.percentile(x, 5)), "p50": float(np.median(x)),
                                    "p95": float(np.percentile(x, 95)),
                                    "se_p50": float(np.std(med, ddof=1) / math.sqrt(BATCHES))}
    return out


def stress(Rd: pd.DataFrame, w: np.ndarray) -> dict:
    """The mix through each dated episode the history covers, and its own worst fall with the dates."""
    r = pd.Series(Rd.values @ w, index=Rd.index)
    v = (1 + r).cumprod()
    out = []
    for name, a, b in EPISODES:
        x = r[(r.index >= a) & (r.index <= b)]
        if len(x) < 10 or Rd.index[0] > pd.Timestamp(a):
            out.append({"name": name, "from": a, "to": b, "covered": False})
            continue
        lv = (1 + x).cumprod()
        dd = lv / np.maximum.accumulate(np.concatenate([[1.0], lv.values]))[1:] - 1
        out.append({"name": name, "from": a, "to": b, "covered": True, "return": float(lv.iloc[-1] - 1),
                    "worst_fall": float(min(dd.min(), 0.0))})
    peak = v.cummax()
    dd = v / peak - 1
    trough = dd.idxmin()
    start = v[:trough].idxmax()
    back = v[trough:][v[trough:] >= v[start]]
    return {"episodes": out, "worst": {"fall": float(dd.min()), "peak": str(start.date()), "trough": str(trough.date()),
                                       "recovered": str(back.index[0].date()) if len(back) else None}}


def run(rt, paths: int = 10_000, years: int = 5, custom: Optional[Dict[str, float]] = None, seed: int = 20261023) -> dict:
    """Every mix, saved for the screen (pm/app/cache/sims.json). One run at a time."""
    from pflab.calc import smalln
    from pflab.risk import montecarlo as mc
    if paths not in PATHS:
        raise ValueError(f"paths must be one of {PATHS}")
    if not 1 <= years <= 5:
        raise ValueError("years must be 1 to 5")
    if not _RUN.acquire(blocking=False):
        raise RuntimeError("a simulation is already running")
    try:
        rt.sims_running = True
        rt.bump("sims")
        now = rt.clock()
        con = rt.cursor()
        R, Rd, info = history(con, rt.data_root, now.date())
        mixes = {"current": current_mix(con, now.date())}
        t = target_mix(con)
        if t:
            mixes["target"] = t
        if custom:
            mixes["what-if"] = clean_mix(custom)
        rng = np.random.default_rng(seed)
        X, Xd = R.values, Rd.values
        out_mixes = {}
        for name, mix in mixes.items():
            w = weights(mix)
            p = mc.fall_any_day_block(Xd, w, 12 * years, paths, rng)
            out_mixes[name] = {"mix": mix, "fan": fan(X, w, 12 * years, paths, rng),
                               "fall": {"p": p, **smalln.tail(p, paths)}, "stress": stress(Rd, w),
                               "point": point(R, Rd, w)}
        fr = mc.frontier(R, FRONTIER_N, Rd=Rd[list(mc.ASSETS)])
        show = fr.sample(min(FRONTIER_SHOW, len(fr)), random_state=1)
        out = {"at": now.isoformat(timespec="seconds"), "paths": paths, "years": years, "mixes": out_mixes,
               "history": f"{R.index[0]:%b %Y} to {R.index[-1]:%b %Y} (monthly), daily from {Rd.index[0]:%b %Y}",
               "invested": invested(con, now.date()), "mine": info,
               "frontier": show[["ret", "vol", "worst_fall_any_day", *mc.FRONTIER_ASSETS]].round(4).to_dict("records")}
        p_ = path(rt)
        p_.parent.mkdir(parents=True, exist_ok=True)
        p_.write_text(json.dumps(out), encoding="utf-8")
        return out
    finally:
        rt.sims_running = False
        _RUN.release()
        rt.bump("sims")


def path(rt):
    return rt.pm_dir / "app" / "cache" / "sims.json"


def cached(rt) -> Optional[dict]:
    p = path(rt)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except ValueError:
        return None
