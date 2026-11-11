"""The exit manager (S81 B4, A51): every position carries an exit plan from its entry, checked by code at every close and on live quotes, and every sale is scored after tax.

    plans      `open_plan` (called when a buy fills), `backfill_plans` (positions that have none, from their lots): target, stop, time stop, thesis-break kinds, the tax boundary
               (the day the oldest short-term lot turns long-term). Defaults by sleeve in `configs/core.toml [exits]` (his to change); the stop is sized from the stock's own volatility.
    checks     `check_close` (after the close: stop, target, time stop, thesis break, rail trims, exemption and loss harvesting, buy-backs), `check_quote` (a live quote against stop,
               target and time stop), `check_thesis` (events from the knowledge graph on a held name). Each returns ORDER DICTS and records an event, so an exit fires once and only once.
    tax        the 12-month guard (a winner within `guard_days` of turning long-term is not sold unless its stop fires); exemption harvesting and loss harvesting (`core/harvest.py`);
               the exemption and the rates come from the tax engine's dated rows (`core/tax_rows.py`), never from this file.
    scoring    every sale is scored after tax against holding the same shares over the same sessions, at 20 and 60 sessions (`exit_scores_s81`); `record` is the summary by kind.
    A60 (2026-11-10)  the swing sleeve is deleted (its study failed); exemption and loss harvesting act only in a sleeve whose switch (`harvest_core`, `harvest_longterm`) is on, and both
               are OFF until the narrower registered study (C4a) passes for that sleeve.

An order is `{"market","isin","side":"sell"|"buy","qty","fraction","kind":"stop"|"target"|"time"|"thesis"|"harvest"|"trim","reason","plan_id"}` plus `symbol`, `price`, `value`,
`est_tax`, `est_charges`, `event_id` for the caller's convenience. The reason is a sentence written by code with the numbers. Orders are paper orders: nothing here reaches a broker.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta
from typing import Dict, List, Optional

import numpy as np

from pflab.core import harvest as hv
from pflab.core import tax_rows as tr
from pflab.tax import rules

MARKET = "IN"
KINDS = ("target", "stop", "time", "thesis", "harvest", "trim")
SEVERITY_WORDS = {"low": 0.25, "minor": 0.25, "medium": 0.5, "moderate": 0.5, "high": 0.75, "major": 0.75, "severe": 0.9, "critical": 1.0}
REBUY_WAIT_DAYS = 10                    # a harvest sale whose buy-back has not happened in this many days: the plan is closed instead of waiting

DEFAULTS = {
    "on": True, "guard_days": 21, "guard_thesis_override": 0.75, "thesis_severity": 0.75,
    "thesis_kinds": ["fraud", "default", "auditor_resignation", "guidance_cut", "regulatory_action", "rating_downgrade", "results_miss", "promoter_selling", "pledge_invoked",
                     "delisting", "insolvency"],
    "trim_over_pts": 0.5, "trim_buffer_pts": 1.0, "min_trim_rupees": 2000.0, "stop_vol_window": 250, "fallback_vol": 0.30,
    "harvest_quarter_months": [1, 2, 3], "harvest_off_quarter_share": 0.34, "harvest_margin": 0.90, "harvest_min_gain": 5000.0, "harvest_cost_multiple": 3.0,
    "harvest_max_book_share": 0.05, "loss_harvest": True, "loss_min_saving": 1000.0, "rebuy": True,
    "harvest_core": False, "harvest_longterm": False,          # S82 C4: the registered study did not pass either arm: still OFF. A60: harvesting is OFF per sleeve until the narrower study (C4a) passes for that sleeve
    "core": {"stop": False, "target_reward": 0.0, "time_stop_days": 0, "thesis_break": False},
    "longterm": {"stop": False, "stop_sigmas": 2.0, "stop_horizon_days": 63, "stop_min_pct": 0.12, "stop_max_pct": 0.35, "target_reward": 0.0, "time_stop_days": 0, "thesis_break": True},
    "score": {"horizons": [20, 60], "min_n": 20},
}


def settings() -> dict:
    """`configs/core.toml [exits]` over the defaults here (an unreadable file leaves the defaults)."""
    out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULTS.items()}
    try:
        from pflab import _toml, core
        for k, v in (_toml.load(core.CONFIG).get("exits") or {}).items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k].update(v)
            else:
                out[k] = v
    except Exception:
        pass
    return out


# --- small helpers -------------------------------------------------------------------------------------------------------------------

def _id(con, table: str, col: str) -> int:
    from pflab.pm.store import next_id
    return next_id(con, table, col)


def _sleeve_of(con, isin: str, market: str = MARKET) -> str:
    try:
        from pflab.core import sleeves
        return sleeves.sleeve_of(con, isin, market)
    except Exception:
        pass
    from pflab.paper import book
    m = book.inst(con, isin)
    name = f"{m['name'] or ''} {m['symbol'] or ''}".lower()
    if (m["asset_class"] or "") == "etf" or any(w in name for w in ("etf", "bees", "gold", "nifty", "sensex")):
        return "core"
    return "longterm"


def _symbol(con, isin: str) -> str:
    from pflab.paper import book
    return book.inst(con, isin)["symbol"] or isin


def own_vol(con, isin: str, day: date, cfg: dict) -> float:
    """The stock's own annual volatility from its daily closes up to `day` (point in time); the stated fallback with too little history."""
    n = int(cfg["stop_vol_window"])
    rows = con.execute("SELECT close FROM prices WHERE isin=? AND date <= ? AND close > 0 ORDER BY date DESC LIMIT ?", [isin, day, n + 1]).fetchall()
    px = np.array([float(r[0]) for r in rows][::-1])
    if len(px) < 60:
        return float(cfg["fallback_vol"])
    r = np.diff(np.log(px))
    return float(max(np.std(r, ddof=1) * math.sqrt(252), 0.05))


def _levels(cfg: dict, sleeve: str, ref: float, vol: float, override: Optional[dict] = None) -> dict:
    sc = cfg.get(sleeve) if isinstance(cfg.get(sleeve), dict) else cfg["longterm"]
    stop = target = None
    dist = None
    if sc.get("stop"):
        dist = min(max(float(sc["stop_sigmas"]) * vol * math.sqrt(float(sc["stop_horizon_days"]) / 252.0), float(sc["stop_min_pct"])), float(sc["stop_max_pct"]))
        stop = ref * (1 - dist)
        if float(sc.get("target_reward") or 0) > 0:
            target = ref * (1 + float(sc["target_reward"]) * dist)
    ts = int(sc.get("time_stop_days") or 0) or None
    kinds = list(cfg["thesis_kinds"]) if sc.get("thesis_break") else []
    out = {"stop": stop, "target": target, "time_stop_days": ts, "thesis_break_kinds": kinds, "stop_pct": dist}
    for k, v in (override or {}).items():
        if k in out:
            out[k] = v
    return out


