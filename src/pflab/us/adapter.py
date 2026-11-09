"""The entry points the close loop calls for the US leg (S81 B8 phase B). Thin: everything is in the modules beside this one.

    close_us(con, now, root=None, cfg=None, book_value_inr=None) -> dict
        Handles the latest US session that has closed (settle_minutes after its close, in the IST morning): splits, dividends, fills of yesterday's orders at the open, the mark at the
        close, the baseline's decision through the rails, and the new orders. Once per session (`us_runs_s81`). Never raises for a missing input: it says what it is waiting for.
        Returns {"off": True} while `[us] on = false` (the default), {"waiting": ...}, {"skipped": ...} or the run's summary.
    state_us(con, day, root=None) -> dict
        The sub-book on `day` for screens, the card and the morning note: account, cash, positions in USD and rupees (the FX rate and its source stated), the financial year's
        realised gains, tax and dividend figures, open orders and the last run. JSON-safe. `{"open": False}` before the account exists.

The loop's wiring (coordinator): after the Indian close loop, `if us.on(): adapter.close_us(con, now)`; call it again on every tick in the IST morning (it is idempotent per session).
Nothing in the Indian paper book reads these tables; the `market="IN"` code paths are unchanged.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime
from typing import Optional

from pflab import us
from pflab.us import book, clock, data, fx as usfx, instruments as uins, policy


def _system_book_value(con, now: datetime) -> Optional[float]:
    """The rupee paper book's value on the last Indian close, or None when it cannot be read (the caller then uses the configured fallback and says so)."""
    try:
        from pflab import markets
        from pflab.paper import book as inbook
        day = markets.get("IN").session_closed_by(now)
        v = inbook.holdings(con, day)["value"]
        return float(v) if v and v > 0 else None
    except Exception:
        return None


def close_us(con, now: datetime, root=None, cfg: Optional[dict] = None, book_value_inr: Optional[float] = None) -> dict:
    s = us.settings(cfg)
    if not s["on"]:
        return {"off": True}
    day = clock.session_closed_by(now, int(s["settle_minutes"]))
    if con.execute("SELECT 1 FROM us_runs_s81 WHERE day=?", [day]).fetchone():
        return {"skipped": f"US session {day} already done"}
    universe = [x.upper() for x in s["universe"]]
    held = [uins.symbol_of(con, k) for k in book.positions(con, day)]
    syms = list(dict.fromkeys(universe + [h for h in held if h]))
    bars = data.load(syms, root)
    if not any(data.bar_on(bars.get(x), day) for x in universe):
        return {"waiting": f"no US bars for {day} yet (tools/backfill_us.py / data/us_prices.py collect them)"}
    fx = usfx.rate_for(con, day, root)
    if fx is None:
        return {"waiting": f"no USD/INR rate within 4 days of {day}"}
    t0 = time.time()
    opened = None
    if book.account(con) is None:
        v, how = (book_value_inr, "given") if book_value_inr else (_system_book_value(con, now), "the rupee paper book")
        if not v:
            v, how = float(s["start_inr_fallback"]) / float(s["start_share"]), "the configured fallback (the system's book could not be read)"
        acct = book.open_account(con, now, day, float(v), fx, float(s["start_share"]))
        opened = {"start_usd": round(acct["start_usd"], 2), "start_inr": round(acct["start_inr"], 2), "book_value_from": how}
    splits = book.detect_splits(con, now, day, bars)
    dividends = book.apply_dividends(con, now, day, bars, w8ben=bool(s["w8ben"]), root=root)
    fills = book.fill_orders(con, now, day, bars, float(s["slippage_bps"]), root)
    marked = book.mark(con, now, day, bars, fx)
    state = policy.build(con, day, bars, cfg, root, now)
    dec = policy.decide(state)
    chk = policy.check(con, state, dec)
    placed = []
    for o in chk["orders"]:
        oid = book.place(con, now, day, o["isin"], o["symbol"], o["side"], qty=o["qty"], amount_usd=o["amount"], reason=o["reason"])
        placed.append({"order_id": oid, "symbol": o["symbol"], "side": o["side"], "usd": round(o["value"], 2), "reason": o["reason"]})
    status = "traded" if (placed or fills) else "held"
    note = "; ".join(dec["notes"])
    con.execute("INSERT INTO us_runs_s81 VALUES (?,?,?,?,?,?,?,?)", [day, now, status, round(time.time() - t0, 3), json.dumps({k: round(v, 5) for k, v in dec["weights"].items()}),
                json.dumps(placed), json.dumps(fills), note[:400]])
    return {"day": str(day), "status": status, "opened": opened, "fills": fills, "orders": placed, "dividends": dividends, "splits": splits, "value_usd": round(marked["value_usd"], 2),
            "cash_usd": round(marked["cash_usd"], 2), "fx": {"rate": fx["rate"], "source": fx["source"], "label": fx["label"]}, "skipped": len(chk["skipped"]),
            "seconds": round(time.time() - t0, 3)}


def state_us(con, day: date, root=None) -> dict:
    acct = book.account(con)
    if acct is None:
        return {"open": False, "on": us.on()}
    fx = usfx.rate_for(con, day, root, max_age_days=10)
    rate = fx["rate"] if fx else None
    pos = []
    for l_isin, q in book.positions(con, day).items():
        sym = uins.symbol_of(con, l_isin) or l_isin
        r = con.execute("SELECT holdings_json FROM us_days_s81 WHERE day <= ? ORDER BY day DESC LIMIT 1", [day]).fetchone()
        info = (json.loads(r[0]) if r and r[0] else {}).get(l_isin, {})
        v = info.get("value_usd")
        pos.append({"isin": l_isin, "symbol": sym, "qty": round(q, 6), "close": info.get("close"), "value_usd": v, "value_inr": None if (v is None or rate is None) else round(v * rate, 2)})
    d = con.execute("SELECT day, value_usd, cash_usd, fx_rate, fx_source, value_inr FROM us_days_s81 WHERE day <= ? ORDER BY day DESC LIMIT 1", [day]).fetchone()
    last = con.execute("SELECT day, status, note FROM us_runs_s81 ORDER BY day DESC LIMIT 1").fetchone()
    return {"open": True, "on": us.on(), "account": {k: (str(v) if isinstance(v, (date, datetime)) else v) for k, v in acct.items()},
            "marked": None if not d else {"day": str(d[0]), "value_usd": d[1], "cash_usd": d[2], "fx_rate": d[3], "fx_source": d[4], "value_inr": d[5]},
            "fx": None if not fx else {"rate": fx["rate"], "source": fx["source"], "rate_day": str(fx["rate_day"]), "label": fx["label"]},
            "positions": pos, "open_orders": [{**o, "placed_day": str(o["placed_day"])} for o in book.open_orders(con)],
            "financial_year": book.realised_fy(con, _fy(day)), "last_run": None if not last else {"day": str(last[0]), "status": last[1], "note": last[2]},
            "label": "paper money in dollars; rupee figures are estimates (docs/US_LEG_S81.md)"}


def _fy(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1
