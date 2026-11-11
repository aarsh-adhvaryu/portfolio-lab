"""The pre-open plan (S81, A54): before a session, per market, what the day's conditional orders are and what triggers them.

    global close   the latest closes before today's open of a few world series (`PFLAB_DATA_DIR/global`): the US index, the Nikkei, the Hang Seng, USD/INR, Brent, gold, the dollar
    expected gap   the Nifty 50's gap (open against the last close) regressed on the S&P 500's last return over the last 250 sessions (numpy least squares); an ESTIMATE with its
                   fit, shown for information: it moves no order and no trigger (a rule that used it would first be a registered study, rule 10)
    orders         the exit plans' stop, target and time-stop levels (`exit_plans_s81`, or the session fallback's table), the
                   orders held over from the last session (`session_queue_s81`) and the active tactical views; each with its trigger in words
    text           written by code, with the numbers; stored in `session_plans_s81` (one row per market and session day)

`ensure_plan` builds the plan once per session day (again when the stored one is older than the pre-open window); the session loop calls it too, so an app opened after the open
still has a plan, marked `late`.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

GLOBALS = (("US_SP500", "S&P 500"), ("JP_NIKKEI225", "Nikkei 225"), ("HK_HANGSENG", "Hang Seng"), ("FX_USDINR", "USD/INR"), ("BRENT_FUT", "Brent"), ("GOLD", "gold (USD)"),
           ("DOLLAR_INDEX", "dollar index"))


def _root(data_root: Optional[Path]) -> Path:
    from pflab.data import data_dir
    return Path(data_root) if data_root else data_dir()


def _series(root: Path, sub: str, name: str) -> Optional[pd.DataFrame]:
    p = root / sub / f"{name}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    col = "adj_close" if "adj_close" in df.columns else "close"
    df = df.assign(date=pd.to_datetime(df["date"]).dt.date, level=df[col].astype(float)).dropna(subset=["level"]).sort_values("date")
    return df[["date", "level"] + [c for c in ("open", "close") if c in df.columns]].reset_index(drop=True)


def global_close(day: date, data_root: Optional[Path] = None) -> List[dict]:
    """The latest value of each world series dated BEFORE `day` (point-in-time), with its change on the session before it."""
    root, out = _root(data_root), []
    for name, label in GLOBALS:
        df = _series(root, "global", name)
        if df is None:
            continue
        df = df[df["date"] < day]
        if len(df) < 2:
            continue
        a, b = df.iloc[-2], df.iloc[-1]
        out.append({"name": label, "date": str(b["date"]), "level": float(b["level"]), "change": float(b["level"] / a["level"] - 1.0)})
    return out


def gap_estimate(day: date, data_root: Optional[Path] = None, window: int = 250) -> Optional[dict]:
    """Expected Nifty 50 gap on `day` from the S&P 500's last return (see the module docstring); None when the data are not there or too few."""
    root = _root(data_root)
    nf, sp = _series(root, "indices", "NIFTY50_PRICE"), _series(root, "global", "US_SP500")
    if nf is None or sp is None or "open" not in nf.columns:
        return None
    nf = nf[nf["date"] < day].reset_index(drop=True)
    sp = sp[sp["date"] < day].reset_index(drop=True)
    if len(nf) < 60 or len(sp) < 60:
        return None
    sp["ret"] = sp["level"].pct_change()
    nf["gap"] = nf["open"] / nf["close"].shift(1) - 1.0
    xs, ys = [], []
    sp_dates = sp["date"].values
    for r in nf.tail(window + 1).itertuples():
        if pd.isna(r.gap):
            continue
        k = np.searchsorted(sp_dates, r.date, side="left") - 1             # the last US session dated before this Indian session
        if k >= 1 and not pd.isna(sp["ret"].iloc[k]):
            xs.append(float(sp["ret"].iloc[k]))
            ys.append(float(r.gap))
    if len(xs) < 60:
        return None
    x, y = np.array(xs), np.array(ys)
    if not (np.isfinite(x).all() and np.isfinite(y).all()) or float(x.std()) == 0.0:          # a degenerate series (found by the drills): no estimate, never an error
        return None
    try:
        beta, alpha = np.polyfit(x, y, 1)
    except (np.linalg.LinAlgError, ValueError):
        return None
    resid = y - (alpha + beta * x)
    r2 = 1.0 - float(resid.var() / y.var()) if y.var() > 0 else 0.0
    last_ret = float(sp["ret"].iloc[-1])
    return {"expected_gap": float(alpha + beta * last_ret), "beta": float(beta), "alpha": float(alpha), "r2": r2, "resid_sd": float(resid.std()), "n": len(x),
            "us_return": last_ret, "us_date": str(sp["date"].iloc[-1]), "label": "estimate: least squares on the last sessions; information only, it moves no order"}


def exit_levels(con, market: str = "IN") -> List[dict]:
    """The open exit plans' levels from the exit manager's table (`exit_plans_s81`, whatever of stop / target / time stop it carries) or, while it is missing, the session fallback's."""
    rows: List[dict] = []
    try:
        cur = con.execute("SELECT * FROM exit_plans_s81")
        cols = [d[0] for d in cur.description]
        for r in cur.fetchall():
            d = dict(zip(cols, r))
            if str(d.get("status") or "open").lower() not in ("open", "active"):
                continue
            rows.append({"plan_id": d.get("plan_id"), "isin": d.get("isin"), "stop": d.get("stop_price", d.get("stop")), "target": d.get("target_price", d.get("target")),
                         "time": d.get("time_stop_on", d.get("time_stop", d.get("time_stop_date"))), "source": "exit_plans_s81"})
    except Exception:
        pass
    for pid, isin, stop, target, due in con.execute("SELECT plan_id, isin, stop_price, target_price, time_stop_on FROM session_exit_fb_s81 WHERE market=? AND status='open'", [market]).fetchall():
        rows.append({"plan_id": pid, "isin": isin, "stop": stop, "target": target, "time": due, "source": "session fallback"})
    return rows


