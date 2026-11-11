"""The session loop (S81, A54): the market-hours rhythm that runs every `[session] every_minutes` while the market is open, by code, free.

    quotes     Kite's live quotes of what the book holds and what a trigger, a queued order or a tactical view wants (read-only; the loop never places an order anywhere)
    exits      the exit plans are checked at the live quote (`core.exits.check_quote`; a tiny fallback for stop, target and time only while that module is missing: it says so)
    thesis     a filing released DURING the session on a held name (`kg.events.material_events`, else the BSE announcements' dissemination times) goes to the exit manager's
               thesis check (a fallback rule while `core.exits` is missing); a sale, if any, fills at the live quote
    views      the tactical views are carried out here, once per name, under the same timing rules (the close loop then does not buy them a second time)
    breaker    `paper.cadence.breaker`: no buy of any kind while it is on; sells go on
    fills      `core.fills.execute`: the quote plus a spread and slippage by liquidity, never better than the quote; the no-same-day-round-trip guard queues an exit to the next
               session unless its stop fired (then it fills and the day is flagged)

Every run leaves a `run` row in `session_log_s81` and every wait, fill, queue, skip and degradation its own row with a reason written by code; Today's card and `GET /api/session`
show them. No Kite login (or one lost mid-session): the loop says so ONCE (Today and Telegram), does only the work that needs no quotes and never raises.
`replay(con, day, bars_dir)` feeds a recorded day's minute bars through the same `run_once` at 5-minute steps (tests and drills).
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import pandas as pd

from pflab.core import fills

MARKET = "IN"
SEVERITY = {"low": 0, "medium": 1, "high": 2, "critical": 3}
LATE_KINDS = ("time", "harvest", "trim", "rebalance")            # exits with no hurry: they wait out the opening spike like an entry (a stop, a target and a thesis break do not)


# --- the record ---------------------------------------------------------------------------------------------------------------------------------

def log(con, now: datetime, kind: str, what: str, isin: Optional[str] = None, flag: Optional[str] = None, detail: Optional[dict] = None, market: str = MARKET) -> int:
    from pflab.paper import book
    from pflab.pm.store import next_id
    lid = next_id(con, "session_log_s81", "log_id")
    sym = book.inst(con, isin)["symbol"] if isin else None
    con.execute("INSERT INTO session_log_s81 VALUES (?,?,?,?,?,?,?,?,?,?)", [lid, now, market, now.date(), kind, isin, sym, what[:600], flag, json.dumps(detail or {}, default=str)[:3000]])
    return lid


def said(con, now: datetime, key: str, text: str = "") -> bool:
    """True the first time `key` is said today (and records it), False afterwards."""
    if con.execute("SELECT 1 FROM session_said_s81 WHERE day=? AND key=?", [now.date(), key]).fetchone():
        return False
    con.execute("INSERT INTO session_said_s81 VALUES (?,?,?,?)", [now.date(), key, now, text[:2000]])
    return True


def say_once(con, now: datetime, key: str, text: str, kind: str = "degrade") -> bool:
    """Say something once a day: a log row (shown on Today) and one Telegram message through the outbox (queued only; the outbox job sends it, never a test)."""
    if not said(con, now, key, text):
        return False
    log(con, now, kind, text)
    try:
        from pflab.service import telegram as tgm
        tgm.enqueue(con, f"Portfolio Lab, session loop: {text}", "summary", dedup_key=f"session:{now.date()}:{key}", now=now)
    except Exception:
        pass
    return True


# --- the exit manager, or the tiny fallback -------------------------------------------------------------------------------------------------------

def _exits():
    """`pflab.core.exits` (the exit manager), or None while it is missing."""
    try:
        from pflab.core import exits
        return exits if hasattr(exits, "check_quote") else None
    except Exception:
        return None


def _fb_orders(con, now: datetime, quotes: Dict[str, float], market: str = MARKET) -> List[dict]:
    out = []
    for pid, isin, stop, target, due in con.execute("SELECT plan_id, isin, stop_price, target_price, time_stop_on FROM session_exit_fb_s81 WHERE market=? AND status='open' ORDER BY plan_id", [market]).fetchall():
        px = quotes.get(isin)
        if px is None:
            continue
        kind = why = None
        if stop and px <= stop:
            kind, why = "stop", f"the live quote {px:,.2f} is at or under the stop {stop:,.2f}"
        elif target and px >= target:
            kind, why = "target", f"the live quote {px:,.2f} is at or over the target {target:,.2f}"
        elif due and now.date() >= due:
            kind, why = "time", f"the time stop of {due} has come (quote {px:,.2f})"
        if kind:
            out.append({"market": market, "isin": isin, "side": "sell", "qty": None, "fraction": 1.0, "kind": kind, "reason": f"fallback exit plan #{pid}: {why}", "plan_id": pid})
    return out


def _fb_close(con, plan_id: int, day: date) -> None:
    con.execute("UPDATE session_exit_fb_s81 SET status='closed', closed_on=? WHERE plan_id=?", [day, plan_id])


# --- the timing of an entry, from the minute data -------------------------------------------------------------------------------------------------

def timing(bars: Optional[pd.DataFrame], quote: float, now: datetime, typical_minute_volume: Optional[float], cfg: Optional[dict] = None, market: str = MARKET) -> dict:
    """Is this a good moment to enter? {'ok', 'reasons' (why not), 'vwap', 'dev' (price against VWAP), 'vol_ratio', 'minutes_in'}. Uses only minute bars that had CLOSED by `now`."""
    from pflab import markets
    c = cfg or fills.session_settings()
    open_dt = datetime.combine(now.date(), markets.get(market).open)
    mins = (now - open_dt).total_seconds() / 60.0
    out = {"ok": False, "reasons": [], "vwap": None, "dev": None, "vol_ratio": None, "minutes_in": round(mins, 1)}
    r = out["reasons"]
    if mins < float(c["no_entry_minutes"]):
        r.append(f"only {mins:.0f} minutes into the session: no entry in the first {int(c['no_entry_minutes'])} (the opening spike)")
    b = bars
    if b is not None and len(b):
        b = b.assign(ts=pd.to_datetime(b["ts"]))
        b = b[(b["ts"] >= open_dt) & (b["ts"] + pd.Timedelta(minutes=1) <= pd.Timestamp(now))]
    if b is None or not len(b):
        r.append("no minute bars of today: no VWAP and no volume context, so the entry waits")
        return out
    vol = b["volume"].astype(float)
    if vol.sum() <= 0:
        r.append("no volume in today's minute bars: no VWAP")
    else:
        vwap = float(((b["high"] + b["low"] + b["close"]) / 3.0 * vol).sum() / vol.sum())
        out["vwap"], out["dev"] = vwap, quote / vwap - 1.0
        if abs(out["dev"]) > float(c["vwap_band"]):
            r.append(f"the price is {out['dev']:+.2%} from the day's VWAP {vwap:,.2f}, outside the {float(c['vwap_band']):.1%} band")
    recent = float(vol.tail(int(c["volume_minutes"])).mean())
    if not typical_minute_volume:
        r.append("no history of the name's typical minute volume: no volume context, so the entry waits")
    else:
        out["vol_ratio"] = recent / typical_minute_volume
        if out["vol_ratio"] < float(c["volume_fraction"]):
            r.append(f"the last {int(c['volume_minutes'])} minutes trade {out['vol_ratio']:.0%} of the typical minute volume, under {float(c['volume_fraction']):.0%}")
    out["ok"] = not r
    return out


# --- live quotes and live bars --------------------------------------------------------------------------------------------------------------------

def kite_quotes(con, kite, isins: Iterable[str]) -> Dict[str, float]:
    """isin -> last price through Kite's ltp (read-only). Raises on a lost login or a network failure (the caller degrades)."""
    from pflab.ingest import kite as km
    sym = {r[0]: r[1] for r in con.execute("SELECT isin, symbol FROM instruments WHERE symbol IS NOT NULL").fetchall()}
    return km.make_quote_fn(kite, sym)(sorted(set(isins)))


