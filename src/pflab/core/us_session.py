"""S86 H4 the US session loop (A77; CHANGES A59's "no US session loop", his words of 2026-11-13: "better to add the USA loop"). Modelled on India's 5-minute session loop (`core/session.py`).

While the app is open on a US trading day:
    regular hours (09:30-16:00 New York, from the market calendar, never hard-coded)   every 5 minutes: quotes, the watch on live quotes, and ACTION
    pre-market (04:00-09:30) and after-hours (16:00-20:00)                              every 15 minutes: quotes and the watch only; a decision becomes an order for the next open, and says so
Quotes: the Yahoo chart request already used for US prices, 1-minute bars with `includePrePost`, for every held and picked US name, the reserve's candidates and SPY. Every quote is stored with
its own time and its DELAY against the clock (`us_quotes_s86`); a quote older than `max_quote_delay_minutes` (20) is never used for a fill.
The watch runs in its mode `us_live` (a name's move against its usual daily move and against SPY NOW); a signal opens or joins a case like a headline does.
Action in regular hours: a stop (the exit plan's level, market US), a case's sell or trim, a reserve buy part and the pending orders of the morning plan fill at the FIRST quote strictly after the
decision's time (never the quote the decision was made on), moved by the slippage estimate; every fill stores the quote's time, its delay and the estimate (`us_fills_s86`). A buy and a sell of one
name on one US day never both happen. A closed laptop in US hours means the old path: the close loop fills at the next US open (`us/book.fill_orders`, unchanged).
Unchanged: the daily allocation and the strategist's picks (decided in the IST morning on the last close), the turnover caps, the sub-book's rails, the kill switch.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d&includePrePost=true"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
IST_OFFSET = timedelta(hours=5, minutes=30)
PRE_HOURS, POST_HOURS = 5.5, 4.0                      # 04:00 to 09:30 and 16:00 to 20:00 New York
MAX_SYMBOLS = 30
LOOP = "us_session"


def settings() -> dict:
    from pflab import us
    return us.settings()


def on() -> bool:
    try:
        from pflab import core, us
        return bool(us.on()) and bool(settings()["session_loop"]) and not core.killed()
    except Exception:
        return False


def phase(now: datetime) -> Tuple[str, Optional[date], Optional[tuple]]:
    """('regular' | 'pre' | 'post' | 'closed', the New York session date, its window in IST) at a naive IST moment, from the market calendar (daylight saving included)."""
    from pflab import markets
    mk = markets.get("US")
    for off in (-1, 0, 1):
        d = now.date() + timedelta(days=off)
        w = mk.window_ist(d)
        if not w:
            continue
        o, c = w
        if o <= now < c:
            return "regular", d, w
        if o - timedelta(hours=PRE_HOURS) <= now < o:
            return "pre", d, w
        if c <= now < c + timedelta(hours=POST_HOURS):
            return "post", d, w
    return "closed", None, None


# ------------------------------------------------------------------ quotes

def fetch_quote(sym: str, now: datetime, get: Optional[Callable] = None, timeout: int = 8) -> Optional[dict]:
    """The latest 1-minute bar of `sym` as {symbol, price, quote_ts (naive IST: the bar's END), delay_min}, or None. `get(url) -> text` is injectable (tests, replays)."""
    try:
        if get is None:
            import requests
            text = requests.get(CHART.format(sym=sym), headers={"User-Agent": UA}, timeout=timeout).text
        else:
            text = get(CHART.format(sym=sym))
        res = json.loads(text)["chart"]["result"][0]
        ts = res.get("timestamp") or []
        close = res["indicators"]["quote"][0].get("close") or []
        for t, c in zip(reversed(ts), reversed(close)):
            if c is not None and c > 0:
                end = datetime.fromtimestamp(int(t) + 60, timezone.utc).replace(tzinfo=None) + IST_OFFSET
                return {"symbol": sym, "price": float(c), "quote_ts": end, "delay_min": max(0.0, (now - end).total_seconds() / 60.0)}
    except Exception:
        return None
    return None


def symbols_for(con, now: datetime, root) -> List[str]:
    """Every held and picked US name (picks include the reserve's named candidates) and SPY."""
    syms = ["SPY"]
    try:
        from pflab.think import watch
        for e in watch.scope(con, now.date(), market="US", root=root):
            if e["held"] or "pick" in str(e.get("why") or ""):
                if e["symbol"] and e["symbol"] not in syms and not str(e["isin"]).startswith(("STORY:", "MARKET:", "MACRO:")):
                    syms.append(e["symbol"])
    except Exception:
        pass
    return syms[:MAX_SYMBOLS]


def store_quote(con, q: dict, now: datetime, ph: str) -> None:
    con.execute("INSERT INTO us_quotes_s86 VALUES (?,?,?,?,?,?) ON CONFLICT (symbol, quote_ts) DO NOTHING", [q["symbol"], q["quote_ts"], q["price"], now, round(q["delay_min"], 2), ph])


# ------------------------------------------------------------------ action

def _held_symbols(con, day: date) -> Dict[str, float]:
    from pflab.us import book as usb, instruments as uins
    out = {}
    for key, q in usb.positions(con, day).items():
        if q > 1e-9:
            out[key] = q
    return out


def stops(con, now: datetime, quotes: Dict[str, dict], d: date) -> List[int]:
    """A held name whose live quote is at or under its exit plan's stop gets a SELL order now (it fills at the NEXT quote, not this one). Plans of market US only."""
    from pflab.core import exits
    from pflab.us import book as usb
    placed: List[int] = []
    try:
        plans = exits._plans(con, "US")
    except Exception:
        return placed
    held = _held_symbols(con, d)
    open_sells = {o["isin"] for o in usb.open_orders(con) if o["side"] == "sell"}
    for p in plans:
        isin, stop = p.get("isin"), p.get("stop")
        if not stop or held.get(isin, 0.0) <= 1e-9 or isin in open_sells:
            continue
        from pflab.us import instruments as uins
        sym = uins.symbol_of(con, isin) or isin
        q = quotes.get(sym)
        if not q or q["delay_min"] > float(settings()["max_quote_delay_minutes"]) or q["price"] > float(stop):
            continue
        if _traded_today(con, d, sym, "buy"):
            continue                                                         # no same-day round trip in a name
        placed.append(usb.place(con, now, d, isin, sym, "sell", qty=round(held[isin], 6),
                                reason=f"stop: the quote {q['price']:,.2f} at {q['quote_ts']:%H:%M} IST is at or under the stop {float(stop):,.2f} (it fills at the next quote; gap risk stated)"))
    return placed


def _traded_today(con, d: date, sym: str, side: str) -> bool:
    return bool(con.execute("SELECT 1 FROM us_trades_s81 WHERE day=? AND symbol=? AND side=? LIMIT 1", [d, sym, side]).fetchone())


def fill_pending(con, now: datetime, quotes: Dict[str, dict], d: date, root=None) -> List[dict]:
    """Regular hours only. Every open order fills at the first quote strictly after its own time (`placed_at`), not older than `max_quote_delay_minutes`, moved by the slippage estimate. A buy and a
    sell of one name on one US day never both happen: the second is left open and the close loop cancels it as it does any order it cannot fill."""
    from pflab.us import book as usb
    cfg = settings()
    out: List[dict] = []
    bps = float(cfg["slippage_bps"])
    for o in usb.open_orders(con):
        q = quotes.get(o["symbol"])
        if not q or q["delay_min"] > float(cfg["max_quote_delay_minutes"]):
            continue                                                         # a stale quote never fills
        placed_at = con.execute("SELECT placed_at FROM us_orders_s81 WHERE order_id=?", [o["order_id"]]).fetchone()[0]
        if q["quote_ts"] <= placed_at:
            continue                                                         # never the quote the decision was made on
        other = "sell" if o["side"] == "buy" else "buy"
        if _traded_today(con, d, o["symbol"], other):
            con.execute("UPDATE us_orders_s81 SET reason = reason || ' [held: one name is not bought and sold on the same US day]' WHERE order_id=? AND reason NOT LIKE '%same US day%'", [o["order_id"]])
            continue
        f = usb.fill_one(con, now, d, o, q["price"], bps / 10000.0, root)
        if f is None:
            continue
        con.execute("INSERT INTO us_fills_s86 VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", [o["order_id"], o["symbol"], o["side"], placed_at, q["quote_ts"], round(q["delay_min"], 2), q["price"], f["price"], bps, d, now, "session"])
        out.append(dict(f, quote_ts=str(q["quote_ts"]), delay_min=round(q["delay_min"], 2), decision_ts=str(placed_at)))
    return out


# ------------------------------------------------------------------ one tick

def _recent_fetch(con, now: datetime, minutes: int) -> bool:
    r = con.execute("SELECT max(fetched_at) FROM us_quotes_s86").fetchone()[0]
    return bool(r) and (now - r) < timedelta(minutes=minutes)


def tick(con, now: datetime, root=None, *, get: Optional[Callable] = None, think_fn: Optional[Callable] = None, symbols: Optional[List[str]] = None, act: bool = True) -> dict:
    """One pass. Never raises: a failure is a line in `problems`. -> {phase, quotes, signals, cases, stops, fills, problems}."""
    out: dict = {"phase": None, "quotes": 0, "problems": [], "stops": [], "fills": [], "cases": []}
    if not on():
        out["off"] = True
        return out
    ph, d, _w = phase(now)
    out["phase"] = ph
    if ph == "closed":
        out["skipped"] = "the US market is closed"
        return out
    cfg = settings()
    if ph != "regular" and _recent_fetch(con, now, int(cfg["session_off_minutes"]) - 1):
        out["skipped"] = "pre-market and after-hours are looked at every 15 minutes"
        return out
    syms = symbols or symbols_for(con, now, root)
    quotes: Dict[str, dict] = {}
    for s in syms:
        q = fetch_quote(s, now, get)
        if q is None:
            out["problems"].append(f"no quote for {s}")
            continue
        store_quote(con, q, now, ph)
        quotes[s] = q
    out["quotes"] = len(quotes)
    out["median_delay_min"] = round(sorted(q["delay_min"] for q in quotes.values())[len(quotes) // 2], 2) if quotes else None
    try:
        from pflab.think import alarm
        alarm.record_eye(con, "us_quotes", now, ok=(None if not syms else bool(quotes)), items=len(quotes), error="" if quotes else "no US quote answered")
    except Exception:
        pass
    if not quotes:
        return out
    try:
        from pflab.think import watch, wire
        res = watch.run(con, now, mode="us_live", quotes={s: q["price"] for s, q in quotes.items() if q["delay_min"] <= float(cfg["max_quote_delay_minutes"])}, root=root) or {}
        out["signals"] = len(res.get("signals") or [])
        out["cases"] = list(res.get("cases_opened") or [])
        if out["cases"]:
            th = {"thought": [], "failed": []}
            wire._think(con, now, out["cases"], root, th)
            out["thought"], out["thinking_problems"] = th["thought"], th["failed"]
    except Exception as e:
        out["problems"].append(f"the watch on live US quotes failed: {type(e).__name__}: {str(e)[:120]}")
    if ph == "regular" and act:
        try:
            out["fills"] = fill_pending(con, now, quotes, d, root)          # first: an order from an earlier tick fills on THIS tick's quote; the stop below places a new one for the next
            out["stops"] = stops(con, now, quotes, d)
        except Exception as e:
            out["problems"].append(f"the US session's orders failed: {type(e).__name__}: {str(e)[:120]}")
        try:
            from pflab.paper import cadence
            if out["fills"] or out["stops"]:
                cadence.act(con, now, LOOP, f"US session {now:%H:%M}: {len(out['fills'])} fill(s), {len(out['stops'])} stop(s) placed", True, {"day": str(d)})
        except Exception:
            pass
    return out


def delay_report(con, day: date) -> dict:
    """Quote delay in minutes over the US session `day` (median, worst) and its fills, for the notes and the 15:45 report."""
    rows = con.execute("SELECT delay_min FROM us_quotes_s86 WHERE CAST(fetched_at AS DATE) IN (?, ?)", [day, day + timedelta(days=1)]).fetchall()
    xs = sorted(float(r[0]) for r in rows if r[0] is not None)
    fills = con.execute("SELECT count(*), max(delay_min) FROM us_fills_s86 WHERE session_day=?", [day]).fetchone()
    return {"quotes": len(xs), "median_delay_min": xs[len(xs) // 2] if xs else None, "worst_delay_min": xs[-1] if xs else None, "fills": fills[0], "worst_fill_delay_min": fills[1]}
