"""The rails around the policy: code the policy cannot edit. `check(con, state, decision)` takes the policy's target weights and returns the orders that may be placed.

    position rails   one company 10%, one sector 25%, one ETF 35% (the same constants as `paper/rails.py`, which also cuts every buy again at the fill); a holding already
                     over a rail is never bought; no borrowing (buys never exceed cash, bank included), no short sales, listed shares and ETFs only
    circuit breaker  while the account is 12% below its own high (`paper/cadence.py`): no buy, sells and holds stay open
    band             a name within `band_pts` points of its target is left alone
    cost and tax     a rebalance trade whose charges plus estimated tax exceed `max_cost_share` of its value is skipped; a risk cut (the fall gauge) is exempt
    turnover         at most `turnover_day` of the book traded in a session and `turnover_month` in a calendar month: every order is scaled down together to fit
"""
from __future__ import annotations

import math
from datetime import date
from typing import Dict, List

from pflab.core import policy


def sell_costs(con, row: dict, qty: float, price: float, day: date) -> Dict[str, float]:
    """Charges and the estimated tax of selling `qty` of a holding at `price` today: FIFO lots, the book's own tax buckets and year-to-date set-off (as `book.fill`)."""
    from pflab.paper import book
    fee = book._charges(row["asset_class"], "sell", qty * price)
    gains, left = {}, qty
    for _lid, acq, lq, cpu, tc in con.execute(book._lots_sql("lot_id, acq_date, qty, cost_per_unit, tax_class", " AND isin=? ORDER BY acq_date, lot_id"), [row["isin"]]).fetchall():
        take = min(lq, left)
        b = book._bucket(tc, row["asset_class"], acq, day)
        gains[b] = gains.get(b, 0.0) + take * (price - cpu) - fee * take / max(qty, 1e-9)
        left -= take
        if left <= 1e-9:
            break
    before = book.year_gains(con, book._fy(day))
    after = dict(before)
    for k, v in gains.items():
        after[k] = after.get(k, 0.0) + v
    return {"charges": round(fee, 2), "tax": round(max(0.0, book.tax_of(after) - book.tax_of(before)), 2)}


def month_traded(con, day: date) -> float:
    r = con.execute("SELECT coalesce(sum(qty * price), 0) FROM paper_trades WHERE day >= ? AND day <= ?", [date(day.year, day.month, 1), day]).fetchone()
    return float(r[0] or 0.0)


def clip_weights(state: dict, targets: Dict[str, float], caps: Dict[str, float] = None) -> Dict[str, dict]:
    """Rails on the weights: returns {isin: {'target': clipped weight, 'was': policy weight, 'why': [...]}}. `caps` (S82, the US sub-book): {isin: cap} replaces the one-name cap of
    those names (the sub-book's broad index ETF may be all of it); None, as for the rupee book, changes nothing."""
    from pflab.paper import rails as hard
    total = float(state["value"])
    rows = {r["isin"]: r for r in state["rows"] if r["buyable"]}
    cur = {k: r["value"] / total for k, r in rows.items()}
    out = {k: {"target": float(targets.get(k, cur[k])), "was": float(targets.get(k, cur[k])), "why": []} for k in rows}
    for k, r in rows.items():                                           # one company / one ETF: never above its rail, and an over-rail holding is never bought
        lim = (caps or {}).get(k, policy.cap_of(r))
        hi = max(lim, cur[k])
        if out[k]["target"] > hi + 1e-12:
            out[k]["target"] = hi
            out[k]["why"].append(f"capped at {hi:.1%} (rail {lim:.0%})")
    sectors: Dict[str, List[str]] = {}
    for k, r in rows.items():
        if r["sector"] and (r["asset_class"] or "") != "etf":
            sectors.setdefault(r["sector"], []).append(k)
    held_sector = {s: sum(r["value"] for r in state["rows"] if r["sector"] == s and (r["asset_class"] or "") != "etf") / total for s in sectors}
    for s, ks in sectors.items():                                       # one sector: the increases are scaled back so the sector stays within its rail (or its current size)
        lim = max(hard.MAX_SECTOR, held_sector[s])
        tot_t = sum(out[k]["target"] for k in ks) + sum(r["value"] / total for r in state["rows"] if r["sector"] == s and not r["buyable"] and (r["asset_class"] or "") != "etf")
        up = sum(max(0.0, out[k]["target"] - cur[k]) for k in ks)
        if tot_t > lim + 1e-12 and up > 0:
            f = max(0.0, 1 - (tot_t - lim) / up)
            for k in ks:
                inc = max(0.0, out[k]["target"] - cur[k])
                if inc:
                    out[k]["target"] = cur[k] + inc * f
                    out[k]["why"].append(f"sector {s} held to {lim:.0%}")
    if state["breaker"]["on"]:                                          # no new buying while the account is far below its high
        for k in rows:
            if out[k]["target"] > cur[k]:
                out[k]["target"] = cur[k]
                out[k]["why"].append("circuit breaker: no buying")
    spend = sum(max(0.0, out[k]["target"] - cur[k]) for k in rows)      # no borrowing: the increases cannot exceed the cash, the sells included
    free = max(0.0, (state["cash"] + state["bank"]) / total) + sum(max(0.0, cur[k] - out[k]["target"]) for k in rows)
    if spend > free + 1e-12 and spend > 0:
        f = free / spend
        for k in rows:
            inc = max(0.0, out[k]["target"] - cur[k])
            if inc:
                out[k]["target"] = cur[k] + inc * f
                out[k]["why"].append("cut to the cash available")
    return out


