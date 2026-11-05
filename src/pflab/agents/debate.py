"""S79 item 12: a bull and a bear argue a contested move on the LOCAL model; only their disagreements go on, and the bear's warnings are scored.

    evidence    one block of numbers made by code (ids such as `calc.ret_20d`); both sides get the SAME block
    two passes  BULL and BEAR, separate prompts, every claim cites an evidence id as [F:id]; a draft the numeric guard (`llm/guard.py`) rejects is
                regenerated once with the violations named, then dropped and replaced by "no guarded argument"
    third step  the local model (constrained JSON, `llm/structured.py`) picks which bull sentence conflicts with which bear sentence; code checks the
                picks are real sentences and takes the evidence ids from the sentences' own citations. Agreement is dropped here: it is stored nowhere
                a reader sees and sent nowhere. The reviewer is handed only the disagreements (`disagreements_for_reviewer`).
    the warning the bear's one testable warning is chosen from a closed list (kind, horizon in sessions, threshold) and written by code as a
                statement ("X underperforms its benchmark over H sessions" / "X closes more than Y% below its reference close within H sessions").
                CODE resolves it on later prices (horizon counted in sessions of the market's own calendar) and `bear_scorecard` compares the hit
                rate with the stock's own base rate for the same statement. Under 20 resolved: the count and no conclusion.

Models never make numbers: every number in an argument equals an evidence value; the warning's numbers come from a closed list. Pre-registered
as docs/protocols/s79_debate_protocol.md. Tests inject the chat client and the price feed.
"""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

MODEL = "qwen3:8b-q8_0"
HORIZONS = (5, 10, 20)                      # sessions a warning may be about (closed list the model picks from)
LEVELS = (3, 5, 10)                         # "falls more than Y%" (closed list)
KINDS = ("underperform", "fall")
MIN_RESOLVED = 20                           # under this the scorecard is a count, not a conclusion (PLAN A9)
MIN_WINDOWS = 250                           # fewer history windows: no base rate (same rule as hq/keeper.py)
HISTORY_ROWS = 3 * 252
SLACK_DAYS = 4                              # the close used may be this many days before the target session
VOID_AFTER_DAYS = 10                        # no close near the target this long after it: void, never guessed
NO_ARGUMENT = "no guarded argument"
UNAVAILABLE = {"skipped": "local model unavailable"}

_CITE = re.compile(r"\[F:([A-Za-z0-9_.\-]+)\]")


# --- the price feed ----------------------------------------------------------------------------------------------------

@dataclass
class Feed:
    """Where prices come from: prices(isin, asof) -> daily closes up to asof; bench(asof) -> the market's benchmark closes up to asof."""
    prices: Callable[[str, date], pd.Series]
    bench: Callable[[date], pd.Series]


def default_feed(rt, market: str = "IN") -> Feed:
    """The research panel joined to the store (India, and the US sleeve through its pseudo-ISIN), the market's benchmark series from the data folder."""
    from pflab.hq import stocks
    con = rt.cursor()
    root = rt.data_root

    def prices(isin: str, asof: date) -> pd.Series:
        return stocks.closes(con, root, isin, asof)

    def bench(asof: date) -> pd.Series:
        try:
            if market == "US":
                df = pd.read_parquet(root / "global" / "US_SP500.parquet", columns=["date", "adj_close"])
                s = pd.Series(df["adj_close"].to_numpy(float), index=pd.to_datetime(df["date"])).sort_index()
            else:
                s = stocks.index_series(root)
            return s[s.index <= pd.Timestamp(asof)]
        except Exception:                                   # no benchmark file: only the fall warnings can be made
            return pd.Series(dtype=float)

    return Feed(prices, bench)


# --- evidence (all numbers by code) ----------------------------------------------------------------------------------------

def _pct(a: float, b: float) -> float:
    return round((a / b - 1.0) * 100.0, 2)


def _rsi(s: pd.Series, n: int = 14) -> Optional[float]:
    d = s.diff().dropna().iloc[-n:]
    if len(d) < n:
        return None
    up, dn = float(d.clip(lower=0).mean()), float((-d.clip(upper=0)).mean())
    return 100.0 if dn == 0 else round(100.0 - 100.0 / (1.0 + up / dn), 1)