_COLS = ("plan_id", "market", "isin", "sleeve", "opened_on", "entry_price", "qty", "target", "stop", "time_stop_days", "thesis_break_kinds", "tax_boundary_date", "status",
         "closed_on", "closed_reason", "source", "vol", "note")


def _plans(con, market: Optional[str] = MARKET, statuses=("open",), isin: Optional[str] = None) -> List[dict]:
    q = "SELECT " + ", ".join(_COLS) + " FROM exit_plans_s81 WHERE status IN (" + ",".join("?" for _ in statuses) + ")"
    args: list = list(statuses)
    if market:
        q += " AND market=?"
        args.append(market)
    if isin:
        q += " AND isin=?"
        args.append(isin)
    out = []
    for r in con.execute(q + " ORDER BY plan_id", args).fetchall():
        d = dict(zip(_COLS, r))
        d["thesis_break_kinds"] = json.loads(d["thesis_break_kinds"] or "[]")
        out.append(d)
    return out


def get_plan(con, plan_id: int) -> Optional[dict]:
    r = con.execute("SELECT " + ", ".join(_COLS) + " FROM exit_plans_s81 WHERE plan_id=?", [plan_id]).fetchone()
    if not r:
        return None
    d = dict(zip(_COLS, r))
    d["thesis_break_kinds"] = json.loads(d["thesis_break_kinds"] or "[]")
    return d


def _boundary(con, isin: str, day: date) -> Optional[date]:
    """The day the oldest still-short-term lot turns long-term (None when every lot is long-term or there is none)."""
    ahead = [tr.long_term_from(l["acq"]) for l in tr.lots(con, isin)]
    ahead = [d for d in ahead if d > day]
    return min(ahead) if ahead else None


def _px(prices: Optional[dict], con, isin: str, day: date) -> Optional[float]:
    v = (prices or {}).get(isin)
    if isinstance(v, dict):
        v = v.get("ltp") or v.get("price") or v.get("close")
    if v is not None and float(v) > 0:
        return float(v)
    from pflab.paper import book
    r = book.close_on(con, isin, day)
    return r[1] if r else None


# --- plans ---------------------------------------------------------------------------------------------------------------------------

def open_plan(con, now: datetime, market: str, isin: str, sleeve: str, entry_price: float, qty: float, plan: Optional[dict] = None) -> int:
    """Write the exit plan for a position that has just been bought (the loop calls this when a buy fills). `plan` overrides any of stop, target, time_stop_days,
    thesis_break_kinds (the swing agent gives its own levels). A buy that adds to an open position updates its plan (weighted entry price, levels recomputed unless overridden);
    the buy-back of a harvest sale re-opens the plan it came from and keeps its levels (only the cost price is reset)."""
    from pflab.paper import book
    cfg = settings()
    day = now.date()
    pos = book.positions(con).get(isin, 0.0)
    existing = _plans(con, market, ("open", "rebuy_pending"), isin)
    ex = existing[-1] if existing else None
    harvest_buy = bool(con.execute("SELECT 1 FROM exit_events_s81 WHERE isin=? AND market=? AND side='buy' AND kind='harvest' AND status IN ('emitted','filled')",
                                   [isin, market]).fetchone())
    vol = own_vol(con, isin, day, cfg)
    if ex is not None:
        total = pos if pos > 0 else float(ex["qty"] or 0) + float(qty)
        if ex["status"] == "rebuy_pending":                                       # the harvest's buy-back: a new cost price, the old levels, the old opening date
            entry, lv, note = float(entry_price), {}, f"re-opened after the harvest sale: bought back at Rs {entry_price:,.2f}, cost price reset"
        elif harvest_buy:
            entry = (float(ex["entry_price"] or entry_price) * max(0.0, total - qty) + entry_price * qty) / max(total, 1e-9)
            lv, note = {}, f"bought back {qty:,.0f} after a harvest sale at Rs {entry_price:,.2f}; levels kept"
        else:
            entry = (float(ex["entry_price"] or entry_price) * max(0.0, total - qty) + entry_price * qty) / max(total, 1e-9)
            lv = _levels(cfg, ex["sleeve"], entry, vol, plan)
            note = f"added {qty:,.0f} at Rs {entry_price:,.2f}; levels recomputed from the average entry Rs {entry:,.2f}"
        sets = {"entry_price": entry, "qty": total, "status": "open", "tax_boundary_date": _boundary(con, isin, day), "updated_at": now, "note": note}
        if lv:
            sets.update({"stop": lv["stop"], "target": lv["target"], "time_stop_days": lv["time_stop_days"], "thesis_break_kinds": json.dumps(lv["thesis_break_kinds"])})
        con.execute("UPDATE exit_plans_s81 SET " + ", ".join(f"{k}=?" for k in sets) + " WHERE plan_id=?", list(sets.values()) + [ex["plan_id"]])
        return int(ex["plan_id"])
    lv = _levels(cfg, sleeve, float(entry_price), vol, plan)
    pid = _id(con, "exit_plans_s81", "plan_id")
    note = ("opened at entry: " + (f"stop Rs {lv['stop']:,.2f} ({lv['stop_pct']:.0%} under the entry, from its own volatility of {vol:.0%} a year)" if lv["stop"] else "no stop (rebalance only)")
            + (f", target Rs {lv['target']:,.2f}" if lv["target"] else "") + (f", time stop {lv['time_stop_days']} days" if lv["time_stop_days"] else "")
            + (f", thesis break on {len(lv['thesis_break_kinds'])} kinds of event" if lv["thesis_break_kinds"] else ""))
    con.execute("INSERT INTO exit_plans_s81 (plan_id, market, isin, sleeve, opened_on, entry_price, qty, target, stop, time_stop_days, thesis_break_kinds, tax_boundary_date, status, "
                "source, vol, note, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [pid, market, isin, sleeve, day, float(entry_price), float(pos if pos > 0 else qty), lv["target"], lv["stop"], lv["time_stop_days"], json.dumps(lv["thesis_break_kinds"]),
                 _boundary(con, isin, day), "open", "entry", vol, note, now, now])
    return pid


