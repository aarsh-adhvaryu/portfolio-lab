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


def build(con, day: date, bars: Dict[str, object], cfg: Optional[dict] = None, root=None, now=None, market: str = "US", pick_syms=()) -> dict:
    """`pick_syms` (S83 L8): the symbols of the picks the sub-book holds or waits to hold: rows of the state (buyable with a bar today, so they can be bought and a withdrawn one sold)."""
    s = us.settings(cfg)
    core_syms = [x.upper() for x in s["broad_index_etfs"]]
    pos = book.positions(con, day)
    held_syms = {}
    for k, q in pos.items():
        sym = uins.symbol_of(con, k)
        if sym and q > 1e-9:
            held_syms[sym] = k
    picks_set = [x.upper() for x in pick_syms if x and x.upper() not in core_syms]
    keys = {**universe_keys(con, core_syms + [x for x in picks_set if x not in held_syms], root, now), **{k: v for k, v in held_syms.items() if k not in core_syms}}
    cash = book.cash(con, day)
    rows, total, caps = [], 0.0, {}
    vol = {}
    for sym in dict.fromkeys(core_syms + list(held_syms) + picks_set):
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
                     "buyable": bool(today) and (sym in core_syms or sym in picks_set), "klass": "us_equity", "price_date": str(last["date"]) if last else None})
        if sym in picks_set:
            vol[key] = _vol(bars.get(sym), day)
    value = total + cash
    for r in rows:
        r["weight"] = r["value"] / value if value > 0 else 0.0
    cc = core.settings()
    try:
        funded_today = bool(con.execute("SELECT 1 FROM us_transfers_s82 WHERE us_day=? AND phase <> 'converted_seed' LIMIT 1", [day]).fetchone())
    except Exception:
        funded_today = False
    return {"day": day, "market": market, "funded_today": funded_today, "currency": "USD" if market == "US" else "INR", "value": value, "cash": cash, "bank": 0.0, "rows": rows, "target": None, "vol": {k: v for k, v in vol.items() if v},
            "gauge": {"fired": False, "why": "no fall gauge for the US sub-book"}, "breaker": {"on": _breaker(con, value)}, "caps": caps,
            "cfg": {"rails": cc["rails"], "baseline": {**cc["baseline"], "band_pts": float(s["band_pts"])}}, "settings": s}


def _vol(df, day: date, n: int = 250) -> Optional[float]:
    """Annual volatility of a name from its last `n` daily closes up to `day` (None under 60 closes: the picks sizing then uses its default)."""
    try:
        c = df[df["date"] <= day]["close"].astype(float).tail(n + 1)
        r = c.pct_change().dropna()
        return float(r.std() * (252 ** 0.5)) if len(r) >= 60 else None
    except Exception:
        return None


def decide(state: dict, extra: Optional[Dict[str, float]] = None, core_total: Optional[float] = None) -> dict:
    """The broad index ETF(s) at equal weights, `invested_share` of the sub-book in all. `extra`: {symbol: weight} for names a later policy adds (S83); they meet their own caps in `check`."""
    s = state["settings"]
    members = [r for r in state["rows"] if r["buyable"] and r["symbol"].upper() in roles(s)["broad"]]
    notes: List[str] = []
    if not members or state["value"] <= 0:
        return {"weights": {}, "notes": ["nothing to hold or no value"], "classes": {}}
    w = (float(s["invested_share"]) if core_total is None else float(core_total)) / len(members)
    notes.append(f"core: {', '.join(r['symbol'] for r in members)} at {w * len(members):.0%} of the sub-book (a broad index ETF may be all of it), the rest in dollars")
    weights = {r["isin"]: w for r in members}
    for sym, x in (extra or {}).items():
        row = next((r for r in state["rows"] if r["symbol"].upper() == sym.upper() and r["buyable"]), None)
        if row is not None:
            weights[row["isin"]] = float(x)
            notes.append(f"{sym} at {float(x):.1%} (an added name)")
    return {"weights": weights, "notes": notes, "classes": {"us_equity": float(s["invested_share"])}}


OUTSIDE = "[outside the monthly cap"                       # the tag an order's reason carries when it is not rebalancing: its fill is left out of the month's turnover (S84 F2)


