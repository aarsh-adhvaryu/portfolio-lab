"""Cash ledger: one signed entry list per account (PLAN §3, §4 `cash_ledger`).

A balance may go negative only inside an overdraft limit that was itself
recorded as an event; otherwise posting raises. That makes a missing deposit
a loud error instead of a silent negative balance.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional

TOL = 1e-6


class CashError(ValueError):
    pass


@dataclass(frozen=True)
class CashEntry:
    account_id: str
    date: date
    amount: float   # signed: + in, - out
    kind: str
    ref: str = ""
    event_id: int = 0


class CashLedger:
    def __init__(self):
        self.entries: List[CashEntry] = []
        self._bal: Dict[str, float] = defaultdict(float)
        self._limit: Dict[str, float] = defaultdict(float)
        self._blocked: Dict[str, float] = defaultdict(float)   # IPO funds held in the account

    def set_overdraft_limit(self, account_id: str, limit: float) -> None:
        if limit < 0:
            raise CashError("limit is a positive amount")
        self._limit[account_id] = limit

    def set_blocked(self, account_id: str, amount: float) -> None:
        """Funds held against open IPO bids: inside the balance, outside what can be spent."""
        self._blocked[account_id] = max(amount, 0.0)

    def blocked(self, account_id: str) -> float:
        return float(self._blocked[account_id])

    def available(self, account_id: str) -> float:
        return float(self._bal[account_id] - self._blocked[account_id])

    def post(self, account_id: str, d: date, amount: float, kind: str, ref: str = "",
             event_id: int = 0) -> CashEntry:
        new = self._bal[account_id] + amount
        if new < -self._limit[account_id] - TOL:
            raise CashError(f"{account_id}: balance would be {new:.2f} on {d} ({kind} {ref}); "
                            f"overdraft limit {self._limit[account_id]:.2f}")
        if amount < 0 and new - self._blocked[account_id] < -self._limit[account_id] - TOL:
            raise CashError(f"{account_id}: {kind} {ref} on {d} would spend Rs {self._blocked[account_id]:,.2f} "
                            "blocked for IPO bids")
        self._bal[account_id] = new
        e = CashEntry(account_id, d, amount, kind, ref, event_id)
        self.entries.append(e)
        return e

    def balance(self, account_id: str, as_of: Optional[date] = None) -> float:
        if as_of is None:
            return float(self._bal[account_id])
        return float(sum(e.amount for e in self.entries
                         if e.account_id == account_id and e.date <= as_of))

    def accounts(self) -> List[str]:
        return sorted(self._bal)