def backfill_plans(con, day: date, market: str = MARKET, now: Optional[datetime] = None) -> List[int]:
    """A plan for every position that has none, from its lots: the entry price is the lots' average cost, the opening date the oldest lot's, the levels are set from the price
    on `day` (the stop of a holding that has already run is measured from where it is, not from a cost far below) and labelled as a backfill."""
    from pflab.paper import book
    cfg = settings()
    now = now or datetime.combine(day, time(15, 45))
    have = {p["isin"] for p in _plans(con, market, ("open", "rebuy_pending"))}
    made = []
    for isin, qty in sorted(book.positions(con).items()):
        if isin in have or qty <= 1e-9:
            continue
        lots = tr.lots(con, isin)
        if not lots:
            continue
        tq = sum(l["qty"] for l in lots)
        avg = sum(l["qty"] * l["cpu"] for l in lots) / tq
        px = book.close_on(con, isin, day)
        ref = px[1] if px else avg
        sleeve = _sleeve_of(con, isin, market)
        vol = own_vol(con, isin, day, cfg)
        lv = _levels(cfg, sleeve, ref, vol)
        pid = _id(con, "exit_plans_s81", "plan_id")
        note = ("backfilled from the lots: " + (f"stop Rs {lv['stop']:,.2f} ({lv['stop_pct']:.0%} under the price of {day}, own volatility {vol:.0%} a year)" if lv["stop"] else "no stop (rebalance only)")
                + (f", target Rs {lv['target']:,.2f}" if lv["target"] else "") + (f", time stop {lv['time_stop_days']} days" if lv["time_stop_days"] else ""))
        con.execute("INSERT INTO exit_plans_s81 (plan_id, market, isin, sleeve, opened_on, entry_price, qty, target, stop, time_stop_days, thesis_break_kinds, tax_boundary_date, status, "
                    "source, vol, note, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [pid, market, isin, sleeve, min(l["acq"] for l in lots), avg, tq, lv["target"], lv["stop"], lv["time_stop_days"], json.dumps(lv["thesis_break_kinds"]),
                     _boundary(con, isin, day), "open", "backfill", vol, note, now, now])
        made.append(pid)
    return made


# --- events, fills and the state of a plan -------------------------------------------------------------------------------------------

def _emit(con, now: datetime, plan: Optional[dict], market: str, isin: str, side: str, kind: str, qty: float, fraction: Optional[float], price: float, reason: str,
          detail: Optional[dict] = None, ref: Optional[str] = None, link: Optional[int] = None, status: str = "emitted") -> int:
    eid = _id(con, "exit_events_s81", "event_id")
    con.execute("INSERT INTO exit_events_s81 (event_id, plan_id, market, isin, side, kind, day, emitted_at, qty, fraction, price, reason, status, link_event_id, ref, detail_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [eid, plan["plan_id"] if plan else None, market, isin, side, kind, now.date(), now, qty, fraction, price, reason[:1500], status, link, ref,
                 json.dumps(detail or {}, default=str)])
    return eid


def _order(con, plan: Optional[dict], market: str, isin: str, side: str, kind: str, qty: float, held: float, price: float, reason: str, event_id: int, est: Optional[dict] = None) -> dict:
    return {"market": market, "isin": isin, "side": side, "qty": float(qty), "fraction": (min(1.0, qty / held) if side == "sell" and held > 0 else None), "kind": kind, "reason": reason,
            "plan_id": plan["plan_id"] if plan else None, "symbol": _symbol(con, isin), "price": price, "value": qty * price, "est_tax": (est or {}).get("tax"),
            "est_charges": (est or {}).get("charges"), "event_id": event_id}


def _open_sides(con, isin: str) -> set:
    return {s for (s,) in con.execute("SELECT DISTINCT side FROM paper_orders WHERE isin=? AND status='open'", [isin]).fetchall()}


def _pending_sells(con, isin: str, market: str) -> List[str]:
    return [k for (k,) in con.execute("SELECT kind FROM exit_events_s81 WHERE isin=? AND market=? AND side='sell' AND status='emitted'", [isin, market]).fetchall()]


def reconcile(con, day: date, market: str = MARKET, now: Optional[datetime] = None) -> dict:
    """Match the emitted events with the fills (and void those nothing came of), close the plans of positions that are gone, re-open a plan whose harvest buy-back filled, give up on
    a buy-back that never happened, adopt the sales of planned names made outside the manager (labelled rebalance), refresh qty and the tax boundary of the open plans."""
    from pflab.paper import book
    now = now or datetime.combine(day, time(15, 45))
    out = {"filled": 0, "voided": 0, "closed": 0, "adopted": 0}
    for eid, isin, side, emitted_day, plan_id, kind, emitted_at in con.execute("SELECT event_id, isin, side, day, plan_id, kind, emitted_at FROM exit_events_s81 WHERE market=? AND status='emitted' ORDER BY event_id", [market]).fetchall():
        after_close = emitted_at is not None and emitted_at.time() >= book.CLOSE_AT        # an order made after the close fills at a LATER session, never the one it was made on
        t = con.execute("SELECT trade_id, day FROM paper_trades WHERE isin=? AND side=? AND day " + (">" if after_close else ">=") + " ? AND trade_id NOT IN "
                        "(SELECT trade_id FROM exit_events_s81 WHERE trade_id IS NOT NULL) ORDER BY trade_id LIMIT 1", [isin, side, emitted_day]).fetchone()
        if t:
            con.execute("UPDATE exit_events_s81 SET status='filled', trade_id=?, filled_on=? WHERE event_id=?", [t[0], t[1], eid])
            out["filled"] += 1
        elif emitted_day < day and side not in _open_sides(con, isin):
            con.execute("UPDATE exit_events_s81 SET status='void' WHERE event_id=?", [eid])
            out["voided"] += 1
    # sales of planned names made by someone else (the rebalance): kept in the record so they are scored like any sale
    planned = {p["isin"]: p for p in _plans(con, market, ("open", "rebuy_pending", "closed"))}
    for tid, d, isin in con.execute("SELECT trade_id, day, isin FROM paper_trades WHERE side='sell' AND trade_id NOT IN (SELECT trade_id FROM exit_events_s81 WHERE trade_id IS NOT NULL) "
                                    "ORDER BY trade_id").fetchall():
        p = planned.get(isin)
        if p is None or p["status"] == "closed" and p["closed_on"] and d > p["closed_on"]:
            continue
        created = con.execute("SELECT created_at FROM exit_plans_s81 WHERE plan_id=?", [p["plan_id"]]).fetchone()[0]
        if created is not None and d < created.date():
            continue
        tr_row = con.execute("SELECT qty, price, realised, detail_json FROM paper_trades WHERE trade_id=?", [tid]).fetchone()
        eid = _emit(con, datetime.combine(d, time(15, 30)), p, market, isin, "sell", "rebalance", float(tr_row[0]), None, float(tr_row[1]),
                    f"a sale made by the rebalance, not by an exit rule ({tr_row[0]:,.0f} shares at Rs {tr_row[1]:,.2f})", {"adopted": True, "gains": (json.loads(tr_row[3] or "{}").get("gains") or {})},
                    status="filled")
        con.execute("UPDATE exit_events_s81 SET trade_id=?, filled_on=? WHERE event_id=?", [tid, d, eid])
        out["adopted"] += 1
    pos = book.positions(con)
    for p in _plans(con, market, ("open", "rebuy_pending")):
        q = pos.get(p["isin"], 0.0)
        last = con.execute("SELECT kind, side, status, filled_on, event_id FROM exit_events_s81 WHERE plan_id=? AND status='filled' ORDER BY event_id DESC LIMIT 1", [p["plan_id"]]).fetchone()
        if p["status"] == "rebuy_pending":
            if q > 1e-9:                                                          # the buy-back filled: the plan is live again, its levels kept, the cost price new
                lots = tr.lots(con, p["isin"])
                avg = sum(l["qty"] * l["cpu"] for l in lots) / sum(l["qty"] for l in lots)
                con.execute("UPDATE exit_plans_s81 SET status='open', qty=?, entry_price=?, tax_boundary_date=?, updated_at=?, note=? WHERE plan_id=?",
                            [q, avg, _boundary(con, p["isin"], day), now, f"re-opened after the harvest sale: bought back, cost price reset to Rs {avg:,.2f}", p["plan_id"]])
            else:
                sold = con.execute("SELECT max(filled_on) FROM exit_events_s81 WHERE plan_id=? AND kind='harvest' AND side='sell' AND status='filled'", [p["plan_id"]]).fetchone()[0]
                waiting = con.execute("SELECT 1 FROM exit_events_s81 WHERE plan_id=? AND kind='harvest' AND side='buy' AND status='emitted'", [p["plan_id"]]).fetchone()
                if not waiting and sold is not None and (day - sold).days > REBUY_WAIT_DAYS:
                    con.execute("UPDATE exit_plans_s81 SET status='closed', closed_on=?, closed_reason=?, updated_at=? WHERE plan_id=?",
                                [day, f"harvest sale of {sold}: not bought back within {REBUY_WAIT_DAYS} days", now, p["plan_id"]])
                    out["closed"] += 1
            continue
        if q <= 1e-9:
            why = "position gone (sold outside the exit manager)"
            status = "closed"
            if last and last[1] == "sell":
                why = f"{last[0]}: sold on {last[3]}"
                if last[0] == "harvest" and settings().get("rebuy", True):
                    status = "rebuy_pending"
            con.execute("UPDATE exit_plans_s81 SET status=?, qty=0, closed_on=?, closed_reason=?, updated_at=? WHERE plan_id=?",
                        [status, day if status == "closed" else None, why if status == "closed" else None, now, p["plan_id"]])
            out["closed"] += 1 if status == "closed" else 0
        else:
            con.execute("UPDATE exit_plans_s81 SET qty=?, tax_boundary_date=?, updated_at=? WHERE plan_id=?", [q, _boundary(con, p["isin"], day), now, p["plan_id"]])
    return out


