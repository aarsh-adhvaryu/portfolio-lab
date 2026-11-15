"""S89b: the Lab's Simulate and Forecast, the one-stock page and the reliability numbers. Every figure is worked out by existing code (the block bootstrap of `risk/montecarlo.py`, the stored forecasts and
their scores, the stored candles, the exit plans, the thinking loop's calibration); nothing here calls a model ("worked out by the Lab tools, 0 tokens") and nothing is invented: a scenario the code has no
preset for is "not built yet".
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

HORIZONS = (20, 60, 250)
SCENARIOS = {"normal": "Normal: the history, resampled", "covid": "March 2020 again", "rates": "Rates up 1%"}
COVID = ("2020-01-15", "2020-03-31")                    # the stress episode `app/sims.EPISODES` already holds
PATHS = 3000
SHOW = 30
LABEL = "worked out by the Lab tools, 0 tokens"


def presets(con, now: datetime) -> List[dict]:
    """The scenario buttons: `enabled` False with a plain reason when the code has no preset (rates up 1% has none: the scenario table holds oil, the rupee and a US crash only)."""
    return [{"key": "normal", "label": SCENARIOS["normal"], "enabled": True, "why": ""},
            {"key": "covid", "label": SCENARIOS["covid"], "enabled": True, "why": "uses the stress episode the simulator already holds (15 Jan to 31 Mar 2020)"},
            {"key": "rates", "label": SCENARIOS["rates"], "enabled": False, "why": "not built yet"}]


def _his_returns(con, root, asof: date) -> tuple:
    """Daily returns of HIS Indian holdings (the stored Kite snapshot) and their value weights, over the days they all have. -> (DataFrame, weights, start value, names used, names held)."""
    from pflab.hq import stocks
    rows = con.execute("SELECT symbol, isin, qty * last_price FROM mine_in_s89 WHERE qty > 0 AND last_price > 0").fetchall()
    if not rows:
        raise ValueError("No Kite snapshot of your holdings yet: log in to Kite first.")
    cols, vals = {}, {}
    for sym, isin, v in rows:
        try:
            c = stocks.closes(con, root, isin, asof).iloc[-2600:]
        except Exception:
            continue
        if len(c) >= 500:
            cols[sym], vals[sym] = c, float(v)
    if not cols:
        raise ValueError("None of your holdings has enough stored price history for a simulation.")
    df = pd.DataFrame(cols).dropna()
    if len(df) < 250:
        raise ValueError("Your holdings share too little price history for a simulation.")
    r = df.pct_change().dropna()
    tot = sum(vals.values())
    w = np.array([vals[c] / tot for c in r.columns])
    return r, w, float(sum(v for _, _, v in rows)), len(cols), len(rows)


def simulate(rt, con, now: datetime, scenario: str, horizon: int, basis: str, paths: int = PATHS) -> dict:
    from pflab.app import s89, sims
    from pflab.risk import montecarlo as mc
    s89.ensure(con)
    if scenario not in SCENARIOS:
        raise ValueError("scenario must be normal, covid or rates")
    if scenario == "rates":
        raise ValueError("Rates up 1% is not built yet.")
    if int(horizon) not in HORIZONS:
        raise ValueError("horizon must be 20, 60 or 250 sessions")
    if basis not in ("mine", "paper"):
        raise ValueError("basis is mine or paper: never both added together")
    horizon, asof, root = int(horizon), now.date(), rt.data_root
    note = ""
    if basis == "paper":
        try:
            R, Rd, _ = sims.history(con, root, asof)
            w = sims.weights(sims.current_mix(con, asof))
        except Exception as e:
            raise ValueError(f"Claude's book has no mix to simulate yet ({type(e).__name__}).")
        rets, start = pd.DataFrame(Rd.values @ w, index=Rd.index), float(sims.invested(con, asof) or 0.0)
        port = rets[0]
        if start <= 0:
            raise ValueError("Claude's paper book has no value yet.")
    else:
        r, w, start, used, held = _his_returns(con, root, asof)
        port = pd.Series(r.values @ w, index=r.index)
        note = f"{used} of your {held} Indian holdings had enough price history; US holdings entered by hand are not simulated."
    if scenario == "covid":
        port = port[(port.index >= pd.Timestamp(COVID[0])) & (port.index <= pd.Timestamp(COVID[1]))]
        if len(port) < 30:
            raise ValueError("Your history does not cover March 2020, so this preset cannot be run on it.")
    rng = np.random.default_rng(20261115)
    idx = mc.block_index(len(port), horizon, paths, rng, 5)
    steps = port.values[idx]                                              # (paths, horizon) daily returns
    cum = np.cumprod(1 + steps, axis=1)
    end = cum[:, -1]
    pc = lambda q: float(np.percentile(end, q))
    fell = float(np.mean(cum.min(axis=1) <= 0.9))
    show = cum[np.linspace(0, paths - 1, SHOW).astype(int)]
    return {"scenario": scenario, "label": SCENARIOS[scenario], "horizon": horizon, "basis": basis, "start_inr": start, "paths_run": paths, "note": note, "worked_out": LABEL,
            "p_fall10": fell, "p_fall10_se": math.sqrt(fell * (1 - fell) / paths),
            "worst_1_in_20": start * pc(5), "middle": start * pc(50), "best_1_in_20": start * pc(95),
            "percentiles": {str(q): start * pc(q) for q in (5, 25, 50, 75, 95)}, "paths": [[round(float(start * x), 0) for x in p[:: max(1, horizon // 60)]] for p in show],
            "history_days": int(len(port)), "caveat": "resampled from past days: a description of what the past allows, not a forecast"}


def forecast(con, market: str = "IN") -> dict:
    """The fan for the next 20 sessions from the stored live forecasts (the combined forecaster when it exists) and how often its 8-in-10 band caught what happened."""
    market = "US" if str(market).upper() == "US" else "IN"
    last = con.execute("SELECT max(as_of) FROM forecasts_s79 WHERE market=? AND source='live'", [market]).fetchone()[0]
    out: Dict[str, Any] = {"market": market, "as_of": str(last) if last else None, "fan": [], "coverage": [], "worked_out": LABEL}
    if not last:
        out["empty"] = "No live forecast has been made yet. They are made after each close and scored when they mature."
        return out
    names = [r[0] for r in con.execute("SELECT DISTINCT forecaster FROM forecasts_s79 WHERE market=? AND source='live' AND as_of=?", [market, last]).fetchall()]
    f = "combined" if "combined" in names else (names[0] if names else None)
    subj = con.execute("SELECT subject, base_price FROM forecasts_s79 WHERE market=? AND source='live' AND as_of=? AND forecaster=? LIMIT 1", [market, last, f]).fetchone()
    out["forecaster"], out["subject"], out["base"] = f, subj[0] if subj else None, float(subj[1]) if subj and subj[1] else None
    for h, q in con.execute("SELECT horizon_sessions, quantiles_json FROM forecasts_s79 WHERE market=? AND source='live' AND as_of=? AND forecaster=? AND subject=? AND horizon_sessions <= 20 ORDER BY 1",
                            [market, last, f, subj[0] if subj else None]).fetchall():
        qs = {float(k): float(v) for k, v in json.loads(q).items()}
        out["fan"].append({"h": int(h), **{("q" + str(int(k * 100))): (out["base"] * (1 + v) if out["base"] else None) for k, v in qs.items()}})
    for h, n, hit in con.execute("SELECT horizon_sessions, count(*), sum(CASE WHEN covered_80 THEN 1 ELSE 0 END) FROM forecast_scores_s79 WHERE market=? AND source='live' AND forecaster=? GROUP BY 1 ORDER BY 1",
                                 [market, f]).fetchall():
        out["coverage"].append({"h": int(h), "n": int(n), "caught": int(hit or 0), "share": (hit or 0) / n if n else None, "judge": bool(n >= 20),
                                "text": (f"the 8-in-10 band caught {round((hit or 0) / n * 100)}% of {n} outcomes" if n >= 20 else f"{n} scored so far, needs 20 to judge")})
    if not out["fan"]:
        out["empty"] = "The stored forecasts have no horizon within 20 sessions yet."
    return out


def reliability(con, now: datetime) -> dict:
    """What the thinking loop has scored so far: for each likelihood word, what it said and how often it was right, and the Brier score from 20 scored decisions."""
    from pflab.think import score
    try:
        t = score.tally(con, now.date(), None)
    except Exception:
        t = {}
    try:
        pr = {w: float(p) for w, p in con.execute("SELECT word, probability FROM think_calibration_s84").fetchall()}
    except Exception:
        pr = {}
    n_dec = 0
    try:
        n_dec = int(con.execute("SELECT count(DISTINCT decision_id) FROM think_scores_s84 WHERE horizon_sessions=20").fetchone()[0])
    except Exception:
        pass
    pts, num, den = [], 0.0, 0
    for w, v in t.items():
        n, hits = int(v.get("n", 0)), int(v.get("hits", 0))
        if n and w in pr:
            pts.append({"word": w, "said": pr[w], "right": hits / n, "n": n})
            num += hits * (1 - pr[w]) ** 2 + (n - hits) * pr[w] ** 2
            den += n
    ok = n_dec >= 20 and den >= 20
    return {"scored": n_dec, "needed": 20, "points": pts, "brier": (num / den) if ok else None,
            "text": (f"{n_dec} of 20 decisions scored. Too few to judge; the chart fills in as they are scored." if n_dec < 20 else f"{n_dec} decisions scored."), "worked_out": LABEL}


def stock(rt, con, now: datetime, symbol: str, tf: str = "day") -> dict:
    """Candles, volume, the volume profile, the stop Claude's book uses, the graph's events and the book's plan for one name, from stored data."""
    from pflab.agents.tradecheck import isin_of
    from pflab.quant import candles, chart
    sym = str(symbol or "").strip().upper()
    isin = isin_of(con, sym)
    if not sym or not isin:
        raise ValueError(f"{sym or 'That name'} is not a name the record knows.")
    root = rt.data_root
    df = candles.daily(root, isin, now.date(), 400)
    if df is None or len(df) < 5:
        return {"symbol": sym, "empty": "No stored prices for this name yet.", "tf": tf}
    d = candles.weekly(df).tail(120) if tf == "week" else df.tail(120)
    d = d.reset_index() if "date" not in d.columns else d
    bars = [{"d": str(r["date"])[:10], "o": float(r["open"]), "h": float(r["high"]), "l": float(r["low"]), "c": float(r["close"]), "v": float(r.get("volume", 0) or 0)} for _, r in d.iterrows()]
    lo, hi = min(b["l"] for b in bars), max(b["h"] for b in bars)
    nb = 24
    edges = np.linspace(lo, hi, nb + 1)
    vol = np.zeros(nb)
    for b in bars:
        k = min(nb - 1, int((((b["h"] + b["l"] + b["c"]) / 3) - lo) / ((hi - lo) or 1) * nb))
        vol[k] += b["v"]
    profile = [{"low": float(edges[i]), "high": float(edges[i + 1]), "v": float(vol[i])} for i in range(nb)]
    plan = None
    try:
        r = con.execute("SELECT stop, target, status, opened_on, entry_price FROM exit_plans_s81 WHERE isin=? AND status IN ('open','active','held') ORDER BY plan_id DESC LIMIT 1", [isin]).fetchone()
        if r:
            plan = {"stop": r[0], "target": r[1], "status": r[2], "opened_on": str(r[3]), "entry": r[4]}
    except Exception:
        plan = None
    events = []
    try:
        from datetime import timedelta
        from pflab.kg import graph as g
        tl = g.timeline(con, f"company:{isin}", now - timedelta(days=60), kinds=("filing", "result", "article", "reading", "deal"), limit=8)
        events = [{"at": str(r.published_at)[:10], "kind": r.kind, "text": (r.title or "")[:140]} for r in tl.itertuples()]
    except Exception:
        events = []
    try:
        facts = chart.facts(df.tail(120))
    except Exception:
        facts = None
    fc = None
    try:
        r = con.execute("SELECT quantiles_json, base_price, as_of FROM forecasts_s79 WHERE symbol=? AND source='live' AND horizon_sessions <= 20 ORDER BY as_of DESC, horizon_sessions DESC LIMIT 1", [sym]).fetchone()
        if r:
            fc = {"as_of": str(r[2]), "base": r[1], "quantiles": json.loads(r[0])}
    except Exception:
        fc = None
    return {"symbol": sym, "tf": tf, "bars": bars, "profile": profile, "plan": plan, "stop": plan["stop"] if plan else None, "events": events, "sees": facts, "forecast": fc,
            "in_claudes_book": plan is not None, "note": None if plan else "Not in Claude's book, so there is no stop or plan for it.", "intraday": "needs a Kite login today (not shown)"}
