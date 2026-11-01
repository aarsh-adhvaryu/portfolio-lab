"""The scoreboard (S65; the twin-books idea from the Q_Alpha project): is the companion any good, measured on paper with his own money flows.

Four books receive THE SAME RUPEES ON THE SAME DAYS: the deposits into and withdrawals from his broker account, from the ledger. They differ
only in what they did with the money:

    REAL     his own book: the broker account's stocks and funds at their value plus its cash, from the ledger (a fact, not a simulation)
    SYSTEM   starts as a copy of REAL on the start day; afterwards it follows ONLY the brain's own suggestions (add / trim, not journal-only
             rivals), each filled at the close of the first session after it was made, with a side's charges; a buy is limited to the
             book's cash; nothing else ever trades in it
    EW       the same rupees in the equal-weight Nifty 500 (the bar: most apparent stock-picking edge in large Indian stocks has been the
             equal-weight premium, which anyone can buy)
    N500     the same rupees in the Nifty 500 total-return index (the do-nothing floor)

Baselines invest each inflow the day it arrives and sell for an outflow. Stocks and the baselines are marked on total-return levels (dividends
reinvested); a holding with no price that day keeps its last level and is named; one with no level on the start day (a mutual fund outside
the exchange's panel) joins SYSTEM's cash and is named in `unpriced`. Before 60 sessions there is no comparison, only values (one
book over a few months is mostly timing and luck); afterwards the gaps are DESCRIPTIVE, never an "edge" (an edge is a pre-registered test).
Taxes are not modelled (the paper books never file); charges are. Nothing here trades or moves money. Run nightly by the `twin` job.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

BOOKS = ("REAL", "SYSTEM", "EW", "N500")
MIN_SESSIONS = 60
TRIM_SHARE = 0.25                     # a trim with no amount sells this share of the position
FLOW_KINDS = ("cash_transfer_in", "cash_transfer_out", "deposit", "withdrawal")


# --- facts from the ledger ------------------------------------------------------------------------------------------------------

def broker_accounts(con) -> List[str]:
    """The accounts that trade (their cash pays for buys)."""
    return [r[0] for r in con.execute("SELECT DISTINCT account_id FROM cash_ledger WHERE kind IN ('buy','sell') ORDER BY 1").fetchall()]


def flows(con, after: date, upto: date, accounts: List[str]) -> float:
    """Net money into the broker accounts from outside in (after, upto]: transfers, deposits, withdrawals; not trades, charges, income."""
    if not accounts:
        return 0.0
    r = con.execute(f"SELECT coalesce(sum(amount), 0) FROM cash_ledger WHERE account_id IN ({','.join('?' * len(accounts))}) "
                    f"AND kind IN ({','.join('?' * len(FLOW_KINDS))}) AND date > ? AND date <= ?",
                    [*accounts, *FLOW_KINDS, after, upto]).fetchone()
    return float(r[0])


def broker_cash(con, upto: date, accounts: List[str]) -> float:
    if not accounts:
        return 0.0
    return float(con.execute(f"SELECT coalesce(sum(amount), 0) FROM cash_ledger WHERE account_id IN ({','.join('?' * len(accounts))}) "
                             "AND date <= ?", [*accounts, upto]).fetchone()[0])


def real_book(con, day: date, accounts: List[str]) -> dict:
    """REAL on `day`: {'value', 'cash', 'holdings': isin -> rupees} for the broker accounts' equity-type holdings."""
    from pflab.pm import today
    n = today.build(con, day)
    p = n["positions"]
    p = p[p["account"].isin(accounts) & p["bucket"].isin(["equity", "equity_fund"]) & p["value"].notna()]
    hold = p.groupby("isin")["value"].sum().to_dict()
    cash = broker_cash(con, day, accounts)
    return {"value": float(sum(hold.values()) + cash), "cash": cash, "holdings": {k: float(v) for k, v in hold.items() if v}}


