"""Paper fills at a live quote (S81, A54): the quote plus a spread and slippage by liquidity, never better than the quote, and the no-same-day-round-trip guard.

A session fill is a paper fill: nothing reaches a broker. The order goes through `paper.book.place` and `paper.book.fill` (charges, FIFO lots, tax, the fake bank and the
rails are the book's own); this module only decides the PRICE and whether the order may be filled today.

MODEL `liquidity_v1` (an ASSUMPTION, stated here and in `configs/core.toml [fills]`; there is no real fill record yet to calibrate it against):
    adv              the name's average traded value (close x volume summed over the minute bars of each session) over its last `adv_days` sessions
    half_spread_bps  from `half_spread_illiquid_bps` (adv at or under `illiquid_adv_rupees`) to `half_spread_liquid_bps` (adv at or over `liquid_adv_rupees`), linear in log(adv)
    slippage_bps     impact_bps * sqrt(order value / adv), at least `min_slippage_bps`  (the square-root impact law: it grows with the order's share of the day's turnover)
    price            quote * (1 + (half_spread_bps + slippage_bps) / 10000) for a buy, quote * (1 - ...) for a sell, rounded to the paisa AGAINST the order
    unknown          no minute history: `unknown_half_spread_bps` and a participation of `unknown_participation` of the order against an assumed adv equal to order / participation
The price is worse than the quote by at least half the modelled spread plus the slippage, always.

THE GUARD: a buy and a sell of the same shares in one name on one day is speculative business income in India and is the intraday strategy the investor dropped (A48, A54). So
    a SELL may not touch shares bought today (FIFO sells the oldest shares first, so only a sale larger than the shares held before today would), and
    a BUY may not follow a sale of the same name today.
A refused part is QUEUED to the next session by the caller. A STOP is the one exception: it fills (a loss cut is not to wait overnight), and the day is flagged in the record.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

DEFAULTS = {
    "adv_days": 20, "liquid_adv_rupees": 1.0e9, "illiquid_adv_rupees": 1.0e7, "half_spread_liquid_bps": 1.0, "half_spread_illiquid_bps": 25.0,
    "impact_bps": 25.0, "min_slippage_bps": 0.5, "unknown_half_spread_bps": 15.0, "unknown_participation": 0.01, "max_participation": 0.10,
}
SESSION_DEFAULTS = {
    "on": True, "every_minutes": 5, "no_entry_minutes": 15, "vwap_band": 0.005, "volume_fraction": 0.5, "volume_minutes": 5, "typical_days": 20,
    "views_in_session": True, "thesis_min_severity": "high", "fallback_stop_pct": 8.0, "fallback_target_pct": 15.0, "fallback_time_sessions": 20, "report_at": "15:45",
}


def _section(name: str, defaults: dict) -> dict:
    out = dict(defaults)
    try:
        from pflab import _toml, core
        out.update({k: v for k, v in (_toml.load(core.CONFIG).get(name) or {}).items() if k in defaults})
    except Exception:
        pass
    return out


def settings(con=None, market: str = "IN") -> dict:
    """`[fills]` of configs/core.toml over the defaults (an unreadable file leaves the defaults). With `con`, the three calibrated numbers (S82 C8) of the latest ACCEPTED row of
    `fills_calibration_s82` replace the file's values (always held inside `bounds()`); no accepted row, or an unreadable table, leaves the file's values."""
    c = _section("fills", DEFAULTS)
    if con is not None:
        c.update(calibrated_values(con, market))
    return c


# --- the calibration of the three fitted numbers (S82 C8; the fit itself is `core/fills_cal.py`) -------------------------------------------

FITTED = ("half_spread_liquid_bps", "half_spread_illiquid_bps", "impact_bps")
MIN_REAL_FILLS = 30
BOUND_FACTORS = (0.5, 3.0)                       # each fitted number stays within 0.5x to 3x of the configured default ...
BOUND_FLOORS = {"half_spread_liquid_bps": 0.5, "half_spread_illiquid_bps": 0.5, "impact_bps": 5.0}      # ... and never under 0.5 bp of spread or 5 bp of impact


def bounds(base: Optional[dict] = None) -> Dict[str, tuple]:
    """{name: (low, high)} of the fitted numbers around the configured defaults."""
    b = base or _section("fills", DEFAULTS)
    return {k: (max(BOUND_FLOORS[k], BOUND_FACTORS[0] * float(b[k])), BOUND_FACTORS[1] * float(b[k])) for k in FITTED}


def _latest_accepted(con, market: str = "IN") -> Optional[dict]:
    try:
        r = con.execute("SELECT cal_id, made_at, n_used, new_json FROM fills_calibration_s82 WHERE market=? AND accepted ORDER BY cal_id DESC LIMIT 1", [market]).fetchone()
    except Exception:
        return None
    if not r:
        return None
    try:
        vals = json.loads(r[3] or "{}")
    except Exception:
        return None
    return {"cal_id": r[0], "made_at": r[1], "n_fills": r[2], "values": vals}


def calibrated_values(con, market: str = "IN") -> dict:
    """The fitted numbers of the latest accepted calibration, each clamped to `bounds()` (so no stored row can break the model); {} when there is none."""
    row = _latest_accepted(con, market)
    if not row:
        return {}
    bd, out = bounds(), {}
    for k in FITTED:
        v = row["values"].get(k)
        if isinstance(v, (int, float)) and math.isfinite(v):
            out[k] = min(bd[k][1], max(bd[k][0], float(v)))
    return out


def real_fill_count(con, market: str = "IN") -> int:
    """Fills recorded from a LIVE Kite quote (source 'live'); tests, drills, replays and simulations never count."""
    try:
        return int(con.execute("SELECT count(*) FROM session_fills_s81 WHERE market=? AND source='live'", [market]).fetchone()[0])
    except Exception:
        return 0


def calibration_status(con, market: str = "IN") -> dict:
    """What Today shows about the fill-cost model: {'source': 'calibrated' | 'defaults', 'n_fills', 'values', 'as_of', 'text'}. 'defaults' counts the real fills so far."""
    row = _latest_accepted(con, market)
    vals = settings(con, market)
    values = {k: round(float(vals[k]), 3) for k in FITTED}
    if row:
        return {"source": "calibrated", "n_fills": int(row["n_fills"] or 0), "values": values, "as_of": str(row["made_at"])[:10],
                "text": f"Fill costs: calibrated from {int(row['n_fills'] or 0)} real fills on {str(row['made_at'])[:10]} "
                        f"(half spread {values['half_spread_liquid_bps']:.1f} bp liquid to {values['half_spread_illiquid_bps']:.1f} bp illiquid, impact {values['impact_bps']:.1f} bp)."}
    n = real_fill_count(con, market)
    return {"source": "defaults", "n_fills": n, "values": values, "as_of": None,
            "text": f"Fill costs: the assumed defaults (not yet calibrated: {n} of {MIN_REAL_FILLS} real fills so far)."}


def session_settings() -> dict:
    """`[session]` of configs/core.toml over the defaults."""
    return _section("session", SESSION_DEFAULTS)


# --- liquidity: the average traded value and the typical minute volume ---------------------------------------------------------------------

def _bars(con, isin: str, start: date, end: date, root: Optional[Path], market: str, data_dir: Optional[Path] = None) -> pd.DataFrame:
    from pflab.ingest import kite_backfill as kb
    from pflab.paper import book
    key = book.inst(con, isin)["symbol"] or isin
    try:
        return kb.read(market, key, start, end, root=root, con=con, data_dir=data_dir)
    except Exception:
        return pd.DataFrame(columns=kb.COLS)


def liquidity(con, isin: str, day: date, market: str = "IN", root: Optional[Path] = None, force: bool = False) -> dict:
    """{'adv_rupees', 'typical_minute_volume', 'sessions', 'source'} from the minute bars of the sessions BEFORE `day` (point-in-time), stored once a day in `session_adv_s81`.
    None values when the name has no minute history."""
    if not force:
        r = con.execute("SELECT adv_rupees, typical_minute_volume, sessions, source FROM session_adv_s81 WHERE market=? AND isin=? AND as_of_day=?", [market, isin, day]).fetchone()
        if r:
            return {"adv_rupees": r[0], "typical_minute_volume": r[1], "sessions": r[2], "source": r[3]}
    cfg_f, cfg_s = settings(), session_settings()
    n = max(int(cfg_f["adv_days"]), int(cfg_s["typical_days"]))
    df = _bars(con, isin, day - timedelta(days=int(n * 1.7) + 7), day - timedelta(days=1), root, market)
    out = {"adv_rupees": None, "typical_minute_volume": None, "sessions": 0, "source": "none"}
    if len(df):
        df = df.assign(d=pd.to_datetime(df["ts"]).dt.date, t=pd.to_datetime(df["ts"]).dt.time, val=df["close"] * df["volume"])
        days = sorted(df["d"].unique())[-n:]
        df = df[df["d"].isin(days)]
        per_day = df.groupby("d")["val"].sum()
        mid = df[(df["t"] >= time(9, 30)) & (df["t"] < time(15, 0))]
        out = {"adv_rupees": float(per_day.tail(int(cfg_f["adv_days"])).mean()),
               "typical_minute_volume": float(mid["volume"].tail(int(cfg_s["typical_days"]) * 330).mean()) if len(mid) else None,
               "sessions": len(days), "source": "minute bars"}
    con.execute("INSERT OR REPLACE INTO session_adv_s81 VALUES (?,?,?,?,?,?,?)", [market, isin, day, out["adv_rupees"], out["typical_minute_volume"], out["sessions"], out["source"]])
    return out


# --- the price model -------------------------------------------------------------------------------------------------------------------------

def model(order_rupees: float, adv_rupees: Optional[float], cfg: Optional[dict] = None) -> dict:
    """The spread and slippage (in basis points) of an order of `order_rupees` in a name that trades `adv_rupees` a day. Pure; the function of the module docstring."""
    c = cfg or settings()
    if not adv_rupees or adv_rupees <= 0:
        part = float(c["unknown_participation"])
        slip = max(float(c["min_slippage_bps"]), float(c["impact_bps"]) * math.sqrt(part))
        return {"half_spread_bps": float(c["unknown_half_spread_bps"]), "slippage_bps": slip, "participation": part, "adv_rupees": None, "adv_known": False}
    hi, lo = float(c["liquid_adv_rupees"]), float(c["illiquid_adv_rupees"])
    x = (math.log(adv_rupees) - math.log(lo)) / (math.log(hi) - math.log(lo))
    x = min(1.0, max(0.0, x))
    half = float(c["half_spread_illiquid_bps"]) + (float(c["half_spread_liquid_bps"]) - float(c["half_spread_illiquid_bps"])) * x
    part = max(0.0, order_rupees) / adv_rupees
    slip = max(float(c["min_slippage_bps"]), float(c["impact_bps"]) * math.sqrt(part))
    return {"half_spread_bps": half, "slippage_bps": slip, "participation": part, "adv_rupees": float(adv_rupees), "adv_known": True}


def price_for(side: str, quote: float, m: dict) -> float:
    """The paper price: the quote moved AGAINST the order by half the spread plus the slippage, rounded to the paisa against the order (never better than the quote)."""
    move = (m["half_spread_bps"] + m["slippage_bps"]) / 10000.0
    if side == "buy":
        return max(round(math.ceil(quote * (1 + move) * 100 - 1e-9) / 100, 2), quote)
    return min(round(math.floor(quote * (1 - move) * 100 + 1e-9) / 100, 2), quote)


# --- the guard -------------------------------------------------------------------------------------------------------------------------------

def _today_qty(con, isin: str, day: date, side: str) -> float:
    return float(con.execute("SELECT coalesce(sum(qty), 0) FROM paper_trades WHERE isin=? AND day=? AND side=?", [isin, day, side]).fetchone()[0])


def round_trip(con, isin: str, side: str, qty: float, day: date) -> dict:
    """{'allowed_qty', 'blocked_qty', 'why'} for an order of `qty` shares today (see the module docstring). `allowed_qty` is `qty` when there is nothing to guard."""
    from pflab.paper import book
    if side == "sell":
        held, bought = book.positions(con).get(isin, 0.0), _today_qty(con, isin, day, "buy")
        sellable = max(0.0, held - min(bought, held))
        allowed = min(float(qty), sellable)
        if bought > 0 and allowed < qty - 1e-9:
            return {"allowed_qty": allowed, "blocked_qty": float(qty) - allowed,
                    "why": f"{bought:,.0f} share(s) of this name were bought today: selling them today would be a same-day round trip (speculative income in India, the dropped intraday strategy); "
                           f"{float(qty) - allowed:,.0f} share(s) wait for the next session"}
    elif side == "buy" and _today_qty(con, isin, day, "sell") > 0:
        return {"allowed_qty": 0.0, "blocked_qty": float(qty), "why": "this name was sold today: buying it back today would be a same-day round trip; the buy waits for the next session"}
    return {"allowed_qty": float(qty), "blocked_qty": 0.0, "why": ""}


# --- the fill --------------------------------------------------------------------------------------------------------------------------------

def _decision(con, now: datetime, isin: str, side: str, qty: Optional[float], amount: Optional[float], reason: str, quote: float, day: date) -> Optional[int]:
    """A paper_decisions row (the record every order has, scored later like the close loop's), its claims registered. Never allowed to stop a fill."""
    try:
        from pflab.paper import book, manager
        from pflab.pm.store import next_id
        held = book.positions(con).get(isin, 0.0)
        px = book.close_on(con, isin, day)
        if side == "buy":
            action, fraction = ("ADD" if held > 0 else "BUY"), None
        else:
            fraction = min(1.0, (qty or held) / held) if held > 0 else 1.0
            action = "SELL" if fraction >= 0.999 else "REDUCE"
        did = next_id(con, "paper_decisions", "decision_id")
        con.execute("INSERT INTO paper_decisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [did, now, None, action, isin, book.inst(con, isin)["symbol"], amount, fraction, reason[:1500], "wait for the close loop", None, None, "executed",
                     "placed by the session loop; filled at the live quote", px[0] if px else None, px[1] if px else None, None, now])
        manager.register(con, did)
        return did
    except Exception:
        return None


