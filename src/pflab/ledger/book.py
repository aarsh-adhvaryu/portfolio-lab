"""Ledger: replay an event log into lots, cash, income and fees (PLAN §3).

State is always derived: `Ledger.replay(log)` is the single code path, so the
database, a restore and a test all agree.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional

from pflab.ledger.cash import CashLedger
from pflab.ledger import ipo as ipo_mod
from pflab.ledger.events import Event, EventLog
from pflab.ledger.lots import Consumption, LotBook


@dataclass(frozen=True)
class Income:
    isin: Optional[str]
    account_id: str
    kind: str          # dividend | interest
    date: date
    gross: float
    tds: float
    event_id: int

    @property
    def net(self) -> float:
        return self.gross - self.tds


@dataclass(frozen=True)
class Fee:
    event_id: int
    account_id: str
    date: date
    kind: str
    amount: float
    origin: str = "trade"   # trade (inside lot cost / proceeds) | charge (paid from cash)


class Ledger:
    def __init__(self):
        self.lots = LotBook()
        self.cash = CashLedger()
        self.income: List[Income] = []
        self.fees: List[Fee] = []
        self.contributions: List[tuple] = []  # (date, account, signed amount) external flows
        self.ipo = ipo_mod.IpoBook()
        self.actions_applied: List[tuple] = []  # (isin, date, action, params, event_id, accounts)

    # --- single code path ---------------------------------------------------
    @classmethod
    def replay(cls, log: EventLog, upto: Optional[date] = None) -> "Ledger":
        """State after every event dated on or before `upto` (all events if None)."""
        led = cls()
        for e in log:
            if upto is not None and e.date > upto:
                break
            led.apply(e)
        return led

    def apply(self, e: Event) -> None:
        k = e.kind
        if k == "overdraft_limit":
            self.cash.set_overdraft_limit(e.account_id, e.amount)
        elif k == "deposit":
            self.cash.post(e.account_id, e.date, e.amount, "deposit", e.ref, e.event_id)
            self.contributions.append((e.date, e.account_id, e.amount))
        elif k == "withdrawal":
            self.cash.post(e.account_id, e.date, -e.amount, "withdrawal", e.ref, e.event_id)
            self.contributions.append((e.date, e.account_id, -e.amount))
        elif k == "buy":
            fee = e.fee_total
            self.cash.post(e.account_id, e.date, -(e.qty * e.price + fee), "buy", e.isin, e.event_id)
            self.lots.buy(e.account_id, e.isin, e.date, e.qty, e.price, e.cost_fee_total, e.tax_class, e.event_id)
            self._fees(e)
        elif k == "sell":
            fee = e.fee_total
            self.lots.sell(e.account_id, e.isin, e.date, e.qty, e.price, e.cost_fee_total, e.event_id)
            self.cash.post(e.account_id, e.date, e.qty * e.price - fee, "sell", e.isin, e.event_id)
            self._fees(e)
        elif k == "cash_transfer":
            # between two of the investor's own accounts: neither an inflow to nor an outflow from the portfolio
            self.cash.post(e.account_id, e.date, -e.amount, "cash_transfer_out", e.ref, e.event_id)
            self.cash.post(e.counter_account, e.date, e.amount, "cash_transfer_in", e.ref, e.event_id)
        elif k == "transfer":
            self.lots.transfer(e.account_id, e.counter_account, e.isin, e.date, e.qty, e.event_id)
        elif k in ("dividend", "interest"):
            tds = float(e.fees.get("tds", 0.0))
            self.income.append(Income(e.isin, e.account_id, k, e.date, e.amount, tds, e.event_id))
            self.cash.post(e.account_id, e.date, e.amount - tds, k, e.isin or "", e.event_id)
        elif k.startswith("ipo_"):
            ipo_mod.apply(self, e)
        elif k == "corp_action":
            from pflab.ledger import corporate_actions
            corporate_actions.apply(self, e)
        elif k == "charge":
            self.cash.post(e.account_id, e.date, -e.amount, "charge", e.ref, e.event_id)
            self.fees.append(Fee(e.event_id, e.account_id, e.date, e.ref or "charge", e.amount, "charge"))

    def _fees(self, e: Event) -> None:
        for kind, amt in sorted(e.fees.items()):
            if kind != "tds" and amt:
                self.fees.append(Fee(e.event_id, e.account_id, e.date, kind, amt))

    # --- views ----------------------------------------------------------------
    @property
    def realised(self) -> List[Consumption]:
        return self.lots.consumed

    def holdings(self, isin: str, account_id: Optional[str] = None) -> float:
        return float(sum(q for (a, i), q in self.lots.positions().items()
                         if i == isin and (account_id is None or a == account_id)))

    def positions(self) -> Dict[tuple, float]:
        return self.lots.positions()

    def cash_balance(self, account_id: str, as_of: Optional[date] = None) -> float:
        return self.cash.balance(account_id, as_of)

    def cash_available(self, account_id: str) -> float:
        """Balance minus funds blocked for open IPO bids."""
        return self.cash.available(account_id)

    # --- derived tables (PLAN §4) ---------------------------------------------
    def write_derived(self, con, now: Optional[datetime] = None) -> None:
        """Replace the derived tables (`lots`, `cash_ledger`, `income`, `fees`), all or nothing."""
        from pflab.pm.store import transaction
        with transaction(con):
            self._write_derived(con, now)

    def _write_derived(self, con, now: Optional[datetime] = None) -> None:
        now = now or datetime.now()
        for t in ("lots", "cash_ledger", "income", "fees"):
            con.execute(f"DELETE FROM {t}")
        for l in self.lots.all_lots():
            con.execute("INSERT INTO lots VALUES (?,?,?,?,?,?,?,?)",
                        [l.lot_id, l.account_id, l.isin, l.acq_date, l.qty, l.cost_per_unit,
                         l.tax_class, l.origin_event])
        for e in self.cash.entries:
            con.execute("INSERT INTO cash_ledger VALUES (?,?,?,?,?,?)",
                        [e.account_id, e.date, e.amount, e.kind, e.ref, e.event_id])
        for i in self.income:
            con.execute("INSERT INTO income VALUES (?,?,?,?,?,?,?,?)",
                        [i.isin, i.account_id, i.kind, i.date, i.gross, i.tds, i.net, i.event_id])
        for f in self.fees:
            con.execute("INSERT INTO fees VALUES (?,?,?,?,?)",
                        [f.event_id, f.account_id, f.date, f.kind, f.amount])
        con.execute("DELETE FROM ipo_applications")
        for a in self.ipo.apps.values():
            con.execute("INSERT INTO ipo_applications VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [a.ipo_id, a.account, a.category, a.bid_qty, a.bid_price, a.amount_blocked,
                         a.blocked_on, a.mandate_ref, a.status, a.allotted_qty, a.allotted_amount,
                         a.refund_on, a.listed_on, a.isin])
        con.execute("DELETE FROM corporate_actions_applied")
        for isin, d, act, params, eid, accts in self.actions_applied:
            con.execute("INSERT INTO corporate_actions_applied VALUES (?,?,?,?,?,?,?,?)",
                        [isin, d, act, json.dumps(params, sort_keys=True, default=str), eid, accts, now, ""])