def _month_traded(con, day: date) -> float:
    """What the month's REBALANCING has traded (dollars): fills of orders tagged OUTSIDE (funding purchases, a named pick's purchase, a reserve buy, the full exit of a withdrawn pick) are not counted."""
    r = con.execute("SELECT coalesce(sum(t.qty * t.price_usd), 0) FROM us_trades_s81 t LEFT JOIN us_orders_s81 o ON o.order_id = t.order_id "
                    "WHERE t.day >= ? AND t.day <= ? AND coalesce(o.reason, '') NOT LIKE ?", [date(day.year, day.month, 1), day, "%" + OUTSIDE + "%"]).fetchone()
    return float(r[0] or 0.0)


def _scale(items: List[dict], cap: float, s: dict, skipped: list, label: str) -> List[dict]:
    """Bring `items` (orders) to a dollar cap: every order scaled by the same share; a full exit never leaves dust under the minimum trade."""
    traded = sum(o["value"] for o in items)
    if not items or traded <= cap + 1e-9:
        return items
    f = cap / traded if traded > 0 else 0.0
    scaled = []
    for o in items:
        if o["side"] == "sell":
            q = round(o["qty"] * f, 6)
            if o.get("full_exit") and (o["held_qty"] - q) * o["price"] < float(s["min_trade_usd"]):
                q = o["held_qty"]                                        # scaling a full exit must not leave dust the minimum trade would never sell: it goes whole (the dust is under the minimum trade)
            o = dict(o, qty=q, value=q * o["price"])
        else:
            o = dict(o, amount=round(o["amount"] * f, 2), value=o["value"] * f)
        if o["value"] < float(s["min_trade_usd"]) and not o.get("full_exit"):
            skipped.append({"isin": o["isin"], "why": "dropped by the turnover cap"})
            continue
        o["note"] = (o["note"] + "; " if o["note"] else "") + f"scaled to {f:.0%} by the {label} turnover cap (USD {cap:,.0f})"
        scaled.append(o)
    return scaled


