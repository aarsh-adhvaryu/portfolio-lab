"""S85 L1 (3): "WHAT DID I MISS". After each close: the biggest rises and falls of the watched universe over 5 and 20 sessions (from the price data, never the model) set beside what the loop noticed
(signals, cases, skips, screens). For every big mover it did NOT notice, a row in `think_misses_s84` (kind = the reason class, `detail` = JSON) and the threshold that would have caught it.

    run(con, now, root=None, only_market=None) -> {"IN": {...}, "US": {...}}   the job's entry: each market's latest closed session once (marker in `paper_acts`, loop `think_missed`)
    one(con, now, market, day, root=None) -> {"movers", "missed", "by_reason", "rows"}
    summary(con, day=None, days=7) -> {"days", "total", "by_reason": {...}, "text"}   plain words: "the cap cost us n, the threshold was too high n, outside scope n"

Reason classes (code decides, in this order; a mover the loop did notice, with a case opened in its window, is not a miss):
    cap              the loop had a signal on it in the window but opened no case (the day's cap), or the move was past the line and no signal was stored (the day's store limit): "the cap cost us"
    outside_scope    the mover is in no list the watch reads (not held, picked, skipped, screened, and not a member of the Nifty 500 / S&P 500): "outside scope"
    below_threshold  in scope, no signal, and the move reached at least half of its line (or an event of the graph was there): a threshold within the tuning bounds would have caught it:
                     `detail.would_catch` = {param, value}: the value of that threshold that would have fired. "the threshold was too high"
    no_event         in scope, no signal, under half of its line and nothing in the graph: an ordinary drift for that name; no threshold inside the tuning bounds would have caught it
The line of a move over 5 sessions is `move_sigmas` x the name's usual 5-day move; over 20 sessions a rise is judged against `wide_run_pts` (points ahead of its index) and a fall against
`fall_pct_10d` (the 10-session fall). Point in time: closes dated on or before the day. A move already recorded for the name and horizon in the last `horizon` days is not recorded again.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab.think import cases, exposure, watch, wide

LOOP = "think_missed"
HORIZONS = (5, 20)
LABELS = {"cap": "the cap cost us", "below_threshold": "the threshold was too high", "outside_scope": "outside scope", "no_event": "no event to notice"}
MISSED_DEFAULTS = {"missed_top_n": 10, "missed_min_turnover_inr": 5.0e7, "missed_event_window_days": 5}


def settings() -> dict:
    out = dict(MISSED_DEFAULTS)
    out.update(wide.settings())
    return out


# --- the universe the movers are drawn from --------------------------------------------------------------------------------------------------------------------------------------

def universe_series(con, root, market: str, day: date, cfg: dict) -> Dict[str, dict]:
    """isin -> {"symbol", "series"} of the liquid names (India: median traded value over 60 sessions of at least `missed_min_turnover_inr`, the picks floor; US: the stored universe).
    Tests replace this function."""
    out: Dict[str, dict] = {}
    root = Path(root) if root is not None else None
    if root is None:
        from pflab.data import data_dir
        root = data_dir()
    if market == "US":
        from pflab.us import instruments as uins
        syms = exposure.us_members(root)
        try:
            ciks = uins.load_ciks(root)
        except Exception:
            ciks = {}
        by = wide.us_series(root, syms, day)
        for s, ser in by.items():
            out[uins.key_for(con, s, ciks)] = {"symbol": s, "series": ser}
        return out
    from pflab.lab import screen
    liq = screen.india_liquidity(root, day)
    liq = liq[liq["median_value_60"] >= float(cfg["missed_min_turnover_inr"])]
    isins = list(liq.index)
    by = wide.india_series(con, root, isins, day)
    for i, ser in by.items():
        out[i] = {"symbol": str(liq.loc[i, "symbol"]), "series": ser}
    return out


def _scope_isins(con, day: date, market: str, root) -> set:
    out = set()
    try:
        out |= {e["isin"] for e in watch.scope(con, day, market=market, root=root)}
    except Exception:
        pass
    try:
        w = exposure.index_weights(wide.INDEX_OF[market], day, root, con)
        out |= set(w["isin"])
    except Exception:
        pass
    return out


# --- one session ---------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _floor(x: float, nd: int = 2) -> float:
    f = 10 ** nd
    return math.floor(x * f) / f


def _movers(data: Dict[str, dict], day: date, ix: Optional[pd.Series], top_n: int) -> List[dict]:
    rows = []
    for isin, d in data.items():
        s = d["series"]
        if s is None or len(s) < 62 or s.index[-1].date() != day:
            continue
        for h in HORIZONS:
            r = float(s.iloc[-1] / s.iloc[-1 - h] - 1.0)
            i1, i0 = (watch._at(ix, s.index[-1]), watch._at(ix, s.index[-1 - h])) if ix is not None else (None, None)
            rel = (r - (i1 / i0 - 1.0)) if (i1 and i0) else None
            rows.append({"isin": isin, "symbol": d["symbol"], "h": h, "ret": r, "rel": rel})
    df = pd.DataFrame(rows)
    out: List[dict] = []
    if df.empty:
        return out
    seen = set()
    for h in HORIZONS:
        g = df[df["h"] == h]
        for rec in g.nlargest(top_n, "ret").to_dict("records") + g.nsmallest(top_n, "ret").to_dict("records"):
            if (rec["isin"], h) not in seen:
                seen.add((rec["isin"], h))
                out.append(rec)
    return out


def _classify(con, day: date, m: dict, s: pd.Series, in_scope: set, cfg: dict) -> Optional[dict]:
    """None when the loop noticed it (a case was opened in the window); else {"kind", "would_catch", "detail"}."""
    isin, h = m["isin"], int(m["h"])
    ws = day - timedelta(days=int(h * 1.5) + 2)
    if con.execute("SELECT 1 FROM think_cases_s84 WHERE isin=? AND opened_on >= ? AND opened_on <= ? AND state <> 'noticed' LIMIT 1", [isin, ws, day]).fetchone():
        return None
    detail = {"horizon": h, "direction": "rise" if m["ret"] > 0 else "fall", "window_from": str(ws)}
    if con.execute("SELECT 1 FROM think_signals_s84 WHERE isin=? AND day >= ? AND day <= ? LIMIT 1", [isin, ws, day]).fetchone():
        return {"kind": "cap", "would_catch": None, "detail": {**detail, "why": "a signal was stored but no case opened (the day's cap, or the thinking was not reached)"}}
    if isin not in in_scope:
        return {"kind": "outside_scope", "would_catch": None, "detail": {**detail, "why": "in no list the watch reads"}}
    r = s.pct_change().dropna()
    sigma = float(r.iloc[-251:-1].std()) if len(r) > 60 else 0.0
    param, value, line = None, None, None
    if h == 5:
        if sigma > 0:
            mult = abs(m["ret"]) / (sigma * math.sqrt(5))
            param, value, line = "move_sigmas", mult, float(cfg["move_sigmas"])
    elif m["ret"] > 0:
        if m["rel"] is not None:
            param, value, line = "wide_run_pts", max(0.0, m["rel"] * 100.0), float(cfg["wide_run_pts"])
    else:
        f10 = float(s.iloc[-1] / s.iloc[-11] - 1.0) if len(s) > 11 else 0.0
        param, value, line = "fall_pct_10d", max(0.0, -f10), float(cfg["fall_pct_10d"])
    if param is None or not line:
        return {"kind": "no_event", "would_catch": None, "detail": {**detail, "why": "no measure of its usual move"}}
    q = value / line
    detail.update({"param": param, "value": round(float(value), 4), "line": round(float(line), 4), "q": round(float(q), 3)})
    if q >= 1.0:
        return {"kind": "cap", "would_catch": None, "detail": {**detail, "why": "the move was past the line: it was found but not stored or not opened (the day's store limit and cap)"}}
    ev = 0
    try:
        ev = int(con.execute("SELECT count(*) FROM kg2_event WHERE isin=? AND CAST(ts AS DATE) >= ? AND CAST(ts AS DATE) <= ?", [isin, day - timedelta(days=int(cfg["missed_event_window_days"])), day]).fetchone()[0])
    except Exception:
        pass
    detail["graph_events"] = ev
    if q >= 0.5 or ev > 0:
        wc = {"param": param, "value": _floor(float(value), 4 if param == "fall_pct_10d" else 2)} if value and q >= 0.5 else None
        return {"kind": "below_threshold", "would_catch": wc, "detail": {**detail, "why": "in scope; the move reached part of its line" if q >= 0.5 else "in scope; an event was in the graph but the price stayed far under its line"}}
    return {"kind": "no_event", "would_catch": None, "detail": {**detail, "why": "an ordinary drift for this name and nothing in the graph"}}


def one(con, now: datetime, market: str, day: date, root=None) -> dict:
    """The misses of one session of `market`. Idempotent (a name and horizon in the same direction already recorded in the last `horizon` days is not recorded again)."""
    cfg = settings()
    out = {"market": market, "day": str(day), "movers": 0, "missed": 0, "by_reason": {}, "rows": []}
    data = universe_series(con, root, market, day, cfg)
    ix = watch._index(market, root)
    movers = _movers(data, day, ix, int(cfg["missed_top_n"]))
    out["movers"] = len(movers)
    in_scope = _scope_isins(con, day, market, root)
    from pflab.pm.store import next_id
    for m in movers:
        d = data[m["isin"]]
        c = _classify(con, day, m, d["series"], in_scope, cfg)
        if c is None:
            continue
        h = int(m["h"])
        lo = day - timedelta(days=h)
        direction = c["detail"]["direction"]
        if con.execute("SELECT 1 FROM think_misses_s84 WHERE isin=? AND day >= ? AND day <= ? AND detail LIKE ? AND detail LIKE ? LIMIT 1",
                       [m["isin"], lo, day, f'%"horizon": {h},%', f'%"direction": "{direction}"%']).fetchone():
            continue
        c["detail"]["would_catch"] = c["would_catch"]
        c["detail"]["reason_text"] = LABELS[c["kind"]]
        mid = next_id(con, "think_misses_s84", "miss_id")
        con.execute("INSERT INTO think_misses_s84 VALUES (?,?,?,?,?,?,?,?,?)", [mid, day, c["kind"], market, m["isin"], m["symbol"], float(m["ret"]) * 100.0, 0.0, json.dumps(c["detail"], default=str)])
        out["missed"] += 1
        out["by_reason"][c["kind"]] = out["by_reason"].get(c["kind"], 0) + 1
        out["rows"].append(mid)
    return out


# --- the job's entry --------------------------------------------------------------------------------------------------------------------------------------------------------------------

def _marked(con, market: str, day: date) -> bool:
    return bool(con.execute("SELECT 1 FROM paper_acts WHERE loop=? AND what LIKE ? LIMIT 1", [LOOP, f"missed {market} {day}:%"]).fetchone())


def run(con, now: datetime, root=None, *, only_market: Optional[str] = None) -> dict:
    """Each market's latest closed session whose closes are in the store, once. Never raises (a failure is `{"error": ...}` for that market)."""
    from pflab.paper import cadence
    from pflab.think import wire
    res: dict = {}
    for market in ("IN", "US"):
        if only_market and market != only_market or not wire._market_on(market):
            continue
        try:
            have = wire._data_through(con, root, market)
            if have is None:
                continue
            day = min(wire._closed(market, now), have)
            if _marked(con, market, day):
                continue
            r = one(con, now, market, day, root)
            cadence.act(con, now, LOOP, f"missed {market} {day}: {r['missed']} of {r['movers']} big movers not noticed", True, {"by_reason": r["by_reason"]})
            res[market] = {k: r[k] for k in ("day", "movers", "missed", "by_reason")}
        except Exception as ex:
            res[market] = {"error": repr(ex)[:200]}
    return res


# --- what the reports show --------------------------------------------------------------------------------------------------------------------------------------------------------------

def summary(con, day: Optional[date] = None, days: int = 7) -> dict:
    """The misses of the last `days` days by reason, in plain words (JSON-able)."""
    day = day or date.today()
    lo = day - timedelta(days=days)
    rows = con.execute("SELECT kind, count(*) FROM think_misses_s84 WHERE day > ? AND day <= ? AND kind IN ('cap','below_threshold','outside_scope','no_event') GROUP BY 1", [lo, day]).fetchall()
    by = {k: int(n) for k, n in rows}
    total = sum(by.values())
    if not total:
        text = f"In the last {days} days no big move went unnoticed (or the job has not run yet)."
    else:
        text = (f"In the last {days} days {total} big move(s) went unnoticed: " + ", ".join(f"{LABELS[k]}: {by[k]}" for k in LABELS if by.get(k)) + ".")
    return {"days": days, "since": str(lo), "total": total, "by_reason": by, "labels": LABELS, "text": text}
