"""S89b: the Lab's Simulate and Forecast, the one-stock page and the reliability numbers. Every figure is worked out by existing code (the block bootstrap of `risk/montecarlo.py`, the stored forecasts and
their scores, the stored candles, the exit plans, the thinking loop's calibration); nothing here calls a model ("worked out by the Lab tools, 0 tokens") and nothing is invented: a scenario the code has no
preset for is "not built yet".
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
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
            "mult_paths": [[1.0] + [round(float(x), 5) for x in p] for p in show],
            "band": {k: [1.0] + [round(float(x), 5) for x in np.percentile(cum, q, axis=0)] for k, q in (("p10", 10), ("p50", 50), ("p90", 90))},
            "history_days": int(len(port)), "caveat": "resampled from past days: a description of what the past allows, not a forecast"}


def forecast(con, market: str = "IN", subject: Optional[str] = None, root=None) -> dict:
    """The fan for the next sessions from the stored live forecasts (the combined forecaster when it has one), the last 80 closes, and how often its bands caught what happened.
    `subjects` lists what has forecasts (the index and named stocks)."""
    from pflab.fcast import protocol as P
    market = "US" if str(market).upper() == "US" else "IN"
    last = con.execute("SELECT max(as_of) FROM forecasts_s79 WHERE market=? AND source='live'", [market]).fetchone()[0]
    out: Dict[str, Any] = {"market": market, "as_of": str(last) if last else None, "fan": [], "coverage": [], "hist": [], "worked_out": LABEL, "subjects": []}
    if not last:
        out["empty"] = "No live forecast has been made yet. They are made after each close and scored when they mature."
        return out
    out["subjects"] = [r[0] for r in con.execute("SELECT subject FROM forecasts_s79 WHERE market=? AND source='live' AND as_of=? GROUP BY subject ORDER BY count(*) DESC LIMIT 6", [market, last]).fetchall()]
    subj = subject if subject in out["subjects"] else (out["subjects"][0] if out["subjects"] else None)
    names = [r[0] for r in con.execute("SELECT DISTINCT forecaster FROM forecasts_s79 WHERE market=? AND source='live' AND as_of=? AND subject=?", [market, last, subj]).fetchall()]
    f = P.COMBINED if P.COMBINED in names else (names[0] if names else None)
    base = con.execute("SELECT base_price FROM forecasts_s79 WHERE market=? AND source='live' AND as_of=? AND forecaster=? AND subject=? LIMIT 1", [market, last, f, subj]).fetchone()
    out["forecaster"], out["subject"], out["base"] = f, subj, float(base[0]) if base and base[0] else None
    for h, q in con.execute("SELECT horizon_sessions, quantiles_json FROM forecasts_s79 WHERE market=? AND source='live' AND as_of=? AND forecaster=? AND subject=? AND horizon_sessions <= 20 ORDER BY 1",
                            [market, last, f, subj]).fetchall():
        qs = {float(k): float(v) for k, v in json.loads(q).items()}
        out["fan"].append({"h": int(h), **{("q" + str(int(round(k * 100)))): (out["base"] * (1 + v) if out["base"] else None) for k, v in qs.items()}})
    try:
        if subj in ("NIFTY 50", "US_SP500"):
            from pflab.fcast import run as fr
            hs = fr.load_series(market, root)
        else:
            from pflab.agents.tradecheck import isin_of
            from pflab.hq import stocks
            hs = stocks.closes(con, root, isin_of(con, subj), last)
        hs = hs[hs.index <= pd.Timestamp(last)].iloc[-80:]
        out["hist"] = [[str(d)[:10], round(float(v), 2)] for d, v in hs.items()]
    except Exception:
        out["hist"] = []
    for h, n, c80, c90 in con.execute("SELECT horizon_sessions, count(*), sum(CASE WHEN covered_80 THEN 1 ELSE 0 END), sum(CASE WHEN covered_90 THEN 1 ELSE 0 END) FROM forecast_scores_s79 "
                                      "WHERE market=? AND source='live' AND forecaster=? GROUP BY 1 ORDER BY 1", [market, f]).fetchall():
        out["coverage"].append({"h": int(h), "n": int(n), "caught": int(c80 or 0), "caught90": int(c90 or 0), "share": (c80 or 0) / n if n else None, "share90": (c90 or 0) / n if n else None, "judge": bool(n >= 20),
                                "text": (f"the 8-in-10 band caught {round((c80 or 0) / n * 100)}% of {n} outcomes" if n >= 20 else f"{n} scored so far, needs 20 to judge")})
    if not out["fan"]:
        out["empty"] = "The stored forecasts have no horizon within 20 sessions yet."
    return out


def pairs_of_book(rt, con, now: datetime, k: int = 4) -> List[dict]:
    """The pairs among the largest stock holdings (his snapshot first, then Claude's book), each with the coded test. Worked out by code, 0 tokens."""
    syms: List[str] = []
    try:
        syms = [r[0] for r in con.execute("SELECT symbol FROM mine_in_s89 ORDER BY qty * last_price DESC LIMIT ?", [k]).fetchall()]
    except Exception:
        pass
    if len(syms) < 2:
        try:
            from pflab.paper import manager
            syms = [h["symbol"] for h in sorted(manager.status(con, rt.data_root).get("holdings") or [], key=lambda h: -(h.get("value") or 0)) if h.get("kind") == "equity"][:k]
        except Exception:
            syms = []
    out = []
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            try:
                from pflab.app.s89 import pair
                out.append(pair(con, rt.data_root, now.date(), syms[i], syms[j]))
            except Exception as e:
                out.append({"a": syms[i], "b": syms[j], "error": str(e)[:120]})
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
        r = con.execute("SELECT stop, target, status, opened_on, entry_price, tax_boundary_date FROM exit_plans_s81 WHERE isin=? AND status='open' ORDER BY plan_id DESC LIMIT 1", [isin]).fetchone()
        if r:
            plan = {"stop": r[0], "target": r[1], "status": r[2], "opened_on": str(r[3]), "entry": r[4], "tax_boundary": str(r[5]) if r[5] else None}
    except Exception:
        plan = None
    events = []
    try:
        first = bars[0]["d"]
        for ts, d0, kind, head in con.execute("SELECT ts, event_date, kind, headline FROM kg2_event WHERE isin=? AND event_date >= ? ORDER BY ts DESC LIMIT 12", [isin, first]).fetchall():
            events.append({"at": str(ts)[:16], "date": str(d0), "kind": kind, "text": str(head or "")[:140]})
    except Exception:
        events = []
    mine = None
    try:
        r = con.execute("SELECT qty, qty * last_price FROM mine_in_s89 WHERE isin=?", [isin]).fetchone()
        mine = {"qty": r[0], "value": r[1]} if r else None
    except Exception:
        mine = None
    weight = None
    try:
        from pflab.paper import manager
        weight = next(((h.get("weight") or 0) * 100 for h in manager.status(con, root).get("holdings") or [] if h.get("isin") == isin), None)
    except Exception:
        weight = None
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
    return {"symbol": sym, "tf": tf, "bars": bars, "profile": profile, "plan": plan, "stop": plan["stop"] if plan else None, "events": events, "sees": facts, "forecast": fc, "mine": mine, "book_weight": weight,
            "in_claudes_book": plan is not None, "note": None if plan else "Not in Claude's book, so there is no stop or plan for it.", "intraday": "needs a Kite login today (not shown)"}


def book(rt, con, now: datetime, market: str = "IN") -> dict:
    """Claude's book for the design's Calibration screen: its curve against the index, the decisions and how they scored, what it changed about itself, and its holdings
    with their stops and 12-month clocks. Everything read from stored state; the US tab reads the US sub-book."""
    from pflab.paper import manager
    market = "US" if str(market).upper() == "US" else "IN"
    p = manager.status(con, rt.data_root) if market == "IN" else {}
    out: Dict[str, Any] = {"market": market, "started": bool(p.get("started")) if market == "IN" else False}
    days = [(d.get("day"), d.get("value")) for d in (p.get("days") or []) if d.get("value") is not None]
    nifty = [(d.get("day"), d.get("value")) for d in (p.get("nifty") or []) if d.get("value") is not None]
    out["days"], out["nifty"] = days, nifty
    ret = (days[-1][1] / days[0][1] - 1) * 100 if len(days) > 1 else None
    bret = (nifty[-1][1] / nifty[0][1] - 1) * 100 if len(nifty) > 1 else None
    worst = (p.get("returns") or {}).get("worst_fall")
    rel = reliability(con, now)
    right = n_scored = 0
    try:
        for did, v in con.execute("SELECT decision_id, sum(vs_nothing_inr) FROM think_scores_s84 WHERE horizon_sessions=20 GROUP BY 1").fetchall():
            n_scored += 1
            right += 1 if (v or 0) >= 0 else 0
    except Exception:
        pass
    out["kpis"] = [{"v": str(n_scored), "l": "decisions scored at 20 sessions"}, {"v": f"{round(right / n_scored * 100)}%" if n_scored else "—", "l": "right" if n_scored else "right: none scored yet"},
                   {"v": (f"{ret - bret:+.1f} pts" if ret is not None and bret is not None else "—"), "l": "against the Nifty 500 since it started"},
                   {"v": f"{worst * 100:.1f}%" if worst is not None else "—", "l": "worst fall so far"}]
    out["rel"] = rel
    dec: List[dict] = []
    try:
        for did, d0, sym, opt, reason in con.execute("SELECT decision_id, decided_on, symbol, acted_option, reason FROM think_decisions_s84 ORDER BY decided_on DESC, decision_id DESC LIMIT 12").fetchall():
            sc = con.execute("SELECT sum(vs_nothing_inr) FROM think_scores_s84 WHERE decision_id=? AND horizon_sessions=20", [did]).fetchone()[0]
            dec.append({"when": str(d0), "what": f"{(opt or '').replace('_', ' ').capitalize()} {sym or ''}".strip(), "said": str(reason or "")[:110],
                        "res": ("scored in 20 sessions" if sc is None else f"₹{sc:+,.0f} against doing nothing"), "v": "open" if sc is None else ("right" if sc >= 0 else "wrong")})
    except Exception:
        pass
    for x in (p.get("recent_decisions") or [])[:8]:
        dec.append({"when": str(x.get("at") or "")[:10], "what": f"{str(x.get('action') or '').capitalize()} {x.get('symbol') or ''}".strip(), "said": str(x.get("reason") or "")[:110],
                    "res": str(x.get("status") or ""), "v": "open"})
    out["dec"] = sorted(dec, key=lambda d: d["when"], reverse=True)[:14]
    log: List[dict] = []
    try:
        for wk, at, worked, nw, cal, cands in con.execute("SELECT week_key, written_at, worked, not_worked, calibration, candidates_json FROM operator_weekly_s87 ORDER BY week_key DESC LIMIT 6").fetchall():
            c = [x.get("idea") for x in json.loads(cands or "[]")]
            log.append({"when": str(wk), "kind": "weekly look", "t": "; ".join(json.loads(worked or "[]"))[:200] or "nothing scored yet", "after": ("to test next: " + "; ".join(c))[:200] if c else str(cal or "")[:200]})
    except Exception:
        pass
    out["log"] = log
    hold, rules = [], {}
    if market == "IN":
        plans = {}
        try:
            for isin, stop, opened, tb, status in con.execute("SELECT isin, stop, opened_on, tax_boundary_date, status FROM exit_plans_s81 WHERE status='open'").fetchall():
                plans[isin] = {"stop": stop, "opened": opened, "tax": tb}
        except Exception:
            pass
        mine_isins = set()
        try:
            mine_isins = {r[0] for r in con.execute("SELECT isin FROM mine_in_s89").fetchall()}
        except Exception:
            pass
        for h in p.get("holdings") or []:
            pl = plans.get(h.get("isin")) or {}
            stop_pct = (1 - pl["stop"] / h["price"]) * 100 if pl.get("stop") and h.get("price") else None
            days_left = (pl["tax"] - now.date()).days if pl.get("tax") else None
            hold.append({"name": h.get("symbol"), "isin": h.get("isin"), "kind": h.get("kind"), "sector": h.get("sector"), "weight": (h.get("weight") or 0) * 100,
                         "ret": (h["gain"] / h["cost"] * 100) if h.get("cost") else None, "stop_pct": stop_pct, "days_left": days_left, "you": h.get("isin") in mine_isins, "plan": bool(pl)})
        hold.append({"name": "Cash", "kind": "cash", "weight": (p.get("cash") or 0) / p["value"] * 100 if p.get("value") else 0, "ret": 0.0, "stop_pct": None, "days_left": None, "you": False, "plan": False})
        rules = {"stops": len(plans), "trades": len(p.get("trades") or []), "over_rails": len(p.get("over_rails") or []), "breaker": "on" if (p.get("breaker") or {}).get("on") else "off"}
        gain = sum((h.get("gain") or 0) for h in p.get("holdings") or [])
        out["hold_kpis"] = [{"v": f"₹{p.get('value', 0):,.0f}", "l": "value (its own account, fake money)"}, {"v": f"₹{gain:+,.0f}", "l": "gain not yet booked"},
                            {"v": f"₹{p.get('cash', 0):,.0f}", "l": "cash"}, {"v": str(len(p.get('trades') or [])), "l": "trades so far"}]
    else:
        out["hold_kpis"] = [{"v": "—", "l": "the US sub-book holds nothing yet"}]
    out["hold"], out["rules"] = hold, rules
    return out


LANES = (("result", 0), ("deal", 1), ("block", 1), ("bulk", 1), ("rating", 2), ("holding", 3), ("pledge", 3), ("shareholding", 3))


def graph_ego(rt, con, now: datetime, symbol: Optional[str] = None) -> dict:
    """One name in the knowledge graph (kg2): its peers by rule, the open storylines, its events of the last 12 months in lanes, the newest event in full, and the graph's
    own health (the nightly audit). The default name is the largest holding (his snapshot first, then Claude's book)."""
    from pflab.agents.tradecheck import isin_of
    sym = (symbol or "").strip().upper()
    if not sym:
        try:
            r = con.execute("SELECT symbol FROM mine_in_s89 ORDER BY qty * last_price DESC LIMIT 1").fetchone()
            sym = r[0] if r else ""
        except Exception:
            sym = ""
    if not sym:
        try:
            from pflab.paper import manager
            hs = sorted(manager.status(con, rt.data_root).get("holdings") or [], key=lambda h: -(h.get("value") or 0))
            sym = next((h["symbol"] for h in hs if h.get("kind") == "equity"), hs[0]["symbol"] if hs else "")
        except Exception:
            sym = ""
    out: Dict[str, Any] = {"symbol": sym, "found": False}
    isin = isin_of(con, sym) if sym else None
    if not isin:
        out["empty"] = f"{sym or 'No name'} is not in the graph yet."
        return out
    out["found"], out["isin"] = True, isin

    def q(sql, args=()):
        try:
            return con.execute(sql, list(args)).fetchall()
        except Exception:
            return []
    node = q("SELECT name, origin FROM kg2_node WHERE isin=?", [isin])
    out["name"] = (node[0][0] if node and node[0][0] else sym)
    tags = []
    try:
        from pflab.paper import manager
        for h in manager.status(con, rt.data_root).get("holdings") or []:
            if h.get("isin") == isin:
                tags += [h.get("sector") or "", "in Claude's book"]
    except Exception:
        pass
    if q("SELECT 1 FROM mine_in_s89 WHERE isin=?", [isin]):
        tags.append("your holding")
    out["tags"] = [t for t in tags if t][:3]
    peers = q("SELECT coalesce(n.symbol, n.name, r.dst_isin), r.rule FROM kg2_relation r LEFT JOIN kg2_node n ON n.isin = r.dst_isin WHERE r.src_isin=? LIMIT 3", [isin])
    out["peers"] = [{"name": p[0], "rule": p[1]} for p in peers]
    out["stories"] = [{"claim": c, "p": p} for c, p in q("SELECT claim, probability FROM storylines_s80 WHERE status='open' ORDER BY probability DESC NULLS LAST LIMIT 2")]
    since = now - timedelta(days=365)
    ev = q("SELECT ts, event_date, kind, severity, headline, source, ref, link_rule FROM kg2_event WHERE isin=? AND event_date >= ? ORDER BY ts DESC LIMIT 200", [isin, since.date()])
    out["events"] = [{"ts": str(e[0])[:16], "date": str(e[1]), "kind": e[2], "severity": e[3], "headline": e[4], "source": e[5], "ref": e[6], "rule": e[7]} for e in ev]
    lanes: List[List[dict]] = [[], [], [], [], []]
    for e in out["events"]:
        k = str(e["kind"]).lower()
        lane = next((i for key, i in LANES if key in k), 4)
        d = date.fromisoformat(e["date"])
        x = 90 + max(0, min(1, (d - since.date()).days / 365)) * 1100
        lanes[lane].append({"x": round(x, 1)})
    out["lanes"] = lanes
    au = q("SELECT day, passed, checks_json FROM kg2_audit ORDER BY day DESC LIMIT 1")
    out["audit"] = {"day": str(au[0][0]), "passed": bool(au[0][1])} if au else None
    out["counts"] = {"events": (q("SELECT count(*) FROM kg2_event") or [[0]])[0][0], "nodes": (q("SELECT count(*) FROM kg2_node") or [[0]])[0][0],
                     "linked": (q("SELECT count(*) FROM kg2_event WHERE link_rule IS NOT NULL") or [[0]])[0][0], "unlinked": (q("SELECT count(*) FROM kg2_unlinked") or [[0]])[0][0]}
    return out


# --- Usage (S90): the plan's tokens by day, road and agent, and what they bought ----------------------------------------------------------------

USAGE_CLASSES = ("desk", "cases", "build", "chat", "chat_light")


def usage_plan(con, now: datetime, days: int = 30) -> dict:
    """The Usage screen: tokens today against the sum of the day budgets, quick vs full answers today, what the tokens bought, tokens per day for `days` days split
    into desk+cases+build / full / quick, today's split by purpose, and a 20-day grid of model runs per agent. Tokens only (the plan has no per-token price)."""
    from pflab.llm import claude_plan as cp
    d0 = datetime(now.year, now.month, now.day)
    start = d0 - timedelta(days=days - 1)
    rows = con.execute("SELECT CAST(created_at AS DATE), split_part(topic, ':', 2), count(*), coalesce(sum(coalesce(input_tokens,0)+coalesce(output_tokens,0)),0) FROM api_calls "
                       "WHERE engine='claude_plan' AND status='done' AND created_at >= ? GROUP BY 1, 2", [start]).fetchall()
    per: Dict[date, Dict[str, list]] = {}
    for d, k, n, t in rows:
        per.setdefault(d, {})[k] = [int(n), int(t)]
    cfg = cp.settings()
    budgets = {k: cp.budget_of(k, cfg) for k in USAGE_CLASSES}
    today = per.get(d0.date(), {})
    used = {k: today.get(k, [0, 0])[1] for k in USAGE_CLASSES}
    calls = {k: today.get(k, [0, 0])[0] for k in USAGE_CLASSES}
    series = []
    for i in range(days):
        d = (start + timedelta(days=i)).date()
        p = per.get(d, {})
        series.append({"day": str(d), "work": sum(p.get(k, [0, 0])[1] for k in ("desk", "cases", "build")), "full": p.get("chat", [0, 0])[1], "quick": p.get("chat_light", [0, 0])[1]})
    def one(sql, a):
        try:
            return int(con.execute(sql, a).fetchone()[0] or 0)
        except Exception:
            return 0
    bought = {"desk": calls["desk"], "cases": one("SELECT count(*) FROM think_cases_s84 WHERE opened_on=? AND state <> 'noticed'", [d0.date()]),
              "fixes_waiting": one("SELECT count(*) FROM operator_builds_s87 WHERE status='card'", []),
              "builds": calls["build"]}
    heat = []
    g0 = d0 - timedelta(days=19)
    for k, name in (("desk", "Daily desk"), ("cases", "Cases and alarms"), ("chat_light", "Quick answers"), ("chat", "Full operator"), ("build", "Fixer")):
        cells = [per.get((g0 + timedelta(days=i)).date(), {}).get(k, [0, 0])[0] for i in range(20)]
        heat.append({"name": name, "cells": cells})
    return {"used": used, "calls": calls, "budgets": budgets, "series": series, "bought": bought, "heat": heat, "state": cp.state(con, now, probe=False)}


def week_status(con, now: datetime) -> dict:
    """Settings' first-week card: the day of 7, and each criterion's PASS / FAIL / NOT TESTED as it stands (the stored verdict when there is one, else evaluated now)."""
    from pflab.service import week_check as wc
    r = None
    try:
        r = con.execute("SELECT check_id, armed_at, verdict, details_json, freeze_from FROM week_check_s79 ORDER BY check_id DESC LIMIT 1").fetchone()
    except Exception:
        r = None
    armed = r[1] if r and r[1] and r[1].date() >= wc.ARM_FROM else None
    out = {"arm_from": str(wc.ARM_FROM), "armed_at": str(armed)[:16] if armed else None, "of": wc.MIN_DAYS, "day": 0, "verdict": None, "freeze_from": None, "criteria": []}
    if armed:
        out["day"] = min(wc.MIN_DAYS, (now.date() - armed.date()).days + 1)
        out["verdict"] = r[2]
        out["freeze_from"] = str(r[4]) if r[4] else None
    try:
        res = json.loads(r[3]) if armed and r[3] else wc.evaluate(con, armed or now, now)
        out["criteria"] = [{"name": c["name"], "status": c["status"], "text": c.get("text", "")} for c in res.get("criteria", [])]
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:160]}"
    return out