def kite_bars(con, kite, isins: Iterable[str], day: date, market: str = MARKET) -> Dict[str, pd.DataFrame]:
    """Today's minute bars so far of the names (Kite historical data, read-only); a name that fails is left out."""
    from pflab import markets
    from pflab.paper import book
    from pflab.service import tasks_s79_bars as tb
    m, out = markets.get(market), {}
    tok = tb.tokens(kite)
    for isin in isins:
        sym = (book.inst(con, isin)["symbol"] or "").upper()
        if sym in tok:
            try:
                out[isin] = tb.fetch_day(kite, tok[sym], m, day)
            except Exception:
                continue
    return out


def _login_lost(e: Exception) -> bool:
    return "token" in type(e).__name__.lower() or "token" in str(e).lower() or "403" in str(e)


# --- the events of the session (thesis breaks) ----------------------------------------------------------------------------------------------------

def _filing_events(isins: List[str], since: datetime, until: datetime, data_root: Optional[Path] = None) -> List[dict]:
    """The plain fallback: BSE announcements disseminated in [since, until] on `isins`, by the red-flag classifier. A filing with no release time counts from the next trading
    day's open (A58, `kg2/filing_time.py`): it is read from the file of its own day, so a session sees the filings dated on the days since the previous session."""
    from pflab.data import bse_scrip_isin, data_dir, red_flags
    root = Path(data_root) if data_root else data_dir()
    out: List[dict] = []
    try:
        m = bse_scrip_isin.load(root)
    except Exception:
        return out
    m = m[m["isin"].isin(isins)]
    if not len(m):
        return out
    codes = {str(r.scrip_code): r.isin for r in m.itertuples()}
    from pflab import markets
    from pflab.kg2 import filing_time as ft
    mk = markets.get("IN")
    d0 = mk.previous_session(until.date()) if mk.is_session(until.date()) else mk.last_session_on_or_before(until.date())
    days, d = [], d0
    while d <= until.date():                                                   # the previous session's day and the days after it: their no-time filings are due at this open
        days.append(d)
        d += timedelta(days=1)
    for day in days:
        f = root / "bse_announcements" / str(day.year) / f"{day.isoformat()}.parquet"
        if not f.exists():
            continue
        df = pd.read_parquet(f)
        df = df[df["scrip_code"].astype(str).isin(codes)]
        for r in df.itertuples():
            ts, rule, _own = ft.filing_time(r.dissem_dt, getattr(r, "news_dt", None), day)
            if ts is None or not (since <= ts <= until) or (rule == ft.RULE_RELEASE and day != until.date()):
                continue
            flags = red_flags.classify(str(r.headline or ""), str(r.category or ""), str(r.subcategory or ""))
            for fl in flags:
                sev = "high" if fl in ("INSOLVENCY", "DEFAULT", "FRAUD", "FORENSIC_AUDIT") else "medium"
                out.append({"isin": codes[str(r.scrip_code)], "kind": fl, "severity": sev, "ts": ts, "source": "bse_announcements", "ref": f"{r.scrip_code}:{ts:%Y%m%d%H%M%S}",
                            "text": str(r.headline or "")[:200], "ts_rule": rule})
    return out


