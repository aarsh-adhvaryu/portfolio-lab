"""Fractional multi-asset FIFO lots, one queue per (account, isin) (PLAN §3).

Cost per unit includes buy-side fees; sale proceeds are net of sell-side fees:
the same convention as `pflab.tax.india_lots` (parity-tested), so an equity
history gives identical gains in both. Holding-period and tax-rule decisions
are NOT made here (S12); a `Consumption` carries the dates and amounts.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from typing import Deque, Dict, List, Optional, Tuple

EPS = 1e-9  # unit dust: a lot smaller than this is gone
WHOLE_TOL = 1e-6  # an entitlement this close to a whole number IS that number (300 x 1/3)


class LotError(ValueError):
    pass


@dataclass
class Lot:
    lot_id: int
    account_id: str
    isin: str
    acq_date: date
    qty: float
    cost_per_unit: float
    tax_class: Optional[str] = None
    origin_event: int = 0

    @property
    def cost(self) -> float:
        return self.qty * self.cost_per_unit


@dataclass(frozen=True)
class Fraction:
    """A fractional entitlement left by a whole-share action; the company pays cash in
    lieu, which is a disposal measured from `acq_date` against `basis`."""
    account_id: str
    isin: str
    units: float
    basis: float
    acq_date: date


@dataclass(frozen=True)
class Consumption:
    """One lot (or part of one) consumed by a sale."""
    lot_id: int
    account_id: str
    isin: str
    acq_date: date
    sell_date: date
    qty: float
    proceeds: float   # net of sell-side fees
    cost: float       # incl. buy-side fees
    tax_class: Optional[str]
    event_id: int

    @property
    def gain(self) -> float:
        return self.proceeds - self.cost

    @property
    def holding_days(self) -> int:
        return (self.sell_date - self.acq_date).days


class LotBook:
    def __init__(self):
        self._q: Dict[Tuple[str, str], Deque[Lot]] = defaultdict(deque)
        self._next = 1
        self.consumed: List[Consumption] = []
        self.history: List[tuple] = []  # (lot_id, kind, detail): the lot_events trail
        self.fractions: List[Fraction] = []

    def _new_id(self) -> int:
        i, self._next = self._next, self._next + 1
        return i

    # --- positions -------------------------------------------------------
    def buy(self, account_id: str, isin: str, d: date, qty: float, price: float,
            fees: float = 0.0, tax_class: Optional[str] = None, event_id: int = 0) -> Lot:
        if qty <= 0:
            raise LotError("qty must be positive")
        lot = Lot(self._new_id(), account_id, isin, d, qty, (qty * price + fees) / qty,
                  tax_class, event_id)
        self._q[(account_id, isin)].append(lot)
        self.history.append((lot.lot_id, "open", {"qty": qty, "date": d}))
        return lot

    def sell(self, account_id: str, isin: str, d: date, qty: float, price: float,
             fees: float = 0.0, event_id: int = 0) -> List[Consumption]:
        if qty <= 0:
            raise LotError("qty must be positive")
        held = self.holdings(account_id, isin)
        if qty > held + EPS:
            raise LotError(f"cannot sell {qty} of {isin} in {account_id}; holding {held}")
        net_ps = (qty * price - fees) / qty
        q, remaining, out = self._q[(account_id, isin)], qty, []
        while remaining > EPS and q:
            lot = q[0]
            take = min(lot.qty, remaining)
            c = Consumption(lot.lot_id, account_id, isin, lot.acq_date, d, take, take * net_ps,
                            take * lot.cost_per_unit, lot.tax_class, event_id)
            out.append(c)
            self.consumed.append(c)
            self.history.append((lot.lot_id, "consume", {"qty": take, "date": d}))
            lot.qty -= take
            remaining -= take
            if lot.qty <= EPS:
                q.popleft()
        return out

    def transfer(self, from_account: str, to_account: str, isin: str, d: date, qty: float,
                 event_id: int = 0) -> List[Lot]:
        """Move units in kind: acquisition date, cost and tax class travel with them."""
        if from_account == to_account:
            raise LotError("transfer needs two different accounts")
        held = self.holdings(from_account, isin)
        if qty > held + EPS:
            raise LotError(f"cannot transfer {qty} of {isin} from {from_account}; holding {held}")
        q, remaining, moved = self._q[(from_account, isin)], qty, []
        while remaining > EPS and q:
            lot = q[0]
            take = min(lot.qty, remaining)
            new = Lot(self._new_id(), to_account, isin, lot.acq_date, take, lot.cost_per_unit,
                      lot.tax_class, event_id)
            self._q[(to_account, isin)].append(new)
            self.history.append((lot.lot_id, "transfer_out", {"qty": take, "to": to_account}))
            self.history.append((new.lot_id, "transfer_in", {"qty": take, "from": from_account}))
            moved.append(new)
            lot.qty -= take
            remaining -= take
            if lot.qty <= EPS:
                q.popleft()
        return moved

    # --- generic adjustments used by corporate actions (S11) --------------
    def scale_units(self, account_id: str, isin: str, factor: float) -> None:
        """Units x factor, total cost unchanged (split/consolidation without fractions)."""
        if factor <= 0:
            raise LotError("factor must be positive")
        for lot in self._q.get((account_id, isin), ()):
            lot.qty *= factor
            lot.cost_per_unit /= factor
            self.history.append((lot.lot_id, "scale", {"factor": factor}))

    def scale_whole(self, account_id: str, isin: str, factor: float) -> float:
        """Units / `factor` (a split has factor < 1) in whole shares. Same algorithm as
        `india_lots.LotBook.adjust_shares`: lots are walked FIFO, the fraction a lot cannot
        make whole carries into the next, a whole share formed from several lots carries
        their pooled basis and the date of the lot that completes it, and the holding's final
        fraction goes to `fractions` for cash in lieu. Returns whole units added (negative
        for a consolidation)."""
        if factor <= 0:
            raise LotError("factor must be positive")
        key = (account_id, isin)
        old = self._q.get(key)
        if not old:
            return 0.0
        before = self.holdings(account_id, isin)
        new: Deque[Lot] = deque()
        carry_u = carry_b = 0.0
        last = None
        for lot in old:
            units = carry_u + lot.qty / factor
            basis = carry_b + lot.qty * lot.cost_per_unit
            last = lot
            whole = math.floor(units + WHOLE_TOL)
            if whole > 0:
                share_basis = basis * min(1.0, whole / units)
                new.append(Lot(lot.lot_id, account_id, isin, lot.acq_date, float(whole),
                               share_basis / whole, lot.tax_class, lot.origin_event))
                carry_u, carry_b = max(0.0, units - whole), basis - share_basis
            else:
                carry_u, carry_b = units, basis
            self.history.append((lot.lot_id, "scale_whole", {"factor": factor}))
        if carry_u > WHOLE_TOL:
            self.fractions.append(Fraction(account_id, isin, carry_u, carry_b, last.acq_date))
        elif carry_b and new:
            new[-1].cost_per_unit += carry_b / new[-1].qty   # rounding dust keeps total basis exact
        self._q[key] = new
        return self.holdings(account_id, isin) - before

    def bonus(self, account_id: str, isin: str, factor: float, d: date,
              whole: bool = True, event_id: int = 0) -> float:
        """Bonus issue, `factor` = b / (a + b) for a:b. Held lots are untouched; the bonus is a
        NEW nil-cost lot dated at allotment `d` (holding period runs from allotment). Its
        fraction goes to `fractions` at nil basis. Returns units added."""
        if not 0 < factor < 1:
            raise LotError(f"bonus factor must be in (0, 1), got {factor}")
        held = self.holdings(account_id, isin)
        if held <= EPS:
            return 0.0
        units = held * (1.0 / factor - 1.0)
        n = math.floor(units + WHOLE_TOL) if whole else units
        if n > EPS:
            lot = Lot(self._new_id(), account_id, isin, d, float(n), 0.0, None, event_id)
            tc = self._q[(account_id, isin)][0].tax_class if self._q[(account_id, isin)] else None
            lot.tax_class = tc
            self._q[(account_id, isin)].append(lot)
            self.history.append((lot.lot_id, "bonus", {"qty": n, "date": d}))
        if whole and units - n > WHOLE_TOL:
            self.fractions.append(Fraction(account_id, isin, units - n, 0.0, d))
        return float(n)

    def settle_fractions(self, account_id: str, isin: str, d: date, proceeds: float,
                         event_id: int = 0) -> List[Consumption]:
        """Cash in lieu for the pending fractions of (account, isin): a disposal against each
        fraction's own basis and date. Proceeds are shared by units."""
        mine = [f for f in self.fractions if f.account_id == account_id and f.isin == isin]
        total = sum(f.units for f in mine)
        out = []
        for f in mine:
            self.fractions.remove(f)
            c = Consumption(0, account_id, isin, f.acq_date, d, f.units,
                            proceeds * f.units / total if total else 0.0, f.basis, None, event_id)
            self.consumed.append(c)
            out.append(c)
        return out

    def scale_cost(self, account_id: str, isin: str, factor: float) -> None:
        """Cost x factor, units unchanged (cash demerger / capital reduction)."""
        if not 0 < factor <= 1:
            raise LotError("cost factor must be in (0, 1]")
        for lot in self._q.get((account_id, isin), ()):
            lot.cost_per_unit *= factor
            self.history.append((lot.lot_id, "scale_cost", {"factor": factor}))

    def rekey(self, account_id: str, old_isin: str, new_isin: str) -> None:
        """ISIN change: lots keep date and cost under the successor ISIN."""
        q = self._q.pop((account_id, old_isin), None)
        if not q:
            return
        for lot in q:
            lot.isin = new_isin
            self.history.append((lot.lot_id, "rekey", {"from": old_isin, "to": new_isin}))
        self._q[(account_id, new_isin)].extend(q)

    # --- views -------------------------------------------------------------
    def holdings(self, account_id: str, isin: str) -> float:
        return float(sum(l.qty for l in self._q.get((account_id, isin), ())))

    def lots(self, account_id: str, isin: str) -> List[Lot]:
        return list(self._q.get((account_id, isin), ()))

    def all_lots(self) -> List[Lot]:
        return [l for q in self._q.values() for l in q if l.qty > EPS]

    def positions(self) -> Dict[Tuple[str, str], float]:
        return {k: q for k in list(self._q) if (q := self.holdings(*k)) > EPS}