# --- prices --------------------------------------------------------------------------------------------------------------------

Levels = Callable[[List[str], date], Dict[str, float]]


def panel_levels(root) -> Levels:
    """Total-return levels for ISINs on a day from the adjusted panel (dividends in); an ISIN not in the panel has none."""
    from pflab.learner import templates as tp
    cache: Dict[str, pd.Series] = {}

    def levels(isins: List[str], day: date) -> Dict[str, float]:
        need = [i for i in isins if i not in cache]
        if need:
            w = tp.wide_panel(root, need, "2015-01-01", day.isoformat())
            for i in need:
                cache[i] = w["tr"][i].dropna() if i in w["tr"] else pd.Series(dtype=float, index=pd.DatetimeIndex([]))
        out = {}
        for i in isins:
            s = cache[i]
            s = s[s.index <= pd.Timestamp(day)]
            if len(s):
                out[i] = float(s.iloc[-1])
        return out
    return levels


def index_levels(root) -> Callable[[date], Dict[str, float]]:
    """The baselines' levels on a day: EW (equal-weight Nifty 500) and N500 (Nifty 500 TRI), carried over a day they did not trade."""
    from pflab.risk import montecarlo as mc
    h = mc.history_daily(root)
    lv = pd.DataFrame({"EW": (1 + h["stocks"]).cumprod(), "N500": (1 + h["n500"]).cumprod()})

    def at(day: date) -> Dict[str, float]:
        s = lv[lv.index <= pd.Timestamp(day)]
        return {} if s.empty else {k: float(v) for k, v in s.iloc[-1].items()}
    return at


# --- the books -------------------------------------------------------------------------------------------------------------------

def _last(con, book: str) -> Optional[tuple]:
    return con.execute("SELECT day, value, cash, holdings_json FROM twin_days WHERE book=? ORDER BY day DESC LIMIT 1", [book]).fetchone()


def _save(con, book: str, day: date, value: float, cash: float, fl: float, holdings: dict) -> None:
    con.execute("INSERT OR REPLACE INTO twin_days VALUES (?,?,?,?,?,?)", [book, day, value, cash, fl, json.dumps(holdings, sort_keys=True)])


def start(con, day: date, real: dict, levels: Levels, idx: Dict[str, float]) -> None:
    """Day one: SYSTEM is a copy of REAL (in total-return units); the baselines hold REAL's value in their index."""
    lv = levels(list(real["holdings"]), day)
    units = {i: v / lv[i] for i, v in real["holdings"].items() if lv.get(i)}
    unpriced = sum(v for i, v in real["holdings"].items() if not lv.get(i))
    _save(con, "REAL", day, real["value"], real["cash"], 0.0, real["holdings"])
    _save(con, "SYSTEM", day, real["value"], real["cash"] + unpriced, 0.0, {"units": units, "last": {i: lv[i] for i in units},
                                                                         "unpriced": sorted(i for i in real["holdings"] if not lv.get(i))})
    for b in ("EW", "N500"):
        _save(con, b, day, real["value"], 0.0, 0.0, {"units": real["value"] / idx[b], "last": idx[b]})


def _fills(con, after: date, day: date) -> List[tuple]:
    """The brain's own add / trim suggestions to fill on `day`: made after the last book day and before `day` (filled at the first close after)."""
    return con.execute("SELECT sug_id, kind, isin, amount FROM hq_suggestions WHERE NOT shadow AND kind IN ('add','trim') AND isin IS NOT NULL "
                       "AND CAST(made_at AS DATE) >= ? AND CAST(made_at AS DATE) < ? ORDER BY made_at, sug_id", [after, day]).fetchall()


