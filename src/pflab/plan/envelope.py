"""The monthly envelope (S73): the sum he has set aside for shares each month, and what is left of it.

His words (2026-11-01): "till January I will invest 50k, and what I do not invest gets added to next month". Two house rules (hq/rules.py; both about money, so they exist only
after his yes) say it:

    monthly_envelope   amount_rupees each month, from `start` (default: the month the rule was made) until `until` (optional), `carry_over` (default true)
    dip_tranche        extra_rupees available while the Nifty 500 total-return index is at least `below_high_pct` below its high of the last year

The envelope is not a promise to buy and not an order. It is arithmetic on his own ledger: what the months so far have made available, minus the equity he has actually bought
since the start (shares and IPO allotments; funds and bonds are not counted here), so that unspent money carries forward by itself and an overspend shows as one. A proposal to
buy is sized against what is available now (hq/proposals.py), and the daily review (hq/daily.py) says where it stands. Nothing here moves money.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

import pandas as pd


def _months(start: date, asof: date) -> int:
    return (asof.year - start.year) * 12 + (asof.month - start.month) + 1


def drawdown(index: Optional[pd.Series], asof: date, window_days: int = 365) -> Optional[dict]:
    """How far the index is below its high of the last year, as of a date (None without an index)."""
    if index is None or not len(index):
        return None
    s = index[index.index <= pd.Timestamp(asof)]
    if not len(s):
        return None
    w = s[s.index >= pd.Timestamp(asof) - pd.Timedelta(days=window_days)]
    hi, last = float(w.max()), float(s.iloc[-1])
    return {"high": hi, "last": last, "below_high_pct": round(100.0 * (1.0 - last / hi), 2), "as_of": str(s.index[-1].date())}


def bought_since(con, start: date, asof: date) -> float:
    """Rupees of equity bought on the ledger from `start` to `asof` (quantity times price; charges are not counted)."""
    r = con.execute("SELECT coalesce(sum(e.qty * e.price), 0) FROM events e JOIN instruments i ON i.isin = e.isin "
                    "WHERE e.kind = 'buy' AND i.asset_class = 'equity' AND e.trade_date >= ? AND e.trade_date <= ?", [start, asof]).fetchone()
    return float(r[0] or 0.0)


def status(con, asof: date, index: Optional[pd.Series] = None) -> dict:
    """Where the envelope stands today. {'active': False} when he has set none."""
    from pflab.hq import rules
    env = next((r for r in rules.active(con) if r["kind"] == "monthly_envelope"), None)
    dip = next((r for r in rules.active(con) if r["kind"] == "dip_tranche"), None)
    if env is None:
        return {"active": False, "pending": [r["text"] for r in rules.pending(con) if r["kind"] in ("monthly_envelope", "dip_tranche")]}
    m = env["machine"]
    created = env["at"].date() if hasattr(env["at"], "date") else asof
    start = date.fromisoformat(m["start"]) if m.get("start") else date(created.year, created.month, 1)
    until = date.fromisoformat(m["until"]) if m.get("until") else None
    amount, carry = float(m["amount_rupees"]), bool(m.get("carry_over", True))
    last_day = min(asof, until) if until else asof
    n = max(0, _months(start, last_day))
    this_month_start = max(start, date(asof.year, asof.month, 1))
    spent_all, spent_month = bought_since(con, start, asof), bought_since(con, this_month_start, asof)
    allowance = amount * n
    available = max(0.0, allowance - spent_all) if carry else max(0.0, amount - spent_month) if (not until or asof <= until) else 0.0
    out = {"active": True, "amount_rupees": amount, "carry_over": carry, "start": str(start), "until": str(until) if until else None, "months_counted": n,
           "allowance_so_far": round(allowance, 2), "bought_since_start": round(spent_all, 2), "bought_this_month": round(spent_month, 2),
           "available_now": round(available, 2), "overspent_by": round(max(0.0, spent_all - allowance), 2) if carry else round(max(0.0, spent_month - amount), 2),
           "rule": env["name"], "finished": bool(until and asof > until)}
    if until:
        out["months_left"] = max(0, (until.year - asof.year) * 12 + (until.month - asof.month))
    if dip is not None:
        d = drawdown(index, asof)
        want = float(dip["machine"]["below_high_pct"])
        trig = bool(d and d["below_high_pct"] >= want)
        out["dip"] = {"extra_rupees": float(dip["machine"]["extra_rupees"]), "below_high_pct_needed": want, "market_below_high_pct": d["below_high_pct"] if d else None,
                      "triggered": trig, "rule": dip["name"]}
        if trig:
            out["available_now_with_dip"] = round(available + float(dip["machine"]["extra_rupees"]), 2)
    return out


def explain(s: dict) -> str:
    """The envelope in plain words (exact numbers from `status`)."""
    from pflab.app.front_render import inr
    if not s.get("active"):
        return ("No monthly envelope is set." + (" Waiting for your yes: " + "; ".join(s["pending"]) if s.get("pending") else ""))
    L = [f"Envelope: {inr(s['amount_rupees'])} a month" + (f" until {s['until']}" if s["until"] else "") + (", unspent carries forward" if s["carry_over"] else ", no carry-forward") + "."]
    L.append(f"So far {inr(s['allowance_so_far'])} has been made available over {s['months_counted']} month(s); you bought {inr(s['bought_since_start'])} of shares since {s['start']}"
             f" ({inr(s['bought_this_month'])} this month). Available now: {inr(s['available_now'])}."
             + (f" You are over by {inr(s['overspent_by'])}." if s["overspent_by"] else ""))
    d = s.get("dip")
    if d:
        L.append(f"Dip tranche: an extra {inr(d['extra_rupees'])} when the market is {d['below_high_pct_needed']:g}% below its high; it is "
                 + (f"{d['market_below_high_pct']:g}% below now: " + ("TRIGGERED." if d["triggered"] else "not triggered.") if d["market_below_high_pct"] is not None else "unknown (no index data)."))
    return " ".join(L)
