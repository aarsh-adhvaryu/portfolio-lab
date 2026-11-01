"""The paper portfolio's own record (S76): lots, cash, orders, fills and days, kept apart from his ledger (tables `paper_*`, migration 56).

Start   on the first run, a copy of his record on the latest close: every open lot of his rupee accounts (shares, ETFs, funds, SGBs, gold) with its own purchase
        date and cost, so tax on paper is his tax; and a FAKE account's cash, Rs 5,00,000 (his choice 2026-11-01: his real balances are not used). FDs are left out (his decision 2026-11-01) and so is the US sleeve (frozen;
        added later). A holding whose purchase cost is not on record starts at its value that day (labelled: no gain is claimed on it).
Money   none: the account is separate; nothing of his real deposits or withdrawals reaches it.
Fills   an order fills at the close of its session: placed on a trading day before 15:30, that day's close; else the next session's. Buying is for listed shares and
        ETFs with a stored close; a fund, an SGB or physical gold can be sold (at its NAV or rate) but not bought. Charges from `pm/costs.py`.
Tax     estimated at each sale and taken from the cash at once (labelled): first in, first out; equity held over a year 12.5% above the year's Rs 1.25 lakh, under a year
        20%; listed gold and other listed non-equity over a year 12.5%, else, like debt funds, at a 30% slab; losses set off as the law allows (a short-term loss against
        any gain, a long-term loss only against long-term). Cess and surcharge are not added. Each sale's tax is what it adds to the year's total.
Nothing here trades: the paper portfolio never reaches a broker.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional, Tuple

LT_EXEMPT, ST_RATE, LT_RATE, SLAB = 125_000.0, 0.20, 0.125, 0.30
START_CASH = 500_000.0                 # the fake account's cash at the start (his answer 2026-11-01); `[paper] start_cash_rupees` changes it before the start
CLOSE_AT = time(15, 30)
BUYABLE = ("equity", "etf")


def _id(con, table: str, col: str) -> int:
    from pflab.pm.store import next_id
    return next_id(con, table, col)


def started(con) -> Optional[date]:
    r = con.execute("SELECT min(day) FROM paper_cash WHERE kind='seed'").fetchone()
    return r[0] if r and r[0] else None


# --- prices -------------------------------------------------------------------------------------------------------------------------

def close_on(con, isin: str, day: date) -> Optional[Tuple[date, float]]:
    """The latest stored close (or NAV, or gold rate) on or before `day`, with its date. Never a live quote: the paper book is marked at closes."""
    r = con.execute("SELECT date, close FROM prices WHERE isin=? AND date<=? AND close > 0 ORDER BY date DESC LIMIT 1", [isin, day]).fetchone()
    if r:
        return r[0], float(r[1])
    r = con.execute("SELECT date, nav FROM navs WHERE isin=? AND date<=? AND nav > 0 ORDER BY date DESC LIMIT 1", [isin, day]).fetchone()
    if r:
        return r[0], float(r[1])
    try:
        from pflab.calc import valuation as val
        info = val.store_price_fn(con)(isin, day)
        return (info.date, float(info.value)) if info else None
    except Exception:
        return None


def sessions_after(con, after: date, upto: date) -> List[date]:
    """Trading days with exchange closes in (after, upto]."""
    return [r[0] for r in con.execute("SELECT DISTINCT date FROM prices WHERE date > ? AND date <= ? AND source='nse_bhavcopy' ORDER BY 1", [after, upto]).fetchall()]


def inst(con, isin: str) -> dict:
    r = con.execute("SELECT symbol, name, asset_class, tax_class, sector, listed FROM instruments WHERE isin=?", [isin]).fetchone()
    if not r:
        return {"symbol": None, "name": None, "asset_class": None, "tax_class": None, "sector": None, "listed": None}
    return dict(zip(("symbol", "name", "asset_class", "tax_class", "sector", "listed"), r))


def isin_of(con, symbol: str) -> Optional[str]:
    r = con.execute("SELECT isin FROM instruments WHERE upper(symbol)=? ORDER BY listed DESC NULLS LAST LIMIT 1", [symbol.strip().upper()]).fetchone()
    return r[0] if r else None


# --- the start ----------------------------------------------------------------------------------------------------------------------

def _rupee_accounts(con) -> Dict[str, str]:
    try:
        return {a: (c or "INR") for a, c in con.execute("SELECT account_id, currency FROM accounts").fetchall()}
    except Exception:
        return {a: "INR" for (a,) in con.execute("SELECT account_id FROM accounts").fetchall()}


def seed(con, asof: date, now: datetime) -> dict:
    """Copy his record on `asof` into the paper book (once). Returns what was copied and what was left out."""
    if started(con):
        return {"started": str(started(con)), "new": False}
    from pflab.ledger import events as ev
    from pflab.ledger.book import Ledger
    led = Ledger.replay(ev.load(con), upto=asof)
    cur = _rupee_accounts(con)
    unknown = {r[0] for r in con.execute("SELECT DISTINCT isin FROM events WHERE kind='buy' AND ref LIKE '%:cost_unknown'").fetchall()}
    left, n = [], 0
    for lot in led.lots.all_lots():
        if cur.get(lot.account_id, "INR") != "INR" or lot.isin.startswith(("ZZ", "US:")):
            left.append({"isin": lot.isin, "why": "the US sleeve is added later"})
            continue
        px = close_on(con, lot.isin, asof)
        if px is None:
            left.append({"isin": lot.isin, "why": "no price on record"})
            continue
        cost, origin = float(lot.cost_per_unit), "seed"
        if lot.isin in unknown:
            cost, origin = px[1], "seed_cost_unknown"
        con.execute("INSERT INTO paper_lots VALUES (?,?,?,?,?,?,?,?)", [_id(con, "paper_lots", "lot_id"), lot.isin, inst(con, lot.isin)["symbol"], lot.acq_date,
                                                                        float(lot.qty), cost, lot.tax_class or inst(con, lot.isin)["tax_class"], origin])
        n += 1
    try:
        from pflab.agents import analyst as an
        cash = float((an.config().get("paper") or {}).get("start_cash_rupees", START_CASH))
    except Exception:
        cash = START_CASH
    # a fake account with its own money (his choice 2026-11-01); none of his real balances or deposits are used
    con.execute("INSERT INTO paper_cash VALUES (?,?,?,?,?,?)", [_id(con, "paper_cash", "entry_id"), asof, cash, "seed", "fake starting cash; his holdings copied, FDs left out", now])
    mark(con, asof)
    return {"started": str(asof), "new": True, "lots": n, "cash": round(cash, 2), "left_out": left}


# --- the state ----------------------------------------------------------------------------------------------------------------------

def cash(con, upto: Optional[date] = None) -> float:
    q = "SELECT coalesce(sum(amount), 0) FROM paper_cash" + (" WHERE day <= ?" if upto else "")
    return float(con.execute(q, [upto] if upto else []).fetchone()[0])


def positions(con) -> Dict[str, float]:
    return {i: float(q) for i, q in con.execute("SELECT isin, sum(qty) FROM paper_lots WHERE qty > 1e-9 GROUP BY isin").fetchall()}


def holdings(con, day: date) -> dict:
    """{'rows': [...], 'value', 'cash', 'invested'} at the closes on or before `day`."""
    rows, invested = [], 0.0
    for isin, qty in sorted(positions(con).items()):
        px = close_on(con, isin, day)
        meta = inst(con, isin)
        cost = float(con.execute("SELECT sum(qty * cost_per_unit) FROM paper_lots WHERE isin=? AND qty > 1e-9", [isin]).fetchone()[0] or 0.0)
        val = qty * px[1] if px else None
        invested += val or 0.0
        rows.append({"isin": isin, "symbol": meta["symbol"] or isin, "name": meta["name"], "sector": meta["sector"], "asset_class": meta["asset_class"],
                     "qty": qty, "price": px[1] if px else None, "price_date": str(px[0]) if px else None, "value": val, "cost": cost})
    c = cash(con, day)
    total = invested + c
    for r in rows:
        r["weight"] = (r["value"] or 0.0) / total if total > 0 else 0.0
    rows.sort(key=lambda r: -(r["value"] or 0.0))
    return {"rows": rows, "value": total, "cash": c, "invested": invested}


def mark(con, day: date, flows: float = 0.0) -> dict:
    h = holdings(con, day)
    con.execute("INSERT OR REPLACE INTO paper_days VALUES (?,?,?,?,?,?)",
                [day, h["value"], h["cash"], h["invested"], flows, json.dumps({r["isin"]: round(r["qty"], 6) for r in h["rows"]}, sort_keys=True)])
    return h


# --- tax ----------------------------------------------------------------------------------------------------------------------------

def _fy(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1


def _bucket(tax_class: Optional[str], asset_class: Optional[str], acq: date, day: date) -> str:
    held = (day - acq).days
    tc, ac = (tax_class or "").upper(), (asset_class or "").lower()
    if tc == "EQUITY" or ac in ("equity", "equity_fund"):
        return "lt_eq" if held > 365 else "st_eq"
    if tc in ("LISTED_NONEQUITY", "SGB") or ac in ("etf", "sgb"):
        return "lt_other" if held > 365 else "slab"
    if ac == "gold_physical":
        return "lt_other" if held > 730 else "slab"
    return "slab"


def tax_of(g: Dict[str, float]) -> float:
    """The year's tax on its gains by bucket (set-off: a short-term equity loss reduces long-term gains; a long-term loss only long-term ones)."""
    st, lt_eq, lt_o, slab = g.get("st_eq", 0.0), g.get("lt_eq", 0.0), g.get("lt_other", 0.0), g.get("slab", 0.0)
    if st < 0:
        lt_eq, st = lt_eq + st, 0.0
    if lt_eq < 0:
        lt_o, lt_eq = lt_o + lt_eq, 0.0
    if lt_o < 0:
        lt_o = 0.0
    return ST_RATE * st + LT_RATE * max(0.0, lt_eq - LT_EXEMPT) + LT_RATE * lt_o + SLAB * max(0.0, slab)