def build_evidence(feed: Feed, isin: str, symbol: str, asof: date) -> Tuple[Dict[str, Tuple[str, Any]], Optional[str]]:
    """{evidence id: (label, value)} from closes dated <= asof only, and the last close's date; ({}, why) when there is too little history."""
    s = feed.prices(isin, asof)
    s = s[s.index <= pd.Timestamp(asof)].dropna() if len(s) else s
    if len(s) < 70:
        return {}, f"only {len(s)} closes on record for {symbol}"
    last = float(s.iloc[-1])
    ev: Dict[str, Tuple[str, Any]] = {"calc.close": ("last close (adjusted)", round(last, 2)), "calc.close_date": ("date of that close", s.index[-1].date())}
    for n in (1, 5, 20, 60):
        ev[f"calc.ret_{n}d"] = (f"return over the last {n} sessions, %", _pct(last, float(s.iloc[-1 - n])))
    r = s.pct_change().dropna()
    sd = float(r.iloc[-61:-1].std()) if len(r) > 61 else float("nan")
    if sd and math.isfinite(sd) and sd > 0:
        ev["calc.move_sigma"] = ("the last day's move in standard deviations of the prior 60 daily moves", round(float(r.iloc[-1]) / sd, 2))
        ev["calc.vol_60d"] = ("annualised volatility of the last 60 daily moves, %", round(sd * math.sqrt(252) * 100.0, 1))
    w = s.iloc[-252:]
    ev["calc.below_high"] = ("% the last close is above (+) or below (-) its 252-session high", _pct(last, float(w.max())))
    ev["calc.above_low"] = ("% the last close is above (+) its 252-session low", _pct(last, float(w.min())))
    if len(s) >= 200:
        ev["calc.vs_sma200"] = ("% the last close is above (+) or below (-) its 200-session average", _pct(last, float(s.iloc[-200:].mean())))
    rsi = _rsi(s)
    if rsi is not None:
        ev["calc.rsi14"] = ("14-session RSI (0 to 100)", rsi)
    b = feed.bench(asof)
    if len(b) > 21:
        b = b[b.index <= pd.Timestamp(asof)]
        a20 = ev["calc.ret_20d"][1]
        b20 = _pct(float(b.iloc[-1]), float(b.iloc[-21]))
        ev["calc.bench_ret_20d"] = ("benchmark return over the last 20 sessions, %", b20)
        ev["calc.excess_20d"] = ("the stock's 20-session return minus the benchmark's, points", round(a20 - b20, 2))
    # the readings that conflict, by rule (words only): this is what makes a move contested
    short, long_ = ev["calc.ret_20d"][1], ev.get("calc.vs_sma200", (None, None))[1]
    conflicts = []
    if long_ is not None and short > 0 and long_ < 0:
        conflicts.append("the month is up while the price is still under its long-term average")
    if long_ is not None and short < 0 and long_ > 0:
        conflicts.append("the month is down while the price is still over its long-term average")
    if rsi is not None and rsi >= 70 and ev["calc.ret_60d"][1] > 0:
        conflicts.append("momentum is strong but the price looks stretched")
    if rsi is not None and rsi <= 30 and ev["calc.below_high"][1] < -20:
        conflicts.append("the price is deeply sold down and oversold")
    if "calc.excess_20d" in ev and (ev["calc.excess_20d"][1] > 0) != (ev["calc.ret_20d"][1] > 0):
        conflicts.append("the stock's own direction and its standing against the benchmark disagree")
    if "calc.move_sigma" in ev and abs(ev["calc.move_sigma"][1]) >= 2:
        conflicts.append("the last day's move was unusually large for this stock")
    for i, c in enumerate(conflicts, 1):
        ev[f"calc.reading_{i}"] = ("a reading by rule", c)
    for n in (1, 5, 14, 20, 60, 200, 252):                    # window lengths named in the labels are code constants the text may repeat
        ev[f"calc.w{n}"] = ("a window length used above, sessions", n)
    return ev, None