# --- the 12-month guard and the cost of a sale ---------------------------------------------------------------------------------------

def _estimate(con, isin: str, qty: float, price: float, day: date) -> dict:
    """Charges and the tax a sale of `qty` now would add (engine rows); `tax` None with the reason when no row covers the date."""
    from pflab.paper import book
    ac = book.inst(con, isin)["asset_class"]
    taken = tr.consume(tr.lots(con, isin), qty)
    fee = book._charges(ac, "sell", qty * price)
    gains = tr.sale_gains(taken, price, fee, ac, day)
    out = {"charges": round(fee, 2), "gain": round(sum(gains.values()), 2), "gains": gains, "taken": taken, "asset_class": ac, "tax": None}
    try:
        base = tr.year_gains(con, day)
        out["tax"] = round(max(0.0, tr.tax_of(tr.add(base, gains), day) - tr.tax_of(base, day)), 2)
    except rules.RuleGap as e:
        out["tax_note"] = f"tax not estimated ({e})"
    return out


def _cost_text(est: dict) -> str:
    t = f"Rs {est['tax']:,.0f}" if est.get("tax") is not None else "not estimated (no tax row)"
    return f"estimated charges Rs {est['charges']:,.0f} and tax {t}"


def guard_hold(con, day: date, isin: str, qty: float, price: float, cfg: dict, est: Optional[dict] = None) -> Optional[str]:
    """The 12-month guard: a sentence when selling `qty` now should wait (a lot in gain turns long-term within `guard_days` and the engine's rates say waiting saves tax), else None."""
    est = est or _estimate(con, isin, qty, price, day)
    from pflab.paper import book
    window = int(cfg["guard_days"])
    for t in est["taken"]:
        lt = tr.long_term_from(t["acq"])
        if lt > day and (lt - day).days <= window and price > t["cpu"]:
            ac = est["asset_class"]
            try:
                now_tax = est["tax"] if est["tax"] is not None else None
                waited = tr.liquidation_tax(con, est["taken"], price, ac, lt)
                if now_tax is not None and waited >= now_tax - 1e-6:
                    continue
                saves = f"selling at the same price after that date would cost Rs {waited:,.0f} of tax instead of Rs {now_tax:,.0f}" if now_tax is not None else "waiting turns the gain long-term"
            except rules.RuleGap:
                saves = "waiting turns the gain long-term"
            return (f"held back by the 12-month guard: {t['take']:,.0f} shares bought {t['acq']:%d %b %Y} turn long-term on {lt:%d %b %Y}, {(lt - day).days} days away "
                    f"(guard window {window} days); {saves}")
    return None


def _guarded(con, now: datetime, plan: dict, market: str, isin: str, kind: str, price: float, why: str) -> None:
    """Record, once a day per plan and kind, that a sale was held back (so the screens can say so)."""
    if not con.execute("SELECT 1 FROM exit_events_s81 WHERE plan_id=? AND kind=? AND status='guarded' AND day=?", [plan["plan_id"], kind, now.date()]).fetchone():
        _emit(con, now, plan, market, isin, "sell", kind, 0.0, None, price, why, status="guarded")


