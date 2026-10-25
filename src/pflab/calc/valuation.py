"""Holdings, cash and whole-portfolio value (PLAN S14).

A position with no price is never valued at cost or zero: it is listed in `unpriced` and
left out of `invested`, so a missing price shows up instead of hiding in a total. Stale
prices are valued (the last known) and flagged. Dormant and read-only accounts are included
in every total (The investor, 2026-10-06) and shown separately by account.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, Optional

import pandas as pd

from pflab.ledger.book import Ledger

# price_fn(isin, asof) -> PriceInfo | None. `value` is Rs per unit held (per share, per
# gram, per bond incl. accrued interest, per fund unit).
PriceFn = Callable[[str, date], Optional["PriceInfo"]]


@dataclass(frozen=True)
class PriceInfo:
    value: float
    date: date
    kind: str            # live | close | nav | gold | bond_model
    stale: bool = False
    source: str = ""


@dataclass
class Valuation:
    asof: date
    positions: pd.DataFrame            # one row per (account, isin)
    cash: pd.DataFrame                 # one row per account
    invested: float
    cash_total: float
    cash_available: float              # cash minus blocked IPO funds (S19)
    total: float
    unpriced: List[tuple] = field(default_factory=list)   # (account, isin, qty, cost)
    stale: List[str] = field(default_factory=list)


def value_ledger(led: Ledger, price_fn: PriceFn, asof: date,
                 accounts: Optional[Dict[str, dict]] = None,
                 blocked: Optional[Dict[str, float]] = None) -> Valuation:
    """Value every open lot at `price_fn`. `accounts`: {account_id: {"dormant": bool,
    "read_only": bool}} for labelling; `blocked`: funds held against open IPO bids per account."""
    accounts, blocked = accounts or {}, blocked or {}
    rows, unpriced, stale = [], [], []
    by_key: Dict[tuple, list] = {}
    for lot in led.lots.all_lots():
        by_key.setdefault((lot.account_id, lot.isin), []).append(lot)
    for (acc, isin), lots in sorted(by_key.items()):
        qty, cost = sum(l.qty for l in lots), sum(l.cost for l in lots)
        info = price_fn(isin, asof)
        if info is None:
            unpriced.append((acc, isin, qty, cost))
            rows.append(dict(account=acc, isin=isin, qty=qty, cost=cost, price=None, price_date=None,
                             price_kind="none", stale=True, value=None, unrealised=None,
                             dormant=accounts.get(acc, {}).get("dormant", False)))
            continue
        value = qty * info.value
        if info.stale:
            stale.append(isin)
        rows.append(dict(account=acc, isin=isin, qty=qty, cost=cost, price=info.value,
                         price_date=info.date, price_kind=info.kind, stale=info.stale, value=value,
                         unrealised=value - cost, dormant=accounts.get(acc, {}).get("dormant", False)))
    pos = pd.DataFrame(rows, columns=["account", "isin", "qty", "cost", "price", "price_date",
                                      "price_kind", "stale", "value", "unrealised", "dormant"])
    crow = [dict(account=a, balance=led.cash_balance(a), blocked=blocked.get(a, 0.0),
                 available=led.cash_balance(a) - blocked.get(a, 0.0),
                 dormant=accounts.get(a, {}).get("dormant", False)) for a in led.cash.accounts()]
    cash = pd.DataFrame(crow, columns=["account", "balance", "blocked", "available", "dormant"])
    invested = float(pos["value"].dropna().sum()) if len(pos) else 0.0
    return Valuation(asof, pos, cash, invested, float(cash["balance"].sum()) if len(cash) else 0.0,
                     float(cash["available"].sum()) if len(cash) else 0.0,
                     invested + (float(cash["balance"].sum()) if len(cash) else 0.0),
                     unpriced, sorted(set(stale)))


def by_isin(v: Valuation) -> pd.DataFrame:
    """Positions summed across accounts."""
    p = v.positions
    if p.empty:
        return p
    g = p.groupby("isin", as_index=False).agg(qty=("qty", "sum"), cost=("cost", "sum"),
                                              value=("value", lambda s: s.sum(min_count=1)))
    g["unrealised"] = g["value"] - g["cost"]
    return g


# --- price function over the PM store ------------------------------------------------------

def store_price_fn(con) -> PriceFn:
    """Prices from the PM store: bonds as clean quote + accrued, physical gold at IBJA,
    SGBs and everything else at the latest close/NAV/live quote (`prices.latest_price`)."""
    from pflab.pm import bonds as bd
    from pflab.pm import gold, prices

    def fn(isin: str, asof: date) -> Optional[PriceInfo]:
        if isin.startswith("PHYS:GOLD"):
            try:
                m = gold.value_physical(con, isin, 1.0, asof)
            except LookupError:
                return None
            return PriceInfo(m["value"], m["rate_date"], "gold", m["stale"], "ibja")
        q = prices.latest_price(con, isin, asof)
        if q is None:
            return None
        b = bd.get_bond(con, isin)
        if b is not None and q.kind in ("close", "live"):
            per_bond = b.face_value * q.value / 100.0 + bd.accrued_interest(b, asof)
            return PriceInfo(per_bond, q.date, q.kind, q.stale, q.source)
        return PriceInfo(q.value, q.date, q.kind, q.stale, q.source)

    return fn
