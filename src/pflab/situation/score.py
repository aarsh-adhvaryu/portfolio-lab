"""Scoring the situation's NEXT claims (S79b item 16), by code only, the same discipline as `fcast/score.py`.

A NEXT claim is a PREDICTION made on a date: an event about the market's index, a probability per horizon taken from a tool's claim (never the model's), the
claim ids and call ids it rests on. Two events exist:

    return_below   the index close `h` sessions later is more than `level` percent below the close on the day it was made (level 0: simply lower)
    fall_within    the lowest close in the `h` sessions after is at least `level` percent under the close on the day it was made

Horizons are SESSIONS on the market's calendar (`markets.session_after`), so a Friday prediction at 1 session matures on Monday. A prediction is scored at each
of its horizons when the target session's close exists: outcome 1 if the event happened, Brier = (p - outcome)^2. Calibration is the mean Brier and a
reliability table; under 20 outcomes only n is shown (the small-n rule). Score and weight updates stay code-only: nothing here calls a model.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Dict, List, Optional

import pandas as pd

from pflab import markets
from pflab.pm.store import next_id

HORIZONS = (1, 5, 20)
MIN_OUTCOMES = 20
BINS = ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001))


def store_prediction(con, report_id: Optional[int], market: str, made_on: date, cand: dict, chain_type: str, now: datetime) -> Optional[int]:
    """One prediction row from a NEXT candidate {key, statement, event, level, probs{h: p}, call_ids}; None when it has no valid probability."""
    probs = {str(int(h)): round(float(p), 4) for h, p in (cand.get("probs") or {}).items() if p is not None and 0.0 <= float(p) <= 1.0}
    if not probs or cand.get("event") not in ("return_below", "fall_within"):
        return None
    old = con.execute("SELECT pred_id FROM situation_prediction WHERE market=? AND made_on=? AND series=? AND event=? AND level=?",
                      [market, made_on, cand["key"], cand["event"], float(cand["level"])]).fetchone()
    if old:                                                      # one prediction per day and scenario: a re-run before anything matured refreshes it, after that it is final
        if con.execute("SELECT 1 FROM situation_outcome WHERE pred_id=?", [old[0]]).fetchone():
            return None
        con.execute("UPDATE situation_prediction SET report_id=?, chain_type=?, statement=?, probability=?, call_ids=?, horizons=?, created_at=? WHERE pred_id=?",
                    [report_id, chain_type or "none", cand["statement"][:300], float(probs[sorted(probs, key=int)[0]]), json.dumps(cand.get("call_ids") or []),
                     json.dumps(probs, sort_keys=True), now, old[0]])
        return int(old[0])
    pid = next_id(con, "situation_prediction", "pred_id")
    con.execute("INSERT INTO situation_prediction (pred_id, report_id, market, made_on, chain_type, statement, series, direction, threshold, probability, call_ids, horizons, "
                "created_at, event, level) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [pid, report_id, market, made_on, chain_type or "none", cand["statement"][:300], cand["key"], "down", float(cand["level"]), float(probs[sorted(probs, key=int)[0]]),
                 json.dumps(cand.get("call_ids") or []), json.dumps(probs, sort_keys=True), now, cand["event"], float(cand["level"])])
    return pid


def realized(series: pd.Series, market: str, made_on: date, h: int, event: str, level: float) -> Optional[dict]:
    """{outcome, observed, target_date} or None when the target session's close is not in the series yet (or the base close is missing)."""
    if series is None or len(series) == 0:
        return None
    mk = markets.get(market)
    target = mk.session_after(made_on, int(h))
    s = series.sort_index()
    base_s = s[s.index <= pd.Timestamp(made_on)]
    if len(base_s) == 0 or pd.Timestamp(target) not in s.index:
        return None
    base = float(base_s.iloc[-1])
    window = s[(s.index > pd.Timestamp(made_on)) & (s.index <= pd.Timestamp(target))]
    if event == "return_below":
        r = (float(s.loc[pd.Timestamp(target)]) / base - 1.0) * 100.0
        return {"outcome": int(r < level), "observed": round(r, 4), "target_date": target}
    if event == "fall_within":
        r = (float(window.min()) / base - 1.0) * 100.0
        return {"outcome": int(r <= -abs(level)), "observed": round(r, 4), "target_date": target}
    return None


def score(con, market: str, upto: date, now: Optional[datetime] = None, root=None, series: Optional[pd.Series] = None) -> dict:
    """Score every prediction horizon that has matured by `upto`. Idempotent: an (prediction, horizon) pair is scored once. `series` is injectable for tests."""
    now = now or datetime.now()
    if series is None:
        from pflab.fcast.run import load_series
        series = load_series(market, root)
    series = series[series.index <= pd.Timestamp(upto)]                       # nothing after `upto` is read
    rows = con.execute("SELECT pred_id, made_on, event, level, horizons FROM situation_prediction WHERE market=? ORDER BY pred_id", [market]).fetchall()
    done = {(p, h) for p, h in con.execute("SELECT pred_id, horizon FROM situation_outcome").fetchall()}
    n = 0
    for pid, made_on, event, level, hz in rows:
        for h, p in json.loads(hz).items():
            if (pid, int(h)) in done:
                continue
            r = realized(series, market, made_on, int(h), event, float(level))
            if r is None or r["target_date"] > upto:
                continue
            con.execute("INSERT INTO situation_outcome VALUES (?,?,?,?,?,?,?)", [pid, int(h), r["target_date"], r["outcome"], r["observed"], (float(p) - r["outcome"]) ** 2, now])
            n += 1
    return {"scored": n, "predictions": len(rows)}


def calibration(con, market: Optional[str] = None) -> dict:
    """Brier and reliability of the synthesizer's NEXT claims. Under MIN_OUTCOMES outcomes: n only, no figure and no verdict."""
    q = ("SELECT o.horizon, o.outcome, o.brier, p.horizons FROM situation_outcome o JOIN situation_prediction p ON p.pred_id=o.pred_id" + (" WHERE p.market=?" if market else ""))
    rows = con.execute(q, [market] if market else []).fetchall()
    n = len(rows)
    out = {"n": n, "min_for_figures": MIN_OUTCOMES}
    if n < MIN_OUTCOMES:
        out["note"] = f"{n} scored outcome(s): under {MIN_OUTCOMES} the count is all there is, no calibration figure"
        return out
    ps, ys, bs = [], [], []
    for h, y, b, hz in rows:
        ps.append(float(json.loads(hz)[str(h)]))
        ys.append(float(y))
        bs.append(float(b))
    base = sum(ys) / n
    out["brier"] = round(sum(bs) / n, 4)
    out["brier_base_rate"] = round(sum((base - y) ** 2 for y in ys) / n, 4)
    rel = []
    for lo, hi in BINS:
        idx = [i for i, p in enumerate(ps) if lo <= p < hi]
        if idx:
            rel.append({"bin": f"{lo:g}-{min(hi, 1.0):g}", "n": len(idx), "mean_p": round(sum(ps[i] for i in idx) / len(idx), 3), "freq": round(sum(ys[i] for i in idx) / len(idx), 3)})
    out["reliability"] = rel
    by_h: Dict[int, List[float]] = {}
    for (h, *_), b in zip(rows, bs):
        by_h.setdefault(int(h), []).append(b)
    out["by_horizon"] = {str(h): {"n": len(v), "brier": round(sum(v) / len(v), 4) if len(v) >= MIN_OUTCOMES else None} for h, v in sorted(by_h.items())}
    return out