def plan_day(now: datetime, market: str = "IN") -> date:
    """The session the plan is for: today while it has not closed, else the next one."""
    from pflab import markets
    m = markets.get(market)
    return now.date() if m.is_session(now.date()) and now < datetime.combine(now.date(), m.close) else m.next_session(now.date())


def build(con, now: datetime, market: str = "IN", day: Optional[date] = None, data_root: Optional[Path] = None) -> dict:
    from pflab.core import session
    from pflab.paper import book
    day = day or plan_day(now, market)
    sym = lambda i: book.inst(con, i)["symbol"] or i                                      # noqa: E731
    last_px = lambda i: (book.close_on(con, i, day - timedelta(days=1)) or (None, None))[1]   # noqa: E731
    orders: List[dict] = []
    for e in exit_levels(con, market):
        px = last_px(e["isin"])
        for kind, key, op in (("stop", "stop", "falls to"), ("target", "target", "rises to")):
            if e.get(key):
                orders.append({"kind": f"exit_{kind}", "isin": e["isin"], "symbol": sym(e["isin"]), "side": "sell", "level": float(e[key]), "plan_id": e["plan_id"],
                               "text": f"sell {sym(e['isin'])} if it {op} {float(e[key]):,.2f}" + (f" (last close {px:,.2f}, {float(e[key]) / px - 1:+.1%} away)" if px else "") + " [exit plan]"})
        if e.get("time"):
            orders.append({"kind": "exit_time", "isin": e["isin"], "symbol": sym(e["isin"]), "side": "sell", "level": None, "plan_id": e["plan_id"], "text": f"sell {sym(e['isin'])} at the time stop of {e['time']}"})
    for qid, isin, side, qty, kind, run_on in con.execute("SELECT queue_id, isin, side, qty, kind, run_on FROM session_queue_s81 WHERE market=? AND status='queued' AND run_on <= ?", [market, day]).fetchall():
        orders.append({"kind": "queued", "isin": isin, "symbol": sym(isin), "side": side, "level": None, "queue_id": qid,
                       "text": f"{side} {qty:,.0f} {sym(isin)} held over from an earlier session ({kind}), after 09:30"})
    for v in session._views(con, day):
        orders.append({"kind": "view", "isin": ",".join(v["names"]), "symbol": ", ".join(sym(i) for i in v["names"]), "side": "buy" if v["direction"] > 0 else "sell", "level": None, "view_id": v["view_id"],
                       "text": f"tactical view #{v['view_id']} ({'up' if v['direction'] > 0 else 'down'} on {', '.join(sym(i) for i in v['names'])}): carried out in session under the timing rules"})
    glob = global_close(day, data_root)
    gap = gap_estimate(day, data_root)
    lines = [f"Pre-open plan for {day:%a %d %b %Y} ({market}):"]
    lines.append("World before the open: " + ("; ".join(f"{g['name']} {g['change']:+.2%} ({g['date'][5:]})" for g in glob) if glob else "no world-market data to read") + ".")
    lines.append((f"Expected Nifty 50 gap about {gap['expected_gap']:+.2%} (S&P 500 {gap['us_return']:+.2%} on {gap['us_date'][5:]}; fitted on {gap['n']} sessions, R2 {gap['r2']:.2f}, typical miss {gap['resid_sd']:.2%}); "
                  "an estimate for information: it moves no order.") if gap else "Expected gap: not estimated (too little index or world data).")
    lines.append(f"{len(orders)} conditional order(s):" if orders else "No conditional order today: nothing is armed (no exit plan, trigger, held-over order or view).")
    lines += [f"- {o['text']}" for o in orders[:12]] + ([f"- ... and {len(orders) - 12} more"] if len(orders) > 12 else [])
    lines.append("Timing rule for entries: not in the first 15 minutes, within the VWAP band, with the volume of the last minutes near its typical; a stop fires at any time.")
    return {"market": market, "day": day, "global": glob, "gap": gap, "orders": orders, "text": "\n".join(lines)}


def get_plan(con, market: str, day: date) -> Optional[dict]:
    r = con.execute("SELECT made_at, late, n_orders, text FROM session_plans_s81 WHERE market=? AND day=?", [market, day]).fetchone()
    return {"made_at": r[0], "late": bool(r[1]), "n_orders": r[2], "text": r[3]} if r else None


def ensure_plan(con, now: datetime, market: str = "IN", force: bool = False, root: Optional[Path] = None) -> dict:
    """Make the plan of the next (or running) session when it has none, or when the stored one is older than the pre-open window; says what it did."""
    from pflab import markets
    m = markets.get(market)
    day = plan_day(now, market)
    old = con.execute("SELECT made_at FROM session_plans_s81 WHERE market=? AND day=?", [market, day]).fetchone()
    start = datetime.combine(day, m.open) - timedelta(hours=m.pre_open_hours)
    if old and not force and not (old[0] < start <= now):
        return {"day": str(day), "kept": True, "made_at": str(old[0])}
    p = build(con, now, market, day=day, data_root=root)
    late = now >= datetime.combine(day, m.open)
    con.execute("INSERT OR REPLACE INTO session_plans_s81 VALUES (?,?,?,?,?,?,?,?,?)",
                [market, day, now, late, json.dumps(p["global"]), json.dumps(p["gap"]), json.dumps(p["orders"], default=str), len(p["orders"]), p["text"]])
    return {"day": str(day), "made": True, "late": late, "orders": len(p["orders"])}