def _sell(con, now: datetime, day: date, plan: dict, isin: str, kind: str, qty: float, held: float, price: float, what: str, cfg: dict, *, live: bool = False, override_guard: bool = False,
          ref: Optional[str] = None, extra: Optional[dict] = None, orders_sides: Optional[set] = None) -> Optional[dict]:
    """The one place a sale order is made: pending, same-session buy, same-day round trip (live) and the 12-month guard are checked, the event is recorded, the order returned."""
    market = plan["market"]
    pend = _pending_sells(con, isin, market)
    if pend and not (kind == "stop" and "stop" not in pend):
        return None
    if "buy" in _open_sides(con, isin):                                          # a buy and a sell of the same name in one session: the speculative-income trap (A54)
        _guarded(con, now, plan, market, isin, kind, price, f"{kind} not placed: an order to buy {_symbol(con, isin)} is open, and a buy and a sell of one name in one session would be a same-day round trip")
        return None
    qty = min(float(qty), held)
    if qty <= 1e-9:
        return None
    est = _estimate(con, isin, qty, price, day)
    if live and kind != "stop" and any(t["acq"] == day for t in est["taken"]):    # shares bought today are not sold today unless the stop fires
        _guarded(con, now, plan, market, isin, kind, price, f"{kind} waits for the next session: part of the shares sold would be bought today (no same-day round trip; only a stop sells them today)")
        return None
    if kind != "stop" and not override_guard:
        why = guard_hold(con, day, isin, qty, price, cfg, est)
        if why:
            _guarded(con, now, plan, market, isin, kind, price, f"{kind} ({what}): {why}")
            return None
    reason = f"{what} Selling {qty:,.0f} of {held:,.0f} shares (about Rs {qty * price:,.0f}); {_cost_text(est)}; the gain on these lots is Rs {est['gain']:,.0f}."
    detail = {"lots": hv._lot_json(est["taken"]), "est_tax": est["tax"], "est_charges": est["charges"], "gain": est["gain"], "gains": est["gains"], **(extra or {})}
    eid = _emit(con, now, plan, market, isin, "sell", kind, qty, min(1.0, qty / held), price, reason, detail, ref=ref)
    return _order(con, plan, market, isin, "sell", kind, qty, held, price, reason, eid, est)


# --- the checks ----------------------------------------------------------------------------------------------------------------------

def _severity(v) -> float:
    if v is None:
        return 0.0
    if isinstance(v, str):
        try:
            v = float(v)
        except ValueError:
            return SEVERITY_WORDS.get(v.strip().lower(), 0.0)
    v = float(v)
    return v if v <= 1.0 else min(1.0, v / 5.0)


def _ts_date(ts) -> Optional[date]:
    if isinstance(ts, datetime):
        return ts.date()
    if isinstance(ts, date):
        return ts
    try:
        return datetime.fromisoformat(str(ts)).date()
    except Exception:
        return None


def check_thesis(con, day: date, events: List[dict], market: str = MARKET, prices: Optional[dict] = None, live: bool = False, now: Optional[datetime] = None) -> List[dict]:
    """Sell orders for the held names whose thesis an event breaks. `events` is `kg.events.material_events`'s shape (`isin, kind, severity, ts, source, ref, text`); an event without a
    dissemination time, dated after `day` or before the plan opened, is ignored (point in time). A plan with no thesis-break kinds (the core) ignores events."""
    from pflab.paper import book
    cfg = settings()
    if not cfg["on"] or not events:
        return []
    now = now or datetime.combine(day, time(15, 45))
    pos = book.positions(con)
    plans = {p["isin"]: p for p in _plans(con, market)}
    orders = []
    for ev in sorted(events, key=lambda e: str(e.get("ts"))):
        isin = ev.get("isin")
        p = plans.get(isin)
        if p is None or not p["thesis_break_kinds"] or pos.get(isin, 0.0) <= 1e-9 or ev.get("ts") is None:
            continue
        d = _ts_date(ev["ts"])
        if d is None or d > day or d < p["opened_on"]:
            continue
        sev = _severity(ev.get("severity"))
        kind_hit = str(ev.get("kind")) in p["thesis_break_kinds"]
        if not ((kind_hit and sev >= 0.5) or sev >= float(cfg["thesis_severity"])):
            continue
        ref = str(ev.get("ref") or f"{ev.get('kind')}|{ev['ts']}|{ev.get('source')}")
        if con.execute("SELECT 1 FROM exit_events_s81 WHERE plan_id=? AND ref=? AND status <> 'void'", [p["plan_id"], ref]).fetchone():
            continue
        px = _px(prices, con, isin, day)
        if px is None:
            continue
        what = (f"Thesis break: {ev.get('kind')} event (severity {sev:.2f}) on {d:%d %b %Y} from {ev.get('source') or 'the filings'}: {str(ev.get('text') or '')[:160]}. "
                f"Position bought {p['opened_on']:%d %b %Y} at an average Rs {float(p['entry_price'] or 0):,.2f}, now Rs {px:,.2f} ({(px / float(p['entry_price']) - 1) * 100 if p['entry_price'] else 0:+.1f}%).")
        o = _sell(con, now, day, p, isin, "thesis", pos[isin], pos[isin], px, what, cfg, live=live, override_guard=sev >= float(cfg["guard_thesis_override"]), ref=ref,
                  extra={"event": {k: str(v) for k, v in ev.items()}})
        if o:
            orders.append(o)
    return orders


def _level_checks(con, now: datetime, day: date, plan: dict, price: float, held: float, cfg: dict, live: bool) -> Optional[dict]:
    """Stop, then target, then time stop, for one plan (the first that fires)."""
    isin = plan["isin"]
    ent = float(plan["entry_price"] or 0)
    gain_txt = f"{(price / ent - 1) * 100:+.1f}% on the average entry Rs {ent:,.2f}" if ent else "entry not on record"
    if plan["stop"] is not None and price <= float(plan["stop"]):
        what = f"Stop hit: Rs {price:,.2f} is at or below the stop Rs {float(plan['stop']):,.2f} (set from the stock's own volatility of {float(plan['vol'] or 0):.0%} a year); {gain_txt}."
        return _sell(con, now, day, plan, isin, "stop", held, held, price, what, cfg, live=live)
    if plan["target"] is not None and price >= float(plan["target"]):
        what = f"Target reached: Rs {price:,.2f} is at or above the target Rs {float(plan['target']):,.2f}; {gain_txt}."
        return _sell(con, now, day, plan, isin, "target", held, held, price, what, cfg, live=live)
    if plan["time_stop_days"]:
        age = (day - plan["opened_on"]).days
        if age >= int(plan["time_stop_days"]):
            what = f"Time stop: held {age} days, the plan allowed {int(plan['time_stop_days'])}; {gain_txt}."
            return _sell(con, now, day, plan, isin, "time", held, held, price, what, cfg, live=live)
    return None


def check_quote(con, now: datetime, quotes: dict, state: Optional[dict] = None, market: str = MARKET) -> List[dict]:
    """The session checks on live quotes (`quotes`: {isin: ltp} or {isin: {"ltp": ...}}): stop, target and time stop of every open plan. A plan opened or added to today waits for
    the next session unless its stop fires (no same-day round trip)."""
    from pflab.paper import book
    cfg = settings()
    if not cfg["on"]:
        return []
    day = now.date()
    reconcile(con, day, market, now)
    pos = book.positions(con)
    out = []
    for p in _plans(con, market):
        isin, held = p["isin"], pos.get(p["isin"], 0.0)
        px = _px(quotes, con, isin, day) if isin in (quotes or {}) else None
        if px is None or held <= 1e-9:
            continue
        o = _level_checks(con, now, day, p, px, held, cfg, live=True)
        if o:
            out.append(o)
    return out


