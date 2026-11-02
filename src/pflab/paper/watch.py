"""The system's watchlist (S78; his question 2026-11-02: does it build a watchlist and wait for the right time, based on calculations?).

An idea the team likes but will not buy yet is put here with the point its OWN calculation set: a price zone (`zone`), a fall from its year's high (`fall_from_high`) or a fall of the
whole market (`market_fall`, for spending cash in tranches). Code checks the price every round (live inside a session, else the last close). When the price reaches the point the
item is TRIGGERED, which is a reason for the team to look again; it never buys by itself. After the look, a decision handles it: a buy closes the item, a wait or hold re-arms it for
a few days (`SNOOZE_DAYS`) so it does not ask again at once.

The numbers are not the model's: a zone or a fall percentage given by the team must be found in the stored result of a calculation it names (`calc_id`), within half a percent.
He may add an item from the chat with his own numbers (his words are the source).
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

KINDS = ("zone", "fall_from_high", "market_fall")
ACTIVE = ("waiting", "near", "triggered")
NEAR_PCT = 3.0                      # within this many percent above the point: "near"
SNOOZE_DAYS = 5
STALE_DAYS = 90                     # an item this old with no trigger is flagged for review (its reason may be gone)
MARKET = "MARKET"
TOLERANCE = 0.005


def _numbers(text: str) -> List[float]:
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text or "")]


def number_in_calc(con, calc_id: int, value: float) -> bool:
    """Is `value` (within half a percent) a number in the stored result of calculation `calc_id`? The team's zones must come from a calculation, not from its own head."""
    r = con.execute("SELECT result_json FROM hq_calcs WHERE calc_id=?", [calc_id]).fetchone()
    if not r or not r[0]:
        return False
    return any(abs(n - value) <= max(TOLERANCE * abs(value), 0.005) for n in _numbers(str(r[0])))


def price_now(con, isin: str, now: datetime) -> Optional[tuple]:
    """(price, 'live'|'close', as-of) : a fresh Kite quote inside a session, else the last close on record."""
    from pflab.paper import book
    live = book.live_prices(con, now, [isin], max_age_min=15).get(isin)
    if live:
        return live, "live", now
    c = book.close_on(con, isin, now.date())
    return (c[1], "close", c[0]) if c else None


def year_high(con, root, isin: str, day: date) -> Optional[float]:
    from pflab.quant import candles
    try:
        df = candles.daily(root, isin, day, bars=252)
    except Exception:
        return None
    return float(df["high"].max()) if len(df) >= 120 else None


