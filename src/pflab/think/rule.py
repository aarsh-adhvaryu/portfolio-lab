"""T5 DECIDE (S84, A65/A66): the registered rule, code only, no model. `docs/protocols/s84_thinking_live_protocol.md` section 4 is this file in words; `RULE` carries its numbers and
`tests/test_s84_odds.py` pins the protocol's JSON block to it.

    decide(con, case_id, answer, asof)   -> {"rule_option", "size_inr", "parts", "reason", "guards", "refused", ...} for the case's own name, and `all`: one such dict per name of the answer
    needs_big_trade_check(...)           a sale over `big_trade_share` of the book and every reserve buy pass the independent check first (the case session calls it)

The model supplies a CLASS, what is pending, one option per name and a likelihood WORD per outcome; this rule reads them as inputs and decides by rupees. The model's own choice is stored
beside the rule's by the caller (the rule acts; where they differ the case says so). Held name: damage = thesis break = sell; unclear with something pending = freeze; else the best
expected rupees after tax among sell, trim and hold, a sale needing to beat holding by `sale_beats_holding_pts` of the position. New money: only from the reserve, only if the expected
rupees are positive and the bad case loses at most `bet_worst_pct_book` of the whole book, sized from that limit, inside the stock rail and a third of the reserve per name, in three
parts 5 sessions apart, with the timing guards (damage wait, new lows, stretched).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

import numpy as np

from pflab import think
from pflab.think import cases, odds

_D = think.DEFAULTS
RULE = {
    **odds.PARAMS,
    "word_p_start": dict(think.WORD_P),
    "bet_worst_pct_book": _D["bet_worst_pct_book"],
    "reserve_third_per_name": _D["reserve_third_per_name"],
    "market_fall_reserve_share": _D["market_fall_reserve_share"],
    "parts": _D["parts"],
    "parts_gap_sessions": _D["parts_gap_sessions"],
    "damage_wait_sessions": _D["damage_wait_sessions"],
    "new_low_sessions": _D["new_low_sessions"],
    "new_low_clear_days": _D["new_low_clear_days"],
    "sale_beats_holding_pts": _D["sale_beats_holding_pts"],
    "stretched_sigmas": _D["stretched_sigmas"],
    "stretched_window": 20,
    "big_trade_share": _D["big_trade_share"],
    "min_bet_inr": 2000.0,                       # `[rails] min_trade_rupees`: a bet under this is refused
    "score_horizons": [5, 20, 60],
    "calibration_min_scored": 20,
    "calibration_step": 0.05,
    "calibration_floor": 0.02,
    "calibration_ceiling": 0.98,
    "advisory_after_scored": _D["advisory_after_scored"],
}
MARKET_FALL_KINDS = ("market", "market_fall", "market_down")                   # "market" is the watch's case kind for the index falling 10% in 20 sessions
MAX_STOCK, MAX_BROAD_ETF = 0.10, 0.60              # his limits (`paper/rails.py`): a stock 10% of the book, a broad-market index ETF 60% (A56); the sector rail is applied at the order


BUY_WAITS = "The buy waits"       # the marker of a refused buy inside a hold's reason (session._retry_refused finds it)


def cfg() -> dict:
    """RULE with the numbers `configs/core.toml [think]` may override (his to change)."""
    s = think.settings()
    out = dict(RULE)
    for k in ("bet_worst_pct_book", "reserve_third_per_name", "market_fall_reserve_share", "parts", "parts_gap_sessions", "damage_wait_sessions", "new_low_sessions", "new_low_clear_days",
              "sale_beats_holding_pts", "stretched_sigmas", "big_trade_share", "advisory_after_scored", "base_rate_min_n"):
        if k in s:
            out[k] = s[k]
    try:
        from pflab import core
        out["min_bet_inr"] = float(core.settings()["rails"]["min_trade_rupees"])
    except Exception:
        pass
    return out


# --- helpers --------------------------------------------------------------------------------------------------------------------------------------------------------------

def reserve(con, market: str, asof: date, override: Optional[float] = None) -> dict:
    """{"reserve_inr", "free_inr"}: the opportunity reserve of the market (`think/reserve.py`); `override` is the free rupees a test or a caller states."""
    if override is not None:
        return {"reserve_inr": float(override), "free_inr": float(override), "source": "stated"}
    try:
        from pflab.think import reserve as rs
        r = rs.reserve_status(con, market, asof)
        return {"reserve_inr": float(r["reserve_inr"]), "free_inr": float(r["free_inr"]), "source": "think/reserve.py"}
    except Exception:
        return {"reserve_inr": 0.0, "free_inr": 0.0, "source": "reserve unreadable: nothing may be spent"}


def _sessions_since(s, d0: Optional[date], d1: date) -> Optional[int]:
    """Sessions with a close in (d0, d1]; business days when the series is empty."""
    if d0 is None:
        return None
    if s is not None and len(s):
        return int(((s.index > np.datetime64(d0)) & (s.index <= np.datetime64(d1))).sum())
    return int(np.busday_count(d0, d1))


def new_low_guard(s, sessions: int, clear_days: int) -> Optional[str]:
    """None when the name has stopped making new lows: in each of the last `clear_days` sessions its close was above the lowest of the last `sessions` closes (it was not itself that low).
    Else the sentence. Too little history: None cannot be said, so a sentence."""
    if s is None or len(s) < sessions + clear_days:
        return "not enough closes to see whether it still makes new lows"
    v = s.to_numpy(dtype=float)
    for i in range(len(v) - clear_days, len(v)):
        if v[i] <= v[i - sessions + 1:i + 1].min() + 1e-12:
            return f"it still makes new lows (its close on {s.index[i].date():%d %b} was the lowest of the last {sessions}); a buy needs {clear_days} sessions above that low"
    return None


def stretched(s, sigmas: float, window: int) -> Optional[dict]:
    """{"z", "average", "limit"}: how many usual daily moves the last close is above its `window`-session average, and the sentence's numbers; None when it cannot be told."""
    if s is None or len(s) < max(window, odds.MIN_OBS):
        return None
    dv = odds.daily_vol(s)
    avg = float(s.tail(window).mean())
    if not dv or avg <= 0:
        return None
    z = (float(s.iloc[-1]) / avg - 1.0) / dv
    return {"z": z, "average": avg, "stretched": z > sigmas}


