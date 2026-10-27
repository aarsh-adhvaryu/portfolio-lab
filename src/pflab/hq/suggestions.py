"""The suggestion ledger (S60, PLAN A18; the investor 2026-10-24: learn from real outcomes, taken or declined).

    record     every suggestion the brain makes: its kind, stock, words, reasoning, the tool results it rested on, its
               horizon, the reference close and the quantity held then; the decision quality judged by code at once
               against the facts (guard, the name's share and cap, the list, tested results), never by the outcome
    answer     the investor's: taken / declined (dashboard, Telegram later); with none, a trade in the suggested direction seen
               in the portfolio by the horizon counts as taken (source 'portfolio')
    score      at the horizon, on the stock against the NIFTY 500 TRI over the same dates (declined and unanswered ones
               too: on paper): add good if it beat the index; trim good if it lagged; hold good if it did not lag by more
               than a round trip's charges; wait good if its price fell. rebalance / review / other are not priced
    lessons    hit rates by kind with their n (counts under 20, the small-numbers rule), luck apart from judgement (sound
               decisions that went badly, unsound ones that went well), for the brain's cached part. Nothing here
               retires a kind: a few misses are a count, not a verdict
All code, nothing leaves the PC.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import pandas as pd

from pflab.calc import smalln

KINDS = ("add", "trim", "hold", "wait", "rebalance", "review", "other")
PRICED = ("add", "trim", "hold", "wait")
HORIZON_MIN, HORIZON_MAX = 5, 180
SLACK_DAYS = 6
ANSWERS = ("taken", "declined", "none")


def quality(kind: str, f: dict) -> tuple:
    """(sound | weak | unsound, why) from the code's facts at the time (`stocks.facts` drift, guard)."""
    d = f.get("drift") or {}
    g = f.get("guard", "not checked")
    if kind == "add":
        if g in ("fail", "block"):
            return "unsound", f"guard {g}: no new buying"
        if not d.get("share_rule", "").startswith("equal share"):
            return "unsound", d.get("share_rule") or "no share for this name"
        if d.get("over_cap"):
            return "unsound", "already over its cap"
        if (d.get("gap_pct") or 0) >= 0:
            return "weak", "already at or above its share"
        return "sound", "below its share, guard OK"
    if kind == "trim":
        if not d.get("held"):
            return "unsound", "not held"
        if d.get("over_cap") or (d.get("gap_pct") or 0) > 0 or g in ("fail", "block") or not d.get("share_rule", "").startswith("equal"):
            return "sound", "over its share or cap, a guard failing, or off the list"
        return "weak", "within its share and guard OK"
    if kind == "wait":
        return "weak", "against a tested result: waiting for the buy zone cost money on average (PLAN A12)"
    if kind == "hold":
        if g in ("fail", "block"):
            return "weak", f"held with guard {g}"
        return "sound", "no fact against holding"
    return "sound", "not judged by code"


def numbers(con, root, isin: str, asof: date, guard: str = "ok") -> dict:
    """The price numbers of a suggestion, all by code (S64 Phase 5 item 5; the model gives words only):
    price_low / price_high = the buy zone (20th-40th percentile of the year's closes); max_buy = the lower of the zone's
    top and the 21-session middle of the price range; wrong_price = the 63-session 10th percentile and `wrong_if` its wording.
    Missing history or no stored range leaves the field None; nothing is guessed."""
    from pflab.app import research
    from pflab.plan import buyzone
    from pflab.quant import forecast as fc
    c = research.closes(con, root, isin, asof, years=4).dropna()
    z = buyzone.zone(c, asof, guard=guard, paths=5_000)
    out: dict = {"price_low": None, "price_high": None, "max_buy": None, "wrong_price": None, "wrong_if": None,
                 "stats": {"zone_verdict": z.get("verdict"), "zone_headline": z.get("headline")}}
    if "bottom" not in z:
        return out
    out["price_low"], out["price_high"] = float(z["bottom"]), float(z["top"])
    method, label = fc.serving_method(root)
    q = {h: con.execute("SELECT q10, q50, q90 FROM forecasts WHERE use=? AND subject=? AND model=? ORDER BY as_of DESC LIMIT 1",
                        [f"price{h}", isin, method]).fetchone() for h in (21, 63)}
    out["max_buy"] = min(out["price_high"], float(q[21][1])) if q[21] else out["price_high"]
    if q[63]:
        out["wrong_price"] = float(q[63][0])
        out["wrong_if"] = (f"it closes below {q[63][0]:,.0f}, the 10th percentile of its 3-month price range "
                           f"(80% range, an estimate: {label})")
    out["stats"].update(price=float(c.iloc[-1]), method=method, q21=q[21], q63=q[63], touch_bottom=z.get("touch_bottom"))
    return out