def normalise(evidence: Dict[str, Any]) -> Dict[str, Tuple[str, Any]]:
    """Accepts {id: value}, {id: (label, value)} or {id: {"label":..., "value":...}}."""
    out = {}
    for k, v in (evidence or {}).items():
        if isinstance(v, dict) and "value" in v:
            out[str(k)] = (str(v.get("label", "")), v["value"])
        elif isinstance(v, tuple) and len(v) == 2 and isinstance(v[0], str):
            out[str(k)] = (v[0], v[1])
        else:
            out[str(k)] = ("", v)
    return out


def block(ev: Dict[str, Tuple[str, Any]]) -> str:
    return "\n".join(f"[F:{k}] {lab or k} = {v}" for k, (lab, v) in ev.items())


# --- the two sides -----------------------------------------------------------------------------------------------------

RULES = ("Use ONLY the evidence block. Write 3 or 4 short sentences. Every sentence ends with a citation naming the evidence line it rests on, written "
         "exactly like [F:calc.ret_20d]. Every number you write must be copied digit for digit from the block (a rounded copy is fine); do not add, "
         "subtract or divide numbers, do not spell numbers out in words, do not state a price target, an amount or a date that is not in the block.")
SIDES = {
    "bull": "You are the BULL analyst in a desk debate. Make the strongest honest case that this move is healthy or the stock deserves to be held or bought, "
            "and say what in the block the bear will have to explain away. ",
    "bear": "You are the BEAR analyst in a desk debate. Make the strongest honest case that this move is a trap or the stock deserves caution, and say "
            "what in the block the bull will have to explain away. ",
}


def _cites(text: str) -> List[str]:
    out: List[str] = []
    for c in _CITE.findall(text or ""):
        if c not in out:
            out.append(c)
    return out


def _side(side: str, chat: Callable, subject: str, ev: Dict[str, Tuple[str, Any]], topic: str) -> dict:
    """One guarded argument. Returns {text|None, status, ids, attempts, seconds}."""
    from pflab.llm import guard
    t0 = time.time()
    system = SIDES[side] + RULES

    def llm(prompt: str) -> str:
        return chat(MODEL, [{"role": "system", "content": system}, {"role": "user", "content": prompt}], num_predict=380, num_ctx=4096, purpose="debate").text

    prompt = f"SUBJECT: {subject}\n" + (f"QUESTION: {topic}\n" if topic else "") + "EVIDENCE BLOCK (made by code; the same block the other side has):\n" + block(ev)
    facts = {k: v for k, (_, v) in ev.items()}
    out = guard.guarded_generate(llm, prompt, facts, None, retries=1)
    text = out.text.strip() if out.text else None
    if text and not _cites(text):                                    # a text with no citation at all is not an argument from the block
        text = None
    return {"text": text, "status": "ok" if text else NO_ARGUMENT, "ids": _cites(text or ""), "attempts": out.attempts,
            "violations": [[v.kind, v.text] for h in out.history for v in h][:6], "seconds": round(time.time() - t0, 1)}


# --- the disagreements ----------------------------------------------------------------------------------------------------

DIS_SYSTEM = ("You compare two arguments, numbered by sentence. Pick only the pairs of sentences (one bull, one bear) that CONTRADICT each other or read "
              "the same evidence in opposite ways. Do not list points they agree on. Answer with JSON only. The topic is 2 to 8 words, in words only.")
DIS_SCHEMA = {"type": "object", "properties": {"disagreements": {"type": "array", "maxItems": 4, "items": {
    "type": "object", "properties": {"topic": {"type": "string"}, "bull": {"type": "integer"}, "bear": {"type": "integer"}},
    "required": ["topic", "bull", "bear"]}}}, "required": ["disagreements"]}


def sentences(text: str) -> List[str]:
    from pflab.llm import guard
    return guard._sentences(text or "")


STANCE_SYSTEM = ("STANCE of each sentence, read alone: 'favourable' if it argues for holding or buying the stock, 'unfavourable' if it argues for caution, "
                 "selling or avoiding it, 'neutral' if it only states a fact. A sentence that says the stock is oversold or may rebound is favourable; one that "
                 "says it is weak, stretched or may fall further is unfavourable. JSON only.")
STANCE_SCHEMA = {"type": "object", "properties": {"stances": {"type": "array", "items": {
    "type": "object", "properties": {"id": {"type": "string"}, "stance": {"type": "string", "enum": ["favourable", "unfavourable", "neutral"]}},
    "required": ["id", "stance"]}}}, "required": ["stances"]}


