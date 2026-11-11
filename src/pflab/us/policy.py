"""The sub-book's state, core-ETF policy and rails (market = "US"). The rails are the rupee book's, reused: `core/rails.clip_weights` works on weights, so it takes the US state as it is
(no borrowing, no shorting, the circuit breaker); the position CAPS are the sub-book's own (S82, `[us]`): a broad US index ETF (`broad_index_etfs`, SPY) up to `broad_index_cap` of the
sub-book (all of it by default), any other ETF `etf_cap` (35%), one company `stock_cap` (10%). The rupee book's constants are not touched: the caps go in through `clip_weights(..., caps=)`.
Not enforced here: the 25% sector rail (no sector map for US stocks; the sub-book holds ETFs only until the stock picks of S83).

    build(con, day, bars, cfg)    the state at the close of `day` (point in time: only bars dated on or before `day`, only lots acquired on or before it)
    decide(state)                 the core policy: the broad index ETF(s) at equal weights, `invested_share` of the sub-book in all, the rest in dollars. Needs no proven edge (like
                                  `baseline_v1`); the 13-ETF equal-weight baseline of S81 is retired. Open to extra names (`extra`, S83) under the same caps
    check(con, state, decision)   the weights -> the orders that may be placed (band, minimum trade, cost filter, turnover cap), each with its reason written by code
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from pflab import core, us
from pflab.core import rails as core_rails
from pflab.data import us_prices
from pflab.us import book, costs, data, instruments as uins

BREAKER_DRAWDOWN = 0.12            # the same 12%-below-its-own-high breaker as the rupee book (paper/cadence.py), on the sub-book's own value


def universe_keys(con, symbols: List[str], root=None, now=None) -> Dict[str, str]:
    """Register each symbol (market US, USD) and return {symbol: key}; keys are ZZ+CIK from the cached SEC map, else the symbol key."""
    ciks = uins.load_ciks(root)
    return {s: uins.ensure(con, s, etf=(s in us_prices.ETFS), name=us_prices.ETFS.get(s, s), ciks=ciks, now=now) for s in symbols}


def _breaker(con, value: float) -> bool:
    r = con.execute("SELECT max(value_usd) FROM us_days_s81").fetchone()
    peak = max(float(r[0] or 0.0), value)
    return peak > 0 and value <= peak * (1 - BREAKER_DRAWDOWN)


def roles(s: dict) -> dict:
    return {"broad": {x.upper() for x in s["broad_index_etfs"]}}


def cap_for(sym: str, etf: bool, s: dict) -> float:
    """The sub-book's cap for a name, as a share of the sub-book: broad index ETF, other ETF, one company."""
    if sym.upper() in roles(s)["broad"]:
        return float(s["broad_index_cap"])
    return float(s["etf_cap"]) if etf else float(s["stock_cap"])


def build(con, day: date, bars: Dict[str, object], cfg: Optional[dict] = None, root=None, now=None, market: str = "US") -> dict:
    s = us.settings(cfg)
    core_syms = [x.upper() for x in s["broad_index_etfs"]]
    pos = book.positions(con, day)
    held_syms = {}
    for k, q in pos.items():
        sym = uins.symbol_of(con, k)
        if sym and q > 1e-9:
            held_syms[sym] = k
    keys = {**universe_keys(con, core_syms, root, now), **{k: v for k, v in held_syms.items() if k not in core_syms}}
    cash = book.cash(con, day)
    rows, total, caps = [], 0.0, {}
    for sym in dict.fromkeys(core_syms + list(held_syms)):
        key = uins.canonical(con, keys.get(sym) or held_syms[sym], day)
        q = pos.get(key, 0.0)
        last = data.last_on_or_before(bars.get(sym), day)
        today = data.bar_on(bars.get(sym), day)
        px = last["close"] if last else None
        value = q * px if px else 0.0
        total += value
        etf = sym in us_prices.ETFS or sym in core_syms
        caps[key] = cap_for(sym, etf, s)
        rows.append({"isin": key, "symbol": sym, "sector": None, "asset_class": "etf" if etf else "equity", "qty": q, "price": px, "value": value, "weight": 0.0,
                     "buyable": bool(today) and sym in core_syms, "klass": "us_equity", "price_date": str(last["date"]) if last else None})
    value = total + cash
    for r in rows:
        r["weight"] = r["value"] / value if value > 0 else 0.0
    cc = core.settings()
    try:
        funded_today = bool(con.execute("SELECT 1 FROM us_transfers_s82 WHERE us_day=? AND phase <> 'converted_seed' LIMIT 1", [day]).fetchone())
    except Exception:
        funded_today = False
    return {"day": day, "market": market, "funded_today": funded_today, "currency": "USD" if market == "US" else "INR", "value": value, "cash": cash, "bank": 0.0, "rows": rows, "target": None, "vol": {},
            "gauge": {"fired": False, "why": "no fall gauge for the US sub-book"}, "breaker": {"on": _breaker(con, value)}, "caps": caps,
            "cfg": {"rails": cc["rails"], "baseline": {**cc["baseline"], "band_pts": float(s["band_pts"])}}, "settings": s}


