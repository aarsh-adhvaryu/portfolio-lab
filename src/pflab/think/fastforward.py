"""S86 H7 the fast-forward after every gap (A77; his words of 2026-11-13: "if the system is off, it covers the backlog, aligns news, data, maths, what caused what, and uses that as a forward test:
the same loop, but in fast forward").

When the app opens after a gap that contains at least one session of either market, AFTER the alarm lane has fetched the backlog (`think/alarm.py` `_gap`) and BEFORE the live book acts:
  1. WHAT CAUSED WHAT (code): for each held and picked name the move over the gap split into its market's part (beta x the index's move), its sector's part (not separated: no sector series is
     stored for a single name, said in the text) and its own part, with the headlines and filings dated inside the gap beside it. Stored as a note `recall` finds (source "fastforward").
  2. THE SAME LOOP IN FAST FORWARD, point in time: each RED headline or filing of the gap counts from its publication time plus the lane's own median delay (never earlier, never the web of
     today); the decision is the code rule the live loop's exit manager applies to a thesis break (a HIGH-severity break sells, a medium one only freezes buying), filled at the first CLOSE after the
     decision (no minute bars are stored for a gap) minus the slippage the fills use. The model's replayed look (at most three cases a gap, RED first) is NOT built tonight: every ghost row says
     `source = code`. It is on the list for Saturday.
  3. GHOST, NOT REAL: the decisions fill `ghost_s86`, never the paper book (a returning trader cannot trade in the past). Then the live book decides NOW, from today's prices.
  4. A FORWARD TEST: the code that replays was frozen before the gap, so a ghost decision is scored at 5, 20 and 60 sessions like a live one, in its own column `replayed_while_off`
     (`score_ghosts`, never mixed with the live scorecard). A gap that began before the running release's own date is not replayed (that would be a backtest of code written after the data).
  5. THE COST OF BEING OFF: ghost against real, in rupees ("Had I been on: sold Monday at 172.98; today it is 160.40: being off cost Rs 1,250", or "saved").
Bounded: a replay is stored per (gap, release) and never done twice; it runs in the catch-up's thread before the live book acts and never delays the live session loop.
Pre-tax: a ghost sale's score is the price move after the decision (tax is not replayed); the live scorecard stays after tax. Said in the column's label.
"""
from __future__ import annotations

import json
import statistics
from datetime import date, datetime, time, timedelta
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from pflab import think

LABEL = "replayed_while_off"
SLIP = 0.0005
HOLD_MARKERS = ("nothing", "hold", "freeze")


def enabled() -> bool:
    try:
        return bool(think.settings().get("fast_forward", True)) and think.on()
    except Exception:
        return False


def release_start() -> Optional[date]:
    """The running release's own date (from its tag vYYYY.MM.DD[.N]); None in the workshop (no release file: every gap may be replayed)."""
    try:
        from pflab import release
        r = release.load()
        tag = str(((r or {}).get("app") or {}).get("tag") or (r or {}).get("tag") or "")
        y, m, d = tag.lstrip("v").split(".")[:3]
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def _release_id() -> str:
    try:
        from pflab import release
        r = release.load()
        return str(((r or {}).get("app") or {}).get("tag") or "workshop")
    except Exception:
        return "workshop"


def hook() -> Optional[Callable]:
    return run_gap if enabled() else None


def _sessions(prev: datetime, now: datetime) -> Dict[str, List[date]]:
    from pflab import markets
    out = {}
    for m in markets.codes():
        try:
            out[m] = markets.get(m).sessions_between(prev.date(), now.date())
        except Exception:
            out[m] = []
    return out


def lane_delay_minutes(con) -> float:
    """The median minutes from first published to first seen in the lane's own live rows (15 when there are none yet)."""
    try:
        xs = [(b - a).total_seconds() / 60.0 for a, b in con.execute("SELECT published_at, first_seen_at FROM alarm_s86 WHERE coalesce(mode,'live')='live' AND published_at IS NOT NULL").fetchall()]
        return float(statistics.median(xs)) if xs else 15.0
    except Exception:
        return 15.0