def stances(bs: List[str], rs: List[str], chat: Callable):
    """{sentence id (B1.. R1..): stance} or the error text."""
    from pflab.llm import structured
    ids = [f"B{i}" for i in range(1, len(bs) + 1)] + [f"R{i}" for i in range(1, len(rs) + 1)]

    def check(o: dict) -> Optional[str]:
        got = {x.get("id") for x in o.get("stances", [])}
        return None if got >= set(ids) else f"give a stance for every id: {ids}"

    prompt = "\n".join(f"{i}. {s}" for i, s in zip(ids, bs + rs))
    res = structured.ask_json(STANCE_SYSTEM, prompt, STANCE_SCHEMA, check, purpose="debate", model=MODEL, num_predict=300, num_ctx=4096, chat=chat)
    return {x["id"]: x["stance"] for x in res.value["stances"]} if res.ok else (res.error or "stance step failed")


def disagreements(bull: dict, bear: dict, chat: Callable, ev: Dict[str, Tuple[str, Any]]) -> Tuple[List[dict], Optional[str]]:
    """[{topic, bull_says, bear_says, bull_ids, bear_ids}] and an error, if any. Needs both sides to have a guarded argument."""
    from pflab.llm import structured
    if not bull.get("text") or not bear.get("text"):
        return [], "one side has no guarded argument"
    bs, rs = sentences(bull["text"]), sentences(bear["text"])
    if not bs or not rs:
        return [], "no sentences"

    def check(o: dict) -> Optional[str]:
        items = o.get("disagreements")
        if not isinstance(items, list):
            return "disagreements must be a list"
        for it in items:
            if not (1 <= it.get("bull", 0) <= len(bs) and 1 <= it.get("bear", 0) <= len(rs)):
                return f"bull must be 1..{len(bs)} and bear 1..{len(rs)}"
            t = str(it.get("topic", "")).strip()
            if not t or len(t) > 90 or re.search(r"\d", t):
                return "the topic must be 2 to 8 words with no digits"
        return None

    prompt = ("BULL sentences:\n" + "\n".join(f"B{i}. {s}" for i, s in enumerate(bs, 1)) + "\nBEAR sentences:\n" + "\n".join(f"R{i}. {s}" for i, s in enumerate(rs, 1)) +
              "\nGive the pairs that disagree, as bull = the B number and bear = the R number. An empty list if they agree.")
    res = structured.ask_json(DIS_SYSTEM, prompt, DIS_SCHEMA, check, purpose="debate", model=MODEL, num_predict=400, num_ctx=4096, chat=chat)
    if not res.ok:
        return [], res.error
    picks = res.value["disagreements"]
    if not picks:
        return [], None
    st = stances(bs, rs, chat)                                    # the 8B model pairs sentences too eagerly: keep a pair only if the two read OPPOSITE ways
    if isinstance(st, str):
        return [], st
    out, seen = [], set()
    for it in picks:
        key = (it["bull"], it["bear"])
        if key in seen or {st[f"B{it['bull']}"], st[f"R{it['bear']}"]} != {"favourable", "unfavourable"}:
            continue
        seen.add(key)
        b, r = bs[it["bull"] - 1], rs[it["bear"] - 1]
        out.append({"topic": it["topic"].strip(), "bull_says": b, "bear_says": r, "bull_ids": _cites(b), "bear_ids": _cites(r)})
    return out, None


# --- the bear's warning ---------------------------------------------------------------------------------------------------

WARN_SYSTEM = ("From the bear's argument, choose ONE warning that can be tested on later prices, or none. Choose only from the lists. "
               "kind 'underperform': the stock does less than its benchmark over the horizon. kind 'fall': the stock closes more than threshold_pct "
               "below its last close on some session within the horizon. 'because' lists the evidence ids the warning rests on. JSON only.")
WARN_SCHEMA = {"type": "object", "properties": {
    "warn": {"type": "boolean"}, "kind": {"type": "string", "enum": list(KINDS)},
    "horizon_sessions": {"type": "integer", "enum": list(HORIZONS)}, "threshold_pct": {"type": "integer", "enum": list(LEVELS)},
    "because": {"type": "array", "items": {"type": "string"}, "maxItems": 4}}, "required": ["warn", "kind", "horizon_sessions", "threshold_pct", "because"]}