def check(con, state: dict, decision: dict) -> dict:
    """The orders that may be placed, with reasons. Buys are in dollars (fractional shares); sells in shares.

    Two caps (S84 F2). REBALANCING keeps the registered caps (a day's `turnover_day`, a month's `turnover_month` of what rebalancing has traded; a fresh account or a tranche moved in today deploys
    under `deploy_turnover_day`). OUTSIDE the monthly cap, limited to `exempt_day_share` (25%) of the sub-book a day: buying a newly named pick (a stock) out of SPY or cash, a reserve buy
    (`decision["kinds"][symbol] == "opportunity"`, set by the thinking loop) and the full exit of a withdrawn pick; the SPY sale that funds such a purchase goes with them. The funding purchases of
    a deploying session never count toward the month either. The tag in the order's reason is what `_month_traded` reads."""
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
        if abs(gap) < band and not (c["target"] <= 1e-9 and float(r["qty"]) > 1e-9):          # a name wanted at zero is sold whatever is left of it: dust inside the band would stay for ever
            skipped.append({"isin": k, "symbol": r["symbol"], "why": f"within the band ({gap * 100:+.1f} points)"})
            continue
        px = float(r["price"])
        if gap > 0:
            val = gap * total
            orders.append({"isin": k, "symbol": r["symbol"], "side": "buy", "qty": None, "amount": round(val, 2), "value": val, "note": "; ".join(c["why"]), "from_w": cur, "to_w": c["target"]})
        else:
            full = c["target"] <= 1e-9                                       # a full exit (a withdrawn pick): never left as dust under the minimum trade or the cost filter (drill accelerated_picks)
            qty = float(r["qty"]) if full else min(float(r["qty"]), round(-gap * total / px, 6))
            if qty * px < float(s["min_trade_usd"]) and not full:
                skipped.append({"isin": k, "symbol": r["symbol"], "why": "below the minimum trade"})
                continue
            ch = costs.charges("sell", qty, px, day)["total"]
            try:
                tax_est = book.plan_sale(con, k, qty, px, ch, day)["tax_inr"]
            except Exception:
                tax_est = 0.0
            orders.append({"isin": k, "symbol": r["symbol"], "side": "sell", "qty": qty, "amount": None, "value": qty * px, "note": "; ".join(c["why"]), "from_w": cur, "to_w": c["target"],
                           "charges_usd": ch, "tax_inr": tax_est, "full_exit": full, "held_qty": float(r["qty"]), "price": px})
    keep = []
    for o in orders:
        if o["value"] < float(s["min_trade_usd"]) and not o.get("full_exit"):
            skipped.append({"isin": o["isin"], "symbol": o["symbol"], "why": f"USD {o['value']:,.0f} is below the minimum trade"})
            continue
        if o["side"] == "sell" and not o.get("full_exit") and o["charges_usd"] > float(cfg["max_cost_share"]) * o["value"]:
            skipped.append({"isin": o["isin"], "symbol": o["symbol"], "why": f"charges USD {o['charges_usd']:,.2f} are {o['charges_usd'] / o['value']:.1%} of the trade"})
            continue
        keep.append(o)
    invested = sum(r["value"] for r in state["rows"]) / total if total > 0 else 0.0
    deploying = invested < 0.5 * float(s["invested_share"]) or bool(state.get("funded_today"))      # a fresh account or a tranche moved in this session is cash to be put to work: the churn caps of a settled book would take months
    kinds = {str(k).upper(): v for k, v in (decision.get("kinds") or {}).items()}
    broad = roles(s)["broad"]
    for o in keep:                                                           # the kind of each order: outside the monthly cap, or rebalancing
        r = rows[o["isin"]]
        pick = r.get("asset_class") == "equity" and r["symbol"].upper() not in broad
        o["outside"] = None
        if o["side"] == "buy" and kinds.get(r["symbol"].upper()) == "opportunity":
            o["outside"] = "reserve buy"
        elif o["side"] == "buy" and pick:
            o["outside"] = "a named pick's purchase"
        elif o["side"] == "sell" and pick and o.get("full_exit"):
            o["outside"] = "the full exit of a withdrawn pick"
    allowance = sum(o["value"] for o in keep if o["outside"] and o["side"] == "buy")          # the SPY sale that funds those purchases rides with them
    for o in sorted((o for o in keep if o["side"] == "sell" and not o["outside"] and rows[o["isin"]]["symbol"].upper() in broad), key=lambda o: -o["value"]):
        if allowance <= 1e-9:
            break
        if o["value"] <= allowance + 1e-9:
            o["outside"], o["funding_sale"] = "the sale that funds a pick", True
            allowance -= o["value"]
    if deploying:
        for o in keep:
            if o["side"] == "buy" and not o["outside"]:
                o["tag"] = "a funding purchase"
    out_items = [o for o in keep if o["outside"]]
    rest = [o for o in keep if not o["outside"]]
    day_cap_out = float(s["exempt_day_share"]) * total
    lead = sum(o["value"] for o in out_items if not o.get("funding_sale"))               # the purchases and exits are what the 25% limits; a funding sale is scaled with them
    if lead > day_cap_out + 1e-9:
        out_items = _scale(out_items, sum(o["value"] for o in out_items) * day_cap_out / lead, s, skipped, "daily 25% pick")
    if deploying:
        cap = float(s["deploy_turnover_day"]) * total
    else:
        cap = min(float(cfg["turnover_day"]) * total, max(0.0, float(cfg["turnover_month"]) * total - _month_traded(con, day)))
    rest = _scale(rest, cap, s, skipped, "rebalancing")
    keep = out_items + rest
    keep.sort(key=lambda o: (o["side"] != "sell", -o["value"]))
    for o in keep:
        tag = o.get("outside") or o.get("tag")
        o["reason"] = (f"us_core_v2: weight {o['from_w']:.1%} now, target {o['to_w']:.1%}" + (f"; {o['note']}" if o["note"] else "") + (f" {OUTSIDE}: {tag}]" if tag else "")
                       + (f"; estimated charges USD {o['charges_usd']:,.2f} and Indian tax Rs {o['tax_inr']:,.0f} (estimate)" if o["side"] == "sell" else ""))
    return {"orders": keep, "skipped": skipped, "clipped": {k: v for k, v in clipped.items() if v["why"]}, "turnover_cap_usd": round(cap, 2)}