def known_day(market: str, now: datetime) -> date:
    """The last session of `market` whose close had passed at `now` (point in time: a bar of a later session is never read, whatever the stored file holds)."""
    from pflab import markets
    if market == "US":
        from pflab.us import clock as uc
        return uc.session_closed_by(now, settle_minutes=30)
    return markets.get(market).session_closed_by(now)


def _closes(con, e: dict, upto: date, root) -> Optional[pd.Series]:
    from pflab.think import watch
    try:
        return watch._history(con, e["market"], e["isin"], e["symbol"], upto, root, watch.settings(), full=True)
    except Exception:
        return None


def _after(s: pd.Series, t: datetime) -> Optional[tuple]:
    """(date, close) of the first close at or after `t`'s own session close: a decision made before a session's close fills at that close; one made after it, at the next session's close."""
    for d, px in s.items():
        if pd.Timestamp(d) + pd.Timedelta(hours=15, minutes=30) > pd.Timestamp(t):
            return pd.Timestamp(d).date(), float(px)
    return None


def caused_by(con, entries: List[dict], prev: datetime, now: datetime, root) -> List[dict]:
    """For each held or picked name: return over the gap, split into market part (beta x index), sector part (not separated) and own part. Code only, point in time (closes on or before today)."""
    from pflab.think import watch
    out: List[dict] = []
    ix_cache: Dict[str, Optional[pd.Series]] = {}
    for e in entries:
        s = _closes(con, e, known_day(e["market"], now), root)
        if s is None or len(s) < 60:
            continue
        a = s[s.index <= pd.Timestamp(prev.date())]
        b = s[s.index > pd.Timestamp(prev.date())]
        if a.empty or b.empty:
            continue
        r_gap = float(b.iloc[-1] / a.iloc[-1] - 1.0)
        ix = ix_cache.setdefault(e["market"], watch._index(e["market"], root))
        beta, r_mkt = 0.0, 0.0
        if ix is not None and len(ix) > 60:
            j = pd.concat([s.pct_change().rename("a"), ix.pct_change().rename("b")], axis=1, join="inner").dropna().iloc[-250:]
            if len(j) > 40 and float(j["b"].var()) > 0:
                beta = float(np.cov(j["a"], j["b"])[0, 1] / j["b"].var())
            ia, ib = ix[ix.index <= pd.Timestamp(prev.date())], ix[ix.index > pd.Timestamp(prev.date())]
            if len(ia) and len(ib):
                r_mkt = float(ib.iloc[-1] / ia.iloc[-1] - 1.0)
        out.append({"isin": e["isin"], "symbol": e["symbol"], "market": e["market"], "gap_return": r_gap, "beta": round(beta, 2), "market_part": round(beta * r_mkt, 5), "sector_part": None,
                    "own_part": round(r_gap - beta * r_mkt, 5), "last_close": float(b.iloc[-1]), "last_close_day": str(b.index[-1].date()), "close_before": float(a.iloc[-1])})
    return out


def _decision(kind: str, sev: str) -> str:
    """The live rule for an unconfirmed-then-confirmed thesis break, in code: a HIGH break sells, a medium one only freezes new buying."""
    return "sell" if sev == "high" else "freeze"


def _qty(con, e: dict) -> float:
    try:
        if e["market"] == "US":
            from pflab.us import book as ub
            return float(ub.positions(con).get(e["isin"], 0.0))
        from pflab.paper import book
        return float(book.positions(con).get(e["isin"], 0.0))
    except Exception:
        return 0.0


def _fx(con, day: date, root) -> float:
    try:
        from pflab.us import fx as ufx
        return float(ufx.rate_for(con, day, root, max_age_days=10)["rate"])
    except Exception:
        return 1.0


