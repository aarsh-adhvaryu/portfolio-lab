"""ONE book (S82, A57): the whole book is the rupee book plus the US paper sub-book in rupees, and the international share is held in the sub-book (or in an India-listed
international ETF while its premium is under the rail). Other parts of the system call these functions; they do not recompute the whole.

    whole_book_inr(con, day)        {rupee_book_inr, us_book_usd, us_book_inr, fx, fx_source, whole_inr, ...}: the value everywhere the whole book is meant (the book card, the benchmark
                                    comparison). The sub-book is valued at its last US close and the day's USD/INR with its source stated (`us/fx.py`: FBIL, else the market close, else FRED).
    international_share(con, day)   the international share of the whole book: the target (`[baseline_v2] international_pct`, 10%), what is held (US sub-book, India-listed international
                                    ETF), what waits as rupee cash, the gap, the phase (build / topup / settled), today's tranche and the reason in plain words
    plan_tranche(con, day, now)     the transfer due today (rupees) with the caps that cut it: at most one a day, `fund_day_share` of the whole book, inside the rails' turnover caps,
                                    never more than the rupee cash that is free; the cash the premium rail left idle goes first. NEVER a sale: a share above target is held (tax)
    attach(con, state)              the one hook in `core/state.py`: puts `whole_value`, `us_book_inr` and `international` into the rupee book's state (its `value` stays the rupee book's:
                                    the policy's weights are weights of the book it can trade)
    returns(con)                    the whole book's time-weighted return since the rupee book's first marked day (transfers are inside the book, only top-ups are outside money)
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, Optional

from pflab import us
from pflab.us import book, fx as usfx, transfer

RESTATED = "estimate: the sub-book's rupee value is its dollars at the stated USD/INR rate (paper money; no tax or exit cost taken)"


def _rupee_holdings(con, day: date) -> dict:
    from pflab.paper import book as pb
    return pb.holdings(con, day)


def us_value_usd(con, day: date) -> dict:
    """{'usd', 'cash_usd', 'marked_day'}: the sub-book's value in dollars on `day`: the last marked day on or before it, plus the cash that moved since the mark (a transfer or a fill
    after it). {'usd': 0.0, 'open': False} while there is no account."""
    if book.account(con) is None:
        return {"usd": 0.0, "cash_usd": 0.0, "marked_day": None, "open": False}
    r = con.execute("SELECT day, value_usd, cash_usd FROM us_days_s81 WHERE day <= ? ORDER BY day DESC LIMIT 1", [day]).fetchone()
    c = book.cash(con, day)
    if not r:
        return {"usd": c, "cash_usd": c, "marked_day": None, "open": True}
    return {"usd": float(r[1]) + (c - float(r[2])), "cash_usd": c, "marked_day": r[0], "open": True}


def _us_inr(con, day: date, root=None) -> dict:
    """The sub-book on `day` in rupees: {'open', 'usd', 'inr', 'fx': {...} or None, 'marked_day'}. No fresh rate: the rate stored with the last mark stands in and says so."""
    u = us_value_usd(con, day)
    fx = usfx.rate_for(con, day, root, max_age_days=10) if u["open"] else None
    if u["open"] and fx is None:
        r = con.execute("SELECT fx_rate, fx_source, day FROM us_days_s81 WHERE day <= ? AND fx_rate IS NOT NULL ORDER BY day DESC LIMIT 1", [day]).fetchone()
        if r:
            fx = {"rate": float(r[0]), "source": r[1], "rate_day": r[2], "label": f"estimate: the rate stored with the mark of {r[2]} ({r[1]}); no fresher rate within 10 days"}
    return {"open": bool(u["open"]), "usd": float(u["usd"]), "inr": u["usd"] * fx["rate"] if (fx and u["open"]) else 0.0, "fx": fx, "marked_day": u.get("marked_day")}


def whole_book_inr(con, day: date, root=None) -> dict:
    """The whole book on `day` in rupees. `fx` is None (and the sub-book counts as 0 with a note) only when no USD/INR rate within 10 days exists."""
    h = _rupee_holdings(con, day)
    rupee = float(h["value"] or 0.0)
    u = _us_inr(con, day, root)
    fx = u["fx"]
    return {"day": str(day), "rupee_book_inr": rupee, "us_book_usd": u["usd"], "us_book_inr": u["inr"], "fx": None if fx is None else float(fx["rate"]),
            "fx_source": None if fx is None else fx["source"], "fx_label": None if fx is None else fx.get("label"), "whole_inr": rupee + u["inr"], "us_open": u["open"],
            "us_marked_day": None if not u["marked_day"] else str(u["marked_day"]), "label": RESTATED,
            "note": None if (fx or not u["open"]) else "no USD/INR rate within 10 days: the sub-book is not counted in rupees"}


def _india_international(con, day: date, h: dict, cfg: dict) -> dict:
    """The India-listed international ETFs: what the rupee book holds of them and, for the ETFs the policy may buy, their premium to NAV against the rail."""
    from pflab.core import premium
    from pflab.paper import allocation, book as pb
    held = 0.0
    for r in h["rows"]:
        if allocation.class_of(r["asset_class"], r.get("name"), r["symbol"], r["isin"]) == "international" and (r["asset_class"] or "") == "etf":
            held += float(r["value"] or 0.0)
    ps = premium.settings()
    rails = []
    for sym in cfg["baseline_v2"]["international_etfs"]:
        isin = pb.isin_of(con, sym)
        if not isin:
            continue
        p = premium.premium_at(con, isin, day, int(ps["max_nav_age_days"]))
        if not ps["on"]:
            blocked, why = False, "the premium rail is off"
        elif not p["known"]:
            blocked = ps["unknown"] == "skip"
            why = f"its premium to NAV is unknown ({p['why']})"
        elif p["premium_pct"] >= float(ps["max_premium_pct"]):
            blocked, why = True, f"it trades {p['premium_pct']:.1f}% above its NAV, over the {float(ps['max_premium_pct']):g}% limit"
        else:
            blocked, why = False, f"it trades {p['premium_pct']:.1f}% above its NAV, under the {float(ps['max_premium_pct']):g}% limit"
        rails.append({"symbol": sym, "isin": isin, "premium_pct": p.get("premium_pct"), "known": p["known"], "blocked": blocked, "why": why})
    return {"held_inr": held, "rails": rails}


def _turnover_room(con, day: date, whole: float, cfg: dict) -> dict:
    """What the rails' turnover caps leave for a transfer today: the day's cap less the rupee book's trades dated today and the month's cap less this month's trades and transfers."""
    from pflab.core import rails
    r = cfg["rails"]
    traded_today = float(con.execute("SELECT coalesce(sum(qty * price), 0) FROM paper_trades WHERE day = ?", [day]).fetchone()[0] or 0.0)
    day_room = max(0.0, float(r["turnover_day"]) * whole - traded_today - sum(t["inr"] for t in transfer.transfers_on(con, day)))
    month_room = max(0.0, float(r["turnover_month"]) * whole - rails.month_traded(con, day) - transfer.month_moved(con, day))
    return {"day_room": day_room, "month_room": month_room}