def year_gains(con, fy: int) -> Dict[str, float]:
    g: Dict[str, float] = {}
    for (dj,) in con.execute("SELECT detail_json FROM paper_trades WHERE side='sell' AND day >= ? AND day < ?", [date(fy, 4, 1), date(fy + 1, 4, 1)]).fetchall():
        for k, v in (json.loads(dj or "{}").get("gains") or {}).items():
            g[k] = g.get(k, 0.0) + float(v)
    return g


# --- orders and fills ---------------------------------------------------------------------------------------------------------------

def fill_day(con, placed_at: datetime, isin: str, upto: date) -> Optional[date]:
    """The session whose close fills an order placed at `placed_at`, if it has happened by `upto`."""
    d0 = placed_at.date()
    first = d0 if placed_at.time() < CLOSE_AT else d0 + timedelta(days=1)
    r = con.execute("SELECT min(date) FROM prices WHERE isin=? AND date >= ? AND date <= ? AND close > 0", [isin, first, upto]).fetchone()
    if r and r[0]:
        return r[0]
    r = con.execute("SELECT min(date) FROM navs WHERE isin=? AND date >= ? AND date <= ?", [isin, first, upto]).fetchone()
    return r[0] if r and r[0] else None


def _charges(asset_class: Optional[str], side: str, notional: float) -> float:
    from pflab.pm import costs
    try:
        return float(costs.estimate(costs.segment_of(asset_class or "equity"), side, notional)[0])
    except Exception:
        return round(notional * 0.0012, 2)                       # (a stated fallback: about a delivery side's STT, exchange and GST)


