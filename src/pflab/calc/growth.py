"""Growth split: where did the change in portfolio value come from (PLAN S14).

    end = start + contributions + gains + income - charges + other

* contributions: deposits minus withdrawals in the period
* gains: realised (net of trade fees) + change in unrealised (open value minus cost)
* income: dividends and interest, net of TDS
* charges: non-trade charges (AMC, DP) paid in the period
* other: what is left: corporate-action cash minus the cost it removed (cash credits). Zero
  for a history without such actions; reported, never folded into gains.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pflab.calc import returns
from pflab.calc.valuation import PriceFn, value_ledger
from pflab.ledger.book import Ledger
from pflab.ledger.events import EventLog


@dataclass(frozen=True)
class Growth:
    start: date
    end: date
    start_value: float
    end_value: float
    contributions: float
    realised: float
    unrealised_change: float
    income: float
    charges: float
    other: float

    @property
    def gains(self) -> float:
        return self.realised + self.unrealised_change

    @property
    def total_change(self) -> float:
        return self.end_value - self.start_value


def growth(log: EventLog, price_fn: PriceFn, start: date, end: date) -> Growth:
    """Split the change from the close of `start` to the close of `end` (events dated in
    (start, end])."""
    a, b = Ledger.replay(log, upto=start), Ledger.replay(log, upto=end)
    va, vb = value_ledger(a, price_fn, start), value_ledger(b, price_fn, end)
    ua = float(va.positions["unrealised"].dropna().sum()) if len(va.positions) else 0.0
    ub = float(vb.positions["unrealised"].dropna().sum()) if len(vb.positions) else 0.0
    contrib = sum(x for d, _a, x in b.contributions if start < d <= end)
    realised = returns.realised_pnl(b, start + _day(), end)
    income = returns.income_total(b, start + _day(), end)
    charges = sum(f.amount for f in b.fees if start < f.date <= end and f.origin == "charge")
    other = vb.total - va.total - contrib - (realised + (ub - ua)) - income + charges
    return Growth(start, end, va.total, vb.total, contrib, realised, ub - ua, income, charges, other)


def _day():
    from datetime import timedelta
    return timedelta(days=1)