def _rows(con, day: date, state: Optional[dict], prices: Optional[dict]) -> tuple:
    from pflab.paper import book
    if state and state.get("rows"):
        return state["rows"], float(state["value"]), bool((state.get("breaker") or {}).get("on"))
    h = book.holdings(con, day)
    rows = [{**r, "buyable": (r["asset_class"] or "") in book.BUYABLE and r["price"] is not None, "value": r["value"] or 0.0} for r in h["rows"]]
    try:
        from pflab.paper import cadence
        br = bool(cadence.breaker(con)["on"])
    except Exception:
        br = False
    return rows, float(h["value"]), br


def _trims(con, now: datetime, day: date, rows: List[dict], total: float, plans: Dict[str, dict], used: set, cfg: dict) -> List[dict]:
    """Names and sectors over the position rails: sold down to the rail less a buffer, the cheapest tax first, the guard respected."""
    from pflab.paper import book, rails as hard
    out: List[dict] = []
    if total <= 0:
        return out
    over, buf, floor = float(cfg["trim_over_pts"]) / 100.0, float(cfg["trim_buffer_pts"]) / 100.0, float(cfg["min_trim_rupees"])
    value = {r["isin"]: float(r["value"] or 0.0) for r in rows}
    price = {r["isin"]: float(r["price"]) for r in rows if r.get("price")}
    meta = {r["isin"]: r for r in rows}

    def trim(isin: str, rupees: float, what: str) -> float:
        p = plans.get(isin)
        if p is None or isin in used or isin not in price:
            return 0.0
        held = float(meta[isin]["qty"])
        qty = float(math.floor(min(rupees, value[isin]) / price[isin]))
        if qty < 1 or qty * price[isin] < floor:
            return 0.0
        o = _sell(con, now, day, p, isin, "trim", qty, held, price[isin], what, cfg)
        if not o:
            return 0.0
        used.add(isin)
        out.append(o)
        value[isin] -= qty * price[isin]
        return qty * price[isin]

    for isin in sorted(value, key=lambda i: -value[i]):                              # one company / one ETF
        ac = meta[isin]["asset_class"] or ""
        if ac not in book.BUYABLE:
            continue
        cap = hard.limit_of(ac, meta[isin].get("symbol"))
        w = value[isin] / total
        if w > cap + over:
            target = cap - buf
            what = f"Rail trim: {meta[isin]['symbol']} is {w:.1%} of the book, over its {cap:.0%} limit; bringing it down to {target:.1%}."
            trim(isin, (w - target) * total, what)
    sectors: Dict[str, List[str]] = {}
    for isin, r in meta.items():
        if r.get("sector") and (r["asset_class"] or "") != "etf":
            sectors.setdefault(r["sector"], []).append(isin)
    for s, members in sorted(sectors.items()):
        ws = sum(value[i] for i in members) / total
        if ws <= hard.MAX_SECTOR + over:
            continue
        need = (ws - (hard.MAX_SECTOR - buf)) * total
        ranked = []
        for i in members:
            if i in used or i not in price or (meta[i]["asset_class"] or "") not in book.BUYABLE:
                continue
            e = _estimate(con, i, float(meta[i]["qty"]), price[i], day)
            ranked.append(((e["tax"] or 0.0) / max(1.0, value[i]), i))
        for _c, i in sorted(ranked):
            if need <= 0:
                break
            what = (f"Sector trim: the {s} sector is {ws:.1%} of the book, over its {hard.MAX_SECTOR:.0%} limit; selling {meta[i]['symbol']} (the cheapest tax of its holdings in the sector) "
                    f"to bring the sector to {hard.MAX_SECTOR - buf:.1%}.")
            need -= trim(i, need, what)
    return out


def _spec_order(con, now: datetime, day: date, spec: dict, market: str, kind_text: str, cfg: dict) -> Optional[dict]:
    from pflab.paper import book
    pos = book.positions(con)
    isin, qty = spec["isin"], spec["qty"]
    held = pos.get(isin, 0.0)
    pend = _pending_sells(con, isin, market)
    if pend or "buy" in _open_sides(con, isin) or held <= 1e-9:
        return None
    qty = min(qty, held)
    est = _estimate(con, isin, qty, spec["price"], day)
    detail = {"lots": spec["lots"], "gain": spec["gain"], "gains": spec["gains"], "sub": spec["sub"], "est_tax": est["tax"], "est_charges": est["charges"],
              "gain_lt": spec["gains"].get("lt_eq", 0.0) if spec["sub"] == "exemption" else 0.0, "roundtrip": spec["roundtrip"]}
    reason = spec["reason"]
    eid = _emit(con, now, spec["plan"], market, isin, "sell", "harvest", qty, min(1.0, qty / held), spec["price"], reason, detail)
    return _order(con, spec["plan"], market, isin, "sell", "harvest", qty, held, spec["price"], reason, eid, est)


def _pending_harvest_gain(con, day: date, market: str) -> float:
    start = date(tr.fy_start_year(day), 4, 1)
    tot = 0.0
    for (dj,) in con.execute("SELECT detail_json FROM exit_events_s81 WHERE market=? AND kind='harvest' AND side='sell' AND status='emitted' AND day >= ?", [market, start]).fetchall():
        tot += float((json.loads(dj or "{}")).get("gain_lt") or 0.0)
    return tot


