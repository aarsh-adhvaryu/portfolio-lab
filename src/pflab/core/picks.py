"""The picks (S83 L1, A61-A63): stocks the system holds on purpose, each with a thesis, what would break it and the storylines it rests on. Modelled on `core/views.py`.

    A pick is a name (India `longterm` sleeve, or a stock beside SPY in the US sub-book), a written thesis (60+ characters), what would break it, the storyline ids, the session that made it
    and, once five picks have a score, what the scorecard taught. It lives in `picks_s83`:  proposed -> buying -> held -> withdrawn / stopped / broken.
    The strategist names stocks and writes reasons; it never writes a size, a price or a weight. CODE checks, sizes, buys, sells and scores:

    propose        validates each item (a listed share with stored closes; the liquidity floor; not already held unless it adds a thesis to a held Kite stock; the India 10% stock and 25% sector
                   rails; the US rails of A62; the thesis; `learned_from` once five picks have a score; no new picks while the share is shrinking) and stores it as `proposed`. Every refusal says why.
    sizing         `target_weights`: his Kite stocks keep what they hold (they are never topped up); the room left under the sleeve's share (`pick_share.share`) is split across the system's picks
                   by equal risk (inverse volatility, as the baseline sizes held names), each at most the stock rail. They enter the policy's target weights BEFORE the rails (`baseline_v2` takes them
                   from `state["picks"]`; any other policy's weights are overridden for these names by `merge`), so every cap, the circuit breaker, the cost filter and the turnover caps apply:
                   buying is gradual. A pick is never sold to reach a share.
    states         proposed -> buying (its first order is placed or a share is held) -> held (its target weight is reached, within the band) ; withdrawn (the strategist no longer believes the
                   thesis: `core/exits.py` sells it as kind `withdraw`, weighed against the 12-month tax guard like any sale and scored after tax against holding) ; stopped / broken (its position is
                   gone through a stop, or a thesis-break event).
    Kite stocks    `adopt_kite_holdings`: every stock the book holds that is not a pick becomes a pick of source 'kite' with the thesis "held from his Kite portfolio" until the strategist writes a
                   real one (propose adds the thesis to it) or withdraws it.

Calls the loops make:  `prepare(con, now, day, market)` before the state is built (adopt, judge the share), `attach(con, state, market)` inside `state.build` (the sizing), `merge(state, dec, pid)`
after the policy has decided, `sync(con, day, market, state)` after the orders are placed (states). The US wiring calls the same with market="US".
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Callable, Dict, List, Optional

from pflab.core import pick_share
from pflab.paper.rails import MAX_STOCK

STATES = ("proposed", "buying", "held", "withdrawn", "stopped", "broken")
ACTIVE = ("proposed", "buying", "held")
KITE_THESIS = "held from his Kite portfolio"
KITE_BREAK = "not written yet: the exit plan's stop and the thesis-break events apply"
MIN_THESIS, MIN_BREAK, MIN_LEARNED, MIN_REASON = 60, 15, 40, 20
SCORED_FOR_LEARNED = 5                      # `learned_from` is required once this many picks have a score
MIN_TRADED_OBS = 50                         # sessions of traded value needed (of the 60 asked for)
MAX_CLOSE_AGE_DAYS = 15                     # a stored close older than this: the share does not trade (halted or delisted)
COLS = ("pick_id", "market", "isin", "symbol", "source", "thesis", "break_condition", "storylines_json", "session_ref", "learned_from", "state", "proposed_on", "state_changed_on", "state_reason")

def settings(market: Optional[str] = None) -> dict:
    return pick_share.settings(market)


traded_value_source: Optional[Callable] = None      # tests and other modules may set `fn(con, market, isin, symbol, day) -> (median_value, observations) | None`


def on(market: str = "IN") -> bool:
    return pick_share.on(market)


# --- rows ----------------------------------------------------------------------------------------------------------------------------

def _norm(s) -> str:
    return " ".join(str(s or "").split())


def _pick(r: tuple) -> dict:
    d = dict(zip(COLS, r))
    d["storylines"] = json.loads(d.pop("storylines_json") or "[]")
    return d


def _q(con, where: str, args: list) -> List[dict]:
    return [_pick(r) for r in con.execute(f"SELECT {', '.join(COLS)} FROM picks_s83 WHERE {where} ORDER BY pick_id", args).fetchall()]


def active(con, market: str = "IN") -> List[dict]:
    """The picks in state proposed, buying or held."""
    return _q(con, "market=? AND state IN ('proposed','buying','held')", [market])


def all_picks(con, market: str = "IN") -> List[dict]:
    return _q(con, "market=?", [market])


def _set_state(con, pick_id: int, state: str, day: date, why: str) -> None:
    con.execute("UPDATE picks_s83 SET state=?, state_changed_on=?, state_reason=? WHERE pick_id=?", [state, day, why[:500], pick_id])


def needs_learned(con, market: str = "IN") -> bool:
    """True once five picks of the market have a score in `pick_scores_s83` (the score agent's table: kind 'pick', `ref_id` = the pick id; read defensively, absent = False)."""
    try:
        return int(con.execute("SELECT count(DISTINCT s.ref_id) FROM pick_scores_s83 s JOIN picks_s83 p ON p.pick_id = s.ref_id WHERE s.kind='pick' AND p.market=?", [market]).fetchone()[0] or 0) >= SCORED_FOR_LEARNED
    except Exception:
        return False


def share(con, market: str = "IN") -> dict:
    return pick_share.share(con, market)


def reserve_points(market: str = "IN") -> float:
    """A64: the points of the market's book (India: the rupee book; US: the sub-book) kept as the OPPORTUNITY RESERVE in cash, which only the thinking loop may spend: ordinary picks never
    take them (`target_weights`, `propose`, the card's room). From `[think] reserve_india_pts` / `reserve_us_pts` (10 and 10)."""
    try:
        from pflab import think
        t = think.settings()
        return float(t["reserve_us_pts" if market == "US" else "reserve_india_pts"])
    except Exception:
        return 10.0


def ordinary_ceiling(market: str, share_now: float) -> float:
    """The most the picks sleeve (his Kite stocks, withdrawn names and the system's ordinary picks) may hold: India, the share less the reserve; US, the share but SPY (at least its floor) and the
    reserve must both fit beside it."""
    res = reserve_points(market) / 100.0
    if market == "US":
        return max(0.0, min(share_now, 1.0 - float(settings("US")["us_spy_floor"]) - res))
    return max(0.0, share_now - res)


# --- the book's numbers (a market at a time) --------------------------------------------------------------------------------------------

def _positions(con, market: str, day: date, strict: bool = False) -> Dict[str, float]:
    """Shares held by key. `strict`: a failure raises (the state moves of `sync` must not read "nothing held" from a failed read); otherwise it reads as nothing held."""
    try:
        if market == "US":
            from pflab.us import book as usbook
            return {k: float(v) for k, v in usbook.positions(con, day).items() if v > 1e-9}
        from pflab.paper import book
        return {k: float(v) for k, v in book.positions(con).items() if v > 1e-9}
    except Exception:
        if strict:
            raise
        return {}


def _weights(con, market: str, day: date) -> tuple:
    """({isin: weight}, {isin: sector}) of the market's book at `day` (the US sub-book: its last marked day)."""
    try:
        if market == "US":
            r = con.execute("SELECT value_usd, holdings_json FROM us_days_s81 WHERE day <= ? ORDER BY day DESC LIMIT 1", [day]).fetchone()
            if not r or not r[0]:
                return {}, {}
            h = json.loads(r[1] or "{}")
            return {k: float((v or {}).get("value_usd") or 0.0) / float(r[0]) for k, v in h.items()}, {}
        from pflab.paper import book
        h = book.holdings(con, day)
        tot = float(h["value"] or 0.0)
        if tot <= 0:
            return {}, {}
        return {r["isin"]: float(r["value"] or 0.0) / tot for r in h["rows"]}, {r["isin"]: r["sector"] for r in h["rows"] if r["sector"]}
    except Exception:
        return {}, {}


def _open_buys(con, market: str) -> set:
    try:
        if market == "US":
            from pflab.us import book as usbook
            return {o["isin"] for o in usbook.open_orders(con) if o.get("side") == "buy"}
        return {i for (i,) in con.execute("SELECT DISTINCT isin FROM paper_orders WHERE status='open' AND side='buy'").fetchall()}
    except Exception:
        return set()


# --- Kite stocks ---------------------------------------------------------------------------------------------------------------------

def adopt_kite_holdings(con, now: datetime) -> List[int]:
    """Every listed share the India book holds that is not already a pick (of any state) becomes a pick of source 'kite', thesis "held from his Kite portfolio", state 'held'. Idempotent."""
    from pflab.paper import book
    from pflab.pm.store import next_id
    day, out = now.date(), []
    for isin in sorted(_positions(con, "IN", day)):
        if (book.inst(con, isin)["asset_class"] or "") != "equity":
            continue
        if con.execute("SELECT 1 FROM picks_s83 WHERE market='IN' AND isin=? AND state IN ('proposed','buying','held','withdrawn')", [isin]).fetchone():
            continue
        if con.execute("SELECT 1 FROM picks_s83 WHERE market='IN' AND isin=? AND source='kite'", [isin]).fetchone():
            continue                                                                # a Kite pick that ended (stopped, broken): the name is not adopted again
        pid = next_id(con, "picks_s83", "pick_id")
        con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, thesis, break_condition, storylines_json, session_ref, learned_from, state, proposed_on, state_changed_on, "
                    "state_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [pid, "IN", isin, book.inst(con, isin)["symbol"] or isin, "kite", KITE_THESIS, KITE_BREAK, "[]", None, None, "held", day, day, "adopted: held from his Kite portfolio"])
        out.append(pid)
    return out


# --- traded value and the floors --------------------------------------------------------------------------------------------------------

def _in_traded_value(con, isin: str, day: date) -> Optional[tuple]:
    """(median daily traded value in rupees over the last 60 sessions up to `day`, observations) from the lab's price panel (`data/panel`: bhavcopy turnover); None when it has none."""
    try:
        import pandas as pd
        from pflab.data import data_dir
        p = data_dir() / "panel" / "prices.parquet"
        if not p.exists():
            return None
        df = pd.read_parquet(p, columns=["date", "isin", "turnover"], filters=[("isin", "==", isin)])
        df = df.assign(date=pd.to_datetime(df["date"]).dt.date)
        df = df[(df["date"] <= day) & df["turnover"].notna()].sort_values("date").tail(60)
        return (float(df["turnover"].median()), int(len(df))) if len(df) else None
    except Exception:
        return None


def _us_bars_value(symbol: str, day: date) -> tuple:
    """(last close, median traded value in USD over 60 sessions, observations, last bar date) from the stored daily bars, or Nones."""
    from pflab.us import data as usdata
    b = usdata.bars(symbol)
    if b is None or b.empty:
        return None, None, 0, None
    b = b[b["date"] <= day]
    if b.empty:
        return None, None, 0, None
    t = b.tail(60)
    vol = t["volume"] if "volume" in t.columns else None
    med = float((t["close"] * vol).median()) if vol is not None and vol.notna().any() else None
    return float(b.iloc[-1]["close"]), med, int(len(t)), b.iloc[-1]["date"]


def us_floor(con, symbol: str, day: date) -> Optional[str]:
    """None when the US stock passes the A62 floor (price at least USD 5, median daily traded value at least USD 2 million over 60 sessions), else the reason. Uses the tools agent's
    `pflab.us.picks_floor.check(con, symbol, day)` when it exists; otherwise the stored daily bars (`data/us`) with the numbers of `[picks]` (labelled in the reason)."""
    try:
        from pflab.us import picks_floor
        r = picks_floor.check(con, symbol, day)
        if isinstance(r, dict):
            ok = r.get("ok", r.get("passes", r.get("pass", r.get("allowed"))))
            return None if ok else str(r.get("reason") or r.get("why") or r.get("problem") or r.get("message") or "it fails the US floor")
        if isinstance(r, (tuple, list)) and r:
            return None if r[0] else str(r[1] if len(r) > 1 else "it fails the US floor")
        return None if r else "it fails the US floor"
    except ImportError:
        pass
    c = settings("US")
    px, med, n, last = _us_bars_value(symbol, day)
    if px is None:
        return f"{symbol} has no stored daily bars up to {day} (the floor is checked on them)"
    if px < float(c["us_floor_price"]):
        return f"{symbol} closed at USD {px:,.2f}, under the USD {float(c['us_floor_price']):g} floor (price floor checked on stored bars, A62)"
    if med is None or n < MIN_TRADED_OBS:
        return f"{symbol} has too few sessions of traded value ({n} of 60) to check the USD {float(c['us_floor_value_usd']):,.0f} floor"
    if med < float(c["us_floor_value_usd"]):
        return f"{symbol} trades a median USD {med:,.0f} a day over {n} sessions, under the USD {float(c['us_floor_value_usd']):,.0f} floor (checked on stored bars, A62)"
    return None


def _in_floor(con, isin: str, symbol: str, day: date) -> Optional[str]:
    fn = traded_value_source or (lambda c_, m_, i_, s_, d_: _in_traded_value(c_, i_, d_))
    r = fn(con, "IN", isin, symbol, day)
    floor = float(settings("IN")["min_liquidity_inr"])
    if not r or r[0] is None or int(r[1]) < MIN_TRADED_OBS:
        return f"{symbol} has no usable record of daily traded value ({0 if not r else int(r[1])} of 60 sessions), so the Rs {floor / 1e7:g} crore liquidity floor cannot be checked"
    if float(r[0]) < floor:
        return f"{symbol} trades a median Rs {float(r[0]) / 1e7:.2f} crore a day over {int(r[1])} sessions, under the Rs {floor / 1e7:g} crore liquidity floor"
    return None


# --- propose ---------------------------------------------------------------------------------------------------------------------------

def _resolve(con, market: str, symbol: str, day: date) -> tuple:
    """-> (key, reason): the security's key and a refusal when it is not a listed share with stored closes."""
    if market == "US":
        from pflab.data import us_prices
        from pflab.us import instruments as uins
        if symbol in us_prices.ETFS:
            return None, f"{symbol} is a fund: a pick is a single stock (the sub-book's core is SPY)"
        px, _m, n, last = _us_bars_value(symbol, day)
        if px is None:
            return None, f"{symbol} has no stored daily bars up to {day}: it is not a share the book can price"
        if (day - last).days > MAX_CLOSE_AGE_DAYS:
            return None, f"{symbol}'s last stored bar is {last}, more than {MAX_CLOSE_AGE_DAYS} days old"
        try:
            return uins.key_for(con, symbol, ciks=uins.load_ciks()), None
        except Exception:
            return uins.SYMBOL_PREFIX + symbol, None
    from pflab.paper import book
    isin = book.isin_of(con, symbol)
    if not isin:
        return None, f"{symbol} is not a listed share this book knows (no instrument with that symbol)"
    meta = book.inst(con, isin)
    ac = (meta["asset_class"] or "")
    if ac == "etf":
        return None, f"{symbol} is an ETF: the core holds the index, gold and international ETFs; a pick is a single listed share"
    if ac != "equity":
        return None, f"{symbol} is a {ac or 'non-share'} holding, not a listed share"
    if meta.get("listed") is False:
        return None, f"{symbol} is not listed any more"
    r = con.execute("SELECT date FROM prices WHERE isin=? AND date<=? AND close>0 ORDER BY date DESC LIMIT 1", [isin, day]).fetchone()
    if not r:
        return None, f"{symbol} has no stored close up to {day}"
    if (day - r[0]).days > MAX_CLOSE_AGE_DAYS:
        return None, f"{symbol}'s last stored close is {r[0]}, more than {MAX_CLOSE_AGE_DAYS} days old"
    return isin, None


def _validate_text(market: str, it: dict, con) -> tuple:
    thesis, brk = _norm(it.get("thesis")), _norm(it.get("break_condition"))
    if len(thesis) < MIN_THESIS:
        return None, f"the thesis is {len(thesis)} characters: write at least {MIN_THESIS} (what you believe and why)"
    if len(brk) < MIN_BREAK:
        return None, f"say what would break the thesis ({MIN_BREAK}+ characters)"
    ids = []
    for s in (it.get("storylines") or []):
        try:
            i = int(s)
        except (TypeError, ValueError):
            return None, f"storyline {s!r} is not an id"
        try:
            from pflab.story import store as sstore
            if not sstore.get(con, i):
                return None, f"storyline {i} does not exist"
        except ImportError:
            pass
        ids.append(i)
    return {"thesis": thesis, "break": brk, "storylines": ids}, None


def propose(con, now: datetime, market: str, items: List[dict], *, session_ref: Optional[str] = None, learned_from: Optional[str] = None) -> dict:
    """Validate and store the strategist's picks for `market`. An item: {"symbol", "thesis", "break_condition", "storylines": [ids]} (never a size, a price or a weight).
    -> {"accepted": [{"symbol", "pick_id"}], "refused": [{"symbol", "reason"}]}. A pick that adds a thesis to a held Kite stock updates that pick (its source stays 'kite')."""
    from pflab.pm.store import next_id
    market = market.upper()
    day = now.date()
    out: dict = {"accepted": [], "refused": []}

    def refuse_all(reason: str) -> dict:
        out["refused"] = [{"symbol": str((i or {}).get("symbol") or "?").upper(), "reason": reason} for i in (items or [])]
        return out
    if market not in pick_share.MARKETS:
        return refuse_all(f"unknown market {market!r}: IN or US")
    c = settings(market)
    if not c["on"]:
        return refuse_all(f"picks are switched off for {pick_share.NAMES[market]} (configs/core.toml [picks])")
    if market == "IN":
        adopt_kite_holdings(con, now)
    learned = _norm(learned_from)
    if needs_learned(con, market) and len(learned) < MIN_LEARNED:
        return refuse_all(f"five picks have a score now: say what the scorecard taught you (learned_from, {MIN_LEARNED}+ characters) and what you do differently")
    sh = share(con, market)
    pos = _positions(con, market, day)
    wts, sectors = _weights(con, market, day)
    act = active(con, market)
    n_system = sum(1 for p in act if p["source"] == "system")
    used_w = sum(max(0.0, wts.get(p["isin"], 0.0)) for p in act if p["source"] == "system")
    seen = set()
    for it in (items or []):
        sym = _norm((it or {}).get("symbol")).upper()
        if not sym:
            out["refused"].append({"symbol": "?", "reason": "an item has no symbol"})
            continue
        if sym in seen:
            out["refused"].append({"symbol": sym, "reason": "named twice in one batch"})
            continue
        seen.add(sym)
        txt, why = _validate_text(market, it, con)
        if why:
            out["refused"].append({"symbol": sym, "reason": why})
            continue
        key, why = _resolve(con, market, sym, day)
        if why:
            out["refused"].append({"symbol": sym, "reason": why})
            continue
        try:                                                                       # S85 E4: his `no_new_names` / `pause_buys` stop a new name entering the picks (a held name's thesis still goes in below)
            from pflab.hq import rules as _rules
            blk = (None if pos.get(key, 0.0) > 1e-9 else _rules.blocks(con, day, isin=key, symbol=sym, sleeve="longterm", cls="stocks", action="buy", new_name=True, market=market))
        except Exception:
            blk = None
        if blk and not any(p["isin"] == key and p["state"] in ACTIVE for p in all_picks(con, market)):
            out["refused"].append({"symbol": sym, "reason": f"{_rules.label(blk)} ({_rules.describe(blk)}) stops a new name from entering the picks"})
            continue
        earlier = _earlier_knowledge(con, now, key, sym)
        takes = _norm((it or {}).get("takes_from"))
        if earlier and len(takes) < MIN_TAKES:                                      # S84 T2x: a name with an earlier note or case says what the pick takes from it
            e = earlier[0]
            out["refused"].append({"symbol": sym, "reason": f"we already hold {len(earlier)} earlier {'note' if len(earlier) == 1 else 'notes or cases'} on {sym} (newest: {e['day']}, {e['kind']} {e['id']}: "
                                                            f"{(e['title'] or '')[:100]}): say in takes_from ({MIN_TAKES}+ characters) what this pick takes from it"})
            continue
        mine = [p for p in all_picks(con, market) if p["isin"] == key]
        live = [p for p in mine if p["state"] in ACTIVE]
        held = pos.get(key, 0.0) > 1e-9
        if live:
            p = live[-1]
            if p["source"] == "kite":                                              # a thesis for a held Kite stock: no buying, so no floors and no rails
                con.execute("UPDATE picks_s83 SET thesis=?, break_condition=?, storylines_json=?, session_ref=?, learned_from=?, state_reason=?, state_changed_on=? WHERE pick_id=?",
                            [txt["thesis"], txt["break"], json.dumps(txt["storylines"]), session_ref, learned or None, f"the strategist wrote its thesis ({session_ref or 'a session'})", day, p["pick_id"]])
                out["accepted"].append({"symbol": sym, "pick_id": p["pick_id"], "note": "thesis added to his Kite stock; it keeps what it holds"})
                _read_earlier(con, now, p["pick_id"], takes, earlier)
                continue
            out["refused"].append({"symbol": sym, "reason": f"{sym} is already a pick ({p['state']}): withdraw it first if you no longer believe it"})
            continue
        if held:
            why = (f"{sym} is already held and its earlier pick is {mine[-1]['state'] if mine else 'unrecorded'}: its sale is still waiting" if any(p["state"] == "withdrawn" for p in mine)
                   else f"{sym} is already held in the book (not as a pick): name it only after it is adopted from his Kite portfolio")
            out["refused"].append({"symbol": sym, "reason": why})
            continue
        if sh["shrinking"]:
            out["refused"].append({"symbol": sym, "reason": f"the {pick_share.NAMES[market]} picks share was just lowered to {sh['share']:.0%}: no new picks until the next judgment ({sh['source']})"})
            continue
        why = _in_floor(con, key, sym, day) if market == "IN" else us_floor(con, sym, day)
        if why:
            out["refused"].append({"symbol": sym, "reason": why})
            continue
        note = None
        if market == "IN":
            from pflab.paper import book, rails as hard
            sec = book.inst(con, key).get("sector")
            sec_w = sum(w for i, w in wts.items() if sectors.get(i) == sec) if sec else 0.0
            if sec and sec_w >= hard.MAX_SECTOR - 0.01:
                out["refused"].append({"symbol": sym, "reason": f"the {sec} sector is already {sec_w:.1%} of the book, at the {hard.MAX_SECTOR:.0%} sector rail: a pick in it could not be bought"})
                continue
            ceil_ = ordinary_ceiling("IN", sh["share"])
            room = ceil_ - sum(wts.get(p["isin"], 0.0) for p in act)
            if room < 0.01:
                note = (f"the sleeve is at or over its {sh['share']:.0%} share less the {reserve_points('IN'):g}-point opportunity reserve (his Kite stocks and the picks hold {ceil_ - room:.0%} "
                        f"of the {ceil_:.0%} ordinary picks may use): it waits for room")
        else:
            if n_system >= int(c["us_max_stocks"]):
                out["refused"].append({"symbol": sym, "reason": f"the sub-book already has {n_system} stocks picked: at most {int(c['us_max_stocks'])}"})
                continue
            ceiling = 1.0 - float(c["us_spy_floor"]) - reserve_points("US") / 100.0
            if used_w + 0.01 > ceiling + 1e-9:
                out["refused"].append({"symbol": sym, "reason": f"the picks already hold {used_w:.0%} of the sub-book: SPY must keep at least {float(c['us_spy_floor']):.0%} and {reserve_points('US'):g} points are the opportunity reserve, so the picks stop at {ceiling:.0%}"})
                continue
        pid = next_id(con, "picks_s83", "pick_id")
        con.execute("INSERT INTO picks_s83 (pick_id, market, isin, symbol, source, thesis, break_condition, storylines_json, session_ref, learned_from, state, proposed_on, state_changed_on, "
                    "state_reason) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [pid, market, key, sym, "system", txt["thesis"], txt["break"], json.dumps(txt["storylines"]), session_ref, learned or None, "proposed", day, day, "proposed by the strategist"])
        if market == "US":
            n_system += 1
        res = {"symbol": sym, "pick_id": pid}
        if note:
            res["note"] = note
        out["accepted"].append(res)
        _read_earlier(con, now, pid, takes, earlier)
    return out


MIN_TAKES = 20


def _earlier_knowledge(con, now: datetime, isin: str, symbol: str) -> List[dict]:
    """S84 T2x: the earlier notes (paid or written back) and cases `think/recall` holds on this name: what a new pick must say it takes from. Never raises (no earlier knowledge, no demand)."""
    try:
        from pflab.think import recall
        r = recall.recall(con, now, isin=isin, symbol=symbol, limit_chars=2500)
        return [i for i in r["items"] if i["kind"] in ("analyst_note", "note", "memory", "case")]
    except Exception:
        return []


def _read_earlier(con, now: datetime, pick_id: int, takes: str, earlier: List[dict]) -> None:
    """The pick read those items: a `knowledge_use_s84` row each, and the sentence it gave is kept on the pick."""
    if not earlier:
        return
    try:
        from pflab.think import recall
        con.execute("UPDATE picks_s83 SET takes_from=? WHERE pick_id=?", [takes[:500], pick_id])
        recall.mark_used(con, earlier, by_kind="pick", by_ref=f"pick:{pick_id}", day=now.date())
    except Exception:
        pass


def withdraw(con, now: datetime, market: str, symbol: str, reason: str, session_ref: Optional[str] = None) -> dict:
    """The strategist no longer believes the thesis. A pick not yet bought is simply dropped; a held one is sold by the exit manager as kind `withdraw` (weighed against the 12-month tax
    guard: inside it, it waits unless a stop or a thesis break fires) and scored after tax against holding."""
    market, sym, day = market.upper(), _norm(symbol).upper(), now.date()
    reason = _norm(reason)
    if len(reason) < MIN_REASON:
        return {"ok": False, "problem": f"say why you no longer believe it ({MIN_REASON}+ characters)"}
    rows = [p for p in active(con, market) if p["symbol"].upper() == sym]
    if not rows:
        return {"ok": False, "problem": f"{sym} is not an active pick in {pick_share.NAMES.get(market, market)}"}
    p = rows[-1]
    q = _positions(con, market, day).get(p["isin"], 0.0)
    _set_state(con, p["pick_id"], "withdrawn", day, f"withdrawn: {reason}" + (f" ({session_ref})" if session_ref else ""))
    if q > 1e-9:
        will = "the exit manager sells it at a close as a 'withdraw' sale, unless the 12-month tax guard makes it wait (a stop or a thesis break would not wait)"
    else:
        will = "it was not bought, so nothing is sold"
    return {"ok": True, "pick_id": p["pick_id"], "symbol": sym, "held": q > 1e-9, "will": will}


def skip_idea(con, now: datetime, market: str, symbol: str, why: str, session_ref: Optional[str] = None) -> dict:
    """An idea looked at and skipped: a row with its price record to score later (`skips_s83`); it is never a book."""
    from pflab.pm.store import next_id
    market, sym, day = market.upper(), _norm(symbol).upper(), now.date()
    why = _norm(why)
    if len(why) < MIN_REASON:
        return {"ok": False, "problem": f"say why you skipped it ({MIN_REASON}+ characters)"}
    if market not in pick_share.MARKETS:
        return {"ok": False, "problem": f"unknown market {market!r}: IN or US"}
    key, bad = _resolve(con, market, sym, day)
    if bad:
        return {"ok": False, "problem": bad}
    r = con.execute("SELECT skip_id FROM skips_s83 WHERE market=? AND isin=? AND skipped_on=?", [market, key, day]).fetchone()
    if r:
        con.execute("UPDATE skips_s83 SET why=?, session_ref=? WHERE skip_id=?", [why[:500], session_ref, r[0]])
        return {"ok": True, "skip_id": r[0], "symbol": sym}
    sid = next_id(con, "skips_s83", "skip_id")
    con.execute("INSERT INTO skips_s83 (skip_id, market, isin, symbol, why, skipped_on, session_ref) VALUES (?,?,?,?,?,?,?)", [sid, market, key, sym, why[:500], day, session_ref])
    return {"ok": True, "skip_id": sid, "symbol": sym}


# --- sizing ----------------------------------------------------------------------------------------------------------------------------

def managed(con, market: str = "IN") -> List[dict]:
    """The picks the sizing owns: the active ones and the withdrawn ones still held (the exit manager sells them; nothing buys them)."""
    return _q(con, "market=? AND state IN ('proposed','buying','held','withdrawn')", [market])


def target_weights(con, state: dict, market: str = "IN") -> Dict[str, float]:
    """{isin: target fraction of the book} for the pick names (the India book; the US sub-book for market 'US'): his Kite stocks and withdrawn picks keep what they hold; the room left under
    the sleeve's share is split across the system's picks by inverse volatility, each at most the stock rail, never below what a pick holds (a pick is never sold to reach a share). A fall
    gauge cuts the held picks like the other equity and stops the buying. `state` is the close loop's state (`rows`, `value`, `vol`, `gauge`, `cfg`)."""
    from pflab.core import policy
    total = float(state.get("value") or 0.0)
    if total <= 0 or not on(market):
        return {}
    c = settings(market)
    rows = {r["isin"]: r for r in state["rows"]}
    cur = {k: float(r["value"] or 0.0) / total for k, r in rows.items()}
    cut = float(state["cfg"]["baseline"]["gauge_cut"])
    gauge = bool((state.get("gauge") or {}).get("fired"))
    out: Dict[str, float] = {}
    system = []
    occupied = 0.0
    try:                                                                     # S84 (A65): names under a thinking-loop freeze get no new buying
        from pflab.think import cases as _tcases
        frozen = set(_tcases.frozen_isins(con, state.get("day"), market))
    except Exception:
        frozen = set()
    for p in managed(con, market):
        k = p["isin"]
        if k not in rows or not rows[k]["buyable"] and p["state"] != "withdrawn":
            continue
        if p["source"] == "kite" or p["state"] == "withdrawn":
            out[k] = cur.get(k, 0.0) * ((1.0 - cut) if gauge and p["state"] != "withdrawn" else 1.0) + (cut * min(cur.get(k, 0.0), (state.get("reserve_protected") or {}).get(k, 0.0)) if gauge and p["state"] != "withdrawn" else 0.0)
            occupied += cur.get(k, 0.0)
            hi = float(c["us_stock_cap"]) if market == "US" else policy.cap_of(rows[k])
            if p["state"] != "withdrawn" and cur.get(k, 0.0) > hi + 1e-9:       # a holding over the company rail is brought down to it (a rail trim, as the baseline always did), never bought
                out[k] = min(out[k], hi)
        else:
            system.append(p)
    sh = share(con, market)["share"]
    budget = max(0.0, ordinary_ceiling(market, sh) - occupied)             # A64: the reserve's points are never spent by an ordinary pick
    if system:
        stock_cap = float(c["us_stock_cap"]) if market == "US" else MAX_STOCK
        inv = {p["isin"]: 1.0 / max(float(state["vol"].get(p["isin"], 0.30)), 0.05) for p in system}
        caps = {k: stock_cap for k in inv}
        want = policy.risk_weights(budget, inv, caps) if budget > 0 else {}
        for p in system:
            k = p["isin"]
            if gauge:
                out[k] = cur.get(k, 0.0) * (1.0 - cut) + cut * min(cur.get(k, 0.0), (state.get("reserve_protected") or {}).get(k, 0.0))      # no buying while the gauge fires; held picks are cut like the rest of the equity (S86: but not what a reserve buy added in the last 10 sessions)
            elif k in frozen:
                out[k] = cur.get(k, 0.0)                                     # S84: a name under a thinking-loop freeze is not bought (what is held stays)
            else:
                out[k] = max(cur.get(k, 0.0), want.get(k, 0.0))              # never sold to reach a share; a pick above its risk size keeps what it holds
            if cur.get(k, 0.0) > stock_cap + 1e-9:                           # only the company rail trims a pick (a rail trim)
                out[k] = min(out[k], stock_cap)
        if market == "IN" and not gauge:
            _from_cash_above_reserve(state, total, cur, out, [p["isin"] for p in system], reserve_points(market) / 100.0)
    return out


def _from_cash_above_reserve(state: dict, total: float, cur: Dict[str, float], out: Dict[str, float], names: List[str], reserve: float) -> None:
    """F1/A64: the system's ordinary picks are bought from cash and new money, and only from the cash ABOVE the reserve: the reserve refills from new money and sale proceeds before an ordinary
    pick takes any. The increases of the pick names are scaled down (never below what a pick holds) to the cash above the reserve. A state with no cash figure is left as it is."""
    if "cash" not in state:
        return
    free = max(0.0, (float(state.get("cash") or 0.0) + float(state.get("bank") or 0.0)) / total - reserve)
    inc = {k: out[k] - cur.get(k, 0.0) for k in names if k in out and out[k] > cur.get(k, 0.0) + 1e-12}
    need = sum(inc.values())
    if need > free + 1e-12:
        f = (free / need) if need > 0 else 0.0
        for k, v in inc.items():
            out[k] = cur.get(k, 0.0) + v * f


def attach(con, state: dict, market: str = "IN") -> dict:
    """Put the picks' sizing in the state (`state["picks"]`): the target weights and the names the sizing owns. `baseline_v2` reads it; with the picks off the key is absent."""
    if not on(market):
        state.pop("picks", None)
        return state
    w = target_weights(con, state, market)
    state["picks"] = {"market": market, "weights": w, "managed": sorted({p["isin"] for p in managed(con, market)}), "share": share(con, market)}
    return state


def universe(con, day: Optional[date] = None, market: str = "IN") -> List[str]:
    """The pick names the book does not hold yet (proposed or buying): they enter the state as rows with no quantity, so the rails and the sizing see them."""
    if not on(market):
        return []
    try:
        return [p["isin"] for p in active(con, market) if p["source"] == "system"]
    except Exception:
        return []


def merge(state: dict, dec: dict, pid: str) -> dict:
    """The picks' target weights over a decision that is NOT a baseline's (a promoted lab policy, a probation blend): the pick names get the picks' sizing (a lab policy never sells a pick to
    reach a weight). A baseline already used `state["picks"]`, so its decision is returned as it is."""
    from pflab.core import policy
    pk = state.get("picks") or {}
    if not pk.get("weights") or pid in policy.BASELINES:
        return dec
    w = dict(dec["weights"])
    changed = {k: v for k, v in pk["weights"].items() if abs(w.get(k, -1.0) - v) > 1e-12}
    if not changed:
        return dec
    w.update(changed)
    return {**dec, "weights": w, "notes": list(dec.get("notes") or []) + [f"picks sleeve: {len(changed)} pick name(s) sized by the picks rule"]}


# --- the close ------------------------------------------------------------------------------------------------------------------------

def prepare(con, now: datetime, day: date, market: str = "IN") -> dict:
    """Before the state is built: adopt his Kite stocks (India) and judge the sleeve's share if it is due. Never raises."""
    out: dict = {}
    try:
        if on(market):
            if market == "IN":
                out["adopted"] = len(adopt_kite_holdings(con, now))
            out["judged"] = pick_share.judge(con, now, market, day)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:160]}"
    return out