def execute(con, now: datetime, isin: str, side: str, *, quote: float, qty: Optional[float] = None, amount: Optional[float] = None, kind: str = "", reason: str = "",
            plan_id: Optional[int] = None, market: str = "IN", root: Optional[Path] = None, liq: Optional[dict] = None, bypass_guard: bool = False, cfg: Optional[dict] = None, source: str = "sim") -> dict:
    """Place and fill ONE paper order at `quote` (a live quote) plus the liquidity model's spread and slippage. A buy is given as `amount` rupees (or `qty`), a sell as `qty`.
    Returns {'status': 'filled' | 'held' | 'partial' | 'not_filled', 'qty', 'price', 'quote', 'half_spread_bps', 'slippage_bps', 'cost_rupees', 'blocked_qty', 'flag', 'why', ...}.
    'held': the guard refused it today (the caller queues it); 'partial': part was filled and `blocked_qty` waits. `bypass_guard` (a stop only) fills anyway and flags the day.
    `source` says where the quote came from: only 'live' (a live Kite quote in the app's session loop) counts as a REAL fill for the calibration; the default 'sim' is a test, drill or simulation."""
    from pflab.paper import book
    from pflab.pm.store import next_id
    if not quote or quote <= 0:
        return {"status": "not_filled", "why": "no valid quote"}
    day = now.date()
    meta = book.inst(con, isin)
    want_qty = float(qty) if qty else (math.floor(float(amount) / quote) if amount else 0.0)
    if side == "sell":
        held = book.positions(con).get(isin, 0.0)
        want_qty = min(want_qty if want_qty else held, held)
        if want_qty <= 1e-9:
            return {"status": "not_filled", "why": "nothing held"}
    elif want_qty <= 0:
        return {"status": "not_filled", "why": "the amount buys less than one share at this quote"}
    g = round_trip(con, isin, side, want_qty, day)
    flag, blocked = None, 0.0
    if g["blocked_qty"] > 1e-9:
        if bypass_guard:
            flag = "same-day round trip: its stop fired, so it fills (flagged)"
        elif g["allowed_qty"] <= 1e-9:
            return {"status": "held", "qty": 0.0, "blocked_qty": g["blocked_qty"], "why": g["why"]}
        else:
            want_qty, blocked = g["allowed_qty"], g["blocked_qty"]
    liq = liq if liq is not None else liquidity(con, isin, day, market, root)
    c = cfg or settings(con, market)
    m = model(want_qty * quote, (liq or {}).get("adv_rupees"), c)
    px = price_for(side, quote, m)
    flags = [flag] if flag else []
    if m["participation"] > float(c["max_participation"]):
        flags.append(f"the order is {m['participation']:.1%} of a day's turnover: the slippage model is extrapolating")
    if not m["adv_known"]:
        flags.append("no minute history: the unknown-liquidity assumption was charged")
    why = reason or f"{kind} order"
    did = _decision(con, now, isin, side, want_qty if side == "sell" else None, want_qty * quote if side == "buy" else None, f"session loop ({kind}): {why}", quote, day)
    oid = book.place(con, now, did, isin, side, qty=want_qty, amount=None,
                     note=f"session {kind}: quote {quote:,.2f}, price {px:,.2f}")
    done = book.fill(con, day, now, live={isin: px}, exact=True, only={oid})
    if not done:
        r = con.execute("SELECT status, note FROM paper_orders WHERE order_id=?", [oid]).fetchone()
        if r and r[0] == "open":                                   # nothing could fill it (no live path): do not leave a stray open order behind
            con.execute("UPDATE paper_orders SET status='cancelled', note=coalesce(note,'') || ' | the session fill did not apply' WHERE order_id=?", [oid])
        return {"status": "not_filled", "why": (r[1] or "").strip(" |") if r else "the book did not fill it", "order_id": oid, "quote": quote, "price": px}
    t = con.execute("SELECT trade_id, qty, price, charges, realised, tax FROM paper_trades WHERE order_id=? ORDER BY trade_id DESC LIMIT 1", [oid]).fetchone()
    tid, fq, fpx, fee, realised, tax = t
    cost = (fpx - quote) * fq if side == "buy" else (quote - fpx) * fq
    fid = next_id(con, "session_fills_s81", "fill_id")
    con.execute("INSERT INTO session_fills_s81 (fill_id, ts, market, day, isin, symbol, side, qty, quote, price, half_spread_bps, slippage_bps, adv_rupees, order_rupees, participation, "
                "cost_rupees, kind, plan_id, reason, flag, order_id, trade_id, decision_id, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [fid, now, market, day, isin, meta["symbol"], side, float(fq), float(quote), float(fpx), m["half_spread_bps"], m["slippage_bps"], m["adv_rupees"], float(fq * fpx),
                 m["participation"], float(cost), kind, plan_id, why[:500], "; ".join(flags) or None, oid, tid, did, source])
    status = "partial" if blocked > 1e-9 else "filled"
    return {"status": status, "fill_id": fid, "order_id": oid, "trade_id": tid, "decision_id": did, "qty": float(fq), "price": float(fpx), "quote": float(quote),
            "half_spread_bps": m["half_spread_bps"], "slippage_bps": m["slippage_bps"], "participation": m["participation"], "cost_rupees": float(cost), "charges": float(fee),
            "tax": float(tax) if tax is not None else None, "blocked_qty": blocked, "flag": "; ".join(flags) or None, "why": g["why"] if blocked else "", "side": side, "isin": isin}