def _harvests(con, now: datetime, day: date, rows: List[dict], total: float, plans: Dict[str, dict], used: set, prices: Optional[dict], cfg: dict, breaker: bool, market: str) -> List[dict]:
    from pflab.paper import book
    out: List[dict] = []
    cands = []
    live = {s for s in ("core", "longterm") if cfg.get(f"harvest_{s}", False)}          # A60: harvesting acts only in a sleeve whose study passed
    if not live:
        return out
    for r in rows:
        isin = r["isin"]
        p = plans.get(isin)
        if p is None or isin in used or p["sleeve"] not in live or (r["asset_class"] or "") not in book.BUYABLE:
            continue
        px = _px(prices, con, isin, day)
        if px is None or _open_sides(con, isin) or _pending_sells(con, isin, market):
            continue
        cands.append({"plan": p, "isin": isin, "symbol": r["symbol"], "asset_class": r["asset_class"], "price": px})
    ex_specs, notes, work = hv.exemption_specs(con, day, cfg, cands, total, _pending_harvest_gain(con, day, market), breaker)
    base = tr.year_gains(con, day)
    for s in ex_specs:
        base = tr.add(base, s["gains"])
    taken = {s["isin"] for s in ex_specs}
    loss_specs, lnotes = hv.loss_specs(con, day, cfg, [c for c in cands if c["isin"] not in taken], base) if not breaker else ([], ["no loss harvesting while the circuit breaker is on"])
    notes += lnotes
    rb = " The same shares are bought back at the next session's close, never the day of the sale (a buy and a sell of one name on one day is speculative income), so the cost price resets."
    for s in ex_specs:
        w = s["work"]
        s["reason"] = (f"Exemption harvest: {s['qty']:,.0f} shares of {s['symbol']} (bought over 12 months ago) show a long-term gain of Rs {s['gain']:,.0f}. The yearly long-term exemption for FY"
                       f"{w['fy'] - 1}-{str(w['fy'])[2:]} is Rs {w['exemption']:,.0f}, Rs {w['used']:,.0f} of it used, so up to Rs {w['room']:,.0f} may still be booked at this close"
                       f"{'' if w['in_last_quarter'] else ' (outside the last quarter only ' + format(float(cfg['harvest_off_quarter_share']), '.0%') + ' of the exemption is booked)'}; extra tax now Rs {s['extra_tax_now']:,.0f}, "
                       f"later tax saved about Rs {s['tax_saved_later']:,.0f} (12.5% of the gain, if it would otherwise be taxed); round-trip charges Rs {s['roundtrip']:,.0f}." + rb)
        o = _spec_order(con, now, day, s, market, "exemption", cfg)
        if o:
            used.add(s["isin"])
            out.append(o)
    for s in loss_specs:
        s["reason"] = (f"Loss harvest: selling {s['qty']:,.0f} shares of {s['symbol']} realises a loss of Rs {-s['gain']:,.0f}, which cuts this year's tax from Rs {s['tax_before']:,.0f} to "
                       f"Rs {s['tax_after']:,.0f} (saves Rs {s['saving']:,.0f}; the set-off is the tax engine's); round-trip charges Rs {s['roundtrip']:,.0f}." + rb)
        o = _spec_order(con, now, day, s, market, "loss", cfg)
        if o:
            used.add(s["isin"])
            out.append(o)
    if notes:
        con.execute("DELETE FROM exit_events_s81 WHERE kind='harvest' AND status='note' AND day=? AND market=?", [day, market])
        _emit(con, now, None, market, "-", "sell", "harvest", 0.0, None, 0.0, "; ".join(notes)[:1400], status="note")
    return out


def _rebuys(con, now: datetime, day: date, prices: Optional[dict], cfg: dict, breaker: bool, market: str) -> List[dict]:
    out = []
    specs, _notes = hv.rebuy_specs(con, day, cfg, breaker)
    for s in specs:
        isin = s["isin"]
        if "sell" in _open_sides(con, isin):
            continue
        px = _px(prices, con, isin, day)
        plans = _plans(con, market, ("open", "rebuy_pending"), isin)
        p = plans[-1] if plans else None
        if px is None or p is None:
            continue
        reason = (f"Buy-back after the harvest sale of {s['qty']:,.0f} shares of {_symbol(con, isin)} (sold at the close of {s['sold_on']:%d %b %Y}): placed now, so it fills at the next session's close, "
                  f"a different session from the sale (no same-day round trip). The cost price resets to the buy-back price; the exit plan's levels are kept.")
        eid = _emit(con, now, p, market, isin, "buy", "harvest", s["qty"], None, px, reason, {"sold_on": str(s["sold_on"])}, link=s["sale_event"])
        o = _order(con, p, market, isin, "buy", "harvest", s["qty"], 0.0, px, reason, eid)
        out.append(o)
    return out


def check_close(con, day: date, prices: Optional[dict], state: Optional[dict], market: str = MARKET, events: Optional[List[dict]] = None, now: Optional[datetime] = None) -> List[dict]:
    """The post-close checks for the close of `day`. In this order: plans backfilled and fills reconciled; thesis breaks (`events`, optional); stops, targets and time stops; rail trims;
    exemption and loss harvesting; buy-backs of earlier harvests; due sales scored. One order per name per close, and every exit once and only once (an event is recorded)."""
    from pflab.paper import book
    cfg = settings()
    if not cfg["on"]:
        return []
    now = now or datetime.combine(day, time(15, 45))
    backfill_plans(con, day, market, now)
    reconcile(con, day, market, now)
    rows, total, breaker = _rows(con, day, state, prices)
    pos = book.positions(con)
    plans = {p["isin"]: p for p in _plans(con, market)}
    orders: List[dict] = []
    used: set = set()
    for o in check_thesis(con, day, events or [], market, prices, now=now):
        orders.append(o)
        used.add(o["isin"])
    for isin, p in plans.items():
        held = pos.get(isin, 0.0)
        if isin in used or held <= 1e-9:
            continue
        px = _px(prices, con, isin, day)
        if px is None:
            continue
        o = _level_checks(con, now, day, p, px, held, cfg, live=False)
        if o:
            orders.append(o)
            used.add(isin)
    for o in _trims(con, now, day, rows, total, plans, used, cfg):
        orders.append(o)
    orders += _harvests(con, now, day, rows, total, plans, used, prices, cfg, breaker, market)
    orders += _rebuys(con, now, day, prices, cfg, breaker, market)
    score_due(con, day, now)
    return orders


# --- scoring -------------------------------------------------------------------------------------------------------------------------

def _lots_of(ev_detail: dict, trade: tuple, meta: dict) -> List[dict]:
    """The lots a sale consumed (recorded when the order was made); for a sale made outside the manager, one lot reconstructed from the trade (an estimate)."""
    if ev_detail.get("lots"):
        return [{"acq": date.fromisoformat(l["acq"]), "take": float(l["take"]), "cpu": float(l["cpu"]), "tax_class": l["tax_class"]} for l in ev_detail["lots"]]
    day, qty, price, realised, dj = trade
    gains = (json.loads(dj or "{}").get("gains") or {})
    dom = max(gains, key=lambda k: abs(gains[k])) if gains else "st_eq"
    acq = day - timedelta(days=400 if dom.startswith("lt") else 30)
    cpu = price - (float(realised or 0.0) / qty if qty else 0.0)
    return [{"acq": acq, "take": float(qty), "cpu": float(cpu), "tax_class": meta["tax_class"]}]


