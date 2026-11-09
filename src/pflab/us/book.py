"""The US sub-book's own record (tables `us_*_s81`, migrations 131-135): a paper account in DOLLARS. Nothing here touches `paper_*`, `us_trades` (his real record) or a rupee lot.

Start    the account opens once with `start_share` of the system's book (rupees) converted at the start FX rate (source stated) less the funding markup (an estimate).
Orders   placed at a US close for the NEXT session; they fill at that session's open plus (buy) or minus (sell) the slippage, never better than the open; charges from `us/costs.py`.
         A buy never spends more than the cash (no borrowing); a sale never exceeds the shares held (no shorting); shares may be fractional (the GIFT City route allows it).
Lots     first in, first out, each with its dollar cost per share (charges in) and the tax FX rate of its purchase.
Tax      a sale's Indian tax (`us/tax.py`, rupees, an estimate) and a dividend's residual tax after the credit are taken from the cash at once, in dollars at the day's rate.
Dividends the bar's `dividend` per share on the ex-date, on the shares held at the previous close; the US withholds 25% (30% without a W-8BEN).
Splits   detected when the data re-states the last marked close by a split ratio (Yahoo adjusts history backwards); the lots are scaled and an event row says so (an estimate).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from pflab.pm.store import next_id
from pflab.us import costs, fx as usfx, instruments as uins, tax as ustax

SPLIT_RATIOS = (1.5, 2.0, 3.0, 4.0, 5.0, 8.0, 10.0, 15.0, 20.0)
EPS = 1e-9


def _id(con, table: str, col: str) -> int:
    return next_id(con, table, col)


# --- the account and the cash ---------------------------------------------------------------------------------------------------------------------------------------

def account(con) -> Optional[dict]:
    r = con.execute("SELECT account_id, opened_on, start_inr, start_fx, fx_source, start_usd, share_of_book, note FROM us_account_s81 ORDER BY account_id LIMIT 1").fetchone()
    if not r:
        return None
    return dict(zip(("account_id", "opened_on", "start_inr", "start_fx", "fx_source", "start_usd", "share_of_book", "note"), r))


def add_cash(con, now: datetime, day: date, usd: float, kind: str, ref: str = "") -> int:
    eid = _id(con, "us_cash_s81", "entry_id")
    con.execute("INSERT INTO us_cash_s81 VALUES (?,?,?,?,?,?)", [eid, day, float(usd), kind, ref, now])
    return eid


def cash(con, upto: Optional[date] = None) -> float:
    if upto is None:
        r = con.execute("SELECT coalesce(sum(usd), 0) FROM us_cash_s81").fetchone()
    else:
        r = con.execute("SELECT coalesce(sum(usd), 0) FROM us_cash_s81 WHERE day <= ?", [upto]).fetchone()
    return float(r[0])


def open_account(con, now: datetime, day: date, book_value_inr: float, fx: dict, share: float) -> dict:
    """Open the account (once). `fx` is `usfx.rate_for(...)`: the start rate and its source are stored with the account."""
    if account(con):
        raise ValueError("the US sub-book is already open")
    if book_value_inr <= 0 or not 0 < share <= 1:
        raise ValueError("a positive book value and a share between 0 and 1 are needed")
    start_inr = book_value_inr * share
    markup = costs.fx_markup_funding()
    start_usd = start_inr / (fx["rate"] * (1.0 + markup))
    aid = 1
    note = (f"start {start_inr:,.0f} rupees = {share:.1%} of the system's book of {book_value_inr:,.0f}; converted at {fx['rate']:.4f} ({fx['label']}, {fx['rate_day']}); "
            f"funding markup {markup:.2%} ({costs.label()})")
    con.execute("INSERT INTO us_account_s81 VALUES (?,?,?,?,?,?,?,?,?)", [aid, day, start_inr, fx["rate"], fx["source"], start_usd, share, note, now])
    add_cash(con, now, day, start_usd, "seed", "start")
    return account(con)


# --- lots and positions ---------------------------------------------------------------------------------------------------------------------------------------------

def open_lots(con, day: Optional[date] = None) -> List[dict]:
    q = "SELECT lot_id, isin, symbol, acq_date, qty, cost_usd_per_share, fx_tax_acq, fx_tax_acq_source FROM us_lots_s81 WHERE qty > ?"
    args: list = [EPS]
    if day is not None:
        q += " AND acq_date <= ?"
        args.append(day)
    q += " ORDER BY acq_date, lot_id"
    return [dict(zip(("lot_id", "isin", "symbol", "acq_date", "qty", "cost_usd_per_share", "fx_tax_acq", "fx_tax_acq_source"), r)) for r in con.execute(q, args).fetchall()]


def positions(con, day: Optional[date] = None, before: bool = False) -> Dict[str, float]:
    """Shares held by canonical key. `before=True`: only lots bought BEFORE `day` (the holders of record on an ex-date)."""
    out: Dict[str, float] = {}
    for l in open_lots(con):
        if day is not None and (l["acq_date"] >= day if before else l["acq_date"] > day):
            continue
        k = uins.canonical(con, l["isin"], day)
        out[k] = out.get(k, 0.0) + l["qty"]
    return out


def _lots_of(con, canon: str, day: date) -> List[dict]:
    return [l for l in open_lots(con) if uins.canonical(con, l["isin"], day) == canon]


# --- fills ----------------------------------------------------------------------------------------------------------------------------------------------------------

def _ytd(con, fy: int) -> Dict[str, float]:
    st = lt = 0.0
    for (dj,) in con.execute("SELECT detail_json FROM us_trades_s81 WHERE side='sell' AND day >= ? AND day <= ?", [date(fy, 4, 1), date(fy + 1, 3, 31)]).fetchall():
        d = json.loads(dj or "{}")
        st += float(d.get("st_inr", 0.0))
        lt += float(d.get("lt_inr", 0.0))
    return {"st": st, "lt": lt}


def plan_sale(con, canon: str, qty: float, price: float, charges_usd: float, day: date, root=None, commit: bool = False) -> dict:
    """FIFO lots for a sale of `qty` at `price` (charges spread over the shares): the gain in rupees, its class and the Indian tax it adds this financial year. `commit` removes the lots."""
    parts, left, used = [], qty, []
    fx_sale = usfx.tax_rate(con, day, root)
    for l in _lots_of(con, canon, day):
        if left <= EPS:
            break
        take = min(l["qty"], left)
        proceeds = take * price - charges_usd * take / qty
        if fx_sale is None or l["fx_tax_acq"] is None:
            parts.append({"qty": take, "acquired": l["acq_date"], "class": ustax.holding_class(l["acq_date"], day), "cost_inr": None, "proceeds_inr": None, "gain_inr": 0.0, "no_rate": True})
        else:
            parts.append(ustax.lot_gain(take, l["cost_usd_per_share"], l["fx_tax_acq"], proceeds, fx_sale["rate"], l["acq_date"], day))
        used.append((l["lot_id"], take))
        left -= take
    if left > 1e-6:
        raise ValueError(f"selling {qty:g} of {canon} but only {qty - left:g} are held: no shorting")
    ytd = _ytd(con, ustax.fy_of(day))
    t = ustax.sale(parts, ytd["st"], ytd["lt"])
    t["no_rate"] = any(p.get("no_rate") for p in parts)
    if t["no_rate"]:
        t["label"] += "; NO TAX FX RATE for a date it needs: the tax of this sale is not estimated"
    t["parts"] = [{k: (str(v) if isinstance(v, date) else v) for k, v in p.items()} for p in parts]
    t["fx_sale"] = fx_sale
    if commit:
        for lot_id, take in used:
            con.execute("UPDATE us_lots_s81 SET qty = qty - ? WHERE lot_id=?", [take, lot_id])
    return t


def place(con, now: datetime, day: date, isin: str, symbol: str, side: str, qty: Optional[float] = None, amount_usd: Optional[float] = None, reason: str = "") -> int:
    if side not in ("buy", "sell"):
        raise ValueError("side is buy or sell")
    if side == "buy" and not amount_usd:
        raise ValueError("a buy order needs an amount in dollars")
    if side == "sell" and not qty:
        raise ValueError("a sell order needs a quantity")
    oid = _id(con, "us_orders_s81", "order_id")
    con.execute("INSERT INTO us_orders_s81 VALUES (?,?,?,?,?,?,?,?,?,?,?)", [oid, day, now, isin, symbol, side, qty, amount_usd, "open", None, reason[:600]])
    return oid


def open_orders(con) -> List[dict]:
    cols = ("order_id", "placed_day", "isin", "symbol", "side", "qty", "amount_usd", "reason")
    return [dict(zip(cols, r)) for r in con.execute("SELECT order_id, placed_day, isin, symbol, side, qty, amount_usd, reason FROM us_orders_s81 WHERE status='open' ORDER BY order_id").fetchall()]


def fill_orders(con, now: datetime, day: date, bars: Dict[str, "object"], slippage_bps: float, root=None, max_wait_sessions: int = 5) -> List[dict]:
    """Fill every open order placed on an EARLIER session at `day`'s open plus slippage. An order whose name has no bar for `day` waits; after `max_wait_sessions` it is cancelled."""
    from pflab.us import clock, data
    fills = []
    slip = float(slippage_bps) / 10000.0
    for o in open_orders(con):
        if o["placed_day"] >= day:
            continue
        sym = o["symbol"]
        bar = data.bar_on(bars.get(sym), day)
        if bar is None:
            waited = len([d for d in _sessions(o["placed_day"], day)])
            if waited > max_wait_sessions:
                con.execute("UPDATE us_orders_s81 SET status='cancelled', fill_day=?, reason=reason || ' [cancelled: no bar for this name in the sessions since]' WHERE order_id=?", [day, o["order_id"]])
            continue
        if o["side"] == "buy":
            px = bar["open"] * (1.0 + slip)
            budget = min(float(o["amount_usd"]), cash(con))
            q = budget / px
            for _ in range(30):                                          # value + charges = the budget (the charges are almost proportional, so this settles at once)
                ch = costs.charges("buy", q, px, day)["total"]
                nq = max(0.0, (budget - ch) / px)
                if abs(nq - q) < 1e-12:
                    break
                q = nq
            while q > 0 and q * px + costs.charges("buy", q, px, day)["total"] > budget + 1e-9:   # never over the budget
                q *= 1 - 1e-9
            if q * px < 1.0:
                con.execute("UPDATE us_orders_s81 SET status='skipped', fill_day=?, reason=reason || ' [skipped: not enough cash]' WHERE order_id=?", [day, o["order_id"]])
                continue
            fills.append(_buy(con, now, day, o, q, px, root))
        else:
            held = positions(con).get(uins.canonical(con, o["isin"], day), 0.0)
            q = min(float(o["qty"]), held)
            if q <= 1e-6:
                con.execute("UPDATE us_orders_s81 SET status='skipped', fill_day=?, reason=reason || ' [skipped: nothing held]' WHERE order_id=?", [day, o["order_id"]])
                continue
            fills.append(_sell(con, now, day, o, q, bar["open"] * (1.0 - slip), root))
    return fills


