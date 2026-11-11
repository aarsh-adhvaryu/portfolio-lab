"""The entry points the close loop calls for the US leg (S81 B8 phase B; S82: one book with the rupee book). Thin: everything is in the modules beside this one.

    close_us(con, now, root=None, cfg=None) -> dict
        Handles every US session that has closed (settle_minutes after its close, in the IST morning) and has not been handled yet, oldest first: a catch-up after days off runs each
        missed session once, in order (the first ever run handles the latest session only). Per session: the pre-S82 seed is converted into a transfer if there is one, the account is
        OPENED BY A TRANSFER out of the rupee book's cash when it is not open, splits, dividends, fills of the earlier orders at this session's open, a funding tranche when the
        international share of the WHOLE book is under its target (one transfer a day at most), the mark at the close, the core policy's decision through the rails, and the new orders
        (they fill at the NEXT US open; a stop acts at the next open too, so a gap can pass it). Once per session (`us_runs_s81`). Never raises for a missing input: it says what it is
        waiting for. Returns {"off": True} while `[us] on = false`, {"waiting": ...}, {"skipped": ...} or the last session's summary (`caught_up` lists all the sessions run).
    state_us(con, day, root=None) -> dict
        The sub-book on `day` for screens, the card and the morning note: account, cash, positions in USD and rupees (the FX rate and its source stated), the financial year's
        realised gains, tax and dividend figures, open orders and the last run. JSON-safe. `{"open": False}` before the account exists. `us/report.py` is the fuller JSON for screens.

The job `us_close` (service/tasks_s79_us.py) calls it, and the missed-session catch-up of the app runs the same job. The `market="IN"` code paths are unchanged.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from typing import List, Optional

from pflab import us
from pflab.us import book, clock, data, fx as usfx, instruments as uins, picks_wire, policy, transfer, wholebook

MAX_CATCHUP_SESSIONS = 40
GAP_RISK = ("Decisions use the last US close and orders fill at the NEXT US open (plus a few basis points); a stop acts at the next open, so a gap can pass it: "
            "the price can open well beyond the stop and the loss is then taken at that price, not at the stop.")


def pending_sessions(con, now: datetime, settle_minutes: int = 30) -> List[date]:
    """The US sessions closed by `now` that the close function has not handled: after the last handled one up to the latest closed. None handled yet: the latest only."""
    latest = clock.session_closed_by(now, int(settle_minutes))
    last = con.execute("SELECT max(day) FROM us_runs_s81").fetchone()[0]
    if last is None:
        return [latest]
    return clock.market().sessions_between(last + timedelta(days=1), latest)[-MAX_CATCHUP_SESSIONS:]


def close_us(con, now: datetime, root=None, cfg: Optional[dict] = None) -> dict:
    s = us.settings(cfg)
    if not s["on"]:
        return {"off": True}
    todo = pending_sessions(con, now, int(s["settle_minutes"]))
    if not todo:
        latest = clock.session_closed_by(now, int(s["settle_minutes"]))
        return {"skipped": f"US session {latest} already done"}
    try:
        uins.map_symbol_keys(con, uins.load_ciks(root), now=now)               # US:SYMBOL keys -> ZZ+CIK keys by alias, once a CIK map is cached (idempotent)
    except Exception:
        pass
    done, last = [], None
    for day in todo:
        r = _session(con, now, day, s, cfg, root)
        if "waiting" in r:
            if last is None:
                return r
            last = dict(last, waiting=r["waiting"])
            break
        last = r
        done.append(r["day"])
    if len(done) > 1:
        last = dict(last, caught_up=done)
    return last


def _session(con, now: datetime, day: date, s: dict, cfg: Optional[dict], root) -> dict:
    universe = [x.upper() for x in s["broad_index_etfs"]]
    held = [uins.symbol_of(con, k) for k in book.positions(con, day)]
    pick_syms = picks_wire.symbols(con)                                    # S83 L8: the US picks (loaded, rows of the state)
    syms = list(dict.fromkeys(universe + [h for h in held if h] + pick_syms))
    bars = data.load(syms, root)
    if not any(data.bar_on(bars.get(x), day) for x in universe):
        return {"waiting": f"no US bars for {day} yet (tools/backfill_us.py / data/us_prices.py collect them)"}
    fx = usfx.rate_for(con, day, root)
    if fx is None:
        return {"waiting": f"no USD/INR rate within 4 days of {day}"}
    t0 = time.time()
    rupee_day = now.date()
    converted = transfer.convert_seed(con, now, root) if book.account(con) else []
    opened, funding = None, None
    if book.account(con) is None:
        plan = wholebook.plan_tranche(con, rupee_day, now, root, us_cfg=cfg)
        if plan["inr"] <= 0:
            return {"waiting": "the account opens by a transfer out of the rupee book's cash, and none is due: " + plan["reason"]}
        try:
            acct = book.open_account(con, now, day, plan["inr"], fx, plan["share_target"], plan["reason"])
        except ValueError as e:
            return {"waiting": f"the opening transfer could not be made: {e}"}
        opened = {"start_usd": round(acct["start_usd"], 2), "start_inr": round(acct["start_inr"], 2), "from": "a transfer out of the rupee book's cash",
                  "transfer_id": acct["transfer"]["transfer_id"]}
        funding = acct["transfer"]
    splits = book.detect_splits(con, now, day, bars)
    dividends = book.apply_dividends(con, now, day, bars, w8ben=bool(s["w8ben"]), root=root)
    fills = book.fill_orders(con, now, day, bars, float(s["slippage_bps"]), root)
    if funding is None:
        plan = wholebook.plan_tranche(con, rupee_day, now, root, us_cfg=cfg)
        if plan["inr"] > 0:
            try:
                funding = transfer.fund(con, now, day, plan["inr"], fx, "topup" if plan["phase"] == "topup" else "build", plan["reason"], rupee_day=rupee_day)
            except ValueError as e:
                funding = {"failed": str(e)}
    marked = book.mark(con, now, day, bars, fx)
    if funding and "transfer_id" in funding:                               # the share reached once this tranche is in (it decides "settled" later)
        after = wholebook.international_share(con, rupee_day, now, root, us_cfg=cfg)
        con.execute("UPDATE us_transfers_s82 SET share_after=? WHERE transfer_id=?", [after["share"], funding["transfer_id"]])
    pick_note = []
    try:                                                                   # S83 L8: the picks sleeve in the sub-book (judge the share, size the picks by code); a failure leaves the core decision as it was
        from pflab.core import picks
        picks.prepare(con, now, day, "US")
        state = picks.attach(con, policy.build(con, day, bars, cfg, root, now, pick_syms=pick_syms), "US")
        pw = picks_wire.extra_weights(con, state)
        dec = policy.decide(state, extra=pw["extra"], core_total=pw["core_total"] if pw["extra"] else None)
        pick_note = pw["notes"]
    except Exception as e:
        pick_note = [f"picks sleeve not applied this session ({type(e).__name__}: {str(e)[:120]})"]
        state = policy.build(con, day, bars, cfg, root, now)
        dec = policy.decide(state)
    dec["notes"] = list(dec["notes"]) + pick_note
    chk = policy.check(con, state, dec)
    placed = []
    for o in chk["orders"]:
        oid = book.place(con, now, day, o["isin"], o["symbol"], o["side"], qty=o["qty"], amount_usd=o["amount"], reason=o["reason"])
        placed.append({"order_id": oid, "symbol": o["symbol"], "side": o["side"], "usd": round(o["value"], 2), "reason": o["reason"]})
    try:
        from pflab.core import picks
        picks.sync(con, day, "US", state)                                   # S83 L8: proposed -> buying -> held, stopped, broken (outside the orders' transaction; never raises)
    except Exception:
        pass
    status = "traded" if (placed or fills or (funding and "transfer_id" in funding)) else "held"
    note = "; ".join(dec["notes"] + ([f"transfer Rs {funding['inr']:,.0f}"] if funding and "inr" in funding else []))
    con.execute("INSERT INTO us_runs_s81 VALUES (?,?,?,?,?,?,?,?)", [day, now, status, round(time.time() - t0, 3), json.dumps({k: round(v, 5) for k, v in dec["weights"].items()}),
                json.dumps(placed), json.dumps(fills), note[:400]])
    return {"day": str(day), "status": status, "opened": opened, "funding": funding, "converted_seed": converted, "fills": fills, "orders": placed, "dividends": dividends, "splits": splits,
            "value_usd": round(marked["value_usd"], 2), "cash_usd": round(marked["cash_usd"], 2), "fx": {"rate": fx["rate"], "source": fx["source"], "label": fx["label"]},
            "skipped": len(chk["skipped"]), "gap_risk": GAP_RISK, "seconds": round(time.time() - t0, 3)}


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
