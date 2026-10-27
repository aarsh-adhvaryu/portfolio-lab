"""The opportunity pot (S64 Phase 5 item 4; the investor 2026-10-25: IPOs and missed winners are a small separate pot with
its own limit; each idea has a reason, a buy price, an exit and a score).

    limit          proposed by code at 5% of equity, cut to the room the equity targets leave; applied only after his yes
    add_idea       the brain gives the stock and the reason in words; the buy price, the exit, the stop and the amount come
                   from code (the buy zone and the calibrated price ranges), the amount at most the room left in the pot
    ipo_candidates new NSE listings enter as ideas after 20 sessions of prices
    score_due      at the horizon: the return since the idea, and the return in excess of the market through the stock's
                   CAPM beta, both by code
An idea is information for him, never an order; the guards check the pot's limit.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Optional

import numpy as np
import pandas as pd

SHARE_OF_EQUITY = 0.05
IPO_MIN_SESSIONS = 20
IPO_WINDOW_DAYS = 180
HORIZON_DEFAULT = 180


def limit_amount(equity_value: float, room_to_target: float) -> float:
    """5% of equity, never more than the room the equity targets leave (rupees)."""
    return max(0.0, min(SHARE_OF_EQUITY * equity_value, room_to_target))


def propose_limit(con, now: datetime, equity_value: float, room_to_target: float) -> Optional[int]:
    from pflab.risk import themes
    lim = limit_amount(equity_value, room_to_target)
    if lim <= 0:
        return None
    return themes.propose(con, "pot_limit", "pot", round(lim, 0),
                          {"equity_value": equity_value, "room_to_target": room_to_target, "share": SHARE_OF_EQUITY},
                          f"Opportunity pot for IPOs and missed winners: up to Rs {lim:,.0f} (5% of your equity, cut to what your "
                          "targets leave). Each idea would come with a reason, a buy price, an exit and a score.", now)


def used(con) -> float:
    return float(con.execute("SELECT coalesce(sum(amount), 0) FROM pot_ideas WHERE status='open'").fetchone()[0])


def limit(con) -> Optional[float]:
    from pflab.risk import themes
    return themes.applied(con, "pot_limit", "pot")


def room(con) -> float:
    lim = limit(con)
    return 0.0 if lim is None else max(0.0, lim - used(con))


def young_numbers(c: pd.Series) -> dict:
    """Buy / exit / stop for a listing too young for the buy zone: the calibrated block-bootstrap ranges on what it has."""
    from pflab.quant import forecast as fc
    lr = np.diff(np.log(c.dropna().to_numpy(float)))
    r = fc.price_ranges(lr, float(c.iloc[-1]), 0.0, paths=5_000, methods=("stats_plain",))["stats_plain"]
    return {"buy_below": r[21][1], "exit_above": r[252][2], "stop_below": r[63][0],
            "how": "price ranges from the listing's own short history, no market drift (an estimate)"}


def numbers(con, root, isin: str, asof: date) -> dict:
    """buy_below, exit_above, stop_below by code. A stock with a year of prices: the buy zone and the stored ranges; younger:
    `young_numbers`. exit_above is the 80% range's top at 252 sessions, stop_below the bottom at 63."""
    from pflab.app import research
    c = research.closes(con, root, isin, asof, years=4).dropna()
    if len(c) < IPO_MIN_SESSIONS:
        raise ValueError(f"{len(c)} sessions of prices, {IPO_MIN_SESSIONS} needed")
    if len(c) < 250:
        n = young_numbers(c)
    else:
        from pflab.hq import suggestions as sg
        from pflab.quant import forecast as fc
        s = sg.numbers(con, root, isin, asof)
        method, _label = fc.serving_method(root)
        q252 = con.execute("SELECT q90 FROM forecasts WHERE use='price252' AND subject=? AND model=? ORDER BY as_of DESC LIMIT 1",
                           [isin, method]).fetchone()
        if not s["max_buy"] or not s["wrong_price"] or not q252:
            n = young_numbers(c)
        else:
            n = {"buy_below": s["max_buy"], "exit_above": float(q252[0]), "stop_below": s["wrong_price"],
                 "how": "buy zone and the stored price ranges (estimates)"}
    n["ref_close"] = float(c.iloc[-1])
    return n


def add_idea(con, root, isin: str, symbol: str, reason: str, asof: date, now: datetime, amount: Optional[float] = None,
             horizon_days: int = HORIZON_DEFAULT) -> int:
    from pflab.pm.store import next_id
    r = room(con)
    if limit(con) is None:
        raise ValueError("the pot has no limit yet: it applies after the investor's yes")
    if r <= 0:
        raise ValueError("the pot is full")
    if con.execute("SELECT 1 FROM pot_ideas WHERE isin=? AND status='open'", [isin]).fetchone():
        raise ValueError(f"{symbol} is already an open idea")
    n = numbers(con, root, isin, asof)
    amt = min(amount if amount else r, r)
    iid = next_id(con, "pot_ideas", "idea_id")
    con.execute("INSERT INTO pot_ideas (idea_id, made_at, isin, symbol, reason, ref_close, buy_below, exit_above, stop_below, "
                "amount, horizon_days, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [iid, now, isin, symbol, reason[:600], n["ref_close"], n["buy_below"], n["exit_above"], n["stop_below"], amt,
                 int(horizon_days), "open"])
    return iid


def ipo_candidates(con, root, asof: date) -> List[tuple]:
    """(isin, symbol) of NSE listings of the last 180 days with 20+ sessions of prices and no idea yet."""
    from pflab.app import research
    ld = pd.read_parquet(f"{root}/panel/listing_dates.parquet")
    recent = ld[(pd.to_datetime(ld["first_trade"]).dt.date >= asof - timedelta(days=IPO_WINDOW_DAYS))
                & (pd.to_datetime(ld["first_trade"]).dt.date <= asof)]
    names = dict(con.execute("SELECT isin, symbol FROM instruments WHERE symbol IS NOT NULL").fetchall())
    have = {i for (i,) in con.execute("SELECT isin FROM pot_ideas").fetchall()}
    out = []
    for isin in recent.index:
        if not str(isin).startswith("INE") or isin in have:
            continue
        if len(research.closes(con, root, isin, asof, years=1).dropna()) >= IPO_MIN_SESSIONS:
            out.append((isin, names.get(isin, isin)))
    return out


def score_due(con, now: datetime, root=None, index: Optional[pd.Series] = None) -> int:
    """Close each open idea past its horizon: return since the idea (paper, from the reference close) and its excess over the
    market through the CAPM beta at the time of the idea."""
    from pflab.hq import suggestions as sg
    n = 0
    for iid, isin, made, ref, h in con.execute("SELECT idea_id, isin, made_at, ref_close, horizon_days FROM pot_ideas "
                                               "WHERE status='open'").fetchall():
        due = made.date() + timedelta(days=int(h))
        if now.date() < due or not ref:
            continue
        end = sg._close_on(con, isin, due)
        if end is None:
            continue
        ret = end[1] / ref - 1.0
        vs = None
        if index is not None:
            a, b = sg._index_on(index, made.date()), sg._index_on(index, due)
            beta = sg.beta_at(isin, made.date())
            if a and b and beta is not None:
                vs = ret - beta * (b / a - 1.0)
        con.execute("UPDATE pot_ideas SET status='closed', closed_at=?, ret=?, ret_vs_market=? WHERE idea_id=?", [now, ret, vs, iid])
        n += 1
    return n