def _sessions(a: date, b: date) -> List[date]:
    from pflab.us import clock
    return clock.market().sessions_between(a + timedelta(days=1), b)


def _buy(con, now, day, o, q, px, root) -> dict:
    ch = costs.charges("buy", q, px, day)
    fxt = usfx.tax_rate(con, day, root)
    fxv = usfx.rate_for(con, day, root)
    tid = _id(con, "us_trades_s81", "trade_id")
    detail = {"charges": ch, "tax_fx": None if fxt is None else {k: str(v) for k, v in fxt.items()}, "label": costs.label()}
    con.execute("INSERT INTO us_trades_s81 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [tid, day, o["order_id"], o["isin"], o["symbol"], "buy", q, px, ch["total"],
                None if fxv is None else fxv["rate"], None if fxv is None else fxv["source"], None, None, json.dumps(detail, default=str)])
    lid = _id(con, "us_lots_s81", "lot_id")
    con.execute("INSERT INTO us_lots_s81 VALUES (?,?,?,?,?,?,?,?,?)", [lid, o["isin"], o["symbol"], day, q, px + ch["total"] / q, None if fxt is None else fxt["rate"],
                None if fxt is None else fxt["source"], "fill"])
    add_cash(con, now, day, -q * px, "buy", f"order {o['order_id']}")
    add_cash(con, now, day, -ch["total"], "fee", f"order {o['order_id']}")
    con.execute("UPDATE us_orders_s81 SET status='filled', fill_day=? WHERE order_id=?", [day, o["order_id"]])
    return {"order_id": o["order_id"], "trade_id": tid, "symbol": o["symbol"], "side": "buy", "qty": round(q, 6), "price": round(px, 4), "charges_usd": ch["total"]}