def choose_warning(bear: dict, chat: Callable, ev: Dict[str, Tuple[str, Any]], has_bench: bool) -> Tuple[Optional[dict], Optional[str]]:
    from pflab.llm import structured
    if not bear.get("text"):
        return None, "no guarded bear argument"

    def check(o: dict) -> Optional[str]:
        if not o.get("warn"):
            return None
        if o.get("kind") not in KINDS or o.get("horizon_sessions") not in HORIZONS or o.get("threshold_pct") not in LEVELS:
            return "kind, horizon_sessions and threshold_pct must come from the lists"
        if o["kind"] == "underperform" and not has_bench:
            return "there is no benchmark series: choose kind fall"
        bad = [x for x in o.get("because", []) if x not in ev]
        if bad or not o.get("because"):
            return f"because must name evidence ids from the block (not: {bad})"
        return None

    prompt = ("BEAR ARGUMENT:\n" + bear["text"] + "\nEVIDENCE IDS: " + ", ".join(ev) + f"\nHorizons {list(HORIZONS)} sessions; thresholds {list(LEVELS)} percent.")
    res = structured.ask_json(WARN_SYSTEM, prompt, WARN_SCHEMA, check, purpose="debate", model=MODEL, num_predict=250, num_ctx=4096, chat=chat)
    if not res.ok:
        return None, res.error
    return (res.value if res.value.get("warn") else None), None


def claim_text(symbol: str, kind: str, h: int, y: Optional[float], bench: str, ref_date: date) -> str:
    if kind == "underperform":
        return f"{symbol} underperforms {bench} over the next {h} sessions after the close of {ref_date}."
    return f"{symbol} closes more than {y:g}% below its close of {ref_date} on some session within the next {h} sessions."


def base_rate(kind: str, h: int, y: float, s: pd.Series, b: pd.Series) -> Optional[float]:
    """How often the stock's own last three years (rows are sessions) made this statement come true; None under MIN_WINDOWS windows."""
    s = s.dropna().iloc[-HISTORY_ROWS:]
    if kind == "fall":
        if len(s) <= h + MIN_WINDOWS - 1:
            return None
        v = s.to_numpy(float)
        win = np.lib.stride_tricks.sliding_window_view(v[1:], h)[: len(v) - h]
        return float(np.mean(win.min(axis=1) / v[: len(v) - h] - 1.0 < -y / 100.0))
    j = pd.concat([s.rename("s"), b.rename("b")], axis=1, join="inner").dropna()
    if len(j) <= h + MIN_WINDOWS - 1:
        return None
    r = (j.shift(-h) / j - 1.0).dropna()
    return float(np.mean(r["s"] < r["b"]))


def make_warning(con, mk, feed: Feed, debate_id: int, symbol: str, isin: str, choice: dict, now: datetime) -> Optional[int]:
    from pflab.pm.store import next_id
    s = feed.prices(isin, now.date())
    s = s[s.index <= pd.Timestamp(now.date())].dropna() if len(s) else s
    if s.empty:
        return None
    ref_date, ref_close = s.index[-1].date(), float(s.iloc[-1])
    kind, h = choice["kind"], int(choice["horizon_sessions"])
    y = float(choice["threshold_pct"]) if kind == "fall" else None
    b = feed.bench(now.date())
    b = b[b.index <= pd.Timestamp(ref_date)] if len(b) else b
    bench_ref = float(b.iloc[-1]) if len(b) else None
    if kind == "underperform" and bench_ref is None:
        return None
    due = mk.session_after(ref_date, h)
    wid = next_id(con, "bear_warnings_s79", "warning_id")
    con.execute("INSERT INTO bear_warnings_s79 (warning_id, debate_id, market, symbol, isin, claim, direction, horizon_sessions, benchmark, threshold_pct, ref_date, "
                "ref_close, bench_ref, base_rate, made_at, due_date) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [wid, debate_id, mk.code, symbol, isin, claim_text(symbol, kind, h, y, mk.benchmark, ref_date), kind, h, mk.benchmark, y, ref_date, ref_close,
                 bench_ref, base_rate(kind, h, y or 0.0, s, b), now, due])
    return wid