def step(con, day: date, prev_day: date, real: dict, levels: Levels, idx: Dict[str, float], side_cost: float, accounts: List[str]) -> dict:
    """One session for every book. Returns the day's values."""
    fl = flows(con, prev_day, day, accounts)
    out = {}
    _save(con, "REAL", day, real["value"], real["cash"], fl, real["holdings"])
    out["REAL"] = real["value"]
    _, _, cash, hj = _last(con, "SYSTEM")
    h = json.loads(hj)
    units, last = dict(h["units"]), dict(h["last"])
    cash += fl
    orders = _fills(con, prev_day, day)
    lv = levels(sorted(set(units) | {o[2] for o in orders}), day)
    last.update({i: v for i, v in lv.items() if i in units})
    for sid, kind, isin, amount in orders:
        px = lv.get(isin)
        if not px:
            con.execute("INSERT INTO twin_trades VALUES (?,?,?,?,?,?,?,?,?)", ["SYSTEM", day, isin, kind, 0.0, 0.0, 0.0, sid, "no price: not filled"])
            continue
        if kind == "add":
            spend = min(float(amount or 0.0), cash)
            if spend <= 0:
                con.execute("INSERT INTO twin_trades VALUES (?,?,?,?,?,?,?,?,?)", ["SYSTEM", day, isin, "add", 0.0, 0.0, 0.0, sid,
                                                                                  "no cash in the book: not filled"])
                continue
            ch = spend * side_cost
            u = (spend - ch) / px
            units[isin] = units.get(isin, 0.0) + u
            last[isin] = px
            cash -= spend
            con.execute("INSERT INTO twin_trades VALUES (?,?,?,?,?,?,?,?,?)", ["SYSTEM", day, isin, "add", spend, u, ch, sid, None])
        else:
            held = units.get(isin, 0.0) * px
            if held <= 0:
                con.execute("INSERT INTO twin_trades VALUES (?,?,?,?,?,?,?,?,?)", ["SYSTEM", day, isin, "trim", 0.0, 0.0, 0.0, sid, "not held: nothing sold"])
                continue
            sell = min(float(amount) if amount else held * TRIM_SHARE, held)
            u = sell / px
            ch = sell * side_cost
            units[isin] -= u
            if units[isin] <= 1e-12:
                units.pop(isin)
            cash += sell - ch
            con.execute("INSERT INTO twin_trades VALUES (?,?,?,?,?,?,?,?,?)", ["SYSTEM", day, isin, "trim", sell, u, ch, sid, None])
    value = cash + sum(u * last.get(i, 0.0) for i, u in units.items())
    stale = sorted(i for i in units if i not in lv)
    _save(con, "SYSTEM", day, value, cash, fl, {"units": units, "last": {i: last[i] for i in units}, "stale": stale})
    out["SYSTEM"] = value
    for b in ("EW", "N500"):
        _, _, _, bj = _last(con, b)
        u = json.loads(bj)["units"] + fl / idx[b]
        _save(con, b, day, u * idx[b], 0.0, fl, {"units": u, "last": idx[b]})
        out[b] = u * idx[b]
    return out


def run(con, root, now: datetime, sessions: Optional[List[date]] = None, levels: Optional[Levels] = None,
        idx_at: Optional[Callable[[date], Dict[str, float]]] = None, real_fn=None, side_cost: Optional[float] = None) -> dict:
    """Bring every book up to the latest session with prices. The first run starts the books on that session."""
    accounts = broker_accounts(con)
    if not accounts:
        return {"skipped": "no broker account in the ledger yet"}
    idx_at = idx_at or index_levels(root)
    levels = levels or panel_levels(root)
    real_fn = real_fn or (lambda d: real_book(con, d, accounts))
    if side_cost is None:
        from pflab.hq import stocks
        side_cost = stocks.round_trip_pct(stocks.DEFAULT_ORDER) / 100 / 2
    if sessions is None:
        from pflab.risk import montecarlo as mc
        sessions = [t.date() for t in mc.history_daily(root).index]
    sessions = [d for d in sessions if d <= now.date()]
    last = _last(con, "N500")
    if last is None:
        day = sessions[-1]
        start(con, day, real_fn(day), levels, idx_at(day))
        _styles_start(con, day)
        return {"started": str(day)}
    done = []
    prev = last[0]
    _styles_start(con, prev)                                                       # an install that already has books gets the style books from its last night
    for day in [d for d in sessions if d > prev]:
        idx = idx_at(day)
        if not idx:
            continue
        fl = flows(con, prev, day, accounts)
        step(con, day, prev, real_fn(day), levels, idx, side_cost, accounts)
        _styles_step(con, day, fl, idx["N500"], side_cost)
        done.append(str(day))
        prev = day
    return {"sessions": len(done), "last": str(prev)}