def record(con, *, pass_id: Optional[int], model: str, kind: str, isin: Optional[str], symbol: Optional[str], text: str,
           reasoning: str, data: dict, horizon_days: int, now: datetime, shadow: bool, ref: Optional[tuple] = None,
           ref_qty: Optional[float] = None, facts: Optional[dict] = None, root=None, amount: Optional[float] = None) -> int:
    """Keep a suggestion. With `root`, a priced kind on a stock gets its numbers from `numbers`; an 'add' that is not a shadow
    also gets a price watch below its highest buy price (the watch's hit carries a ready ticket) and the amount given."""
    from pflab.pm.store import next_id
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if not HORIZON_MIN <= int(horizon_days) <= HORIZON_MAX:
        raise ValueError(f"horizon {horizon_days} days: {HORIZON_MIN}-{HORIZON_MAX}")
    q, why = quality(kind, facts or {}) if isin else ("sound", "not about one stock")
    num = None
    if root is not None and isin and kind in PRICED:
        try:
            num = numbers(con, root, isin, now.date(), (facts or {}).get("guard", "ok"))
        except Exception as e:                                   # no prices or ranges: the words stand, the numbers wait
            num = {"stats": {"numbers_error": f"{type(e).__name__}: {str(e)[:120]}"}}
    num = num or {}
    amt = amount if kind == "add" else None
    sid = next_id(con, "hq_suggestions", "sug_id")
    con.execute("INSERT INTO hq_suggestions (sug_id, pass_id, model, made_at, kind, isin, symbol, text, reasoning, data_json, "
                "horizon_days, ref_date, ref_close, ref_qty, shadow, quality, quality_why, price_low, price_high, max_buy, "
                "amount, wrong_if, wrong_price, stats_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [sid, pass_id, model, now, kind, isin, symbol, text[:600], reasoning[:1500],
                 json.dumps(data, default=str)[:20000], int(horizon_days), ref[0] if ref else None, ref[1] if ref else None,
                 ref_qty, shadow, q, why, num.get("price_low"), num.get("price_high"), num.get("max_buy"), amt,
                 num.get("wrong_if"), num.get("wrong_price"), json.dumps(num.get("stats"), default=str) if num.get("stats") else None])
    if kind == "add" and not shadow and isin and num.get("max_buy"):
        from pflab.app import research
        wid = research.add_watch(con, isin, symbol or isin, "below", round(float(num["max_buy"]), 2),
                                 f"suggestion #{sid}: highest buy price", now)
        con.execute("UPDATE hq_suggestions SET watch_id=? WHERE sug_id=?", [wid, sid])
    return sid


def answer(con, sug_id: int, ans: str, now: datetime, source: str = "dashboard") -> None:
    if ans not in ANSWERS:
        raise ValueError(f"answer is one of {ANSWERS}")
    if not con.execute("SELECT 1 FROM hq_suggestions WHERE sug_id=?", [sug_id]).fetchone():
        raise LookupError(f"no suggestion #{sug_id}")
    con.execute("UPDATE hq_suggestions SET answer=?, answered_at=?, answer_source=? WHERE sug_id=?",
                [ans, now if ans != "none" else None, source, sug_id])