def _at_or_before(s: pd.Series, d: date) -> Optional[Tuple[date, float]]:
    s = s[s.index <= pd.Timestamp(d)]
    return (s.index[-1].date(), float(s.iloc[-1])) if len(s) else None


def resolve_open(con, now: datetime, feed_for: Callable[[str], Feed]) -> dict:
    """Resolve every open warning that is due by CODE on prices dated after the warning. A hit is the warning coming true. One whose target session has no
    close near it long after it passed is void (never guessed). Returns counts."""
    from pflab import markets
    out = {"resolved": 0, "hits": 0, "void": 0, "waiting": 0}
    rows = con.execute("SELECT warning_id, market, isin, symbol, direction, horizon_sessions, threshold_pct, ref_date, ref_close, bench_ref, due_date "
                       "FROM bear_warnings_s79 WHERE outcome IS NULL ORDER BY warning_id").fetchall()
    feeds: Dict[str, Feed] = {}
    for wid, mkt, isin, sym, kind, h, y, ref_date, ref_close, bench_ref, due in rows:
        mk = markets.get(mkt)
        target = mk.session_after(ref_date, h)
        if now.date() < target:
            out["waiting"] += 1
            continue
        feed = feeds.setdefault(mkt, feed_for(mkt))
        s = feed.prices(isin, now.date())
        s = s[s.index <= pd.Timestamp(now.date())].dropna() if len(s) else s
        end = _at_or_before(s, target) if len(s) else None
        stale = end is None or end[0] <= ref_date or (target - end[0]).days > SLACK_DAYS or s.index[-1].date() < target
        if stale:
            if (now.date() - target).days > VOID_AFTER_DAYS:
                con.execute("UPDATE bear_warnings_s79 SET resolved_at=?, outcome='void', detail=? WHERE warning_id=?", [now, "no close near the target session", wid])
                out["void"] += 1
            else:
                out["waiting"] += 1
            continue
        path = s[(s.index > pd.Timestamp(ref_date)) & (s.index <= pd.Timestamp(target))]
        stock_ret = _pct(end[1], ref_close)
        if kind == "fall":
            worst = _pct(float(path.min()), ref_close)
            hit, detail = worst < -float(y), f"lowest close {worst:+.2f}% from {ref_date} (rule: below -{float(y):g}%), {stock_ret:+.2f}% at {end[0]}"
        else:
            b = feed.bench(now.date())
            be = _at_or_before(b, target) if len(b) else None
            if be is None or bench_ref is None or (target - be[0]).days > SLACK_DAYS:
                if (now.date() - target).days > VOID_AFTER_DAYS:
                    con.execute("UPDATE bear_warnings_s79 SET resolved_at=?, outcome='void', detail=? WHERE warning_id=?", [now, "no benchmark close near the target", wid])
                    out["void"] += 1
                else:
                    out["waiting"] += 1
                continue
            b_ret = _pct(be[1], bench_ref)
            hit, detail = stock_ret < b_ret, f"stock {stock_ret:+.2f}% against benchmark {b_ret:+.2f}% from {ref_date} to {end[0]}"
        con.execute("UPDATE bear_warnings_s79 SET resolved_at=?, outcome=?, hit=?, detail=? WHERE warning_id=?", [now, "hit" if hit else "miss", bool(hit), detail, wid])
        out["resolved"] += 1
        out["hits"] += int(hit)
    return out