def session_events(con, isins: List[str], since: datetime, until: datetime, data_root: Optional[Path] = None) -> tuple:
    """(events, source): the knowledge graph's `kg.events.material_events` when it exists, else the filings fallback. Only events with a dissemination time in (since, until]."""
    try:
        from pflab.kg import events as kev
        ev = list(kev.material_events(con, isins, since))
        src = "kg.events"
    except Exception:
        ev, src = _filing_events(isins, since, until, data_root), "bse_announcements (fallback)"
    keep = []
    for e in ev:
        ts = e.get("ts")
        if ts is None:
            continue
        ts = pd.to_datetime(ts).to_pydatetime()
        if since <= ts <= until:                                              # a filing with no release time is due AT the open (A58: derived time 09:15)
            keep.append(dict(e, ts=ts))
    return keep, src


def _fb_thesis_orders(events: List[dict], held: Dict[str, float], cfg: dict) -> List[dict]:
    floor = SEVERITY.get(str(cfg["thesis_min_severity"]).lower(), 2)
    out = []
    for e in events:
        if held.get(e["isin"], 0) > 0 and SEVERITY.get(str(e.get("severity")).lower(), 0) >= floor:
            out.append({"market": MARKET, "isin": e["isin"], "side": "sell", "qty": None, "fraction": 1.0, "kind": "thesis", "plan_id": None,
                        "reason": f"thesis break by the fallback rule: a {e['kind']} filing ({e.get('severity')}) was released at {e['ts']:%H:%M} ({e.get('source')}): {str(e.get('text') or '')[:120]}"})
    return out


# --- carrying out an order ------------------------------------------------------------------------------------------------------------------------