def decide(state: dict, extra: Optional[Dict[str, float]] = None) -> dict:
    """The broad index ETF(s) at equal weights, `invested_share` of the sub-book in all. `extra`: {symbol: weight} for names a later policy adds (S83); they meet their own caps in `check`."""
    s = state["settings"]
    members = [r for r in state["rows"] if r["buyable"] and r["symbol"].upper() in roles(s)["broad"]]
    notes: List[str] = []
    if not members or state["value"] <= 0:
        return {"weights": {}, "notes": ["nothing to hold or no value"], "classes": {}}
    w = float(s["invested_share"]) / len(members)
    notes.append(f"core: {', '.join(r['symbol'] for r in members)} at {float(s['invested_share']):.0%} of the sub-book (a broad index ETF may be all of it), the rest in dollars")
    weights = {r["isin"]: w for r in members}
    for sym, x in (extra or {}).items():
        row = next((r for r in state["rows"] if r["symbol"].upper() == sym.upper() and r["buyable"]), None)
        if row is not None:
            weights[row["isin"]] = float(x)
            notes.append(f"{sym} at {float(x):.1%} (an added name)")
    return {"weights": weights, "notes": notes, "classes": {"us_equity": float(s["invested_share"])}}


def _month_traded(con, day: date) -> float:
    r = con.execute("SELECT coalesce(sum(qty * price_usd), 0) FROM us_trades_s81 WHERE day >= ? AND day <= ?", [date(day.year, day.month, 1), day]).fetchone()
    return float(r[0] or 0.0)


def check(con, state: dict, decision: dict) -> dict:
    """The orders that may be placed, with reasons. Buys are in dollars (fractional shares); sells in shares."""
    cfg, s = state["cfg"]["rails"], state["settings"]
    band = float(s["band_pts"]) / 100.0
    total, day = float(state["value"]), state["day"]
    rows = {r["isin"]: r for r in state["rows"] if r["buyable"]}
    clipped = core_rails.clip_weights(state, decision["weights"], caps=state.get("caps"))
    orders, skipped = [], []
    for k, c in clipped.items():
        r = rows[k]
        cur = r["value"] / total
        gap = c["target"] - cur
        if abs(gap) < band:
            skipped.append({"isin": k, "symbol": r["symbol"], "why": f"within the band ({gap * 100:+.1f} points)"})
            continue
        px = float(r["price"])
        if gap > 0:
            val = gap * total
            orders.append({"isin": k, "symbol": r["symbol"], "side": "buy", "qty": None, "amount": round(val, 2), "value": val, "note": "; ".join(c["why"]), "from_w": cur, "to_w": c["target"]})
        else:
            qty = float(r["qty"]) if c["target"] <= 1e-9 else min(float(r["qty"]), round(-gap * total / px, 6))
            if qty * px < float(s["min_trade_usd"]):
                skipped.append({"isin": k, "symbol": r["symbol"], "why": "below the minimum trade"})
                continue
            ch = costs.charges("sell", qty, px, day)["total"]
            try:
                tax_est = book.plan_sale(con, k, qty, px, ch, day)["tax_inr"]
            except Exception:
                tax_est = 0.0
            orders.append({"isin": k, "symbol": r["symbol"], "side": "sell", "qty": qty, "amount": None, "value": qty * px, "note": "; ".join(c["why"]), "from_w": cur, "to_w": c["target"],
                           "charges_usd": ch, "tax_inr": tax_est})
    keep = []
    for o in orders:
        if o["value"] < float(s["min_trade_usd"]):
            skipped.append({"isin": o["isin"], "symbol": o["symbol"], "why": f"USD {o['value']:,.0f} is below the minimum trade"})
            continue
        if o["side"] == "sell" and o["charges_usd"] > float(cfg["max_cost_share"]) * o["value"]:
            skipped.append({"isin": o["isin"], "symbol": o["symbol"], "why": f"charges USD {o['charges_usd']:,.2f} are {o['charges_usd'] / o['value']:.1%} of the trade"})
            continue
        keep.append(o)
    invested = sum(r["value"] for r in state["rows"]) / total if total > 0 else 0.0
    deploying = invested < 0.5 * float(s["invested_share"]) or bool(state.get("funded_today"))      # a fresh account or a tranche moved in this session is cash to be put to work: the churn caps of a settled book would take months
    if deploying:
        cap = float(s["deploy_turnover_day"]) * total
    else:
        cap = min(float(cfg["turnover_day"]) * total, max(0.0, float(cfg["turnover_month"]) * total - _month_traded(con, day)))
    traded = sum(o["value"] for o in keep)
    if keep and traded > cap + 1e-9:
        f = cap / traded if traded > 0 else 0.0
        scaled = []
        for o in keep:
            px = float(rows[o["isin"]]["price"])
            if o["side"] == "sell":
                o = dict(o, qty=round(o["qty"] * f, 6), value=o["value"] * f)
            else:
                o = dict(o, amount=round(o["amount"] * f, 2), value=o["value"] * f)
            if o["value"] < float(s["min_trade_usd"]):
                skipped.append({"isin": o["isin"], "why": "dropped by the turnover cap"})
                continue
            o["note"] = (o["note"] + "; " if o["note"] else "") + f"scaled to {f:.0%} by the turnover cap (USD {cap:,.0f})"
            scaled.append(o)
        keep = scaled
    keep.sort(key=lambda o: (o["side"] != "sell", -o["value"]))
    for o in keep:
        o["reason"] = (f"us_core_v2: weight {o['from_w']:.1%} now, target {o['to_w']:.1%}" + (f"; {o['note']}" if o["note"] else "")
                       + (f"; estimated charges USD {o['charges_usd']:,.2f} and Indian tax Rs {o['tax_inr']:,.0f} (estimate)" if o["side"] == "sell" else ""))
    return {"orders": keep, "skipped": skipped, "clipped": {k: v for k, v in clipped.items() if v["why"]}, "turnover_cap_usd": round(cap, 2)}