def _score_one(con, ev: tuple, h: int, T: date, tpx: float) -> dict:
    from pflab.paper import book, manager
    eid, plan_id, market, isin, kind, trade_id, filled_on, dj = ev
    t = con.execute("SELECT day, qty, price, charges, tax, realised, detail_json FROM paper_trades WHERE trade_id=?", [trade_id]).fetchone()
    day, qty, price, charges, tax, realised, tdj = t
    meta = book.inst(con, isin)
    ac = meta["asset_class"]
    detail = json.loads(dj or "{}")
    lots = _lots_of(detail, (day, qty, price, realised, tdj), meta)
    cash_growth = 1 + manager.CASH_PA * (T - day).days / 365.0
    after_tax = qty * price - float(charges or 0.0) - float(tax or 0.0)
    # the world without this sale: the year's gains without it (when T is in the same year), then liquidated at T
    base = tr.year_gains(con, T)
    if tr.fy_start_year(T) == tr.fy_start_year(day):
        base = tr.add(base, {k: -v for k, v in (json.loads(tdj or "{}").get("gains") or {}).items()})
    try:
        hold_tax = tr.liquidation_tax(con, lots, tpx, ac, T, base=base)
        tax_note = "engine rows"
    except rules.RuleGap as e:
        hold_tax, tax_note = float(tax or 0.0) * (tpx / price if price else 1.0), f"estimate: no tax row ({e})"
    hold_value = qty * tpx - book._charges(ac, "sell", qty * tpx) - hold_tax
    sale_value = after_tax * cash_growth
    how = "sale proceeds after tax and charges, earning cash"
    if kind == "harvest":
        b = con.execute("SELECT trade_id FROM exit_events_s81 WHERE link_event_id=? AND status='filled' AND trade_id IS NOT NULL", [eid]).fetchone()
        if b:
            bt = con.execute("SELECT day, qty, price, charges FROM paper_trades WHERE trade_id=?", [b[0]]).fetchone()
            bday, bq, bpx, bfee = bt
            newlot = [{"acq": bday, "take": float(bq), "cpu": (bq * bpx + float(bfee or 0.0)) / bq, "tax_class": meta["tax_class"]}]
            new_tax = tr.liquidation_tax(con, newlot, tpx, ac, T, base=base) if tax_note == "engine rows" else 0.0
            leftover = after_tax - (bq * bpx + float(bfee or 0.0))
            sale_value = bq * tpx - book._charges(ac, "sell", bq * tpx) - new_tax + leftover * cash_growth
            how = "the shares bought back (new cost price) valued at the date, less the tax and charges of selling them, plus the cash left over"
    diff = sale_value - hold_value
    return {"qty": qty, "price": price, "proceeds_after_tax": after_tax, "tax": float(tax or 0.0), "sale_value": sale_value, "hold_value": hold_value, "diff": diff,
            "diff_pct": diff / max(1.0, qty * price) * 100.0, "outcome": "good" if diff > 0 else "bad",
            "detail": {"to": str(T), "close_then": tpx, "hold_tax": round(hold_tax, 2), "hold_tax_from": tax_note, "sale_value_is": how, "cash_rate": manager.CASH_PA,
                       "lots_reconstructed": not detail.get("lots")}}


def score_due(con, day: date, now: Optional[datetime] = None, market: Optional[str] = None) -> int:
    """Score every filled sale at each horizon (20 and 60 sessions after the sale) once that session has closed. Idempotent. Returns the number of new scores."""
    from pflab.paper import book
    cfg = settings()
    hz = [int(h) for h in cfg["score"]["horizons"]]
    n = 0
    q = ("SELECT e.event_id, e.plan_id, e.market, e.isin, e.kind, e.trade_id, e.filled_on, e.detail_json FROM exit_events_s81 e WHERE e.side='sell' AND e.status='filled' "
         "AND e.trade_id IS NOT NULL" + (" AND e.market=?" if market else "") + " ORDER BY e.event_id")
    for ev in con.execute(q, [market] if market else []).fetchall():
        eid, plan_id, mk, isin, kind, trade_id, filled_on, _dj = ev
        sessions = None
        for h in hz:
            if con.execute("SELECT 1 FROM exit_scores_s81 WHERE trade_id=? AND horizon_sessions=?", [trade_id, h]).fetchone():
                continue
            sessions = sessions if sessions is not None else book.sessions_after(con, filled_on, day)
            if len(sessions) < h:
                continue
            T = sessions[h - 1]
            px = book.close_on(con, isin, T)
            if px is None:
                continue
            s = _score_one(con, ev, h, T, px[1])
            sl = con.execute("SELECT sleeve FROM exit_plans_s81 WHERE plan_id=?", [plan_id]).fetchone()
            con.execute("INSERT INTO exit_scores_s81 (score_id, event_id, plan_id, market, isin, kind, sleeve, trade_id, sold_on, qty, sale_price, proceeds_after_tax, tax, horizon_sessions, "
                        "due_on, scored_on, sale_value, hold_value, diff, diff_pct, outcome, detail_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [_id(con, "exit_scores_s81", "score_id"), eid, plan_id, mk, isin, kind, sl[0] if sl else None, trade_id, filled_on, s["qty"], s["price"], s["proceeds_after_tax"],
                         s["tax"], h, T, day, s["sale_value"], s["hold_value"], s["diff"], s["diff_pct"], s["outcome"], json.dumps(s["detail"], default=str)])
            n += 1
    return n


def record(con, horizon: Optional[int] = None) -> dict:
    """The record by kind (target, stop, time, thesis, harvest, trim, rebalance) for the autonomy check and the Today screen: scored sales, how many beat holding after tax, the
    Laplace-smoothed hit rate (only from `min_n` sales; fewer are shown as counts), the mean difference, and the actions taken."""
    cfg = settings()
    min_n = int(cfg["score"]["min_n"])
    hs = [horizon] if horizon else [int(h) for h in cfg["score"]["horizons"]]
    by_kind = []
    for h in hs:
        for kind, n, good, mean, tot in con.execute("SELECT kind, count(*), count(*) FILTER (WHERE outcome='good'), avg(diff_pct), sum(diff) FROM exit_scores_s81 WHERE horizon_sessions=? "
                                                    "GROUP BY kind ORDER BY kind", [h]).fetchall():
            row = {"kind": kind, "horizon_sessions": h, "n": int(n), "good": int(good), "mean_diff_pct": round(float(mean or 0.0), 2), "total_diff_rupees": round(float(tot or 0.0), 2)}
            if n >= min_n:
                row["hit_rate"] = round((good + 1) / (n + 2), 3)
            else:
                row["note"] = f"only {int(n)} scored sale(s): a count, not a conclusion"
            by_kind.append(row)
    actions = {}
    for kind, status, c in con.execute("SELECT kind, status, count(*) FROM exit_events_s81 WHERE status IN ('emitted','filled','guarded','void') GROUP BY 1, 2").fetchall():
        actions.setdefault(kind, {})[status] = int(c)
    n_plans = con.execute("SELECT count(*) FILTER (WHERE status IN ('open','rebuy_pending')) FROM exit_plans_s81").fetchone()[0]
    total = sum(r["n"] for r in by_kind if r["horizon_sessions"] == hs[0])
    return {"by_kind": by_kind, "actions": actions, "open_plans": int(n_plans or 0),
            "summary": (f"{int(n_plans or 0)} open exit plan(s); {sum(v.get('filled', 0) for v in actions.values())} exit sale/buy fill(s); {total} sale(s) scored after tax at {hs[0]} sessions"
                        + (" (under 20 per kind: counts, not conclusions)" if total < min_n else ""))}