def sync(con, day: date, market: str = "IN", state: Optional[dict] = None) -> dict:
    """Move the picks along their states from what the book shows: proposed -> buying (a buy is open or a share is held), buying -> held (its target weight reached, within the band), held or
    buying -> stopped / broken (its position is gone: a stop or other exit, or a thesis-break event). Returns the moves. Never raises."""
    moved = []
    try:
        pos = _positions(con, market, day, strict=True)
        opens = _open_buys(con, market)
        tw = ((state or {}).get("picks") or {}).get("weights") or {}
        band = float((state or {}).get("cfg", {}).get("baseline", {}).get("band_pts", 1.5)) / 100.0
        total = float((state or {}).get("value") or 0.0)
        cur = {r["isin"]: float(r["value"] or 0.0) / total for r in (state or {}).get("rows", [])} if total > 0 else {}
        for p in active(con, market):
            k, q = p["isin"], pos.get(p["isin"], 0.0)
            st = p["state"]
            if st == "proposed" and (q > 1e-9 or k in opens):
                _set_state(con, p["pick_id"], "buying", day, "its first order is placed" if q <= 1e-9 else "shares are held")
                st = "buying"
                moved.append((p["symbol"], "buying"))
            if st == "buying" and q > 1e-9 and k in tw and k in cur and cur[k] >= tw[k] - band:
                _set_state(con, p["pick_id"], "held", day, f"its target weight of {tw[k]:.1%} is reached")
                moved.append((p["symbol"], "held"))
            if st in ("held", "buying") and q <= 1e-9 and k not in opens:
                ev = None
                try:
                    ev = con.execute("SELECT kind, filled_on FROM exit_events_s81 WHERE isin=? AND market=? AND side='sell' AND status='filled' AND filled_on >= ? ORDER BY event_id DESC LIMIT 1",
                                     [k, market, p["proposed_on"]]).fetchone()
                except Exception:
                    pass
                if st == "held" or ev:
                    new = "broken" if ev and ev[0] == "thesis" else "stopped"
                    _set_state(con, p["pick_id"], new, day, (f"sold by the exit manager ({ev[0]}) on {ev[1]}" if ev else "the position is gone"))
                    moved.append((p["symbol"], new))
    except Exception as e:
        return {"moved": moved, "error": f"{type(e).__name__}: {str(e)[:160]}"}
    return {"moved": moved}


def status(con, market: str = "IN", day: Optional[date] = None) -> dict:
    """What a screen or the strategist's card needs (JSON-able): the share and why, each pick with its thesis, state and weight, the last 'learned', whether `learned_from` is required."""
    day = day or date.today()
    wts, _ = _weights(con, market, day)
    picks = []
    for p in all_picks(con, market):
        picks.append({"pick_id": p["pick_id"], "symbol": p["symbol"], "isin": p["isin"], "source": p["source"], "state": p["state"], "thesis": p["thesis"], "break_condition": p["break_condition"],
                      "storylines": p["storylines"], "proposed_on": str(p["proposed_on"]), "days_held": (day - p["proposed_on"]).days if p["proposed_on"] else None,
                      "weight": round(wts.get(p["isin"], 0.0), 4), "state_reason": p["state_reason"]})
    r = con.execute("SELECT learned_from FROM picks_s83 WHERE market=? AND learned_from IS NOT NULL ORDER BY pick_id DESC LIMIT 1", [market]).fetchone()
    return {"market": market, "on": on(market), "share": pick_share.status(con, market), "picks": picks, "needs_learned": needs_learned(con, market), "last_learned": r[0] if r else None}