def check(con, state: dict, decision: dict, skip=(), used: float = 0.0) -> dict:
    """The policy's targets -> the orders that may be placed, and what was clipped or skipped, each with its reason. `skip`: isins the exit manager already ordered this close (S81)
    (the rebalance must not trade the same names twice). `used`: rupees of discretionary HARVESTING the exit manager already trades this close; the turnover caps are net of it (it is never cut by them, the rebalance is; stops, targets, thesis breaks and rail trims are risk exits: exempt and not counted)."""
    cfg = state["cfg"]["rails"]
    band = float(state["cfg"]["baseline"]["band_pts"]) / 100.0
    total, day = float(state["value"]), state["day"]
    rows = {r["isin"]: r for r in state["rows"] if r["buyable"]}
    from pflab.core import premium                  # S81 A53 phase A: no new buying of an India-listed international ETF far above its NAV (core/premium.py; [premium] in core.toml)
    weights, prem_why = premium.rail_reasons(premium.attach(con, state), decision["weights"])
    clipped = clip_weights(state, weights)
    for k, why in prem_why.items():
        if k in clipped:
            clipped[k]["was"] = float(decision["weights"][k])
            clipped[k]["why"].append(why)
    orders, skipped = [], []
    gauge_on = bool(state["gauge"]["fired"])
    for k, c in clipped.items():
        r = rows[k]
        if k in skip:
            skipped.append({"isin": k, "symbol": r["symbol"], "why": "the exit manager already ordered this name at this close"})
            continue
        cur = r["value"] / total
        gap = c["target"] - cur
        if abs(gap) < band:
            skipped.append({"isin": k, "symbol": r["symbol"], "why": f"within the band ({gap * 100:+.1f} points)"})
            continue
        price = float(r["price"])
        if gap > 0:
            val = gap * total
            orders.append({"isin": k, "symbol": r["symbol"], "side": "buy", "qty": None, "amount": round(val, 2), "value": val, "risk_cut": False, "charges": 0.0, "tax": 0.0,
                           "note": "; ".join(c["why"]), "from_w": cur, "to_w": c["target"]})
        else:
            qty = float(r["qty"]) if c["target"] <= 1e-9 else float(math.floor(-gap * total / price))
            qty = min(qty, float(r["qty"]))
            if qty < 1:
                skipped.append({"isin": k, "symbol": r["symbol"], "why": "less than one share to sell"})
                continue
            cost = sell_costs(con, r, qty, price, day)
            orders.append({"isin": k, "symbol": r["symbol"], "side": "sell", "qty": qty, "amount": None, "value": qty * price, "risk_cut": gauge_on and r["klass"] == "equity",
                           "charges": cost["charges"], "tax": cost["tax"], "note": "; ".join(c["why"]), "from_w": cur, "to_w": c["target"]})
    keep = []
    for o in orders:
        if o["value"] < float(cfg["min_trade_rupees"]):
            skipped.append({"isin": o["isin"], "symbol": o["symbol"], "why": f"Rs {o['value']:,.0f} is below the minimum trade"})
            continue
        if o["side"] == "sell" and not o["risk_cut"] and (o["charges"] + o["tax"]) > float(cfg["max_cost_share"]) * o["value"]:
            skipped.append({"isin": o["isin"], "symbol": o["symbol"], "why": f"charges and tax Rs {o['charges'] + o['tax']:,.0f} are {(o['charges'] + o['tax']) / o['value']:.1%} of the trade"})
            continue
        keep.append(o)
    cap = max(0.0, min(float(cfg["turnover_day"]) * total, max(0.0, float(cfg["turnover_month"]) * total - month_traded(con, day))) - float(used))
    traded = sum(o["value"] for o in keep)
    if keep and traded > cap + 1e-9:                                     # the turnover caps: every order is scaled down together
        f = cap / traded if traded > 0 else 0.0
        scaled = []
        for o in keep:
            price = float(rows[o["isin"]]["price"])
            if o["side"] == "sell":
                q = float(math.floor(o["qty"] * f))
                o = dict(o, qty=q, value=q * price) if q >= 1 else None
            else:
                o = dict(o, amount=round(o["amount"] * f, 2), value=o["value"] * f)
            if o is None or o["value"] < float(cfg["min_trade_rupees"]):
                skipped.append({"isin": (o or {}).get("isin"), "why": "dropped by the turnover cap"})
                continue
            o["note"] = (o["note"] + "; " if o["note"] else "") + f"scaled to {f:.0%} by the turnover cap (Rs {cap:,.0f})"
            scaled.append(o)
        keep = scaled
    keep.sort(key=lambda o: (o["side"] != "sell", -o["value"]))        # sells first: their proceeds fund the buys
    return {"orders": keep, "skipped": skipped, "clipped": {k: v for k, v in clipped.items() if v["why"]}, "turnover_cap_rupees": round(cap, 2)}