# --- the style books (S75): same money, a different way of using it; kept apart from BOOKS so the scoreboard's four stay four ---------------------------

def _n500(con, upto: date) -> pd.Series:
    rows = con.execute("SELECT day, holdings_json FROM twin_days WHERE book='N500' AND day <= ? ORDER BY day", [upto]).fetchall()
    return pd.Series({pd.Timestamp(d): float(json.loads(h)["last"]) for d, h in rows}, dtype=float)


def _targets():
    try:
        from pflab.plan import targets as tg
        return tg.load()
    except Exception:
        return None


def _styles_start(con, day: date) -> None:
    from pflab.plan import styles
    if all(styles._last(con, b) is not None for b in styles.STYLES):
        return
    s = _n500(con, day)
    r = _last(con, "N500")
    if s.empty or r is None or r[0] != day:
        return
    styles.start(con, day, float(r[1]), float(s.iloc[-1]), styles.gold_on(con, day), _targets())


def _styles_step(con, day: date, fl: float, level: float, side_cost: float) -> None:
    from pflab.plan import styles
    styles.step(con, day, fl, level, styles.gold_on(con, day), index=_n500(con, day), side_cost=side_cost)


def status(con) -> dict:
    """Each book's value now and since the start; a comparison only after MIN_SESSIONS sessions (descriptive, never an edge)."""
    rows = con.execute("SELECT book, min(day), max(day), count(*) FROM twin_days WHERE book IN ('REAL','SYSTEM','EW','N500') GROUP BY book").fetchall()
    if not rows:
        return {"started": False, "note": "the scoreboard starts on the first night the app runs with a ledger"}
    out = {"started": True, "books": {}}
    n = min(r[3] for r in rows) - 1
    total_in = con.execute("SELECT coalesce(sum(flows), 0) FROM twin_days WHERE book='N500'").fetchone()[0]
    for b in BOOKS:
        r = con.execute("SELECT value FROM twin_days WHERE book=? ORDER BY day DESC LIMIT 1", [b]).fetchone()
        s = con.execute("SELECT value FROM twin_days WHERE book=? ORDER BY day LIMIT 1", [b]).fetchone()
        if r:
            out["books"][b] = {"value": round(r[0], 2), "start": round(s[0], 2)}
    first, last = min(r[1] for r in rows), max(r[2] for r in rows)
    out.update({"since": str(first), "to": str(last), "sessions": n, "money_added": round(float(total_in), 2)})
    if n < MIN_SESSIONS:
        out["note"] = (f"{n} session(s) so far: values only. A comparison is shown after {MIN_SESSIONS} sessions, and even then one book over "
                       "months is mostly timing and luck; it is a description, not an edge.")
    else:
        base = out["books"]["EW"]["value"]
        out["vs_equal_weight"] = {b: round(v["value"] - base, 2) for b, v in out["books"].items() if b != "EW"}
        out["note"] = ("All four books got the same money on the same days. The gaps are descriptive: the equal-weight Nifty 500 is the bar; "
                       "an edge is only what a pre-registered test shows.")
    from pflab.plan import styles
    out["styles"] = styles.status(con)
    out["system_trades"] = con.execute("SELECT count(*) FROM twin_trades WHERE book='SYSTEM' AND rupees > 0").fetchone()[0]
    return out
