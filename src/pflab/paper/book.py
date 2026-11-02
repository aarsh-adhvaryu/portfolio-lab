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


def _own() -> bool:
    """S77: the profile is the system's own account: positions and cash are the ledger's (`lots`, `cash_ledger`), fills are ledger events."""
    from pflab.ledger import system
    return system.active()


def started(con) -> Optional[date]:
    if _own():
        r = con.execute("SELECT min(day) FROM paper_days").fetchone()
    else:
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


_SECTORS: dict = {}


def _industry(isin: str) -> Optional[str]:
    """The industry label of the system's sector map (Nifty 500 names), when the instruments table has none: the 25% rail needs a label to count by. Cached."""
    if isin not in _SECTORS:
        try:
            from pflab.data import sector_map
            if "table" not in _SECTORS:
                _SECTORS["table"] = sector_map.load()
            lab = sector_map.sector_at(_SECTORS["table"], [isin], date.today(), allow_later=True)
            _SECTORS[isin] = (lab["industry"].iloc[0] if len(lab) else None) or None
        except Exception:
            _SECTORS[isin] = None
    return _SECTORS[isin]


def inst(con, isin: str) -> dict:
    r = con.execute("SELECT symbol, name, asset_class, tax_class, sector, listed FROM instruments WHERE isin=?", [isin]).fetchone()
    if not r:
        return {"symbol": None, "name": None, "asset_class": None, "tax_class": None, "sector": None, "listed": None}
    d = dict(zip(("symbol", "name", "asset_class", "tax_class", "sector", "listed"), r))
    if not d["sector"] and d["asset_class"] == "equity":
        d["sector"] = _industry(isin)
    return d


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
    if _own():                                              # in the system's own account the ledger IS the book: the first marked day is the start
        mark(con, asof)
        return {"started": str(asof), "new": True, "own_ledger": True}
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
    if _own():
        from pflab.ledger import system
        q = "SELECT coalesce(sum(amount), 0) FROM cash_ledger WHERE account_id = ?" + (" AND date <= ?" if upto else "")
        return float(con.execute(q, [system.SYSBROKER] + ([upto] if upto else [])).fetchone()[0])
    q = "SELECT coalesce(sum(amount), 0) FROM paper_cash" + (" WHERE day <= ?" if upto else "")
    return float(con.execute(q, [upto] if upto else []).fetchone()[0])


def _lots_sql(cols: str, where: str = "") -> str:
    """The lot table of the active backend: the ledger's `lots` of the system broker, or the paper book's own."""
    if _own():
        return f"SELECT {cols} FROM lots WHERE account_id = 'SYSBROKER' AND qty > 1e-9" + where
    return f"SELECT {cols} FROM paper_lots WHERE qty > 1e-9" + where


def positions(con) -> Dict[str, float]:
    return {i: float(q) for i, q in con.execute(_lots_sql("isin, sum(qty)", " GROUP BY isin")).fetchall()}


def holdings(con, day: date) -> dict:
    """{'rows': [...], 'value', 'cash', 'invested'} at the closes on or before `day`."""
    rows, invested = [], 0.0
    for isin, qty in sorted(positions(con).items()):
        px = close_on(con, isin, day)
        meta = inst(con, isin)
        cost = float(con.execute(_lots_sql("sum(qty * cost_per_unit)", " AND isin=?"), [isin]).fetchone()[0] or 0.0)
        val = qty * px[1] if px else None
        invested += val or 0.0
        rows.append({"isin": isin, "symbol": meta["symbol"] or isin, "name": meta["name"], "sector": meta["sector"], "asset_class": meta["asset_class"],
                     "qty": qty, "price": px[1] if px else None, "price_date": str(px[0]) if px else None, "value": val, "cost": cost})
    c = cash(con, day)
    bank = 0.0
    if _own():                                              # the account is the fake bank plus the fake broker
        from pflab.ledger import system
        bank = float(con.execute("SELECT coalesce(sum(amount), 0) FROM cash_ledger WHERE account_id = ? AND date <= ?", [system.SYSBANK, day]).fetchone()[0])
    total = invested + c + bank
    for r in rows:
        r["weight"] = (r["value"] or 0.0) / total if total > 0 else 0.0
    rows.sort(key=lambda r: -(r["value"] or 0.0))
    return {"rows": rows, "value": total, "cash": c, "bank": bank, "invested": invested}


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


SLIPPAGE = 0.0005                      # a live fill is 0.05% worse than the quote on each side (stated)