def run_gap(con, now: datetime, root, prev: datetime, red_items: List[dict], *, model_fn: Optional[Callable] = None, no_model: bool = False) -> dict:
    """The fast-forward over [prev, now]. -> {note, ghosts, caused, skipped?}. Never raises. `model_fn(system, user) -> {"json", "cost_rupees"}` replaces the gateway call (tests)."""
    out: dict = {"ghosts": [], "caused": [], "note": ""}
    code_opt = None
    try:
        model_on = bool(think.settings().get("fast_forward_model", True))
        if not enabled():
            return {"skipped": "switched off", "note": ""}
        rs = release_start()
        if rs is not None and prev.date() < rs:
            return {"skipped": f"the gap began {prev:%d %b}, before this release ({rs}): replaying it would test code written after the data", "note": ""}
        ses = _sessions(prev, now)
        if not any(ses.values()):
            return {"skipped": "no session of either market inside the gap", "note": ""}
        rel = _release_id()
        gid = con.execute("SELECT max(gap_id) FROM alarm_gap_s86").fetchone()[0]
        gid = (gid or 0) + 1                                                                           # the alarm lane stores its own gap row after this hook returns
        if con.execute("SELECT 1 FROM ghost_s86 WHERE release=? AND decided_at >= ? AND label=? LIMIT 1", [rel, prev, LABEL]).fetchone() and not red_items:
            return {"skipped": "this gap was replayed already", "note": ""}
        from pflab.think import watch
        entries = [e for e in watch.scope(con, now.date(), root=root) if (e["held"] or "pick" in str(e.get("why"))) and not str(e["isin"]).startswith(("STORY:", "MARKET:", "MACRO:"))]
        out["caused"] = caused_by(con, entries, prev, now, root)
        delay = lane_delay_minutes(con)
        model_budget = MODEL_LOOKS_MAX if model_on and not no_model else 0
        looks: List[dict] = []
        sold = []
        done = set()
        for it in sorted(red_items, key=lambda x: -x["entry"]["exposure_inr"]):
            e = it["entry"]
            if e["isin"] in done or it.get("lane") != "red":
                continue
            pub = it.get("published")
            pub = datetime.fromisoformat(str(pub)) if pub and not isinstance(pub, datetime) else pub
            if pub is None:
                continue
            done.add(e["isin"])
            at = pub + timedelta(minutes=delay)                                                         # counted from its publication plus the lane's own median delay
            opt = _decision(it["kind"], it["sev"])
            s = _closes(con, e, known_day(e["market"], now), root)
            if s is None:
                continue
            look = None
            if model_budget > 0 and len(looks) < MODEL_LOOKS_MAX:                                       # C3.1: the model's own look at that moment, RED first (items arrive largest exposure first)
                look = model_look(con, now, root, e, it, at, prev, rel, model_fn)
                looks.append(look)
                if look and look.get("option"):
                    code_opt, opt = opt, look["option"]
            fill = _after(s, at) if opt in ("sell", "trim") else None
            qty = _qty(con, e)
            live_px = float(s.iloc[-1])
            cost = None
            if fill and qty > 0:
                fx = _fx(con, now.date(), root) if e["market"] == "US" else 1.0
                px = fill[1] * (1.0 - SLIP)
                cost = qty * (px - live_px) * fx                                                        # positive: being off cost this much
            gh = (con.execute("SELECT coalesce(max(ghost_id),0)+1 FROM ghost_s86").fetchone()[0])
            lk = look or {}
            con.execute("INSERT INTO ghost_s86 (ghost_id, gap_id, release, isin, symbol, market, decided_at, option, source, headline, fill_ts, fill_price, qty, live_price, cost_of_being_off_inr, label, "
                        "code_option, model_class, model_words, model_reason, model_cost, replay_key, steps) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [gh, gid, rel, e["isin"], e["symbol"], e["market"], at, opt, "model" if lk.get("option") else "code", str(it.get("title"))[:300],
                         datetime.combine(fill[0], time(15, 30)) if fill else None, (fill[1] * (1.0 - SLIP)) if fill else None, qty, live_px, cost, LABEL,
                         code_opt or _decision(it["kind"], it["sev"]), lk.get("klass"), lk.get("words"), lk.get("reason"), lk.get("cost"), lk.get("key"), "closes (no minute bars stored for a gap)"])
            code_opt = None
            out["ghosts"].append({"ghost_id": gh, "symbol": e["symbol"], "option": opt, "decided_at": str(at), "fill_day": str(fill[0]) if fill else None, "fill_price": round(fill[1] * (1 - SLIP), 2) if fill else None,
                                  "live_price": round(live_px, 2), "cost_inr": None if cost is None else round(cost, 2)})
            if fill and cost is not None:
                sold.append(f"Had I been on: {opt}s {e['symbol']} {fill[0]:%a} at {fill[1] * (1 - SLIP):,.2f}; the last close is {live_px:,.2f}: being off "
                            + (f"cost Rs {cost:,.0f}" if cost >= 0 else f"saved Rs {-cost:,.0f}") + ".")
        out["note"] = " ".join(sold[:2])
        try:                                                                                              # the what-caused-what split, as a note `recall` finds
            from pflab.think import recall
            for c in out["caused"]:
                if abs(c["gap_return"]) >= 0.03:
                    recall.write_back(con, now, isin=c["isin"], symbol=c["symbol"], title=f"While the app was off ({prev:%d %b} to {now:%d %b}): {c['symbol']} {c['gap_return']:+.1%}"[:200],
                                      text=(f"{c['symbol']} moved {c['gap_return']:+.1%} over the gap: the market's part {c['market_part']:+.1%} (beta {c['beta']}), its own part {c['own_part']:+.1%}; "
                                            "the sector's part is not separated (no sector series is stored for one name)."), source="fastforward")
        except Exception:
            pass
    except Exception as ex:
        out["problem"] = f"{type(ex).__name__}: {str(ex)[:200]}"
    return out