def _prior_parts(con, case_id: int, isin: Optional[str]) -> dict:
    """The parts of this case already bought for the name: how many, when last, and the rupees."""
    done, last, spent = 0, None, 0.0
    try:
        for d in cases.decisions(con, case_id):
            if d["isin"] == isin and d["acted_option"] == "buy_in_parts" and not d.get("advisory"):
                done += 1
                last = d["decided_on"]
        spent = float(sum(o["size_inr"] for o in cases.options(con, case_id) if o["track"] == "rule" and o["isin"] == isin and o["option"] == "buy_in_parts" and o["chosen"]))
    except Exception:
        pass
    return {"done": done, "last_on": last, "spent_inr": spent}


def needs_big_trade_check(con, option: str, size_inr: float, asof, *, whole_inr: Optional[float] = None, reserve_buy: Optional[bool] = None) -> bool:
    """A sale over `big_trade_share` of the book, and every reserve buy, pass the independent big-trade check first."""
    asof = asof.date() if isinstance(asof, datetime) else asof
    if option == "buy_in_parts":
        return True if reserve_buy is None else bool(reserve_buy)
    if option not in ("sell", "trim"):
        return False
    whole = whole_inr if whole_inr is not None else odds.whole_book(con, asof)
    return whole > 0 and float(size_inr) > cfg()["big_trade_share"] * whole