def live_prices(con, now: datetime, isins, max_age_min: int = 10) -> Dict[str, float]:
    """The latest Kite quote of each name when it is at most `max_age_min` minutes old, in market hours only (else {}: orders wait for the close)."""
    from pflab.pm import prices as pp
    if not pp.market_open(now) or not isins:
        return {}
    out = {}
    for isin in isins:
        r = con.execute("SELECT ltp FROM live_quotes WHERE isin=? AND ts >= ? AND ts <= ? ORDER BY ts DESC LIMIT 1",
                        [isin, now - timedelta(minutes=max_age_min), now]).fetchone()
        if r and r[0]:
            out[isin] = float(r[0])
    return out


def fill_live(con, now: datetime) -> List[dict]:
    """Orders placed in market hours today fill NOW at the live quote (+/- the slippage) instead of waiting for the close."""
    rows = con.execute("SELECT DISTINCT isin FROM paper_orders WHERE status='open' AND CAST(placed_at AS DATE) = ?", [now.date()]).fetchall()
    live = live_prices(con, now, [r[0] for r in rows])
    return fill(con, now.date(), now, live=live) if live else []


def fill(con, upto: date, now: datetime, live: Optional[Dict[str, float]] = None) -> List[dict]:
    """Fill every open order whose session has closed by `upto`, or (with `live`) fill today's orders now at the live quote. Buys are cut to the cash and the rails at the fill price; sells never exceed the holding."""
    from pflab.paper import rails
    done = []
    for oid, placed, did, isin, side, qty, amount in con.execute(
            "SELECT order_id, placed_at, decision_id, isin, side, qty, amount FROM paper_orders WHERE status='open' ORDER BY placed_at, order_id").fetchall():
        live_px = None
        if live is not None:
            if isin not in live or placed.date() != now.date():
                continue
            d, live_px = now.date(), live[isin] * (1 + SLIPPAGE if side == "buy" else 1 - SLIPPAGE)
        else:
            d = fill_day(con, placed, isin, upto)
        if d is None:
            if (upto - placed.date()).days > 10:
                con.execute("UPDATE paper_orders SET status='lapsed', note=coalesce(note,'') || ' | no close in 10 days' WHERE order_id=?", [oid])
            continue
        px = live_px if live_px is not None else close_on(con, isin, d)[1]
        meta = inst(con, isin)
        if side == "buy":
            want = qty * px if qty else float(amount or 0.0)
            room = rails.buy_room(con, isin, d)
            if _own():                                              # the fake bank funds the broker when a buy needs cash (and the system may top the bank up, inside its month cap)
                from pflab.paper import funds
                funds.ensure(con, min(want, room) * 1.002, d, now)
            avail = cash(con, d)
            spend = max(0.0, min(want, room, avail / 1.002))
            q = math.floor(spend / px) if meta["asset_class"] in BUYABLE else 0
            if q <= 0:
                con.execute("UPDATE paper_orders SET status='cancelled', fill_day=?, note=coalesce(note,'') || ? WHERE order_id=?",
                            [d, f" | nothing bought: room Rs {room:,.0f} under the rails, cash Rs {avail:,.0f}", oid])
                continue
            fee = _charges(meta["asset_class"], "buy", q * px)
            _apply_buy(con, d, oid, isin, meta, q, px, fee, now)
            tid = _trade(con, d, oid, did, isin, meta["symbol"], "buy", q, px, fee, None, None, {"cut": round(want - q * px, 2) if want - q * px > px else 0})
        else:
            held = positions(con).get(isin, 0.0)
            q = min(held, float(qty) if qty else (math.floor(float(amount) / px) if amount else held))
            if q <= 1e-9:
                con.execute("UPDATE paper_orders SET status='cancelled', fill_day=?, note=coalesce(note,'') || ' | nothing held' WHERE order_id=?", [d, oid])
                continue
            fee = _charges(meta["asset_class"], "sell", q * px)
            gains, left = {}, q
            for lid, acq, lq, cpu, tc in con.execute(_lots_sql("lot_id, acq_date, qty, cost_per_unit, tax_class", " AND isin=? ORDER BY acq_date, lot_id"), [isin]).fetchall():
                take = min(lq, left)
                b = _bucket(tc, meta["asset_class"], acq, d)
                gains[b] = gains.get(b, 0.0) + take * (px - cpu) - fee * take / q
                left -= take
                if left <= 1e-9:
                    break
            fy = _fy(d)
            before = year_gains(con, fy)
            after = dict(before)
            for k, v in gains.items():
                after[k] = after.get(k, 0.0) + v
            tax = round(tax_of(after) - tax_of(before), 2)
            _apply_sell(con, d, oid, isin, meta, q, px, fee, tax, now)
            tid = _trade(con, d, oid, did, isin, meta["symbol"], "sell", q, px, fee, round(sum(gains.values()), 2), tax,
                         {"gains": {k: round(v, 2) for k, v in gains.items()}, "tax_label": "estimate: FIFO lots, cess and surcharge not added"})
        con.execute("UPDATE paper_orders SET status='filled', fill_day=? WHERE order_id=?", [d, oid])
        done.append({"order_id": oid, "trade_id": tid, "day": str(d)})
    return done


