"""Standing instructions at the order sites (S85 E4, A69 door b): the one place where the loop, the session loop, the US step and the thinking loop's cases ask `hq/rules.py`
whether an order may be placed, so every site reads the rules the same way and every order held back names the rule.

    apply_close(con, now, day, state, chk)       the close loop: the rail-checked orders (the exit manager's included) -> the ones the rules let through; a buy is held back by `pause_buys` /
                                                  `no_new_names`, shrunk by a `cash_floor`; a discretionary sale by `hold_name` (a stop, a rail trim, a thesis break and the gauge's risk cut are never held)
    apply_us(con, now, day, orders)              the same for the US step's orders (rupee books and the sub-book use one list of rules; a rule with a market names it)
    session_block(con, now, o, market)           the session loop's `_carry_out`: -> the sentence saying why this order is not carried out, or None
    case_block(con, now, day, ...)               the thinking loop's `act`: -> the sentence, or None
    report_line(con, day) / card_text(con, day)  the lines the 15:45 report and the book card say about what the rules held back that day

The kill switch and the rails sit ABOVE rules (a rule only ever tightens): nothing here lets an order through that the rails refused, and a failure to read the rules holds every buy (never lets one pass).
A held-back order is a row in `rules_held_back_s85` (the rule's id, name and words, where it was met, the rupees) and the card, the report and the case say "not bought: your rule '...'".
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from pflab.hq import rules

BLOCKED_BY_CLOSE = "close"


def _market_of(isin: Optional[str], default: str = "IN") -> str:
    return "US" if str(isin or "").startswith(("ZZ", "US:")) else default


def classify_row(r: dict) -> Tuple[str, set]:
    """(sleeve, classes) of a state row of the rupee book: gold, international, index (an equity ETF), stocks (a share)."""
    k, ac = r.get("klass"), (r.get("asset_class") or "")
    if k == "gold":
        c = {"gold"}
    elif k == "international":
        c = {"international"}
    elif k == "cash":
        c = {"cash"}
    elif ac == "etf":
        c = {"index"}
    else:
        c = {"stocks"}
    return str(r.get("sleeve") or ""), c


def classify(con, isin: str, symbol: Optional[str] = None, market: str = "IN") -> Tuple[str, set]:
    """(sleeve, classes) of a security for a site that has no state row (the session loop, a case)."""
    if market == "US" or str(isin).startswith(("ZZ", "US:")):
        try:
            from pflab.data import us_prices
            etf = str(symbol or "").upper() in us_prices.ETFS
        except Exception:
            etf = str(symbol or "").upper() in ("SPY", "QQQ", "VOO", "IVV")
        return "us", {"international", "index" if etf else "stocks"}
    from pflab.core import sleeves
    from pflab.paper import allocation, book
    m = book.inst(con, isin)
    return sleeves.sleeve_of(con, isin), classify_row({"klass": allocation.class_of(m["asset_class"], m["name"], m["symbol"], isin), "asset_class": m["asset_class"]})[1]


def _note(con, now: datetime, day: date, market: str, isin, symbol, side: str, rule: Optional[dict], site: str, kind: Optional[str], value: float, note: str) -> None:
    from pflab.pm.store import next_id
    try:
        con.execute("INSERT INTO rules_held_back_s85 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [next_id(con, "rules_held_back_s85", "held_id"), day, now, market, isin, symbol, side, (rule or {}).get("rule_id"), (rule or {}).get("name"), (rule or {}).get("text"),
                     site, kind, float(value or 0.0), note[:400]])
    except Exception:
        pass


def _held_text(rule: dict, side: str, symbol: str, value: float, market: str = "IN") -> str:
    cur = "USD" if market == "US" else "Rs"
    what = "not bought" if side == "buy" else "not sold"
    return f"{what}: {rules.label(rule)}" + (f" holds back {symbol} ({cur} {value:,.0f})" if symbol else "")


def _sell_kind(o: dict, row: Optional[dict]) -> Optional[str]:
    """The order kind a hold_name looks at: the exit manager's own kind, a risk cut, or 'rail' for a rebalance sale of a name over its rail (a rail trim is a rail, not a wish)."""
    k = str(o.get("kind") or "").lower()
    if k:
        return k
    if o.get("risk_cut"):
        return "risk"
    if row is not None and o.get("from_w") is not None:
        try:
            from pflab.core import policy
            if float(o["from_w"]) > policy.cap_of(row) + 1e-9:
                return "rail"
        except Exception:
            pass
    if "over the" in str(o.get("note") or "") or "rail" in str(o.get("note") or "").lower() or "capped at" in str(o.get("note") or ""):
        return "rail"
    return None