def _close_on(con, isin: str, day: date) -> Optional[tuple]:
    from pflab.hq import keeper
    s = keeper.closes(con, isin, day, days=SLACK_DAYS + 5)
    s = s[s.index.date >= day - timedelta(days=SLACK_DAYS)] if len(s) else s
    return (s.index[-1].date(), float(s.iloc[-1])) if len(s) else None


def _index_on(index: pd.Series, day: date) -> Optional[float]:
    s = index[(index.index <= pd.Timestamp(day)) & (index.index >= pd.Timestamp(day - timedelta(days=SLACK_DAYS)))]
    return float(s.iloc[-1]) if len(s) else None


def judge(kind: str, stock_pct: float, excess_pct: float, cost_pct: float) -> str:
    if kind == "add":
        return "good" if excess_pct > 0 else "bad"
    if kind == "trim":
        return "good" if excess_pct < 0 else "bad"
    if kind == "hold":
        return "good" if excess_pct > -cost_pct else "bad"
    if kind == "wait":
        return "good" if stock_pct < 0 else "bad"
    return "n/a"


def _qty_now(con, isin: str, asof: date) -> Optional[float]:
    from pflab.pm import today
    pos = today.build(con, asof)["positions"]
    return float(pos.loc[pos["isin"] == isin, "qty"].sum())


def beta_at(isin: str, day: date) -> Optional[float]:
    """The stock's CAPM beta as known on `day` (the day the suggestion was made); None when it has no fit."""
    try:
        from pflab.data import data_dir
        from pflab.risk import capm
        return capm.for_isin(data_dir(), isin, day)["beta"]
    except Exception:
        return None


def score_due(con, now: datetime, index: Optional[pd.Series], qty_fn=None) -> int:
    """Score every suggestion past its horizon (outcomes after it was made, never before); detect a taken one."""
    from pflab.hq import stocks
    qty_fn = qty_fn or (lambda isin: _qty_now(con, isin, now.date()))
    n = 0
    rows = con.execute("SELECT sug_id, kind, isin, made_at, horizon_days, ref_date, ref_close, ref_qty, answer FROM hq_suggestions "
                       "WHERE scored_at IS NULL").fetchall()
    for sid, kind, isin, made, h, ref_date, ref_close, ref_qty, ans in rows:
        due = made.date() + timedelta(days=int(h))
        if due > now.date():
            continue
        if ans == "none" and isin and ref_qty is not None and kind in ("add", "trim"):
            q = qty_fn(isin)
            if q is not None and ((kind == "add" and q > ref_qty + 1e-6) or (kind == "trim" and q < ref_qty - 1e-6)):
                con.execute("UPDATE hq_suggestions SET answer='taken', answered_at=?, answer_source='portfolio' WHERE sug_id=?",
                            [now, sid])
        if kind not in PRICED or not isin or ref_close is None:
            con.execute("UPDATE hq_suggestions SET outcome='n/a', scored_at=? WHERE sug_id=?", [now, sid])
            n += 1
            continue
        end = _close_on(con, isin, due)
        i0 = _index_on(index, ref_date) if index is not None else None
        i1 = _index_on(index, due) if index is not None else None
        if end is None or end[0] <= ref_date or i0 is None or i1 is None:
            if (now.date() - due).days > 10:
                con.execute("UPDATE hq_suggestions SET outcome='void', outcome_json=?, scored_at=? WHERE sug_id=?",
                            [json.dumps({"why": "no close or index level near the horizon"}), now, sid])
            continue
        sp = (end[1] / ref_close - 1) * 100
        ip = (i1 / i0 - 1) * 100
        cost = stocks.round_trip_pct(stocks.DEFAULT_ORDER)
        beta = beta_at(isin, ref_date)                     # S64: an edge is beating market exposure, not the market
        adj = sp - (beta if beta is not None else 1.0) * ip
        out = judge(kind, sp, adj, cost)
        con.execute("UPDATE hq_suggestions SET outcome=?, outcome_json=?, scored_at=? WHERE sug_id=?",
                    [out, json.dumps({"from": str(ref_date), "to": str(end[0]), "stock_pct": round(sp, 2),
                                      "nifty500_pct": round(ip, 2), "excess_pct": round(sp - ip, 2),
                                      "beta": None if beta is None else round(beta, 2),
                                      "market_adjusted_pct": round(adj, 2),
                                      "judged_on": "return - beta x Nifty 500 return" if beta is not None
                                      else "excess over Nifty 500 (no beta fit)",
                                      "round_trip_pct": round(cost, 3)}), now, sid])
        n += 1
    return n