def _queue(con, now: datetime, isin: str, side: str, qty: float, kind: str, plan_id: Optional[int], reason: str, market: str = MARKET) -> int:
    from pflab import markets
    from pflab.pm.store import next_id
    same = con.execute("SELECT queue_id FROM session_queue_s81 WHERE market=? AND isin=? AND side=? AND kind=? AND queued_on=? AND status='queued'", [market, isin, side, kind, now.date()]).fetchone()
    if same:                                                                   # the same order is not queued twice in a day (the loop meets it again every 5 minutes)
        return same[0]
    qid = next_id(con, "session_queue_s81", "queue_id")
    con.execute("INSERT INTO session_queue_s81 (queue_id, market, isin, side, qty, kind, plan_id, reason, queued_on, run_on, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [qid, market, isin, side, qty, kind, plan_id, reason[:500], now.date(), markets.get(market).next_session(now.date()), "queued"])
    log(con, now, "queue", f"held to the next session ({markets.get(market).next_session(now.date())}): {reason}", isin, detail={"qty": qty, "kind": kind, "side": side}, market=market)
    return qid


def _carry_out(con, now: datetime, o: dict, ctx: dict, results: dict) -> Optional[dict]:
    """One order dict of the exit contract (or an entry): quote it, apply the breaker and the guard, fill it at the live quote plus slippage, record it."""
    from pflab.paper import book
    isin, side, kind = o["isin"], o["side"], str(o.get("kind") or "")
    px = ctx["quotes"].get(isin)
    if px is None:
        log(con, now, "skip", f"{kind} order not carried out: no live quote for it this round ({o.get('reason', '')})", isin)
        return None
    if side == "buy" and ctx["breaker"].get("on"):
        log(con, now, "skip", f"{kind} buy not carried out: the circuit breaker is on (drawdown {ctx['breaker'].get('drawdown'):.1%}); selling stays open", isin)
        results["blocked"].append({"isin": isin, "why": "circuit breaker"})
        return None
    if kind in LATE_KINDS and ctx["minutes_in"] < float(ctx["cfg"]["no_entry_minutes"]):
        log(con, now, "wait", f"{kind} sale waits out the opening spike (first {int(ctx['cfg']['no_entry_minutes'])} minutes): {o.get('reason', '')}", isin)
        return None
    held = book.positions(con).get(isin, 0.0)
    qty = o.get("qty")
    if side == "sell":
        if qty is None:
            f = float(o.get("fraction") or 1.0)
            qty = held if f >= 0.999 else math.floor(f * held)
        qty = min(float(qty), held)
        if qty <= 1e-9:
            log(con, now, "skip", f"{kind} order not carried out: nothing held ({o.get('reason', '')})", isin)
            return None
    elif qty is None:
        qty = math.floor(float(o.get("amount") or 0.0) / px)
    r = fills.execute(con, now, isin, side, quote=px, qty=qty, kind=kind, reason=o.get("reason", ""), plan_id=o.get("plan_id"), root=ctx.get("root"), liq=(ctx.get("liq") or {}).get(isin),
                      bypass_guard=(kind == "stop"), source=str(ctx.get("source") or "injected"))
    return _record(con, now, o, r, qty, results)


def _record(con, now: datetime, o: dict, r: dict, asked_qty: float, results: dict) -> dict:
    isin, kind = o["isin"], str(o.get("kind") or "")
    if r["status"] in ("filled", "partial"):
        why = (f"{kind}: {o.get('reason', '')}; filled {r['qty']:,.0f} at {r['price']:,.2f} against the live quote {r['quote']:,.2f} (spread {r['half_spread_bps']:.1f} bp + slippage {r['slippage_bps']:.1f} bp, "
               f"costing Rs {r['cost_rupees']:,.2f}); charges Rs {r['charges']:,.2f}" + (f", tax estimate Rs {r['tax']:,.2f}" if r.get("tax") else ""))
        log(con, now, "fill", why, isin, r.get("flag"), {k: r.get(k) for k in ("fill_id", "order_id", "trade_id", "qty", "price", "quote", "plan_id")}, )
        results["fills"].append({k: r.get(k) for k in ("isin", "side", "qty", "price", "quote", "half_spread_bps", "slippage_bps", "cost_rupees", "kind", "flag")} | {"kind": kind})
        if o.get("plan_id") and o["side"] == "sell" and _exits() is None:
            if book_positions_zero(con, isin):
                _fb_close(con, int(o["plan_id"]), now.date())
        if r["status"] == "partial":
            _queue(con, now, isin, o["side"], r["blocked_qty"], kind, o.get("plan_id"), r["why"])
            results["queued"].append({"isin": isin, "qty": r["blocked_qty"], "kind": kind})
    elif r["status"] == "held":
        _queue(con, now, isin, o["side"], r["blocked_qty"], kind, o.get("plan_id"), f"{kind}: {o.get('reason', '')}; {r['why']}")
        results["queued"].append({"isin": isin, "qty": r["blocked_qty"], "kind": kind})
    else:
        log(con, now, "skip", f"{kind} order not filled: {r.get('why')} ({o.get('reason', '')})", isin)
        results["blocked"].append({"isin": isin, "why": r.get("why")})
    return r


def book_positions_zero(con, isin: str) -> bool:
    from pflab.paper import book
    return book.positions(con).get(isin, 0.0) <= 1e-9


# --- one run --------------------------------------------------------------------------------------------------------------------------------------

def _symbols(con, isins) -> Dict[str, str]:
    from pflab.paper import book
    return {i: book.inst(con, i)["symbol"] or i for i in isins}


def _views(con, day: date) -> List[dict]:
    try:
        from pflab.core import views
        return views.active(con, day)
    except Exception:
        return []


def _wanted(con, day: date, market: str) -> Dict[str, set]:
    from pflab.paper import book
    held = {i for i, q in book.positions(con).items() if q > 1e-9}
    queue = {r[0] for r in con.execute("SELECT isin FROM session_queue_s81 WHERE market=? AND status='queued' AND run_on <= ?", [market, day]).fetchall()}
    views_ = {i for v in _views(con, day) for i in v["names"]}
    return {"held": held, "queue": queue, "views": views_}


def run_once(con, now: datetime, quotes: Optional[Dict[str, float]] = None, bars: Optional[Dict[str, pd.DataFrame]] = None, *, kite=None, events: Optional[List[dict]] = None,
             root: Optional[Path] = None, data_root: Optional[Path] = None, liq: Optional[Dict[str, dict]] = None, market: str = MARKET) -> dict:
    """One pass of the session loop at `now` (naive IST). `quotes` {isin: price} and `bars` {isin: minute bars of today up to now} may be injected (replay, tests); without `quotes` the
    live quotes come from `kite` (a read-only client) and without `bars` the bars come from it too. Never raises: a problem is a stated degradation."""
    from pflab import core, markets
    from pflab.paper import book, cadence
    cfg = fills.session_settings()
    out: dict = {"at": now.isoformat(timespec="minutes"), "day": str(now.date()), "fills": [], "queued": [], "blocked": [], "waiting": [], "degraded": None}
    if not cfg["on"]:
        return {"off": True, "why": "configs/core.toml [session] on = false"}
    if core.killed() or not core.on():
        return {"off": True, "why": "the kill switch or [core] on = false"}
    m = markets.get(market)
    if m.mode(now) != "session":
        return {"skipped": f"{market} is not in session at {now:%a %H:%M}"}
    if not book.started(con):
        return {"waiting": "the paper book has not started"}
    day = now.date()
    open_dt = datetime.combine(day, m.open)
    minutes_in = (now - open_dt).total_seconds() / 60.0
    try:                                                                       # the day's plan, if the pre-open job has not made it (the app was opened after the open): made late, said so
        from pflab.core import preopen
        preopen.ensure_plan(con, now, market, root=data_root)
    except Exception as e:
        log(con, now, "degrade", f"the day's plan could not be made ({type(e).__name__}: {str(e)[:120]})")
    want = _wanted(con, day, market)
    names = sorted(set().union(*want.values()))
    live = quotes is None
    if live:                                                                    # live quotes: Kite, read-only
        if kite is None:
            say_once(con, now, "kite", "there is no valid Kite login: the session loop checks no live quotes today and only the work that needs none runs (the post-close loop still runs). "
                                       "Log in to Kite to switch it on.")
            out["degraded"] = "no Kite login"
            quotes = {}
        else:
            try:
                quotes = kite_quotes(con, kite, names) if names else {}
                for i, p in quotes.items():
                    con.execute("INSERT INTO live_quotes VALUES (?,?,?,?) ON CONFLICT DO NOTHING", [i, now, float(p), "kite"])
            except Exception as e:
                lost = _login_lost(e)
                first_today = con.execute("SELECT count(*) FROM session_log_s81 WHERE day=? AND kind='run' AND detail_json LIKE '%\"quotes\": %' AND detail_json NOT LIKE '%\"quotes\": 0%'", [day]).fetchone()[0]
                say_once(con, now, "kite", (f"the Kite login was lost at {now:%H:%M}" if lost and first_today else "the Kite login is not valid" if lost else f"Kite quotes failed at {now:%H:%M} ({type(e).__name__})")
                         + ": the session loop checks no live quotes from here and only the work that needs none runs. Log in to Kite to switch it back on.")
                out["degraded"] = "Kite login lost" if lost else f"quotes failed: {type(e).__name__}"
                quotes = {}
        if bars is None and kite is not None and quotes and (want["views"] | want["queue"]):
            try:
                bars = kite_bars(con, kite, want["views"] | want["queue"], day, market)
            except Exception as e:
                log(con, now, "degrade", f"minute bars of today could not be read ({type(e).__name__}): entries wait for them")
    bars = bars or {}
    br = cadence.breaker(con)
    ctx = {"quotes": quotes, "bars": bars, "breaker": br, "cfg": cfg, "minutes_in": minutes_in, "root": root, "liq": liq or {},
           "source": "live" if live else "injected"}            # S82 C8: only a fill at a live Kite quote counts as a real fill for the fill-cost calibration
    res = {"fills": out["fills"], "queued": out["queued"], "blocked": out["blocked"]}
    checks = {"exit_plans": 0, "orders_due": 0, "views": 0, "queued": 0, "events": 0}

    def liquidity(isin):
        if isin not in ctx["liq"]:
            try:
                ctx["liq"][isin] = fills.liquidity(con, isin, day, market, root)
            except Exception:
                ctx["liq"][isin] = {}
        return ctx["liq"][isin]

    if quotes:
        state = {"day": day, "market": market, "positions": book.positions(con), "bars": bars, "breaker": br, "open_at": open_dt, "minutes_in": minutes_in}
        # 1. the queue: what the guard held from an earlier session
        for q in con.execute("SELECT queue_id, isin, side, qty, kind, plan_id, reason FROM session_queue_s81 WHERE market=? AND status='queued' AND run_on <= ? ORDER BY queue_id", [market, day]).fetchall():
            checks["queued"] += 1
            qid, isin, side, qty, kind, plan_id, reason = q
            if side == "sell" and book.positions(con).get(isin, 0.0) <= 1e-9:
                con.execute("UPDATE session_queue_s81 SET status='void', done_at=?, result=? WHERE queue_id=?", [now, "nothing held any more (an exit plan sold it first)", qid])
                continue
            if isin not in quotes:
                continue
            if minutes_in < float(cfg["no_entry_minutes"]):
                continue
            if side == "buy":
                t = timing(bars.get(isin), quotes[isin], now, liquidity(isin).get("typical_minute_volume"), cfg, market)
                if not t["ok"]:
                    if said(con, now, f"qwait:{qid}:{t['reasons'][0][:40]}"):
                        log(con, now, "wait", f"queued buy waits: {'; '.join(t['reasons'])}", isin)
                    continue
            r = _carry_out(con, now, {"market": market, "isin": isin, "side": side, "qty": qty, "kind": kind or "queued", "plan_id": plan_id, "reason": f"queued from an earlier session: {reason}"}, ctx, res)
            if r is not None and r["status"] in ("filled", "partial"):
                con.execute("UPDATE session_queue_s81 SET status='done', done_at=?, result=? WHERE queue_id=?", [now, f"filled {r['qty']:,.0f} at {r['price']:,.2f}", qid])
            elif r is not None and r["status"] == "not_filled":
                con.execute("UPDATE session_queue_s81 SET status='void', done_at=?, result=? WHERE queue_id=?", [now, str(r.get("why"))[:200], qid])
        # 2. the exit plans at the live quote
        ex = _exits()
        orders: List[dict] = []
        if ex is not None:
            try:
                orders = list(ex.check_quote(con, now, quotes, state) or [])
                out["exits_from"] = "core.exits"
            except Exception as e:
                log(con, now, "degrade", f"the exit manager's quote check failed ({type(e).__name__}: {str(e)[:120]}): the fallback checks stop, target and time")
                orders = _fb_orders(con, now, quotes, market)
                out["exits_from"] = "fallback"
        else:
            orders = _fb_orders(con, now, quotes, market)
            out["exits_from"] = "fallback"
            if said(con, now, "fallback_exits"):
                log(con, now, "degrade", "pflab.core.exits is not installed: only the tiny fallback (stop, target and time stop of the positions the session opened) checks exits")
        checks["exit_plans"] = con.execute("SELECT count(*) FROM session_exit_fb_s81 WHERE status='open'").fetchone()[0] if ex is None else None
        done_today = {(r[0], r[1]) for r in con.execute("SELECT plan_id, kind FROM session_fills_s81 WHERE day=? AND plan_id IS NOT NULL", [day]).fetchall()}
        for o in orders:
            if (o.get("plan_id"), o.get("kind")) in done_today:
                continue
            checks["orders_due"] += 1
            _carry_out(con, now, o, ctx, res)
        # 3. a thesis break from a filing released during the session
        held_now = book.positions(con)
        evs, src = events_for(con, now, open_dt, [i for i, q in held_now.items() if q > 1e-9], events, data_root)
        fresh = [e for e in evs if said(con, now, f"event:{e.get('ref') or e['isin'] + str(e['ts'])}")]
        checks["events"] = len(evs)
        if fresh:
            try:
                th = list(ex.check_thesis(con, day, fresh) or []) if ex is not None and hasattr(ex, "check_thesis") else _fb_thesis_orders(fresh, held_now, cfg)
            except Exception as e:
                log(con, now, "degrade", f"the exit manager's thesis check failed ({type(e).__name__}): the fallback rule applies")
                th = _fb_thesis_orders(fresh, held_now, cfg)
            for e in fresh:
                log(con, now, "thesis", f"a filing was released at {e['ts']:%H:%M} on a held name: {e['kind']} ({e.get('severity')}), {str(e.get('text') or '')[:120]} [{src}]", e["isin"], detail={"ref": e.get("ref")})
            for o in th:
                o.setdefault("kind", "thesis")
                _carry_out(con, now, o, ctx, res)
        # 4. the tactical views, carried out in session
        if cfg["views_in_session"]:
            _views_in_session(con, now, day, ctx, res, checks, market, liquidity, out)
    elif out["degraded"]:
        # without quotes only the work that needs none: a thesis break is noted (the post-close loop sees the same filing and sells at the close)
        held_now = book.positions(con)
        evs, src = events_for(con, now, open_dt, [i for i, q in held_now.items() if q > 1e-9], events, data_root)
        for e in evs:
            if said(con, now, f"event:{e.get('ref') or e['isin'] + str(e['ts'])}"):
                log(con, now, "thesis", f"a filing was released at {e['ts']:%H:%M} on a held name: {e['kind']} ({e.get('severity')}); with no live quote nothing is sold now, the post-close loop decides [{src}]", e["isin"])
    n_fill = len(out["fills"])
    summary = {"quotes": len(quotes or {}), "checks": checks, "fills": n_fill, "queued": len(out["queued"]), "waiting": len(out["waiting"]), "degraded": out["degraded"], "breaker": bool(br.get("on")),
               "source": "live" if live else "injected"}
    log(con, now, "run", f"session check at {now:%H:%M}: " + (f"{len(quotes or {})} quote(s), {n_fill} fill(s), {len(out['queued'])} held to the next session, {len(out['waiting'])} waiting on timing"
                                                              if quotes else f"no quotes ({out['degraded'] or 'nothing to quote'})") + ("; circuit breaker ON" if br.get("on") else ""), detail=summary)
    out["summary"] = summary
    return out


def events_for(con, now: datetime, open_dt: datetime, isins: List[str], injected: Optional[List[dict]], data_root: Optional[Path]) -> tuple:
    if not isins:
        return [], "no held names"
    if injected is not None:
        keep = []
        for e in injected:
            ts = pd.to_datetime(e.get("ts")).to_pydatetime() if e.get("ts") is not None else None
            if ts is not None and open_dt <= ts <= now and e["isin"] in isins:         # released DURING the session and already out by now (point-in-time)
                keep.append(dict(e, ts=ts))
        return keep, "injected"
    try:
        return session_events(con, isins, open_dt, now, data_root)
    except Exception as e:
        return [], f"events unavailable ({type(e).__name__})"


def _views_in_session(con, now, day, ctx, res, checks, market, liquidity, out) -> None:
    from pflab.core import views
    from pflab.paper import book
    cfg = ctx["cfg"]
    act = views.active(con, day)
    if not act:
        return
    share = views.budget_share(con)["share"]
    value = book.holdings(con, day)["value"]
    for v in act:
        done = json.loads(con.execute("SELECT executed_json FROM core_views_s80 WHERE view_id=?", [v["view_id"]]).fetchone()[0] or "{}")
        each = v["share"] * share * value / max(1, len(v["names"]))
        for isin in v["names"]:
            if isin in done:
                continue
            checks["views"] += 1
            px = ctx["quotes"].get(isin)
            if px is None:
                continue
            tm = timing(ctx["bars"].get(isin), px, now, liquidity(isin).get("typical_minute_volume"), cfg, market)
            if not tm["ok"]:
                out["waiting"].append({"isin": isin, "why": tm["reasons"]})
                if said(con, now, f"vwait:{v['view_id']}:{isin}:{tm['reasons'][0][:40]}"):
                    log(con, now, "wait", f"tactical view #{v['view_id']} waits: {'; '.join(tm['reasons'])}", isin)
                continue
            qty = math.floor(each / px)
            side = "buy" if v["direction"] > 0 else "sell"
            if side == "sell":
                qty = min(qty, math.floor(book.positions(con).get(isin, 0.0)))
            if qty <= 0:
                done[isin] = {"day": str(day), "qty": 0, "why": "less than one share at this size"}
            else:
                r = _carry_out(con, now, {"market": market, "isin": isin, "side": side, "qty": qty, "kind": "view", "plan_id": None,
                                         "reason": f"tactical view #{v['view_id']} ({'up' if v['direction'] > 0 else 'down'}): carried out in session at VWAP {tm['vwap']:,.2f}"}, ctx, res)
                if r is None or r["status"] == "held":
                    continue
                done[isin] = {"day": str(day), "qty": r.get("qty", 0.0) if r["status"] in ("filled", "partial") else 0, "price": r.get("price"), "status": r["status"]}
            con.execute("UPDATE core_views_s80 SET executed_json=? WHERE view_id=?", [json.dumps(done), v["view_id"]])


# --- the replay -----------------------------------------------------------------------------------------------------------------------------------

def replay(con, day: date, bars_dir: Path, *, isins: Optional[Iterable[str]] = None, step_minutes: int = 5, events: Optional[List[dict]] = None, times: Optional[List[datetime]] = None,
           first: Optional[time] = None, last: Optional[time] = None, data_root: Optional[Path] = None, market: str = MARKET, on_step: Optional[Callable[[datetime, dict], None]] = None) -> dict:
    """Feed the recorded minute bars of `day` (`bars_dir/<market>/<SYMBOL>.parquet`, columns ts, open, high, low, close, volume) through `run_once` at `step_minutes` steps, the SAME code the
    live loop runs. At each step `now` is the step time, a quote is the close of the last minute that had closed, and `bars` are only the minutes closed by then (nothing from the future).
    `times` injects the clock (a list of datetimes). Defaults: every name held, with a queued order or a view. Returns {'steps', 'runs', 'fills', ...}."""
    from pflab import markets
    from pflab.paper import book
    m = markets.get(market)
    bars_dir = Path(bars_dir)
    want = _wanted(con, day, market)
    names = list(isins) if isins is not None else sorted(set().union(*want.values()))
    sym = _symbols(con, names)
    full: Dict[str, pd.DataFrame] = {}
    for isin in names:
        p = bars_dir / market / f"{sym[isin]}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            df["ts"] = pd.to_datetime(df["ts"])
            full[isin] = df[(df["ts"] >= datetime.combine(day, time(0, 0))) & (df["ts"] < datetime.combine(day + timedelta(days=1), time(0, 0)))].sort_values("ts").reset_index(drop=True)
    if times is None:
        t0 = datetime.combine(day, first or m.open) + timedelta(minutes=step_minutes)
        t1 = datetime.combine(day, last or m.close) - timedelta(minutes=step_minutes)
        times, t = [], t0
        while t <= t1:
            times.append(t)
            t += timedelta(minutes=step_minutes)
    runs, all_fills = [], []
    for t in times:
        cutoff = pd.Timestamp(t)
        bars_t, quotes = {}, {}
        for isin, df in full.items():
            b = df[df["ts"] + pd.Timedelta(minutes=1) <= cutoff]
            if len(b):
                bars_t[isin], quotes[isin] = b, float(b["close"].iloc[-1])
        r = run_once(con, t, quotes=quotes, bars=bars_t, events=events, root=bars_dir, data_root=data_root, market=market)
        runs.append(r)
        all_fills += r.get("fills", [])
        if on_step:
            on_step(t, r)
    return {"day": str(day), "steps": len(times), "runs": runs, "fills": all_fills, "names": len(full)}


# --- what Today shows -----------------------------------------------------------------------------------------------------------------------------

def card(con, now: datetime, market: str = MARKET, limit: int = 12) -> dict:
    """The one compact card on Today (and `GET /api/session`): today's plan, the checks that ran, the last things that happened, the fills, what waits for the next session."""
    from pflab import markets
    m = markets.get(market)
    day = now.date() if m.is_session(now.date()) else m.previous_session(now.date())
    plan = con.execute("SELECT made_at, late, n_orders, text, gap_json FROM session_plans_s81 WHERE market=? AND day=?", [market, day]).fetchone()
    runs = con.execute("SELECT count(*), max(ts) FROM session_log_s81 WHERE day=? AND kind='run'", [day]).fetchone()
    rows = con.execute("SELECT ts, kind, symbol, what, flag FROM session_log_s81 WHERE day=? AND kind <> 'run' ORDER BY log_id DESC LIMIT ?", [day, limit]).fetchall()
    fl = con.execute("SELECT ts, symbol, side, qty, quote, price, half_spread_bps, slippage_bps, cost_rupees, kind, flag FROM session_fills_s81 WHERE day=? ORDER BY fill_id", [day]).fetchall()
    kite = con.execute("SELECT text FROM session_said_s81 WHERE day=? AND key='kite'", [day]).fetchone()
    rep = con.execute("SELECT text FROM session_said_s81 WHERE day=? AND key='report'", [day]).fetchone()
    queued = con.execute("SELECT count(*) FROM session_queue_s81 WHERE status='queued'").fetchone()[0]
    return {"day": str(day), "mode": m.mode(now), "on": bool(fills.session_settings()["on"]),
            "plan": {"made_at": str(plan[0])[:16], "late": bool(plan[1]), "orders": plan[2], "text": plan[3]} if plan else None,
            "runs": int(runs[0]), "last_run": str(runs[1])[:16] if runs[1] else None, "kite": kite[0] if kite else "ok" if runs[0] else None,
            "recent": [{"at": str(r[0])[11:16], "kind": r[1], "name": r[2], "what": r[3], "flag": r[4]} for r in rows],
            "fills": [{"at": str(r[0])[11:16], "name": r[1], "side": r[2], "qty": r[3], "quote": r[4], "price": r[5], "spread_bps": round(r[6], 2), "slippage_bps": round(r[7], 2),
                       "cost_rupees": round(r[8], 2), "kind": r[9], "flag": r[10]} for r in fl],
            "held_to_next_session": int(queued), "report": rep[0] if rep else None}


# --- the 15:45 self-report ------------------------------------------------------------------------------------------------------------------------

def report_day(con, day: date, market: str = MARKET) -> str:
    """The message sent after the close: what the pre-open plan was, how many session checks ran, what fired and filled (quote, price, slippage charged), what was held to the next session
    and anything that did not run, each with its reason. Plain words, code-written, about a dozen lines."""
    L: List[str] = [f"Session {day:%a %d %b} ({market}):"]
    plan = con.execute("SELECT made_at, late, n_orders, orders_json, gap_json FROM session_plans_s81 WHERE market=? AND day=?", [market, day]).fetchone()
    if plan:
        kinds: Dict[str, int] = {}
        for o in json.loads(plan[3] or "[]"):
            kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
        gap = json.loads(plan[4] or "null")
        L.append(f"Plan: {plan[2]} conditional order(s)" + (" (" + ", ".join(f"{n} {k.replace('_', ' ')}" for k, n in kinds.items()) + ")" if kinds else "") + f", made {str(plan[0])[11:16]}"
                 + (" (late: the app was opened after the open)" if plan[1] else "") + (f"; expected Nifty gap about {gap['expected_gap']:+.2%} (an estimate)" if gap else "") + ".")
    else:
        L.append("Plan: none was made (the pre-open step did not run).")
    n_runs, first, last = con.execute("SELECT count(*), min(ts), max(ts) FROM session_log_s81 WHERE day=? AND kind='run'", [day]).fetchone()
    if n_runs:
        withq = con.execute("SELECT count(*) FROM session_log_s81 WHERE day=? AND kind='run' AND detail_json NOT LIKE '%\"quotes\": 0,%'", [day]).fetchone()[0]
        L.append(f"Checks: {n_runs} session check(s) between {first:%H:%M} and {last:%H:%M}, {withq} with live quotes.")
    else:
        L.append("Checks: the session loop did not run today.")
    fl = con.execute("SELECT ts, symbol, side, qty, quote, price, half_spread_bps, slippage_bps, cost_rupees, kind, flag, reason FROM session_fills_s81 WHERE market=? AND day=? ORDER BY fill_id", [market, day]).fetchall()
    if fl:
        L.append(f"Filled: {len(fl)} paper order(s).")
        for ts, sym, side, qty, quote, price, hs, sl, cost, kind, flag, reason in fl[:8]:
            L.append(f"- {ts:%H:%M} {side} {qty:,.0f} {sym} ({kind}) at {price:,.2f} against the quote {quote:,.2f}; spread {hs:.1f} bp + slippage {sl:.1f} bp cost Rs {cost:,.0f}" + (f" [{flag}]" if flag else ""))
    else:
        L.append("Filled: nothing fired, nothing was bought or sold in the session.")
    waits = con.execute("SELECT count(*) FROM session_log_s81 WHERE day=? AND kind='wait'", [day]).fetchone()[0]
    if waits:
        L.append(f"Waited: {waits} trigger or view hit but the moment was not right (first 15 minutes, away from VWAP or thin volume).")
    q = con.execute("SELECT count(*) FROM session_queue_s81 WHERE queued_on=?", [day]).fetchone()[0]
    if q:
        L.append(f"Held to the next session: {q} order(s) that would have been a same-day round trip.")
    notes = [r[0] for r in con.execute("SELECT what FROM session_log_s81 WHERE day=? AND kind='degrade' ORDER BY log_id", [day]).fetchall()]
    if notes:
        L.append("Did not run as planned: " + " | ".join(dict.fromkeys(n[:160] for n in notes[:4])))
    try:                                                                                # S83 L5: a move of the picks sleeve's share, in plain words
        from pflab.core import pick_share
        share_line = pick_share.report_line(con, day)
        if share_line:
            L.append(share_line)
    except Exception:
        pass
    core = con.execute("SELECT status, orders_json FROM core_runs_s80 WHERE day=?", [day]).fetchone()
    tail = [strategist_line(con, day)] if strategist_line(con, day) else []                        # S82 C9: one plain line on the strategist's newest note
    tail.append("Post-close loop: " + (f"{core[0]} ({len(json.loads(core[1] or '[]'))} order(s))." if core else "not yet; it runs when NSE's closing files arrive this evening."))
    return "\n".join(L[:15 - len(tail)] + tail)


def strategist_line(con, day: date) -> Optional[str]:
    """One plain line for the self-report: the strategist's newest note when it was written in the last 3 days (what it concluded, any allocation it put forward, what the session cost)."""
    try:
        from pflab.lab import service as lab
        n = lab.latest_strategist_note(con)
        if not n["note"] or str(n["when"])[:10] < str(day - timedelta(days=3)):
            return None
        p = n["proposal"]
        prop = ""
        if p:
            mix = ", ".join(f"{k} {v:g}%" for k, v in sorted(p["classes"].items(), key=lambda kv: -kv[1]) if v)
            prop = f" It {'kept the allocation as it stands' if p.get('reaffirmed') else 'proposed an allocation'}" + (f" ({mix})" if mix else "") + "."
        cost = f" The session cost Rs {n['cost_rupees']:,.0f}." if n["cost_rupees"] is not None else ""
        return f"Strategist ({n['when']}): {' '.join(str(n['note']).split())[:220]}{prop}{cost}"
    except Exception:
        return None