def apply_close(con, now: datetime, day: date, state: dict, chk: dict) -> dict:
    """The close loop's hook: `chk` is rails.check's output (the exit orders already in front). -> chk with the orders the rules let through; the held ones are added to `chk["skipped"]`
    (with the rule's words) and to `chk["rule_notes"]`. Reading the rules failing holds every buy."""
    orders = list(chk["orders"])
    rows = {r["isin"]: r for r in state["rows"]}
    total = float(state.get("value") or 0.0)
    keep: List[dict] = []
    skipped = list(chk.get("skipped") or [])
    notes: List[str] = []
    try:
        for o in orders:
            r = rows.get(o["isin"]) or {}
            sleeve, cls = classify_row(r) if r else classify(con, o["isin"], o.get("symbol"))
            if o["side"] == "buy":
                new = float(r.get("qty") or 0.0) <= 1e-9
                rule = rules.blocks(con, day, isin=o["isin"], symbol=o.get("symbol"), sleeve=sleeve, cls=cls, action="buy", new_name=new, market="IN")
            else:
                rule = rules.blocks(con, day, isin=o["isin"], symbol=o.get("symbol"), sleeve=sleeve, cls=cls, action="sell", order_kind=_sell_kind(o, r or None), market="IN")
            if rule:
                why = _held_text(rule, o["side"], o.get("symbol") or o["isin"], float(o.get("value") or 0.0))
                skipped.append({"isin": o["isin"], "symbol": o.get("symbol"), "why": why})
                notes.append(why)
                _note(con, now, day, "IN", o["isin"], o.get("symbol"), o["side"], rule, BLOCKED_BY_CLOSE, o.get("kind"), float(o.get("value") or 0.0), o.get("reason") or o.get("note") or "")
                continue
            keep.append(o)
        keep, skipped, notes = _cash_floor_close(con, now, day, state, keep, skipped, notes, total)
    except Exception as e:
        keep = [o for o in orders if o["side"] != "buy"]
        why = f"the standing instructions could not be read ({type(e).__name__}: {str(e)[:100]}): no buying at this close"
        skipped.append({"isin": None, "symbol": None, "why": why})
        notes.append(why)
    keep.sort(key=lambda o: (o["side"] != "sell", -float(o.get("value") or 0.0)))
    return {**chk, "orders": keep, "skipped": skipped, "rule_notes": notes}


def _cash_floor_close(con, now, day, state, keep, skipped, notes, total):
    cf = rules.cash_floor(con, day, "IN")
    if not cf or total <= 0:
        return keep, skipped, notes
    cash = float(state.get("cash") or 0.0) + float(state.get("bank") or 0.0)
    sells = sum(float(o.get("value") or 0.0) for o in keep if o["side"] == "sell")
    buys = [o for o in keep if o["side"] == "buy"]
    want = sum(float(o.get("value") or 0.0) for o in buys)
    room = max(0.0, cash + sells - cf["share"] * total)
    if want <= room + 1e-6:
        return keep, skipped, notes
    f = room / want if want > 0 else 0.0
    min_trade = float(state["cfg"]["rails"]["min_trade_rupees"])
    out = [o for o in keep if o["side"] != "buy"]
    for o in buys:
        v = float(o.get("value") or 0.0) * f
        if v < min_trade:
            why = _held_text(cf["rule"], "buy", o.get("symbol") or o["isin"], float(o.get("value") or 0.0))
            skipped.append({"isin": o["isin"], "symbol": o.get("symbol"), "why": why})
            notes.append(why)
            _note(con, now, day, "IN", o["isin"], o.get("symbol"), "buy", cf["rule"], BLOCKED_BY_CLOSE, "cash_floor", float(o.get("value") or 0.0), "cash floor leaves no room")
            continue
        why = f"shrunk to {f:.0%} (Rs {v:,.0f} of Rs {float(o.get('value') or 0.0):,.0f}): {rules.label(cf['rule'])} keeps {cf['share']:.0%} of the book in cash"
        o = dict(o, amount=round(float(o["amount"]) * f, 2), value=v, note=((o.get("note") or "") + "; " if o.get("note") else "") + why)
        notes.append(f"{o.get('symbol')}: {why}")
        _note(con, now, day, "IN", o["isin"], o.get("symbol"), "buy", cf["rule"], BLOCKED_BY_CLOSE, "cash_floor", v, why)
        out.append(o)
    return out, skipped, notes