def international_share(con, day: date, now: Optional[datetime] = None, root=None, cfg: Optional[dict] = None, us_cfg: Optional[dict] = None) -> dict:
    """The international share of the whole book, split into the US sub-book, the India-listed international ETF and the cash waiting to be moved, with the target and the reason.
    `day` is the rupee-side day (the transfer's date); `tranche_inr` is what may be moved on it. Read-only."""
    from pflab import core
    cfg = cfg or core.settings()
    s = us.settings(us_cfg)
    day = day
    now = now or datetime.combine(day, datetime.min.time())
    h = _rupee_holdings(con, day)
    w = whole_book_inr(con, day, root)
    whole = float(w["whole_inr"])
    target = float(cfg["baseline_v2"]["international_pct"]) / 100.0
    ind = _india_international(con, day, h, cfg)
    us_inr, india_inr = float(w["us_book_inr"]), float(ind["held_inr"])
    us_cash_inr = float(book.cash(con, day)) * float(w["fx"] or 0.0) if w["us_open"] else 0.0
    held = us_inr + india_inr
    share = held / whole if whole > 0 else 0.0
    free = transfer.rupee_cash(con, day)["free"]
    gap = max(0.0, target * whole - held)
    waiting = min(gap, free)
    settled = bool(w["us_open"]) and (share >= target - 0.002 or any((t["share_after"] or 0.0) >= target - 0.002 for t in transfer.transfers(con)))
    phase = "open" if not w["us_open"] else ("topup" if settled else "build")
    below = share < float(s["topup_below_share"])
    need = 0.0
    if whole > 0:
        need = gap if (phase in ("open", "build") or below) else 0.0
    caps = {"day_share": float(s["fund_day_share"]) * whole}
    room = _turnover_room(con, day, whole, cfg) if whole > 0 else {"day_room": 0.0, "month_room": 0.0}
    why_cut = []
    tranche = need
    if tranche > caps["day_share"] + 1e-9:
        tranche = caps["day_share"]
        why_cut.append(f"at most {float(s['fund_day_share']):.0%} of the whole book in a day")
    if tranche > room["day_room"] + 1e-9:
        tranche = room["day_room"]
        why_cut.append("inside the rails' daily turnover cap")
    if tranche > room["month_room"] + 1e-9:
        tranche = room["month_room"]
        why_cut.append("inside the rails' monthly turnover cap")
    if tranche > free + 1e-9:
        tranche = free
        why_cut.append("only the rupee cash that is free (not claimed by the rupee book's own open buys)")
    done_today = transfer.transfers_on(con, day)
    if done_today:
        tranche = 0.0
        why_cut.append("one transfer a day at most, and one was made today")
    min_inr = float(cfg["rails"]["min_trade_rupees"])
    if 0 < tranche < min_inr:
        tranche = 0.0
        why_cut.append(f"under the minimum trade of Rs {min_inr:,.0f}")
    reason = _reason(target, share, held, whole, ind, phase, below, need, tranche, why_cut, free, s)
    return {"day": str(day), "target": target, "target_pct": target * 100.0, "share": share, "whole_inr": whole, "us_sub_book_inr": us_inr, "us_cash_inr": us_cash_inr,
            "us_invested_inr": max(0.0, us_inr - us_cash_inr), "india_etf_inr": india_inr, "waiting_cash_inr": waiting, "gap_inr": gap, "rupee_cash_free_inr": free, "phase": phase,
            "topup_below_share": float(s["topup_below_share"]), "tranche_inr": tranche, "tranche_cut_by": why_cut, "india_etf_rail": ind["rails"], "fx": w["fx"], "fx_source": w["fx_source"],
            "reason": reason, "label": RESTATED}