# --- the buy ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def _buy(con, case: dict, klass: Optional[str], ch: dict, pos: dict, asof: date, market: str, c: dict, rates: dict, free_override: Optional[float], root, answer: dict) -> dict:
    """The new-money branch. {"option": buy_in_parts | wait | nothing, ...}: the bet's size and parts, or why it was refused."""
    isin, symbol = ch["isin"], ch["symbol"]
    guards: List[str] = []
    timing = False
    kind = case.get("kind")
    fall = kind in MARKET_FALL_KINDS
    s = odds.closes(con, market, isin, symbol, asof, 120, root)
    prior = _prior_parts(con, case["case_id"], isin) if case.get("case_id") else {"done": 0, "last_on": None, "spent_inr": 0.0}
    if prior["done"] >= c["parts"]:
        return {"option": "hold" if pos["held"] else "nothing", "refused": False, "guards": [f"all {c['parts']} parts of this case are bought"], "parts": None, "size_inr": 0.0}
    if klass == "damage":
        guards.append("class is damage to the business or its governance: no buying until the pending outcome is public and %d sessions have passed" % c["damage_wait_sessions"])
        timing = True
    elif case.get("klass") == "damage":
        res = answer.get("pending_resolved_on")
        if isinstance(res, str):
            try:
                res = date.fromisoformat(res[:10])
            except ValueError:
                res = None
        n = _sessions_since(s, res, asof)
        if res is None or n is None or n < c["damage_wait_sessions"]:
            guards.append(f"it was a damage case: no buying until {c['damage_wait_sessions']} sessions after its pending outcome is public"
                          + ("" if res is None else f" ({n} so far)"))
            timing = True
    low = new_low_guard(s, c["new_low_sessions"], c["new_low_clear_days"])
    if low:
        guards.append(low)
        timing = True
    if prior["done"] == 0 and kind == "missed_run":
        st = stretched(s, c["stretched_sigmas"], c["stretched_window"])
        if st and st["stretched"]:
            guards.append(f"it is {st['z']:.1f} of its usual daily moves above its {c['stretched_window']}-session average (limit {c['stretched_sigmas']:g}): wait for a pullback towards Rs {st['average']:,.2f}")
            timing = True
    if prior["done"] > 0:
        n = _sessions_since(s, prior["last_on"], asof)
        if n is not None and n < c["parts_gap_sessions"]:
            guards.append(f"the next part waits: {n} of {c['parts_gap_sessions']} sessions since the last part")
            timing = True
        if klass not in ("market_fear", "temporary"):
            guards.append("a later part only while the case's thesis holds, and it no longer does")
            timing = True
    if timing:
        return {"option": "wait", "refused": True, "guards": guards, "parts": None, "size_inr": 0.0}
    b = odds.bet_size(con, case, isin, asof, market=market, symbol=symbol, rates=rates, root=root)
    whole = b["whole_book_inr"]
    rs = reserve(con, market, asof, free_override)
    share = c["market_fall_reserve_share"] if fall else c["reserve_third_per_name"]
    cap_reserve = min(rs["free_inr"], share * rs["reserve_inr"])
    rail_base = whole
    if market == "US":                                   # A62: a US stock is at most 10% of the SUB-BOOK (not of the whole book)
        try:
            from pflab.us import wholebook
            rail_base = float(wholebook.whole_book_inr(con, asof, root)["us_book_inr"]) or whole
        except Exception:
            rail_base = whole
    cap_rail = max(0.0, (MAX_BROAD_ETF if fall else MAX_STOCK) * rail_base - pos["value_inr"])
    limit_total = b["size_inr"] if b["size_inr"] is not None else float("inf")
    total = min(limit_total, cap_rail, cap_reserve)
    parts = {"n": c["parts"], "this_part": prior["done"] + 1, "gap_sessions": c["parts_gap_sessions"], "total_inr": total}
    binding = min([(limit_total, "the 1% limit"), (cap_rail, "the stock rail" if not fall else "the index ETF rail"), (cap_reserve, "a third of the reserve" if not fall else "half the reserve")])[1]
    remaining = max(0.0, total - prior["spent_inr"]) if prior["done"] else total
    part = min(total / c["parts"], remaining, rs["free_inr"])
    guards.append(f"the bet's size is set by {binding}: Rs {total:,.0f} in all (the bad case would lose Rs {abs(total * b['worst_per_inr']):,.0f}, limit Rs {b['limit_inr']:,.0f} = {c['bet_worst_pct_book']:.0%} of the whole book)")
    if rs["free_inr"] <= 0:
        guards.append("the reserve has nothing free to spend (" + rs["source"] + ")")
    if part < c["min_bet_inr"]:
        return {"option": "nothing", "refused": True, "guards": guards + [f"a part of Rs {part:,.0f} is under the minimum trade of Rs {c['min_bet_inr']:,.0f}: refused"], "parts": parts, "size_inr": 0.0}
    o = odds.outcomes(con, case, "buy_in_parts", isin=isin, asof=asof, bet_inr=total, words=ch.get("words"), rates=rates, market=market, symbol=symbol, root=root)
    if o["expected_inr"] <= 0:
        return {"option": "nothing", "refused": True, "guards": guards + [f"expected result is Rs {o['expected_inr']:,.0f}, not positive: no new money"], "parts": parts, "size_inr": 0.0, "outcome": o}
    if o["worst_inr"] < -b["limit_inr"] * (1 + 1e-9):
        return {"option": "nothing", "refused": True, "guards": guards + ["the bad case does not fit the 1% limit"], "parts": parts, "size_inr": 0.0, "outcome": o}
    parts["part_inr"] = part
    return {"option": "buy_in_parts", "refused": False, "guards": guards, "parts": parts, "size_inr": part, "outcome": o}