def add(con, now: datetime, *, symbol: Optional[str], kind: str, reason: str, by: str, zone_low: Optional[float] = None, zone_high: Optional[float] = None,
        fall_pct: Optional[float] = None, calc_id: Optional[int] = None, case_id: Optional[int] = None, his_numbers: bool = False) -> dict:
    """Put an idea on the watchlist. The team must name the calculation its numbers come from; he may use his own. Returns the item or the problem (nothing stored)."""
    from pflab.paper import book
    from pflab.pm.store import next_id
    if kind not in KINDS:
        return {"stored": False, "problem": f"kind must be one of {KINDS}"}
    reason = " ".join(str(reason or "").split())
    if len(reason) < 20:
        return {"stored": False, "problem": "give the reason it is worth waiting for, in a sentence or two"}
    isin, sym = MARKET, "the market"
    if kind != "market_fall":
        isin = book.isin_of(con, symbol or "") if symbol else None
        if not isin:
            return {"stored": False, "problem": f"no instrument with the symbol {symbol!r}"}
        meta = book.inst(con, isin)
        if (meta["asset_class"] or "") not in book.BUYABLE:
            return {"stored": False, "problem": f"{symbol} is not a listed share or ETF: only those can be bought, so only those can wait"}
        sym = meta["symbol"] or symbol
        if book.close_on(con, isin, now.date()) is None:
            return {"stored": False, "problem": f"no price on record for {symbol}"}
    if kind == "zone":
        if not zone_high or zone_high <= 0 or (zone_low is not None and zone_low > zone_high):
            return {"stored": False, "problem": "a zone needs zone_high (and zone_low not above it), in rupees"}
    else:
        if not fall_pct or not 2 <= fall_pct <= 60:
            return {"stored": False, "problem": "fall_pct is the percentage fall from the year's high that triggers it, between 2 and 60"}
    if not his_numbers:
        nums = [("zone_high", zone_high), ("zone_low", zone_low)] if kind == "zone" else [("fall_pct", fall_pct)]
        if not calc_id:
            return {"stored": False, "problem": "name the calculation the numbers come from (calc_id): a zone is not a guess"}
        for name, v in nums:
            if v is not None and not number_in_calc(con, int(calc_id), float(v)):
                return {"stored": False, "problem": f"{name} {v:g} is not a number in the stored result of calculation #{calc_id}: take the number from it"}
    old = con.execute("SELECT watch_id FROM paper_watch WHERE isin=? AND kind=? AND status IN ('waiting','near','triggered') ORDER BY watch_id DESC LIMIT 1", [isin, kind]).fetchone()
    vals = [zone_low, zone_high, fall_pct, reason[:600], f"calc #{calc_id}" if calc_id else ("his own numbers" if his_numbers else None), case_id]
    if old:
        con.execute("UPDATE paper_watch SET zone_low=?, zone_high=?, fall_pct=?, reason=?, calc_ref=?, case_id=?, status='waiting', snooze_until=NULL, updated_at=? WHERE watch_id=?", vals + [now, old[0]])
        wid, new = int(old[0]), False
    else:
        wid, new = next_id(con, "paper_watch", "watch_id"), True
        con.execute("INSERT INTO paper_watch (watch_id, isin, symbol, added_at, added_by, kind, zone_low, zone_high, fall_pct, reason, calc_ref, case_id, status, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [wid, isin, sym, now, by, kind, zone_low, zone_high, fall_pct, reason[:600], vals[4], case_id, "waiting", now])
    return {"stored": True, "watch_id": wid, "new": new, "symbol": sym, "kind": kind, "note": "checked every round; when it reaches the point the team looks again. It never buys by itself."}


def remove(con, now: datetime, key, why: str = "") -> dict:
    """Take an item off (by id or symbol). The row stays (status removed) for the record."""
    if isinstance(key, int) or str(key).isdigit():
        rows = con.execute("SELECT watch_id FROM paper_watch WHERE watch_id=? AND status IN ('waiting','near','triggered')", [int(key)]).fetchall()
    else:
        rows = con.execute("SELECT watch_id FROM paper_watch WHERE upper(symbol)=? AND status IN ('waiting','near','triggered')", [str(key).strip().upper()]).fetchall()
    for (wid,) in rows:
        con.execute("UPDATE paper_watch SET status='removed', note=?, updated_at=? WHERE watch_id=?", [(why or "removed")[:300], now, wid])
    return {"removed": len(rows)}


def _market_drawdown(index) -> Optional[float]:
    from pflab.plan import envelope
    d = envelope.drawdown(index, date.today())
    return d["below_high_pct"] if d else None


def check(con, now: datetime, root=None, index=None) -> dict:
    """One pass over every active item: its price now, its status, newly triggered ones. Free (code). Returns counts and the items that just triggered."""
    fired, near, n = [], 0, 0
    for r in con.execute("SELECT watch_id, isin, symbol, kind, zone_low, zone_high, fall_pct, status, snooze_until, added_at FROM paper_watch WHERE status IN ('waiting','near','triggered') "
                         "ORDER BY watch_id").fetchall():
        wid, isin, sym, kind, zl, zh, fp, status, snooze, added = r
        n += 1
        if kind == "market_fall":
            dd = _market_drawdown(index) if index is not None else None
            if dd is None:
                continue
            hit, gap, price = dd >= float(fp), (float(fp) - dd), None
            trig = None
        else:
            p = price_now(con, isin, now)
            if p is None:
                continue
            price = p[0]
            if kind == "fall_from_high":
                hi = year_high(con, root, isin, now.date()) if root is not None else None
                if hi is None:
                    continue
                zh = round(hi * (1 - float(fp) / 100), 2)
                con.execute("UPDATE paper_watch SET zone_high=? WHERE watch_id=?", [zh, wid])
            hit, gap = price <= float(zh), (price / float(zh) - 1) * 100
        snoozed = bool(snooze and now < snooze)
        new_status = "triggered" if (hit and not snoozed) else "near" if (gap <= NEAR_PCT and not hit) or (hit and snoozed) else "waiting"
        if kind == "market_fall":
            new_status = "triggered" if (hit and not snoozed) else "near" if (gap <= 2.0) else "waiting"
        con.execute("UPDATE paper_watch SET status=?, last_price=?, last_checked=?, updated_at=?, triggered_at=CASE WHEN ? = 'triggered' AND triggered_at IS NULL THEN ? ELSE triggered_at END "
                    "WHERE watch_id=?", [new_status, price, now, now, new_status, now, wid])
        if new_status == "triggered" and status != "triggered":
            fired.append({"watch_id": wid, "symbol": sym, "price": price, "point": zh if kind != "market_fall" else fp, "kind": kind})
        near += new_status == "near"
    return {"checked": n, "near": near, "triggered_now": fired}


def triggered(con) -> List[dict]:
    return [{"watch_id": r[0], "symbol": r[1], "price": r[2], "point": r[3], "kind": r[4], "reason": r[5]} for r in con.execute(
        "SELECT watch_id, symbol, last_price, coalesce(zone_high, fall_pct), kind, reason FROM paper_watch WHERE status='triggered' ORDER BY watch_id").fetchall()]


def reasons(con) -> List[str]:
    """For `manager.reasons_to_look`: what the watchlist asks the team to look at now, and what has gone stale."""
    out = []
    for t in triggered(con):
        out.append(f"watchlist: {t['symbol']} reached its point " + (f"(Rs {t['price']:,.2f} against Rs {t['point']:,.2f})" if t["kind"] != "market_fall" else f"(the market is {t['point']:g}% below its high)"))
    return out


def handled(con, now: datetime, isin: Optional[str], action: str, decision_id: int) -> int:
    """A decision was made about a triggered name: a buy closes the item; anything else re-arms it for SNOOZE_DAYS (the team looked and chose to wait or hold)."""
    n = 0
    for (wid,) in con.execute("SELECT watch_id FROM paper_watch WHERE status='triggered' AND (isin = ? OR (kind='market_fall' AND ? IN ('BUY','ADD')))", [isin, action]).fetchall():
        if action in ("BUY", "ADD"):
            con.execute("UPDATE paper_watch SET status='handled', note=?, updated_at=? WHERE watch_id=?", [f"decision #{decision_id}: {action}", now, wid])
        else:
            con.execute("UPDATE paper_watch SET status='waiting', snooze_until=?, triggered_at=NULL, note=?, updated_at=? WHERE watch_id=?",
                        [now + timedelta(days=SNOOZE_DAYS), f"looked again (decision #{decision_id}: {action}); it waits {SNOOZE_DAYS} days before asking again", now, wid])
        n += 1
    return n


def listing(con, now: datetime) -> List[dict]:
    """The screen's list: each active item with its price, its gap to the point, the position of the dot against the zone, and how old it is."""
    out = []
    for r in con.execute("SELECT watch_id, symbol, kind, zone_low, zone_high, fall_pct, reason, calc_ref, status, last_price, last_checked, triggered_at, added_at, added_by, note, snooze_until, case_id "
                         "FROM paper_watch WHERE status IN ('waiting','near','triggered') ORDER BY CASE status WHEN 'triggered' THEN 0 WHEN 'near' THEN 1 ELSE 2 END, watch_id").fetchall():
        k = dict(zip(("watch_id", "symbol", "kind", "zone_low", "zone_high", "fall_pct", "reason", "calc_ref", "status", "price", "checked", "triggered_at", "added_at", "by", "note", "snooze_until", "case_id"), r))
        zh, px = k["zone_high"], k["price"]
        k["gap_pct"] = round((px / zh - 1) * 100, 2) if (zh and px) else None
        k["age_days"] = (now - k["added_at"]).days
        k["stale"] = k["age_days"] >= STALE_DAYS and k["status"] != "triggered"
        out.append(json.loads(json.dumps(k, default=str)))
    return out