def _sell(con, now, day, o, q, px, root) -> dict:
    ch = costs.charges("sell", q, px, day)
    canon = uins.canonical(con, o["isin"], day)
    plan = plan_sale(con, canon, q, px, ch["total"], day, root, commit=True)
    fxv = usfx.rate_for(con, day, root)
    tid = _id(con, "us_trades_s81", "trade_id")
    detail = {"charges": ch, "st_inr": plan["st_inr"], "lt_inr": plan["lt_inr"], "parts": plan["parts"], "label": plan["label"]}
    con.execute("INSERT INTO us_trades_s81 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [tid, day, o["order_id"], o["isin"], o["symbol"], "sell", q, px, ch["total"],
                None if fxv is None else fxv["rate"], None if fxv is None else fxv["source"], plan["gain_inr"], plan["tax_inr"], json.dumps(detail, default=str)])
    add_cash(con, now, day, q * px, "sell", f"order {o['order_id']}")
    add_cash(con, now, day, -ch["total"], "fee", f"order {o['order_id']}")
    if plan["tax_inr"] > 0 and fxv:
        add_cash(con, now, day, -plan["tax_inr"] / fxv["rate"], "india_tax", f"order {o['order_id']}: {plan['tax_inr']:,.2f} rupees at {fxv['rate']:.4f}")
    con.execute("UPDATE us_orders_s81 SET status='filled', fill_day=? WHERE order_id=?", [day, o["order_id"]])
    return {"order_id": o["order_id"], "trade_id": tid, "symbol": o["symbol"], "side": "sell", "qty": round(q, 6), "price": round(px, 4), "charges_usd": ch["total"],
            "gain_inr": round(plan["gain_inr"], 2), "tax_inr": round(plan["tax_inr"], 2)}


