"""The opportunity reserve (S84, A64): cash only the thinking loop may spend.

    India   `[think] reserve_india_pts` points of the India part (the rupee book) held as cash
    US      `[think] reserve_us_pts` points of the US sub-book held as dollars

`reserve_status(con, market, day)` -> {"market", "reserve_inr", "used_inr", "free_inr", "points", "text", ...}: the reserve is the target (points of the part); `free` is the cash that is really
there for it (cash and bank less the money open buy orders will take), at most the reserve; `used` is what is not cash now (spent by a case, or not refilled yet). Nothing is booked on a side
table: the reserve refills by itself, because the baseline and the picks keep the reserve's points out of their own cash (`hold_fraction`, read by `core/baseline_v2.py` through the state), so new
money and sale proceeds meet the reserve first. A US figure is in rupees at the stated rate (`usd_inr`), the dollars are beside it.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from pflab import think


def hold_fraction(market: str = "IN") -> float:
    """The reserve as a fraction of its part: what the baseline and the picks leave as cash."""
    s = think.settings()
    if not think.on():
        return 0.0
    return max(0.0, float(s["reserve_us_pts" if market == "US" else "reserve_india_pts"])) / 100.0


def _india(con, day: date) -> dict:
    from pflab.paper import book
    h = book.holdings(con, day)
    value = float(h["value"] or 0.0)
    cash = float(h["cash"] or 0.0) + float(h.get("bank") or 0.0)
    pending = float(con.execute("SELECT coalesce(sum(amount), 0) FROM paper_orders WHERE status='open' AND side='buy'").fetchone()[0] or 0.0)
    return {"value": value, "cash": cash - pending, "fx": 1.0}


def _us(con, day: date) -> dict:
    from pflab.us import book as usb, wholebook
    if usb.account(con) is None:
        return {"value": 0.0, "cash": 0.0, "fx": 1.0, "open": False}
    u = wholebook.us_value_usd(con, day)
    pending = float(sum(float(o.get("amount_usd") or 0.0) for o in usb.open_orders(con) if o["side"] == "buy"))
    fx = 1.0
    try:
        w = wholebook.whole_book_inr(con, day)
        fx = float(w.get("fx") or 1.0)
    except Exception:
        pass
    return {"value": float(u.get("usd") or 0.0), "cash": float(usb.cash(con, day)) - pending, "fx": fx, "open": True}


def reserve_status(con, market: str, day: date) -> dict:
    market = (market or "IN").upper()
    pts = float(think.settings()["reserve_us_pts" if market == "US" else "reserve_india_pts"])
    try:
        p = _us(con, day) if market == "US" else _india(con, day)
    except Exception as e:
        return {"market": market, "reserve_inr": 0.0, "used_inr": 0.0, "free_inr": 0.0, "points": 0.0, "reserve_points": pts, "text": f"{market} reserve: unreadable now ({type(e).__name__})"}
    fx = p["fx"]
    reserve = pts / 100.0 * p["value"]
    free = max(0.0, min(reserve, p["cash"]))
    used = max(0.0, reserve - free)
    part = "the sub-book" if market == "US" else "the India part"
    name = "US" if market == "US" else "India"
    if p["value"] <= 0:
        text = f"{name} reserve: nothing to keep yet ({part} has no value)."
    else:
        text = (f"{name} reserve: Rs {free * fx:,.0f} of Rs {reserve * fx:,.0f} is free to spend on a chance ({pts:.0f} points of {part}); "
                + ("the rest is spent or waits to be refilled from new money and sale proceeds." if used > 1e-6 else "it is whole."))
    out = {"market": market, "reserve_inr": round(reserve * fx, 2), "used_inr": round(used * fx, 2), "free_inr": round(free * fx, 2),
           "points": round(100.0 * free / p["value"], 2) if p["value"] > 0 else 0.0, "reserve_points": pts, "text": text}
    if market == "US":
        out.update({"reserve_usd": round(reserve, 2), "free_usd": round(free, 2), "fx": fx})
    return out


def text(con, day: Optional[date] = None) -> str:
    """The reserve lines for Today and the 15:45 report (both markets), plain words."""
    day = day or date.today()
    return " ".join(reserve_status(con, m, day)["text"] for m in ("IN", "US"))