# --- the rule ---------------------------------------------------------------------------------------------------------------------------------------------------------------

def _decide_one(con, case: dict, ans: dict, ch: dict, asof: date, free_override: Optional[float], root, cache: Optional[dict] = None) -> dict:
    c = cfg()
    isin, symbol = ch.get("isin") or case.get("isin"), ch.get("symbol") or case.get("symbol")
    market = (case.get("market") or "IN").upper()
    ch = {**ch, "isin": isin, "symbol": symbol}
    klass = ans["class"] or case.get("klass")
    pending = ans["pending"] or case.get("pending")
    pos = odds.position(con, market, isin, symbol, asof, root)
    kind, move, window = odds.case_kind_move(con, case)
    rates = odds.base_rates(con, ch.get("base_rate_set") if ch.get("base_rate_set") not in (None, "history", "own range", "own_range") else kind, move=move, isin=isin, asof=asof,
                            market=market, symbol=symbol, window=window, root=root, cache=cache)
    whole = odds.whole_book(con, asof, root)

    def out(option, reason, size=0.0, guards=None, refused=False, parts=None, thesis=False, extra=None):
        o = {"isin": isin, "symbol": symbol, "rule_option": option, "size_inr": float(size), "parts": parts, "reason": reason, "guards": guards or [], "refused": bool(refused),
             "thesis_break": bool(thesis), "klass": klass, "pending": pending, "held": pos["held"], "base_rates_basis": rates["basis"],
             "big_trade_check": needs_big_trade_check(con, option, size, asof, whole_inr=whole)}
        o.update(extra or {})
        return o
    pn = f" Looks again at: {pending}." if pending else ""
    if pos["held"]:
        v0 = pos["value_inr"]
        if klass == "damage":
            sell = odds.outcomes(con, case, "sell", isin=isin, asof=asof, words=ch.get("words"), rates=rates, market=market, symbol=symbol, root=root)
            guard = odds._guard(con, isin, pos["qty"], pos["price"], asof) if market == "IN" and pos["price"] else None
            g = ([guard + " (a thesis break overrides it)"] if guard else [])
            return out("sell", f"Damage to the business or its governance is a thesis break: sell the whole position (about Rs {v0:,.0f}); it costs Rs {sell['tax_inr']:,.0f} of estimated tax now.", v0, g, thesis=True,
                       extra={"outcome": sell})
        if klass in ("unclear", None) and pending:
            return out("freeze", f"Not yet clear and something is pending ({pending}): no new buying of the name, and look again at that event.", 0.0, [f"waiting for: {pending}"])
        tab = {o: odds.outcomes(con, case, o, isin=isin, asof=asof, words=ch.get("words"), rates=rates, market=market, symbol=symbol, root=root) for o in ("sell", "trim", "hold")}
        thr = c["sale_beats_holding_pts"] / 100.0 * v0
        best, gain = "hold", 0.0
        for o in ("sell", "trim"):
            d = tab[o]["expected_inr"] - tab["hold"]["expected_inr"]
            if d >= thr and d > gain:
                best, gain = o, d
        if best != "hold":
            return out(best, f"{best.capitalize()}: its expected result after tax and charges beats holding by Rs {gain:,.0f}, more than the {c['sale_beats_holding_pts']:g}% of the position (Rs {thr:,.0f}) a sale must clear.",
                       tab[best]["size_inr"], extra={"outcome": tab[best], "hold": tab["hold"]})
        waits, wait_guards = "", []
        if ch.get("option") == "buy_in_parts" and klass in ("market_fear", "temporary"):
            b = _buy(con, case, klass, ch, pos, asof, market, c, rates, free_override, root, ans)
            if b["option"] == "buy_in_parts":
                return out("buy_in_parts", f"Add in parts: the expected result is positive and the bad case fits the 1% limit; this part Rs {b['size_inr']:,.0f}.", b["size_inr"], b["guards"], parts=b["parts"],
                           extra={"outcome": b.get("outcome")})
            # S85 fix3: a refused buy of a name already held is still a buy that WAITS: the guard that held it back stays in the stored reason (the retry reads BUY_WAITS to find it again)
            wait_guards = [g for g in b["guards"] if not g.startswith("the bet's size is set by")]
            if wait_guards:
                waits = f" {BUY_WAITS}: " + "; ".join(wait_guards[:2]) + "."
        return out("hold", f"Hold: no sale beats holding by {c['sale_beats_holding_pts']:g}% of the position after tax and charges (best sale gain Rs {max(0.0, tab['sell']['expected_inr'] - tab['hold']['expected_inr']):,.0f}, trim "
                           f"Rs {max(0.0, tab['trim']['expected_inr'] - tab['hold']['expected_inr']):,.0f}; the bar is Rs {thr:,.0f}).{waits}{pn}", 0.0, wait_guards, extra={"hold": tab["hold"]})
    # not held
    if klass == "damage":
        return out("wait" if pending else "nothing", f"Damage to the business or its governance: no buying until the outcome is public and {c['damage_wait_sessions']} sessions after it.{pn}", 0.0,
                   [f"damage: wait {c['damage_wait_sessions']} sessions after the pending outcome is public"])
    if klass in ("unclear", None):
        return out("wait" if pending else "nothing", f"Not yet clear: no new money until it is.{pn}", 0.0, [f"waiting for: {pending}"] if pending else [])
    b = _buy(con, case, klass, ch, pos, asof, market, c, rates, free_override, root, ans)
    if b["option"] == "buy_in_parts":
        return out("buy_in_parts", f"Buy in {c['parts']} parts from the reserve: expected result positive, the bad case fits {c['bet_worst_pct_book']:.0%} of the whole book; this part Rs {b['size_inr']:,.0f} "
                                   f"of Rs {b['parts']['total_inr']:,.0f}.", b["size_inr"], b["guards"], parts=b["parts"], extra={"outcome": b.get("outcome")})
    why = " ".join(g for g in b["guards"][:2])
    return out(b["option"], f"No new money now: {why}", 0.0, b["guards"], refused=b["refused"], parts=b.get("parts"), extra={"outcome": b.get("outcome")})


