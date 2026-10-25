"""Realised and unrealised P&L, income, XIRR and time-weighted return (PLAN S14).

External flows are deposits and withdrawals only: dividends, interest, sale proceeds and
charges stay inside the portfolio. XIRR follows `pflab.eval.metrics.xirr` (money in is
negative); TWR is the unitized NAV from `metrics.unitized_nav`.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from pflab.calc.valuation import PriceFn, value_ledger
from pflab.eval import metrics
from pflab.ledger.book import Ledger
from pflab.ledger.events import EventLog
from pflab.tax.india_lots import fy_of


def realised_pnl(led: Ledger, start: Optional[date] = None, end: Optional[date] = None) -> float:
    """Realised gain before tax, net of buy and sell fees, for sales dated in [start, end]."""
    return float(sum(c.gain for c in led.realised
                     if (start is None or c.sell_date >= start) and (end is None or c.sell_date <= end)))


def realised_by_fy(led: Ledger) -> Dict[int, float]:
    out: Dict[int, float] = {}
    for c in led.realised:
        out[fy_of(c.sell_date)] = out.get(fy_of(c.sell_date), 0.0) + c.gain
    return dict(sorted(out.items()))


def income_total(led: Ledger, start: Optional[date] = None, end: Optional[date] = None,
                 kind: Optional[str] = None, net: bool = True) -> float:
    return float(sum((i.net if net else i.gross) for i in led.income
                     if (start is None or i.date >= start) and (end is None or i.date <= end)
                     and (kind is None or i.kind == kind)))


def income_by_fy(led: Ledger, kind: Optional[str] = None) -> Dict[int, dict]:
    out: Dict[int, dict] = {}
    for i in led.income:
        if kind and i.kind != kind:
            continue
        r = out.setdefault(fy_of(i.date), {"gross": 0.0, "tds": 0.0, "net": 0.0})
        r["gross"] += i.gross
        r["tds"] += i.tds
        r["net"] += i.net
    return dict(sorted(out.items()))


def unrealised_pnl(led: Ledger, price_fn: PriceFn, asof: date) -> float:
    """Open-lot value minus cost; unpriced positions are left out (see `value_ledger`)."""
    v = value_ledger(led, price_fn, asof)
    return float(v.positions["unrealised"].dropna().sum()) if len(v.positions) else 0.0


# --- external flows, XIRR, TWR --------------------------------------------------------------------

def external_flows(led: Ledger, start: Optional[date] = None, end: Optional[date] = None) -> List[Tuple[date, float]]:
    """(date, signed amount) deposits +, withdrawals -, summed per day."""
    agg: Dict[date, float] = {}
    for d, _acc, amt in led.contributions:
        if (start is None or d >= start) and (end is None or d <= end):
            agg[d] = agg.get(d, 0.0) + amt
    return sorted((d, a) for d, a in agg.items() if abs(a) > 1e-9)      # a net-zero day is no flow


def xirr(led: Ledger, end_value: float, asof: date, start: Optional[date] = None,
         start_value: float = 0.0) -> float:
    """Money-weighted annual return over [start, asof]. `start_value` is the portfolio value on
    `start` (treated as money in on that date); deposits and withdrawals in (start, asof]."""
    dates, amts = [], []
    if start is not None and start_value:
        dates.append(start)
        amts.append(-start_value)
    for d, a in external_flows(led, start if start is None else start + timedelta(days=1), asof):
        dates.append(d)
        amts.append(-a)
    dates.append(asof)
    amts.append(end_value)
    order = sorted(range(len(dates)), key=lambda i: dates[i])
    return metrics.xirr([dates[i] for i in order], [amts[i] for i in order])


def value_series(log: EventLog, price_fn: PriceFn, dates: Iterable[date]) -> Tuple[pd.Series, pd.Series]:
    """Total portfolio value (invested + cash) on each date, and the external flow on it.
    Replays the log once, applying events up to each date."""
    ds = sorted(dates)
    events = log.ordered()
    led, k = Ledger(), 0
    vals, flows = {}, {}
    prev = None
    for d in ds:
        while k < len(events) and events[k].date <= d:
            led.apply(events[k])
            k += 1
        vals[d] = value_ledger(led, price_fn, d).total
        flows[d] = sum(a for dd, _acc, a in led.contributions if (prev is None or dd > prev) and dd <= d) \
            if prev is not None else 0.0
        prev = d
    return pd.Series(vals), pd.Series(flows)


def twr(values: pd.Series, flows: pd.Series) -> pd.Series:
    """Unitized NAV (base 100) from total values and external flows (a flow on a date is
    treated as arriving at the start of that date, as `unitized_nav` does)."""
    return metrics.unitized_nav(values, flows)