MODEL_LOOKS_MAX = 3                      # at most this many cases a gap are looked at by the model; the rest by code, labelled so
SYSTEM_REPLAY = ("You are the thinking desk of a small paper portfolio, REPLAYING a past moment after the app was off. Only the text below was known at that moment: no other news, no web, nothing "
                 "later. Read it and answer with the closed lists only: the situation's class, ONE option for the name, and a likelihood WORD for the worst, likely and best outcome. "
                 "Never write a number as a field and never a figure the text does not give. The reason is one plain sentence.")
REPLAY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["klass", "option", "worst", "likely", "best", "reason"],
                 "properties": {"klass": {"type": "string", "enum": list(think.CLASSES)}, "option": {"type": "string", "enum": list(think.OPTIONS)},
                                "worst": {"type": "string", "enum": list(think.WORDS)}, "likely": {"type": "string", "enum": list(think.WORDS)}, "best": {"type": "string", "enum": list(think.WORDS)},
                                "reason": {"type": "string"}}}


def _known_text(con, e: dict, at: datetime, root) -> str:
    """Everything the desk would have had at `at`, and nothing later: the headlines published by then (the lane's delay is already in `at`), the stored notes as of that day (`recall`), and the closes
    of the sessions already over."""
    parts = []
    rows = con.execute("SELECT published, outlet, title FROM headlines_s86 WHERE isin=? AND published IS NOT NULL AND published <= ? ORDER BY published DESC LIMIT 12", [e["isin"], at]).fetchall()
    if rows:
        parts.append("HEADLINES (newest first):\n" + "\n".join(f"- {p:%a %d %b %H:%M} IST, {o or 'outlet unknown'}: {t[:200]}" for p, o, t in rows))
    try:
        from pflab.think import recall
        r = recall.recall(con, at, isin=e["isin"], symbol=e["symbol"], asof=at, limit_chars=1500)
        if r.get("text"):
            parts.append("WHAT WE ALREADY KNEW (stored notes as of then):\n" + r["text"][:1500])
    except Exception:
        pass
    s = _closes(con, e, known_day(e["market"], at), root)
    if s is not None and len(s) > 6:
        s = s[s.index <= pd.Timestamp(known_day(e["market"], at))]
        parts.append("CLOSES SO FAR: last close " + f"{float(s.iloc[-1]):.2f} on {s.index[-1]:%d %b}; five sessions earlier {float(s.iloc[-6]):.2f}.")
    return "\n\n".join(parts) or "nothing stored."