def _apply_buy(con, d: date, oid: int, isin: str, meta: dict, q: int, px: float, fee: float, now: datetime) -> None:
    if _own():
        from pflab.ledger import events as ev, system
        system.append(con, [ev.Event(kind="buy", account_id=system.SYSBROKER, date=d, isin=isin, qty=float(q), price=float(px), fees={"charges": round(fee, 2)},
                                     ref=f"sys:order:{oid}", tax_class=meta["tax_class"])], now)
        return
    con.execute("INSERT INTO paper_lots VALUES (?,?,?,?,?,?,?,?)", [_id(con, "paper_lots", "lot_id"), isin, meta["symbol"], d, float(q), (q * px + fee) / q,
                                                                    meta["tax_class"], f"order:{oid}"])
    _cash(con, d, -(q * px + fee), "buy", f"order:{oid}", now)


def _apply_sell(con, d: date, oid: int, isin: str, meta: dict, q: float, px: float, fee: float, tax: float, now: datetime) -> None:
    if _own():
        from pflab.ledger import events as ev, system
        evs = [ev.Event(kind="sell", account_id=system.SYSBROKER, date=d, isin=isin, qty=float(q), price=float(px), fees={"charges": round(fee, 2)}, ref=f"sys:order:{oid}")]
        if tax:
            evs.append(ev.Event(kind="charge", account_id=system.SYSBROKER, date=d, amount=float(tax), ref=f"tax estimate for sys:order:{oid}"))
        system.append(con, evs, now)
        return
    left = q
    for lid, lq in con.execute("SELECT lot_id, qty FROM paper_lots WHERE isin=? AND qty > 1e-9 ORDER BY acq_date, lot_id", [isin]).fetchall():
        take = min(lq, left)
        con.execute("UPDATE paper_lots SET qty = qty - ? WHERE lot_id=?", [take, lid])
        left -= take
        if left <= 1e-9:
            break
    _cash(con, d, q * px - fee, "sell", f"order:{oid}", now)
    if tax:
        _cash(con, d, -tax, "tax", f"order:{oid}", now)


def _cash(con, day: date, amount: float, kind: str, ref: str, now: datetime) -> None:
    con.execute("INSERT INTO paper_cash VALUES (?,?,?,?,?,?)", [_id(con, "paper_cash", "entry_id"), day, round(amount, 2), kind, ref, now])


def _trade(con, day, oid, did, isin, sym, side, qty, px, fee, realised, tax, detail) -> int:
    tid = _id(con, "paper_trades", "trade_id")
    con.execute("INSERT INTO paper_trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [tid, day, oid, did, isin, sym, side, float(qty), float(px), round(fee, 2), realised, tax,
                                                                               json.dumps(detail, sort_keys=True)])
    return tid


# --- the nightly bookkeeping --------------------------------------------------------------------------------------------------------

def catch_up(con, upto: date, now: datetime) -> dict:
    """Every session since the last marked day: the orders that filled and the day's value. In the paper-only mode none of his real money moves in; in the system's own
    account the only outside money is a top-up of the fake bank (taken out of the return, like any deposit)."""
    last = con.execute("SELECT max(day) FROM paper_days").fetchone()[0]
    if last is None:
        return {"skipped": "not started"}
    days, filled = [], []
    for d in sessions_after(con, last, upto):
        filled += fill(con, d, now)
        flow = 0.0
        if _own():
            flow = float(con.execute("SELECT coalesce(sum(amount), 0) FROM events WHERE kind='deposit' AND account_id='SYSBANK' AND trade_date = ? AND ref LIKE 'topup:%'", [d]).fetchone()[0])
        mark(con, d, flow)
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