# --- dividends and splits -------------------------------------------------------------------------------------------------------------------------------------------

def apply_dividends(con, now: datetime, day: date, bars: Dict[str, "object"], w8ben: bool = True, root=None) -> List[dict]:
    """The dividends whose ex-date is `day`, on the shares held at the previous close. The paid date is taken as the ex-date (the data has only that)."""
    from pflab.us import data
    out = []
    held = positions(con, day, before=True)
    for canon, q in held.items():
        sym = uins.symbol_of(con, canon)
        bar = data.bar_on(bars.get(sym or ""), day)
        if not bar or bar["dividend"] <= 0 or q <= EPS:
            continue
        if con.execute("SELECT 1 FROM us_dividends_s81 WHERE day=? AND isin=?", [day, canon]).fetchone():
            continue
        gross = q * bar["dividend"]
        fxt = usfx.tax_rate(con, day, root)
        fxv = usfx.rate_for(con, day, root)
        div_id = _id(con, "us_dividends_s81", "div_id")
        if fxt is None or fxv is None:
            t = {"withholding_rate": ustax.withholding_rate(w8ben), "withheld_usd": gross * ustax.withholding_rate(w8ben), "gross_inr": None, "india_tax_inr": None, "credit_inr": None,
                 "residual_tax_inr": 0.0, "label": "NO FX RATE: the Indian tax on this dividend is not estimated"}
        else:
            t = ustax.dividend(gross, fxt["rate"], w8ben)
        con.execute("INSERT INTO us_dividends_s81 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [div_id, day, canon, sym, q, bar["dividend"], gross, t["withheld_usd"], t["withholding_rate"],
                    None if fxt is None else fxt["rate"], None if fxt is None else fxt["source"], t["gross_inr"], t["india_tax_inr"], t["credit_inr"], t["residual_tax_inr"], t["label"]])
        add_cash(con, now, day, gross, "dividend", f"{sym} {bar['dividend']:.4f} a share")
        add_cash(con, now, day, -t["withheld_usd"], "withholding", f"US tax {t['withholding_rate']:.0%}")
        if t["residual_tax_inr"] and fxv:
            add_cash(con, now, day, -t["residual_tax_inr"] / fxv["rate"], "india_tax", f"dividend {sym}: {t['residual_tax_inr']:,.2f} rupees after the credit")
        out.append({"symbol": sym, "gross_usd": round(gross, 4), "withheld_usd": round(t["withheld_usd"], 4), "credit_inr": None if t["credit_inr"] is None else round(t["credit_inr"], 2),
                    "residual_tax_inr": round(t["residual_tax_inr"], 2)})
    return out


def _split_ratio(r: float) -> Optional[float]:
    """The split ratio a re-statement of history by `r` (old close / new close) is: a forward split k gives r = k, a reverse one 1/k. None when it is no round ratio."""
    for k in SPLIT_RATIOS:
        if abs(r / k - 1) < 0.03:
            return k
        if abs(r * k - 1) < 0.03:
            return 1.0 / k
    return None