def place(con, now: datetime, decision_id: Optional[int], isin: str, side: str, *, qty: Optional[float] = None, amount: Optional[float] = None, note: str = "") -> int:
    oid = _id(con, "paper_orders", "order_id")
    con.execute("INSERT INTO paper_orders VALUES (?,?,?,?,?,?,?,?,?,?,?)", [oid, now, decision_id, isin, inst(con, isin)["symbol"], side, qty, amount, "open", None, note[:300]])
    return oid


def fill(con, upto: date, now: datetime) -> List[dict]:
    """Fill every open order whose session has closed by `upto`. Buys are cut to the cash and the rails at the fill price; sells never exceed the holding."""
    from pflab.paper import rails
    done = []
    for oid, placed, did, isin, side, qty, amount in con.execute(
            "SELECT order_id, placed_at, decision_id, isin, side, qty, amount FROM paper_orders WHERE status='open' ORDER BY placed_at, order_id").fetchall():
        d = fill_day(con, placed, isin, upto)
        if d is None:
            if (upto - placed.date()).days > 10:
                con.execute("UPDATE paper_orders SET status='lapsed', note=coalesce(note,'') || ' | no close in 10 days' WHERE order_id=?", [oid])
            continue
        px = close_on(con, isin, d)[1]
        meta = inst(con, isin)
        if side == "buy":
            want = qty * px if qty else float(amount or 0.0)
            room = rails.buy_room(con, isin, d)
            avail = cash(con, d)
            spend = max(0.0, min(want, room, avail / 1.002))
            q = math.floor(spend / px) if meta["asset_class"] in BUYABLE else 0
            if q <= 0:
                con.execute("UPDATE paper_orders SET status='cancelled', fill_day=?, note=coalesce(note,'') || ? WHERE order_id=?",
                            [d, f" | nothing bought: room Rs {room:,.0f} under the rails, cash Rs {avail:,.0f}", oid])
                continue
            fee = _charges(meta["asset_class"], "buy", q * px)
            con.execute("INSERT INTO paper_lots VALUES (?,?,?,?,?,?,?,?)", [_id(con, "paper_lots", "lot_id"), isin, meta["symbol"], d, float(q), (q * px + fee) / q,
                                                                            meta["tax_class"], f"order:{oid}"])
            _cash(con, d, -(q * px + fee), "buy", f"order:{oid}", now)
            tid = _trade(con, d, oid, did, isin, meta["symbol"], "buy", q, px, fee, None, None, {"cut": round(want - q * px, 2) if want - q * px > px else 0})
        else:
            held = positions(con).get(isin, 0.0)
            q = min(held, float(qty) if qty else (math.floor(float(amount) / px) if amount else held))
            if q <= 1e-9:
                con.execute("UPDATE paper_orders SET status='cancelled', fill_day=?, note=coalesce(note,'') || ' | nothing held' WHERE order_id=?", [d, oid])
                continue
            fee = _charges(meta["asset_class"], "sell", q * px)
            gains, left = {}, q
            for lid, acq, lq, cpu, tc in con.execute("SELECT lot_id, acq_date, qty, cost_per_unit, tax_class FROM paper_lots WHERE isin=? AND qty > 1e-9 ORDER BY acq_date, lot_id",
                                                     [isin]).fetchall():
                take = min(lq, left)
                b = _bucket(tc, meta["asset_class"], acq, d)
                gains[b] = gains.get(b, 0.0) + take * (px - cpu) - fee * take / q
                con.execute("UPDATE paper_lots SET qty = qty - ? WHERE lot_id=?", [take, lid])
                left -= take
                if left <= 1e-9:
                    break
            fy = _fy(d)
            before = year_gains(con, fy)
            after = dict(before)
            for k, v in gains.items():
                after[k] = after.get(k, 0.0) + v
            tax = round(tax_of(after) - tax_of(before), 2)
            _cash(con, d, q * px - fee, "sell", f"order:{oid}", now)
            if tax:
                _cash(con, d, -tax, "tax", f"order:{oid}", now)
            tid = _trade(con, d, oid, did, isin, meta["symbol"], "sell", q, px, fee, round(sum(gains.values()), 2), tax,
                         {"gains": {k: round(v, 2) for k, v in gains.items()}, "tax_label": "estimate: FIFO lots, cess and surcharge not added"})
        con.execute("UPDATE paper_orders SET status='filled', fill_day=? WHERE order_id=?", [d, oid])
        done.append({"order_id": oid, "trade_id": tid, "day": str(d)})
    return done


