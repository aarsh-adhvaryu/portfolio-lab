"""Scanners (S64 Phase 5 item 9; the Streak idea, without its backtest that flatters).

A scan is a list of conditions from a CLOSED set, written in a small text form ("price_below_sma:200; volume_spike:2"),
evaluated by code over a universe (holdings, his list, or the Nifty 500) as of a date. A hit is information: the numbers that
made it true. A scan used as a buying rule is NOT tested here: it is tested only through the learner, as a claim on the
`scan_rule` template (conditions -> next-month return in excess of the Nifty 500, after costs), registered before its run
and counted by the test counter. Until a claim passes, the scan is labelled "not tested: information, not evidence".

Conditions (name:value):
    price_below_sma:N / price_above_sma:N      close against its N-day average (N in 20, 50, 200)
    cross_up_sma:N / cross_down_sma:N          close crossed the N-day average within the last 5 sessions
    rsi_below:V / rsi_above:V                  RSI(14), Wilder
    near_52w_high:PCT / near_52w_low:PCT       within PCT percent of the 52-week high / low
    ath_fall_at_least:PCT                      at least PCT percent below its all-time high in the data
    volume_spike:MULT                          today's volume more than MULT times its 20-day average
    pe_above_median:MULT / pe_below_median:MULT  P/E against its own 5-year median (holdings and list only)
    alpha_negative / alpha_positive            sign of the CAPM alpha (holdings and list only)
    buildup:CLASS                              futures build-up class: long build-up, short build-up, short covering, long unwinding
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

UNIVERSES = ("holdings", "list", "nifty500")
SMA = (20, 50, 200)
CLASSES = ("long build-up", "short build-up", "short covering", "long unwinding")
CROSS_WITHIN = 5
NAMES = ("price_below_sma", "price_above_sma", "cross_up_sma", "cross_down_sma", "rsi_below", "rsi_above", "near_52w_high",
         "near_52w_low", "ath_fall_at_least", "volume_spike", "pe_above_median", "pe_below_median", "alpha_negative",
         "alpha_positive", "buildup")
NEEDS_FACTS = {"pe_above_median", "pe_below_median", "alpha_negative", "alpha_positive"}      # holdings and list only
STARTERS = [
    ("Near its 52-week low", "near_52w_low:5", "list"),
    ("Volume spike (over 2x its 20-day average)", "volume_spike:2", "list"),
    ("Below its 200-day average", "price_below_sma:200", "list"),
    ("Alpha turned negative", "alpha_negative", "list"),
]
LABEL_UNTESTED = "not tested: information, not evidence"


def parse(text: str) -> List[dict]:
    """"a:1; b" -> [{"name": "a", "value": "1"}, {"name": "b", "value": None}], every part checked against the closed set."""
    out = []
    for part in [p.strip() for p in str(text).split(";") if p.strip()]:
        name, _, val = part.partition(":")
        name, val = name.strip(), val.strip() or None
        if name not in NAMES:
            raise ValueError(f"unknown condition {name!r}; one of {', '.join(NAMES)}")
        if name in ("alpha_negative", "alpha_positive"):
            val = None
        elif name == "buildup":
            if val not in CLASSES:
                raise ValueError(f"buildup is one of {', '.join(CLASSES)}")
        else:
            try:
                x = float(val)
            except (TypeError, ValueError):
                raise ValueError(f"{name} needs a number, as {name}:N")
            if name.endswith("_sma") and int(x) not in SMA:
                raise ValueError(f"{name}: N is one of {SMA}")
            if not 0 < x < 1000:
                raise ValueError(f"{name}: {x} is out of range")
            val = str(int(x)) if name.endswith("_sma") else str(x)
        out.append({"name": name, "value": val})
    if not out:
        raise ValueError("a scan needs at least one condition")
    if len(out) > 6:
        raise ValueError("at most 6 conditions in a scan")
    return out


def text_of(conds: List[dict]) -> str:
    return "; ".join(c["name"] + (f":{c['value']}" if c["value"] else "") for c in conds)


def indicators(close: pd.Series, volume_ratio: Optional[float] = None) -> dict:
    """Price indicators from the adjusted close series (oldest first)."""
    from pflab.quant import technicals as tc
    c = close.dropna()
    if len(c) < 30:
        return {"sessions": int(len(c))}
    px = float(c.iloc[-1])
    out: dict = {"sessions": int(len(c)), "close": px}
    for n in SMA:
        if len(c) >= n + CROSS_WITHIN:
            m = c.rolling(n).mean()
            out[f"sma{n}"] = float(m.iloc[-1])
            side = np.sign((c - m).iloc[-(CROSS_WITHIN + 1):].to_numpy())
            out[f"cross_up_{n}"] = bool(side[-1] > 0 and (side[:-1] < 0).any())
            out[f"cross_down_{n}"] = bool(side[-1] < 0 and (side[:-1] > 0).any())
    out["rsi14"] = float(tc.rsi(c).iloc[-1]) if len(c) > 30 else None
    y = c.iloc[-250:]
    out["from_high52_pct"] = (px / float(y.max()) - 1.0) * 100.0
    out["above_low52_pct"] = (px / float(y.min()) - 1.0) * 100.0
    out["from_ath_pct"] = (px / float(c.max()) - 1.0) * 100.0
    out["ath_window_years"] = round(len(c) / 250.0, 1)
    out["volume_ratio"] = volume_ratio
    return out


def holds(cond: dict, ind: dict, facts: dict) -> Tuple[Optional[bool], str]:
    """(True/False/None for unknown, the numbers behind it)."""
    n, v = cond["name"], cond["value"]
    x = float(v) if v and n != "buildup" else None
    if n in ("price_below_sma", "price_above_sma"):
        s = ind.get(f"sma{int(x)}")
        if s is None:
            return None, "too little history"
        below = ind["close"] < s
        return (below if n == "price_below_sma" else not below), f"close {ind['close']:,.2f} vs {int(x)}-day {s:,.2f}"
    if n in ("cross_up_sma", "cross_down_sma"):
        f = ind.get(f"{'cross_up' if n == 'cross_up_sma' else 'cross_down'}_{int(x)}")
        return f, f"{'up' if n == 'cross_up_sma' else 'down'} through the {int(x)}-day average within {CROSS_WITHIN} sessions"
    if n in ("rsi_below", "rsi_above"):
        r = ind.get("rsi14")
        if r is None:
            return None, "no RSI"
        return (r < x if n == "rsi_below" else r > x), f"RSI {r:.0f}"
    if n == "near_52w_high":
        return ind["from_high52_pct"] >= -x, f"{ind['from_high52_pct']:.1f}% from the 52-week high"
    if n == "near_52w_low":
        return ind["above_low52_pct"] <= x, f"{ind['above_low52_pct']:.1f}% above the 52-week low"
    if n == "ath_fall_at_least":
        return ind["from_ath_pct"] <= -x, f"{ind['from_ath_pct']:.1f}% from its high of the last {ind['ath_window_years']} years"
    if n == "volume_spike":
        r = ind.get("volume_ratio")
        return (None, "no volume") if r is None else (r > x, f"volume {r:.1f}x its 20-day average")
    if n in ("pe_above_median", "pe_below_median"):
        pe, own = facts.get("pe_ttm"), (facts.get("pe_own_5y") or {})
        med = own.get("median") if isinstance(own, dict) else None
        if not pe or not med:
            return None, "no P/E or no own history"
        return (pe > x * med if n == "pe_above_median" else pe < x * med), f"P/E {pe:.1f} vs its median {med:.1f}"
    if n in ("alpha_negative", "alpha_positive"):
        a = facts.get("alpha_ann")
        if a is None:
            return None, "no CAPM fit"
        return (a < 0 if n == "alpha_negative" else a > 0), f"alpha {a * 100:+.1f}% a year (t {facts.get('alpha_t'):+.1f})"
    if n == "buildup":
        b = facts.get("buildup")
        return (None, "no futures") if not b else (b["class"] == v, f"futures: {b['class']}")
    return None, "unknown"


def universe_isins(con, root, universe: str, asof: date) -> Dict[str, str]:
    """isin -> symbol."""
    names = dict(con.execute("SELECT isin, symbol FROM instruments WHERE symbol IS NOT NULL").fetchall())
    if universe == "nifty500":
        from pflab.learner import templates as tp
        m = tp.members(Path(root))
        t = pd.Timestamp(asof)
        isins = m[(m["from_date"] <= t) & (m["to_date"] > t)]["isin"].tolist()
        return {i: names.get(i, i) for i in isins}
    from pflab.pm import today
    pos = today.build(con, asof)["positions"]
    held = {r.isin: r.symbol for r in pos.itertuples() if str(r.isin).startswith("INE") and r.qty > 0}
    if universe == "holdings":
        return held
    from pflab.plan import guards as gd
    return {**{s["isin"]: s["symbol"] for s in gd.stock_list()}, **held}


def evaluate(con, root, conds: List[dict], universe: str, asof: date, isins: Optional[Dict[str, str]] = None) -> dict:
    """{'hits': [{isin, symbol, why: [..]}], 'checked': n, 'unknown': n, 'skipped_conditions': [...]}"""
    from pflab.app import research
    from pflab.hq import valuation
    from pflab.quant import options, technicals as tc
    isins = isins if isins is not None else universe_isins(con, root, universe, asof)
    needs_facts = any(c["name"] in NEEDS_FACTS for c in conds)
    skipped = []
    if universe == "nifty500" and needs_facts:
        skipped = sorted(c["name"] for c in conds if c["name"] in NEEDS_FACTS)
        conds = [c for c in conds if c["name"] not in NEEDS_FACTS]
        needs_facts = False
        if not conds:
            return {"hits": [], "checked": 0, "unknown": 0, "skipped_conditions": skipped}
    want_ath = any(c["name"] == "ath_fall_at_least" for c in conds)
    want_vol = any(c["name"] == "volume_spike" for c in conds)
    bu = options.buildup_for(root, asof, list(isins.values())) if any(c["name"] == "buildup" for c in conds) else {}
    hits, unknown = [], 0
    for isin, sym in isins.items():
        c = research.closes(con, root, isin, asof, years=25 if want_ath else 2)
        vr = None
        if want_vol:
            s = tc.for_isin(root, isin, asof)
            vr = s.get("volume_ratio") if s else None
        ind = indicators(c, vr)
        facts: dict = {}
        if needs_facts and "close" in ind:
            if any(x["name"].startswith("pe_") for x in conds):
                try:
                    facts.update(valuation.facts(con, root, isin, sym, c, asof))
                except Exception:
                    pass
            if any(x["name"].startswith("alpha_") for x in conds):
                try:
                    from pflab.risk import capm
                    f = capm.for_isin(Path(root), isin, asof)
                    facts.update(alpha_ann=f.get("alpha_ann"), alpha_t=f.get("alpha_t") or 0.0)
                except Exception:
                    pass
        facts["buildup"] = bu.get(sym)
        if "close" not in ind:
            unknown += 1
            continue
        why, ok = [], True
        for cond in conds:
            res, note = holds(cond, ind, facts)
            if res is None:
                ok = None if ok is not False else False
            elif not res:
                ok = False
            why.append(f"{cond['name']}{':' + cond['value'] if cond['value'] else ''}: {note}")
        if ok:
            hits.append({"isin": isin, "symbol": sym, "close": ind["close"], "why": why})
        elif ok is None:
            unknown += 1
    return {"hits": hits, "checked": len(isins), "unknown": unknown, "skipped_conditions": skipped}


# --- the store: scans, their results, their tested label -----------------------------------------------------------------

def make_scan(con, name: str, text: str, universe: str, created_by: str, now: datetime) -> int:
    from pflab.pm.store import next_id
    if universe not in UNIVERSES:
        raise ValueError(f"universe is one of {UNIVERSES}")
    conds = parse(text)
    if con.execute("SELECT 1 FROM scans WHERE name=?", [name.strip()]).fetchone():
        raise ValueError(f"a scan named {name!r} exists")
    sid = next_id(con, "scans", "scan_id")
    con.execute("INSERT INTO scans (scan_id, name, conditions_json, universe, active, created_by, created_at) VALUES (?,?,?,?,?,?,?)",
                [sid, name.strip()[:80], json.dumps(conds), universe, True, created_by, now])
    return sid


def seed_starters(con, now: datetime) -> int:
    n = 0
    for name, text, universe in STARTERS:
        if not con.execute("SELECT 1 FROM scans WHERE name=?", [name]).fetchone():
            make_scan(con, name, text, universe, "starter", now)
            n += 1
    return n


def tested(con, scan_id: int) -> str:
    """'passed' / 'failed' from the learner's decision on the scan's claim, else 'not tested'."""
    r = con.execute("SELECT c.decision FROM scans s JOIN learn_claims c ON c.claim_id = s.claim_id WHERE s.scan_id=?", [scan_id]).fetchone()
    return {"pass": "passed", "fail": "failed"}.get(r[0] if r else None, "not tested")


def listing(con) -> List[dict]:
    out = []
    for sid, name, cj, uni, active, by, at in con.execute(
            "SELECT scan_id, name, conditions_json, universe, active, created_by, created_at FROM scans ORDER BY scan_id").fetchall():
        t = tested(con, sid)
        out.append({"scan_id": sid, "name": name, "conditions": text_of(json.loads(cj)), "universe": uni, "active": bool(active),
                    "created_by": by, "tested": t, "label": LABEL_UNTESTED if t == "not tested" else f"tested: {t}"})
    return out


def run_all(con, root, asof: date, now: datetime) -> dict:
    """Every active scan; hits on holdings or his list become held lines for the evening summary (never straight to Telegram)."""
    from pflab.service import telegram as tgm
    held = universe_isins(con, root, "list", asof)
    out, lines = {}, 0
    cache = {}
    for sid, name, cj, uni, in_by in con.execute("SELECT scan_id, name, conditions_json, universe, created_by FROM scans WHERE active "
                                                  "ORDER BY scan_id").fetchall():
        conds = json.loads(cj)
        try:
            r = evaluate(con, root, conds, uni, asof)
        except Exception as e:
            out[name] = f"failed: {type(e).__name__}: {str(e)[:100]}"
            continue
        out[name] = len(r["hits"])
        cache[sid] = {"name": name, "at": str(now)[:16], "hits": r["hits"][:60], "checked": r["checked"], "unknown": r["unknown"],
                      "skipped": r["skipped_conditions"]}
        for h in r["hits"]:
            if h["isin"] in held:
                lines += tgm.enqueue(con, f"Scan '{name}': {h['symbol']} ({'; '.join(h['why'])}). {LABEL_UNTESTED}.", "scan",
                                     dedup_key=f"scan:{sid}:{h['isin']}:{asof}", now=now) is not None
    out["_summary_lines"] = lines
    out["_cache"] = cache
    return out