def detect_splits(con, now: datetime, day: date, bars: Dict[str, "object"]) -> List[dict]:
    """Compare each held name's close on the last marked day (as stored then) with the same day's close in the data now: a round ratio is a split; the lots are rescaled."""
    from pflab.us import data
    last = con.execute("SELECT day, holdings_json FROM us_days_s81 WHERE day < ? ORDER BY day DESC LIMIT 1", [day]).fetchone()
    if not last:
        return []
    out = []
    stored = json.loads(last[1] or "{}")
    for canon, info in stored.items():
        sym, old = info.get("symbol"), info.get("close")
        bar = data.bar_on(bars.get(sym or ""), last[0])
        if not bar or not old or bar["close"] <= 0 or positions(con).get(canon, 0.0) <= EPS:
            continue
        r = old / bar["close"]
        if abs(r - 1) < 0.15:
            continue
        k = _split_ratio(r)
        eid = _id(con, "us_events_s81", "event_id")
        if k is None:
            con.execute("INSERT INTO us_events_s81 VALUES (?,?,?,?,?,?)", [eid, day, canon, "unexplained_revision", json.dumps({"symbol": sym, "was": old, "now": bar["close"], "on": str(last[0])}), now])
            out.append({"symbol": sym, "kind": "unexplained_revision", "ratio": round(r, 4)})
            continue
        for l in _lots_of(con, canon, last[0]):
            con.execute("UPDATE us_lots_s81 SET qty = qty * ?, cost_usd_per_share = cost_usd_per_share / ? WHERE lot_id=?", [k, k, l["lot_id"]])
        con.execute("INSERT INTO us_events_s81 VALUES (?,?,?,?,?,?)", [eid, day, canon, "split", json.dumps({"symbol": sym, "ratio": k, "was": old, "now": bar["close"], "on": str(last[0]),
                    "note": "inferred from the data re-stating history: an estimate"}), now])
        out.append({"symbol": sym, "kind": "split", "ratio": k})
    return out


# --- the mark -------------------------------------------------------------------------------------------------------------------------------------------------------

def mark(con, now: datetime, day: date, bars: Dict[str, "object"], fx: Optional[dict]) -> dict:
    """Value the book at `day`'s closes and store the day (holdings_json keeps each name's close for the next split check). A name with no bar that day is marked at its last close."""
    from pflab.us import data
    rows, total = {}, 0.0
    for canon, q in positions(con, day).items():
        if q <= EPS:
            continue
        sym = uins.symbol_of(con, canon) or canon
        b = data.last_on_or_before(bars.get(sym), day)
        px = b["close"] if b else None
        v = q * px if px else 0.0
        rows[canon] = {"symbol": sym, "qty": round(q, 6), "close": px, "close_date": str(b["date"]) if b else None, "value_usd": round(v, 2)}
        total += v
    c = cash(con, day)
    value = total + c
    con.execute("INSERT OR REPLACE INTO us_days_s81 VALUES (?,?,?,?,?,?,?)", [day, value, c, None if fx is None else fx["rate"], None if fx is None else fx["source"],
                None if fx is None else value * fx["rate"], json.dumps(rows)])
    return {"day": day, "value_usd": value, "cash_usd": c, "positions": rows}


def realised_fy(con, fy: int) -> dict:
    """The financial year's realised gains (rupees, estimates), the tax they add and the dividends' tax figures."""
    y = _ytd(con, fy)
    tax_gain = ustax.fy_tax(y["st"], y["lt"])
    d = con.execute("SELECT coalesce(sum(gross_usd),0), coalesce(sum(withheld_usd),0), coalesce(sum(credit_inr),0), coalesce(sum(residual_tax_inr),0) FROM us_dividends_s81 WHERE day >= ? AND day <= ?",
                    [date(fy, 4, 1), date(fy + 1, 3, 31)]).fetchone()
    return {"fy": f"{fy}-{str(fy + 1)[-2:]}", "short_term_gain_inr": round(y["st"], 2), "long_term_gain_inr": round(y["lt"], 2), "capital_gains_tax_inr": round(tax_gain, 2),
            "dividends_gross_usd": round(d[0], 4), "dividends_withheld_usd": round(d[1], 4), "dividend_credit_inr": round(d[2], 2), "dividend_residual_tax_inr": round(d[3], 2),
            "label": ustax.rows.label(list(dict.fromkeys(ustax.CG_ROWS + ustax.DIV_ROWS))) + "; excludes surcharge and cess"}