def record_table(con, model: Optional[str] = None) -> dict:
    q = "SELECT kind, answer, outcome, quality FROM hq_suggestions WHERE outcome IN ('good', 'bad')"
    rows = con.execute(q + (" AND model=?" if model else ""), [model] if model else []).fetchall()
    by: Dict[str, dict] = {}
    for kind, ans, out, qual in rows:
        d = by.setdefault(kind, {"n": 0, "good": 0, "taken": [0, 0], "declined": [0, 0], "none": [0, 0]})
        d["n"] += 1
        d["good"] += out == "good"
        d[ans][0] += out == "good"
        d[ans][1] += 1
    luck = {"sound_bad": 0, "sound_good": 0, "unsound_good": 0, "unsound_bad": 0, "weak_good": 0, "weak_bad": 0}
    for _k, _a, out, qual in rows:
        luck[f"{qual or 'sound'}_{out}"] = luck.get(f"{qual or 'sound'}_{out}", 0) + 1
    open_ = con.execute("SELECT count(*) FROM hq_suggestions WHERE scored_at IS NULL" + (" AND model=?" if model else ""),
                        [model] if model else []).fetchone()[0]
    return {"kinds": {k: {**d, "rate": smalln.rate(d["good"], d["n"])["text"]} for k, d in by.items()}, "luck": luck,
            "open": int(open_)}


def lessons_text(con, model: str) -> str:
    t = record_table(con, model)
    if not t["kinds"]:
        return (f"YOUR SUGGESTIONS' RECORD: nothing scored yet ({t['open']} open). Each suggestion is scored at its horizon "
                "on what the stock did against the Nifty 500, taken or not.")
    parts = []
    for k, d in sorted(t["kinds"].items()):
        tk = d["taken"]
        parts.append(f"{k}: {d['rate']} good ({d['good']} of {d['n']}; taken {tk[0]} of {tk[1]})")
    L = t["luck"]
    s = ("YOUR SUGGESTIONS' RECORD (scored on what followed, taken or declined; under 20 a count, not a rate): "
         + "; ".join(parts) + f". Sound at the time but went badly: {L['sound_bad']} (luck, not a mistake); "
         f"unsound or weak but went well: {L['unsound_good'] + L['weak_good']} (luck, not skill). {t['open']} open. "
         "A few misses never retire a kind of suggestion.")
    last = con.execute("SELECT kind, symbol, outcome, outcome_json, quality FROM hq_suggestions WHERE model=? AND outcome IN "
                       "('good','bad') ORDER BY scored_at DESC LIMIT 3", [model]).fetchall()
    if last:
        s += " Latest: " + "; ".join(f"{k} {sym}: {o} ({json.loads(j)['excess_pct']:+.1f}% against the index; {q} at the time)"
                                     for k, sym, o, j, q in last)
    return s


def recent(con, limit: int = 40) -> List[dict]:
    keys = ["id", "pass", "model", "at", "kind", "symbol", "text", "reasoning", "horizon", "shadow", "quality", "quality_why",
            "answer", "answer_source", "outcome", "outcome_json"]
    rows = con.execute("SELECT sug_id, pass_id, model, made_at, kind, symbol, text, reasoning, horizon_days, shadow, quality, "
                       "quality_why, answer, answer_source, outcome, outcome_json FROM hq_suggestions ORDER BY sug_id DESC "
                       "LIMIT ?", [limit]).fetchall()
    out = []
    for r in rows:
        d = dict(zip(keys, r))
        d["outcome_json"] = json.loads(d["outcome_json"]) if d["outcome_json"] else None
        out.append(d)
    return out
