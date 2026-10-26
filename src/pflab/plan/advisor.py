"""The advisor (S45, PLAN A7): turn the rupees the bucket plan gives to direct stocks into per-stock quantities and
prices, then hand each buy to the trader planner. It proposes; the investor decides and places every order himself.

Rule (a default the investor can change in his targets file, `[stocks]`):
    candidates   names on his stock list whose safety verdict is OK today (guards); FAIL and data-gap names get nothing
    targets      equal shares of the direct-stock bucket among the candidates, each capped at `max_weight` of the
                 investable total (default 0.08)
    steering     this month's rupees go to the candidates furthest below their share first (in proportion to the
                 shortfall), never above it; nothing is sold
    quantities   whole shares at the last close; what does not buy a whole share is left unspent
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

DEFAULT_MAX_WEIGHT = 0.08


@dataclass
class StockBuy:
    symbol: str
    isin: str
    rupees: float
    price: float
    qty: int
    cost: float
    held_value: float
    target_value: float


@dataclass
class Advice:
    asof: date
    amount: float
    buys: List[StockBuy] = field(default_factory=list)
    unspent: float = 0.0
    skipped: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def allocate(amount: float, held: Dict[str, float], target_each: float, cap_value: float) -> Dict[str, float]:
    """Rupees per candidate: shortfalls to min(target_each, cap_value) filled in proportion, never past them."""
    tgt = min(target_each, cap_value)
    short = {s: max(tgt - v, 0.0) for s, v in held.items()}
    tot = sum(short.values())
    if amount <= 0 or tot <= 0:
        return {s: 0.0 for s in held}
    scale = min(1.0, amount / tot)
    return {s: d * scale for s, d in short.items()}


def advise(amount: float, candidates: List[dict], held: Dict[str, float], prices: Dict[str, float],
           bucket_target_value: float, investable: float, asof: date, max_weight: float = DEFAULT_MAX_WEIGHT,
           skipped: Optional[List[str]] = None) -> Advice:
    """`candidates`: [{symbol, isin}] that passed the guards; `held`: symbol -> value held now; `prices`: symbol ->
    last price; `bucket_target_value`: the direct-stock bucket's target in rupees after this month's money."""
    adv = Advice(asof, amount, skipped=list(skipped or []))
    if not candidates:
        adv.unspent = amount
        adv.notes.append("no list name passes the safety checks today: the money stays unspent")
        return adv
    syms = [c["symbol"] for c in candidates]
    each = bucket_target_value / len(syms)
    alloc = allocate(amount, {s: held.get(s, 0.0) for s in syms}, each, max_weight * investable)
    if each > max_weight * investable:
        adv.notes.append(f"each name is capped at {max_weight:.0%} of the investable total "
                         f"(Rs {max_weight * investable:,.0f}); the rest of the bucket's share waits")
    spent = 0.0
    for c in candidates:
        r = alloc[c["symbol"]]
        px = prices.get(c["symbol"])
        if r <= 0 or not px:
            if not px:
                adv.notes.append(f"{c['symbol']}: no price; nothing proposed")
            continue
        q = int(math.floor(r / px + 1e-9))
        if q <= 0:
            continue
        adv.buys.append(StockBuy(c["symbol"], c["isin"], r, px, q, q * px, held.get(c["symbol"], 0.0), each))
        spent += q * px
    adv.unspent = round(amount - spent, 2)
    return adv


def run(con, asof: date, amount: float, with_plan: bool = False):
    """The whole month for `amount` rupees: the bucket plan (funds, gold and the rest as `pflab pm propose` does),
    the direct-stock share split into names, and the trader's tickets. Returns (bucket plan text, Advice, tickets),
    and the bucket plan itself and the bucket split as well with `with_plan` (S55 ready plans)."""
    from pflab import _toml
    from pflab.calc import valuation as val
    from pflab.ingest import kite_depth
    from pflab.ledger import events as ev
    from pflab.ledger.book import Ledger
    from pflab.plan import guards as gd
    from pflab.plan import monthly, rebalance, trader
    from pflab.plan import targets as tg
    from pflab.risk import report as riskreport
    t = tg.load()
    plan, _ = monthly.run(con, asof, amount, t, log=False)
    led = Ledger.replay(ev.load(con), upto=asof)
    pf = val.store_price_fn(con)
    v = val.value_ledger(led, pf, asof)
    extra, _ = monthly.fd_debt(con, asof)
    vals = rebalance.bucket_values(v, riskreport.instruments_frame(con), t, extra)
    alloc = rebalance.steer(vals, t, amount)
    investable = sum(vals.values()) + amount
    eq_t = t.buckets.get("equity")
    raw = _toml.load(tg.default_path()).get("stocks", {})
    lst = gd.stock_list()
    verdicts = {g.symbol: g.verdict for g in gd.check_all(con, asof, lst)}
    cands = [s for s in lst if verdicts.get(s["symbol"]) == "ok"]
    skipped = [f"{s['symbol']} ({verdicts.get(s['symbol'], 'unknown')})" for s in lst if verdicts.get(s["symbol"]) != "ok"]
    sym_of = {s["isin"]: s["symbol"] for s in lst}
    held: Dict[str, float] = {}
    for r in v.positions.itertuples():
        if r.isin in sym_of and r.value == r.value:
            held[sym_of[r.isin]] = held.get(sym_of[r.isin], 0.0) + float(r.value)
    prices = {}
    for s in cands:
        p = pf(s["isin"], asof)
        if p is not None:
            prices[s["symbol"]] = float(p.value)
    adv = advise(alloc.get("equity", 0.0), cands, held, prices, (eq_t.target if eq_t else 0.0) * investable,
                 investable, asof, float(raw.get("max_weight", DEFAULT_MAX_WEIGHT)), skipped)
    from pflab.quant import forecast
    tk = trader.plan_all(adv.buys, impact=kite_depth.impact_note_fn(con),
                         turnover=forecast.turnover_fn(con, asof))          # the size check
    if with_plan:
        return monthly.render(plan), adv, tk, plan, alloc
    return monthly.render(plan), adv, tk


def render(adv: Advice, tickets: Optional[Dict[str, List[str]]] = None) -> str:
    L = [f"Direct-stock buys for Rs {adv.amount:,.0f} on {adv.asof} (a proposal, not an order; you place every trade):"]
    for b in sorted(adv.buys, key=lambda x: -x.cost):
        L.append(f"  {b.symbol:<12} {b.qty:>5} x ~{b.price:,.2f} = Rs {b.cost:,.0f}   "
                 f"(held Rs {b.held_value:,.0f}, share Rs {b.target_value:,.0f})")
        for t in (tickets or {}).get(b.symbol, []):
            L.append(f"      {t}")
    if adv.skipped:
        L.append("  not bought (safety checks): " + ", ".join(adv.skipped))
    L.append(f"  unspent Rs {adv.unspent:,.0f}")
    L += [f"  note: {n}" for n in adv.notes]
    return "\n".join(L)