def bear_scorecard(con, market: str = "IN") -> dict:
    """How often the bear's warnings came true against how often such statements come true by chance for the same stocks. Under MIN_RESOLVED: counts only."""
    rows = con.execute("SELECT hit, base_rate FROM bear_warnings_s79 WHERE market=? AND outcome IN ('hit','miss')", [market]).fetchall()
    n, hits = len(rows), sum(1 for r in rows if r[0])
    open_n = con.execute("SELECT count(*) FROM bear_warnings_s79 WHERE market=? AND outcome IS NULL", [market]).fetchone()[0]
    void_n = con.execute("SELECT count(*) FROM bear_warnings_s79 WHERE market=? AND outcome='void'", [market]).fetchone()[0]
    out = {"market": market, "resolved": n, "hits": hits, "open": int(open_n), "void": int(void_n), "conclusion": None}
    if n < MIN_RESOLVED:
        out["note"] = f"{n} resolved, {hits} came true; under {MIN_RESOLVED} resolved the count is all there is: no conclusion"
        return out
    with_base = [r for r in rows if r[1] is not None]
    out["hit_rate"] = round(hits / n, 3)
    if len(with_base) >= MIN_RESOLVED:
        p = np.array([r[1] for r in with_base], float)
        k = sum(1 for r in with_base if r[0])
        var = float((p * (1 - p)).sum())
        z = (k - float(p.sum())) / math.sqrt(var) if var > 0 else 0.0
        out.update({"base_rate": round(float(p.mean()), 3), "hit_rate_on_those": round(k / len(with_base), 3), "z": round(z, 2), "n_with_base": len(with_base)})
        out["conclusion"] = ("the bear's warnings come true more often than chance" if z >= 1.96 else
                             "the bear's warnings come true less often than chance" if z <= -1.96 else "no difference from chance shown")
    else:
        out["note"] = "too few warnings have a base rate (under 250 history windows): no conclusion"
    return out


# --- the debate -----------------------------------------------------------------------------------------------------------

def _down(err: Optional[str]) -> bool:
    return bool(err) and str(err).split(":")[0] in ("OllamaError", "ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout", "TimeoutError", "Busy", "HTTPError")


def _chat_default() -> Callable:
    from pflab.llm import client
    return client.chat


def debate(rt, market: str, symbol: str, evidence: Dict[str, Any], now: datetime, *, isin: Optional[str] = None, topic: str = "",
           case_id: Optional[int] = None, chat: Optional[Callable] = None, feed: Optional[Feed] = None) -> dict:
    """Run one debate on `evidence` (ids -> values made by code) and keep it. Never raises when the local model is down: returns {"skipped": ...}.
    The result carries only the disagreements and the bear's warning; the two full arguments are kept in `debates_s79` for audit."""
    from pflab import markets
    from pflab.llm.client import OllamaError
    from pflab.pm.store import next_id
    chat = chat or _chat_default()
    con = rt.cursor()
    mk = markets.get(market)
    ev = normalise(evidence)
    if not ev:
        return {"skipped": "no evidence given"}
    subject = (symbol or "").strip().upper()
    t0 = time.time()
    try:
        bull = _side("bull", chat, subject, ev, topic)
        bear = _side("bear", chat, subject, ev, topic)
        dis, dis_err = disagreements(bull, bear, chat, ev)
        choice, w_err = (choose_warning(bear, chat, ev, True) if bear.get("text") else (None, "no guarded bear argument"))
    except OllamaError:
        return dict(UNAVAILABLE)
    except Exception as e:                                       # a down server may surface as a connection error from a fake or a transport
        if isinstance(e, (ConnectionError, TimeoutError, OSError)) or "refused" in str(e).lower() or "unreachable" in str(e).lower():
            return dict(UNAVAILABLE)
        raise
    if _down(dis_err) or _down(w_err):                           # structured.ask_json swallows a transport error into its result: "OllamaError: ..."
        return dict(UNAVAILABLE)
    status = ("no_guarded_argument" if not bull["text"] and not bear["text"] else "one_side_missing" if not (bull["text"] and bear["text"]) else
              "extract_failed" if dis_err else "done")
    did = next_id(con, "debates_s79", "debate_id")
    used = sorted({i for d in dis for i in d["bull_ids"] + d["bear_ids"]})
    con.execute("INSERT INTO debates_s79 (debate_id, market, subject, symbol, case_id, created_at, bull_json, bear_json, disagreements_json, evidence_ids, evidence_json, "
                "status, seconds) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [did, mk.code, subject, subject, case_id, now, json.dumps(bull), json.dumps(bear), json.dumps(dis), json.dumps(sorted(ev)),
                 json.dumps({k: [lab, str(v)] for k, (lab, v) in ev.items()}), status, round(time.time() - t0, 1)])
    warning = None
    if choice and isin and feed is not None:
        wid = make_warning(con, mk, feed, did, subject, isin, choice, now)
        if wid:
            warning = dict(zip(("warning_id", "claim", "horizon_sessions", "base_rate", "due_date"),
                               con.execute("SELECT warning_id, claim, horizon_sessions, base_rate, due_date FROM bear_warnings_s79 WHERE warning_id=?", [wid]).fetchone()))
            warning["due_date"] = str(warning["due_date"])
    return {"debate_id": did, "status": status, "disagreements": dis, "evidence_used": used, "bear_warning": warning, "warning_note": w_err if not choice else None,
            "extract_error": dis_err, "seconds": round(time.time() - t0, 1),
            "steps": {"bull": [bull["status"], bull["attempts"], bull["seconds"]], "bear": [bear["status"], bear["attempts"], bear["seconds"]]}}