def option_row(d: dict) -> dict:
    """The keyword arguments for `cases.add_option(con, case_id, now, track="rule", chosen=True, **row)` of one decision of `decide` (`d` or an entry of `d["all"]`): the rupees of the chosen
    option; a buy's rupees are scaled from the whole bet to the part decided now (so the row's size and its rupees agree, as `think/score.py` reads them)."""
    o = d.get("outcome") or {}
    k = 1.0
    tot = (d.get("parts") or {}).get("total_inr")
    if d.get("rule_option") == "buy_in_parts" and tot and tot > 0 and o:
        k = float(d["size_inr"]) / float(tot)
    return {"isin": d.get("isin"), "symbol": d.get("symbol"), "option": d["rule_option"], "worst_inr": float(o.get("worst_inr", 0.0)) * k, "likely_inr": float(o.get("likely_inr", 0.0)) * k,
            "best_inr": float(o.get("best_inr", 0.0)) * k, "expected_inr": float(o.get("expected_inr", 0.0)) * k, "worst_pct_book": float(o.get("worst_pct_book", 0.0)) * k,
            "size_inr": float(d.get("size_inr") or 0.0), "reason": d.get("reason", "")}


def decide(con, case_id: int, answer: Optional[dict], asof, *, reserve_free_inr: Optional[float] = None, root=None, cache: Optional[dict] = None) -> dict:
    """The rule's decision for the case. The returned dict is the case's own name's decision; `all` lists one per name in the answer. `reserve_free_inr` states the free reserve (tests). `cache`: the dict
    passed to `odds.option_table` for the same case, so the history is scanned once."""
    asof = asof.date() if isinstance(asof, datetime) else asof
    case = cases.get_case(con, case_id) or {"case_id": case_id}
    ans = odds.norm_answer(answer)
    choices = ans["choices"] or [{"isin": case.get("isin"), "symbol": case.get("symbol"), "option": None, "words": {}, "base_rate_set": None, "reason": ""}]
    res = [_decide_one(con, case, ans, ch, asof, reserve_free_inr, root, cache) for ch in choices]
    primary = next((r for r in res if r["isin"] == case.get("isin")), res[0])
    return {**primary, "all": res, "case_id": case_id, "asof": str(asof)}