def _reason(target, share, held, whole, ind, phase, below, need, tranche, why_cut, free, s) -> str:
    if whole <= 0:
        return "the whole book has no value yet, so there is nothing to size the international share on"
    blocked = [r for r in ind["rails"] if r["blocked"]]
    bits = [f"the international share is {share:.1%} of the whole book against a target of {target:.0%}"]
    if blocked:
        r = blocked[0]
        bits.append(f"the Indian international ETF {r['symbol']}: {r['why']}, so that part is held in the US book or waits as cash")
    elif ind["rails"]:
        bits.append(f"the Indian international ETF {ind['rails'][0]['symbol']}: {ind['rails'][0]['why']}")
    if phase in ("open", "build"):
        bits.append(f"building it in steps from the rupee book's cash ({'a transfer of Rs ' + format(tranche, ',.0f') + ' today' if tranche > 0 else 'no transfer today'}"
                    f"{': ' + '; '.join(why_cut) if why_cut else ''})")
    elif below:
        bits.append(f"it fell under {float(s['topup_below_share']):.0%}, so it is topped up from rupee cash ({'Rs ' + format(tranche, ',.0f') + ' today' if tranche > 0 else 'nothing free today'})")
    else:
        bits.append(f"it is at or above the {float(s['topup_below_share']):.0%} floor: nothing is moved, and a share above the target is never sold down (that would cost tax)")
    if need > 0 and free <= 0:
        bits.append("the rupee book has no free cash to move")
    return "; ".join(bits)


def plan_tranche(con, day: date, now: Optional[datetime] = None, root=None, cfg: Optional[dict] = None, us_cfg: Optional[dict] = None) -> dict:
    """The transfer due on the rupee day `day`: {'inr', 'phase', 'reason', 'share'}; inr is 0.0 when none is due."""
    ish = international_share(con, day, now, root, cfg, us_cfg)
    return {"inr": float(ish["tranche_inr"]), "phase": ish["phase"], "reason": ish["reason"], "share": ish["share"], "share_target": ish["target"], "international": ish}


def attach(con, state: dict, root=None) -> dict:
    """The hook in `core/state.build`: the whole book beside the rupee book. Never raises into the loop; `state['value']` is not changed."""
    try:
        w = whole_book_inr(con, state["day"], root)
        state["whole_value"] = w["whole_inr"]
        state["us_book_inr"] = w["us_book_inr"]
        state["whole"] = w
    except Exception as e:
        state.setdefault("whole_value", state.get("value"))
        state["us_book_inr"] = 0.0
        state["whole"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    return state


def returns(con, root=None) -> Optional[dict]:
    """The whole book's time-weighted return since the rupee book's first marked day: each marked day's rupee value plus the sub-book in rupees on that day, the rupee book's flows less
    the transfers (a transfer is inside the book; only a top-up is outside money). None before two marked days."""
    rows = con.execute("SELECT day, value, flows FROM paper_days ORDER BY day").fetchall()
    if len(rows) < 2:
        return None
    vals, flows, prev = [], [], None
    for d, v, f in rows:
        vals.append(float(v) + _us_inr(con, d, root)["inr"])
        flows.append(float(f) - transfer.rupee_flows(con, prev, d))      # flows include the transfers as money out; take them back out
        prev = d
    g, peak, worst = 1.0, 1.0, 0.0
    for i in range(1, len(vals)):
        r = (vals[i] - flows[i]) / vals[i - 1] - 1 if vals[i - 1] > 0 else 0.0
        g *= 1 + r
        peak = max(peak, g)
        worst = min(worst, g / peak - 1)
    return {"since": str(rows[0][0]), "to": str(rows[-1][0]), "sessions": len(rows) - 1, "twr": g - 1, "worst_fall": worst, "label": RESTATED}