def apply_us(con, now: datetime, day: date, orders: List[dict], cash_usd: Optional[float] = None, total_usd: Optional[float] = None) -> Tuple[List[dict], List[str]]:
    """The US step's hook: `orders` as `us.policy.check` made them (USD). -> (the orders the rules let through, the plain lines for what was held). The cash floor of a US-market rule
    keeps that share of the sub-book in cash when the sub-book's cash and total are given."""
    held_lines: List[str] = []
    keep: List[dict] = []
    try:
        pos = None
        for o in orders:
            sleeve, cls = classify(con, o["isin"], o.get("symbol"), "US")
            if o["side"] == "buy":
                if pos is None:
                    from pflab.us import book as usb
                    pos = usb.positions(con)
                rule = rules.blocks(con, day, isin=o["isin"], symbol=o.get("symbol"), sleeve=sleeve, cls=cls, action="buy", new_name=float(pos.get(o["isin"], 0.0)) <= 1e-9, market="US")
            else:
                n = str(o.get("note") or "")
                rule = rules.blocks(con, day, isin=o["isin"], symbol=o.get("symbol"), sleeve=sleeve, cls=cls, action="sell", order_kind=("rail" if ("capped at" in n or "rail" in n) else None), market="US")
            if rule:
                line = _held_text(rule, o["side"], o.get("symbol") or o["isin"], float(o.get("value") or 0.0), "US")
                held_lines.append(line)
                _note(con, now, day, "US", o["isin"], o.get("symbol"), o["side"], rule, "us_step", o.get("kind"), float(o.get("value") or 0.0), o.get("reason") or "")
                continue
            keep.append(o)
        cf = rules.cash_floor(con, day, "US")
        if cf and cash_usd is not None and total_usd and total_usd > 0:
            sells = sum(float(o.get("value") or 0.0) for o in keep if o["side"] == "sell")
            buys = [o for o in keep if o["side"] == "buy"]
            want = sum(float(o.get("value") or 0.0) for o in buys)
            room = max(0.0, cash_usd + sells - cf["share"] * total_usd)
            if buys and want > room + 1e-6:
                f = room / want if want > 0 else 0.0
                keep = [o for o in keep if o["side"] != "buy"]
                for o in buys:
                    v = float(o["value"]) * f
                    if v < 1.0:
                        line = _held_text(cf["rule"], "buy", o.get("symbol") or o["isin"], float(o["value"]), "US")
                        held_lines.append(line)
                        _note(con, now, day, "US", o["isin"], o.get("symbol"), "buy", cf["rule"], "us_step", "cash_floor", float(o["value"]), "cash floor leaves no room")
                        continue
                    why = f"shrunk to {f:.0%} by {rules.label(cf['rule'])} (keeps {cf['share']:.0%} of the sub-book in cash)"
                    keep.append(dict(o, amount=round(float(o["amount"]) * f, 2) if o.get("amount") else o.get("amount"), value=v, reason=f"{o.get('reason', '')}; {why}"))
                    held_lines.append(f"{o.get('symbol')}: {why}")
                    _note(con, now, day, "US", o["isin"], o.get("symbol"), "buy", cf["rule"], "us_step", "cash_floor", v, why)
    except Exception as e:
        keep = [o for o in orders if o["side"] != "buy"]
        held_lines.append(f"the standing instructions could not be read ({type(e).__name__}: {str(e)[:100]}): no US buying at this step")
    return keep, held_lines