def debate_symbol(rt, market: str, symbol: str, isin: str, now: datetime, *, topic: str = "", case_id: Optional[int] = None,
                  chat: Optional[Callable] = None, feed: Optional[Feed] = None) -> dict:
    """Build the evidence block from prices (code) and debate it."""
    feed = feed or default_feed(rt, market)
    ev, why = build_evidence(feed, isin, symbol, now.date())
    if not ev:
        return {"skipped": why}
    return debate(rt, market, symbol, ev, now, isin=isin, topic=topic, case_id=case_id, chat=chat, feed=feed)


# --- the hand-off to the reviewer ------------------------------------------------------------------------------------------------

def disagreements_for_reviewer(con, case_id_or_subject, max_debates: int = 3) -> str:
    """Compact text for the reviewer's dossier: ONLY the points the bull and the bear disagree on, each with the evidence ids each relied on (and their
    values), the bear's open warning and the bear's record. "" when there is nothing to show. Agreement and the full arguments are not included."""
    key = case_id_or_subject
    rows: list = []
    cols = "debate_id, subject, created_at, disagreements_json, evidence_json, status"
    try:
        if isinstance(key, int):
            rows = con.execute(f"SELECT {cols} FROM debates_s79 WHERE case_id=? AND status='done' ORDER BY debate_id DESC LIMIT ?", [key, max_debates]).fetchall()
            if not rows:
                sub = con.execute("SELECT subject FROM hq_cases WHERE case_id=?", [key]).fetchone()
                key = (sub[0] if sub and sub[0] else None)
        if not rows and isinstance(key, str) and key:
            rows = con.execute(f"SELECT {cols} FROM debates_s79 WHERE status='done' AND (upper(subject)=upper(?) OR upper(symbol)=upper(?)) "
                               "ORDER BY debate_id DESC LIMIT ?", [key, key, max_debates]).fetchall()
    except Exception:                                    # the tables are not there yet: nothing to attach
        return ""
    lines: List[str] = []
    for did, subject, at, dj, ej, _ in rows:
        dis, evj = json.loads(dj or "[]"), json.loads(ej or "{}")
        if not dis:
            continue
        lines.append(f"DEBATE #{did} on {subject} ({str(at)[:16]}, bull and bear on the local model; ONLY the points they disagree on; ids are evidence ids, values made by code):")
        shown: Dict[str, str] = {}
        for i, d in enumerate(dis, 1):
            lines.append(f"  {i}. {d['topic']}: BULL \"{d['bull_says']}\" vs BEAR \"{d['bear_says']}\" (bull relied on {', '.join(d['bull_ids']) or 'inference'}; "
                         f"bear relied on {', '.join(d['bear_ids']) or 'inference'})")
            for k in d["bull_ids"] + d["bear_ids"]:
                if k in evj and not k.startswith("calc.w"):
                    shown[k] = f"{evj[k][0] or k} = {evj[k][1]}"
        if shown:
            lines.append("  evidence: " + "; ".join(f"{k}: {v}" for k, v in shown.items()))
        for claim, due, out in con.execute("SELECT claim, due_date, coalesce(outcome, 'open') FROM bear_warnings_s79 WHERE debate_id=?", [did]).fetchall():
            lines.append(f"  bear's warning ({out}, due {due}): {claim}")
    if lines:
        try:
            sc = bear_scorecard(con, "IN")
            lines.append(f"  bear's record so far: {sc['hits']} of {sc['resolved']} warnings came true" + ("" if sc.get("conclusion") else " (too few to conclude)"))
        except Exception:
            pass
    return "\n".join(lines)