def model_look(con, now: datetime, root, e: dict, it: dict, at: datetime, prev: datetime, release: str, model_fn: Optional[Callable] = None) -> Optional[dict]:
    """C3.1: ONE replayed model look at the moment `at`. Cached by (gap start, gap end day, release, name, headline): a replay is never paid twice. Budget: the workshop / his cap (the gateway refuses
    past it: the look is then skipped and the ghost stays a code decision). No web, no tools. Returns {klass, option, words, reason, cost, key} or None."""
    import hashlib
    key = hashlib.sha1(f"{prev:%Y%m%d%H%M}|{now:%Y%m%d}|{release}|{e['isin']}|{it.get('id')}".encode()).hexdigest()[:16]
    old = con.execute("SELECT option, model_class, model_words, model_reason FROM ghost_s86 WHERE replay_key=? AND source='model' LIMIT 1", [key]).fetchone()
    if old:
        return {"klass": old[1], "option": old[0], "words": old[2], "reason": old[3], "cost": 0.0, "key": key, "cached": True}
    user = (f"NAME: {e['symbol']} (the book holds {e.get('exposure_pct', 0.0):.1%} of itself in it)\nMOMENT: {at:%a %d %b %Y %H:%M} IST\n\n" + _known_text(con, e, at, root) +
            "\n\nAnswer with the form only.")
    try:
        if model_fn is not None:
            r = model_fn(SYSTEM_REPLAY, user)
        else:
            from pflab.llm import gateway
            r = gateway.call(con, "decide", SYSTEM_REPLAY, [{"role": "user", "content": user}], schema=REPLAY_SCHEMA, purpose="s86b_replay_look", now=now, max_tokens=900, agent="think", web=False)
        j = r.get("json") or {}
        if j.get("option") not in think.OPTIONS or j.get("klass") not in think.CLASSES:
            return None
        return {"klass": j["klass"], "option": j["option"], "words": f"{j.get('worst')}/{j.get('likely')}/{j.get('best')}", "reason": str(j.get("reason") or "")[:300], "cost": float(r.get("cost_rupees") or 0.0), "key": key}
    except Exception:
        return None


# --- the forward test ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def score_ghosts(con, day: date, root=None) -> int:
    """Score each ghost SALE at 5, 20 and 60 sessions after its fill: the share of the fill price the name has since fallen (positive = selling was right), pre-tax. Idempotent; point in time (closes up to
    `day`). Returns the number of cells written."""
    from pflab import markets
    from pflab.think import watch
    n = 0
    rows = con.execute("SELECT ghost_id, isin, symbol, market, fill_ts, fill_price, scored_5, scored_20, scored_60 FROM ghost_s86 WHERE label=? AND fill_price IS NOT NULL", [LABEL]).fetchall()
    for gid, isin, sym, mk, fts, fpx, s5, s20, s60 in rows:
        s = _closes(con, {"market": mk, "isin": isin, "symbol": sym}, day, root)
        if s is None:
            continue
        after = s[s.index > pd.Timestamp(fts.date())]
        for k, col, cur in ((5, "scored_5", s5), (20, "scored_20", s20), (60, "scored_60", s60)):
            if cur is None and len(after) >= k:
                con.execute(f"UPDATE ghost_s86 SET {col}=? WHERE ghost_id=?", [round(float(fpx - after.iloc[k - 1]) / float(fpx), 6), gid])
                n += 1
    return n


def scorecard(con) -> dict:
    """The column `replayed_while_off` of the decision scorecard (never mixed with the live one): how many ghost decisions, how many scored at each horizon, how many were right."""
    rows = con.execute("SELECT option, scored_5, scored_20, scored_60, cost_of_being_off_inr FROM ghost_s86 WHERE label=?", [LABEL]).fetchall()
    out = {"label": LABEL, "decisions": len(rows), "basis": "pre-tax price move after the decision; code decisions only", "right": {}}
    for k, i in ((5, 1), (20, 2), (60, 3)):
        xs = [r[i] for r in rows if r[i] is not None]
        out["right"][str(k)] = {"scored": len(xs), "right": sum(1 for x in xs if x > 0)}
    out["cost_of_being_off_inr"] = round(sum(r[4] for r in rows if r[4] is not None), 2)
    return out


def scorecard_line(con) -> Optional[str]:
    sc = scorecard(con)
    if not sc["decisions"]:
        return None
    r5 = sc["right"]["5"]
    return (f"While off ({LABEL}): {sc['decisions']} replayed decision{'s' if sc['decisions'] != 1 else ''}; at 5 sessions {r5['right']} of {r5['scored']} scored were right (pre-tax, code only); "
            f"being off cost Rs {sc['cost_of_being_off_inr']:+,.0f} so far.")