def _cash(con, day: date, amount: float, kind: str, ref: str, now: datetime) -> None:
    con.execute("INSERT INTO paper_cash VALUES (?,?,?,?,?,?)", [_id(con, "paper_cash", "entry_id"), day, round(amount, 2), kind, ref, now])


def _trade(con, day, oid, did, isin, sym, side, qty, px, fee, realised, tax, detail) -> int:
    tid = _id(con, "paper_trades", "trade_id")
    con.execute("INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [tid, day, oid, did, isin, sym, side, float(qty), float(px), round(fee, 2), realised, tax,
                                                                               json.dumps(detail, sort_keys=True)])
    return tid


# --- the nightly bookkeeping --------------------------------------------------------------------------------------------------------

def catch_up(con, upto: date, now: datetime) -> dict:
    """Every session since the last marked day: the orders that filled and the day's value. The account is separate: none of his real money moves into it."""
    last = con.execute("SELECT max(day) FROM paper_days").fetchone()[0]
    if last is None:
        return {"skipped": "not started"}
    days, filled = [], []
    for d in sessions_after(con, last, upto):
        filled += fill(con, d, now)
        mark(con, d, 0.0)
        days.append(str(d))
    return {"days": days, "filled": filled}


def returns(con) -> Optional[dict]:
    """Time-weighted return since the start (money in and out taken out), the worst fall, and the days counted."""
    rows = con.execute("SELECT day, value, flows FROM paper_days ORDER BY day").fetchall()
    if len(rows) < 2:
        return None
    g, peak, worst, level = 1.0, 1.0, 0.0, 1.0
    for (d0, v0, _), (d1, v1, f1) in zip(rows, rows[1:]):
        r = (v1 - f1) / v0 - 1 if v0 > 0 else 0.0
        g *= 1 + r
        level = g
        peak = max(peak, level)
        worst = min(worst, level / peak - 1)
    return {"since": str(rows[0][0]), "to": str(rows[-1][0]), "sessions": len(rows) - 1, "twr": g - 1, "worst_fall": worst}