def session_block(con, now: datetime, o: dict, market: str = "IN", px: Optional[float] = None) -> Optional[str]:
    """The session loop: the sentence saying why order `o` (the exit contract: isin, side, kind, qty/amount) is not carried out, or None. Fails closed for a buy."""
    day, side, isin = now.date(), o["side"], o["isin"]
    kind = str(o.get("kind") or "").lower()
    try:
        from pflab.paper import book
        sym = book.inst(con, isin)["symbol"] or isin
        sleeve, cls = classify(con, isin, sym, market)
        held = float(book.positions(con).get(isin, 0.0))
        rule = rules.blocks(con, day, isin=isin, symbol=sym, sleeve=sleeve, cls=cls, action=side, order_kind=kind, new_name=(side == "buy" and held <= 1e-9), market=market)
        value = float(o.get("qty") or 0.0) * float(px or 0.0) if o.get("qty") else float(o.get("amount") or 0.0)
        if rule:
            _note(con, now, day, market, isin, sym, side, rule, "session", kind, value, o.get("reason") or "")
            return _held_text(rule, side, sym, value)
        if side == "buy":
            cf = rules.cash_floor(con, day, market)
            if cf:
                h = book.holdings(con, day)
                total = float(h.get("value") or 0.0)
                cash = float(h.get("cash") or 0.0) + float(h.get("bank") or 0.0)
                if total > 0 and cash - value < cf["share"] * total:
                    _note(con, now, day, market, isin, sym, side, cf["rule"], "session", "cash_floor", value, "cash floor")
                    return _held_text(cf["rule"], side, sym, value) + f" (it keeps {cf['share']:.0%} of the book in cash)"
    except Exception as e:
        if side == "buy":
            return f"not bought: the standing instructions could not be read ({type(e).__name__}: {str(e)[:100]})"
    return None


def case_block(con, now: datetime, *, isin: str, symbol: Optional[str], market: str, side: str, option: str, thesis_break: bool, value: float = 0.0) -> Optional[str]:
    """The thinking loop's `act`: the sentence saying why a case's order is held back by a rule, or None. A sale that the case calls a thesis break (class damage) is never held (hold_name
    stops wishes, not thesis breaks). Fails closed for a buy."""
    day = now.date()
    try:
        from pflab.paper import book
        sleeve, cls = classify(con, isin, symbol, market)
        if side == "buy":
            if market == "US":
                from pflab.us import book as usb
                held = float(usb.positions(con).get(isin, 0.0))
            else:
                held = float(book.positions(con).get(isin, 0.0))
            rule = rules.blocks(con, day, isin=isin, symbol=symbol, sleeve=sleeve, cls=cls, action="buy", new_name=held <= 1e-9, market=market)
        else:
            rule = rules.blocks(con, day, isin=isin, symbol=symbol, sleeve=sleeve, cls=cls, action="sell", order_kind=("thesis" if thesis_break else "case"), market=market)
        if rule:
            _note(con, now, day, market, isin, symbol, side, rule, "case", option, value, "")
            return _held_text(rule, side, symbol or isin, value, market)
        if side == "buy" and market != "US":                                      # a cash floor: the reserve may not be spent below it (the sub-book's cash is its own)
            cf = rules.cash_floor(con, day, market)
            if cf:
                h = book.holdings(con, day)
                total = float(h.get("value") or 0.0)
                cash = float(h.get("cash") or 0.0) + float(h.get("bank") or 0.0)
                if total > 0 and cash - value < cf["share"] * total:
                    _note(con, now, day, market, isin, symbol, side, cf["rule"], "case", "cash_floor", value, "cash floor")
                    return _held_text(cf["rule"], side, symbol or isin, value, market) + f" (it keeps {cf['share']:.0%} of the book in cash)"
    except Exception as e:
        if side == "buy":
            return f"not bought: the standing instructions could not be read ({type(e).__name__}: {str(e)[:100]})"
    return None


# --- what the card and the report say -------------------------------------------------------------------------------------------------

def _active_line(con, day) -> str:
    rs = [r for r in rules.active(con, day) if r["kind"] in rules.NEW_KINDS]
    return "; ".join(rules.describe(r) for r in rs[:4]) + (f" (+{len(rs) - 4} more)" if len(rs) > 4 else "")


def card_text(con, day) -> str:
    """The book card's RULES line: the standing instructions in force and what they held back at this close."""
    try:
        act = _active_line(con, day)
        held = rules.held_back(con, day)
        if not act and not held:
            return "none in force"
        bits = [act] if act else []
        if held:
            bits.append("held back today: " + "; ".join(f"{h['side']} {h['symbol']} ({h['rule_text'][:50] if h['rule_text'] else h['rule_name']})" for h in held[:6]))
        return " | ".join(bits)
    except Exception:
        return "unreadable"


def report_line(con, day) -> Optional[str]:
    """One line for the 15:45 report: None when no rule held anything back that day."""
    try:
        held = rules.held_back(con, day)
        if not held:
            return None
        names = dict.fromkeys(f"your rule '{(h['rule_text'] or h['rule_name'] or '')[:60]}'" for h in held)
        return f"Held back by {', '.join(list(names)[:2])}: {len(held)} order(s) ({', '.join(sorted({h['symbol'] or '?' for h in held})[:5])})."
    except Exception:
        return None
