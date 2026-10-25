"""India listed-equity capital-gains lot engine (charter E1 §8).

FIFO per ISIN; short/long split at the 12-month boundary (held for MORE
than 12 months is long-term); FY netting with statutory set-off order;
carry-forward by character; LTCG exemption; cess; dividends and cash
interest at slab. Today's regime is applied to every year: a policy
counterfactual.
"""
from __future__ import annotations

import copy
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from typing import Callable, Deque, Dict, List

from dateutil.relativedelta import relativedelta

from pflab import _toml


# A share entitlement within this of a whole number IS that whole number:
# 300 shares at a factor of 1/3 is 900.0000000001 in floating point.
_WHOLE_TOL = 1e-6


@dataclass(frozen=True)
class Fraction:
    """A fractional entitlement left by a share-count action (E1 §15,
    2026-09-27): the company pays cash in lieu, which is a disposal. `units`
    are new shares (< 1), `basis` the cost that goes with them, `buy_date`
    the date the gain is measured from. Settled by `LotBook.settle_fraction`.
    """
    isin: str
    units: float
    basis: float
    buy_date: date


@dataclass(frozen=True)
class TaxPolicy:
    stcg_rate: float = 0.20
    ltcg_rate: float = 0.125
    ltcg_exemption: float = 125_000.0
    cess: float = 0.04
    dividend_rate: float = 0.30
    # Cash-sleeve interest at slab, in the FY it accrues (E1 §15, 2026-09-27).
    # Declared conservative: taxed on accrual, as a deposit's interest is.
    interest_rate: float = 0.30
    long_term_months: int = 12
    loss_carry_years: int = 8

    @classmethod
    def from_toml(cls, path) -> "TaxPolicy":
        return cls(**_toml.load(path)["tax"])


def fy_of(d: date) -> int:
    """FY label = calendar year in which the FY ends. 2024-07-01 -> 2025 (FY2024-25)."""
    return d.year + 1 if d.month >= 4 else d.year


def fy_end(fy: int) -> date:
    return date(fy, 3, 31)


def is_long_term(buy: date, sell: date, months: int = 12) -> bool:
    """Held for MORE than `months`. Selling on the anniversary is short-term."""
    return sell > buy + relativedelta(months=months)


@dataclass
class Lot:
    isin: str
    buy_date: date
    qty: int
    cost_per_share: float  # price plus buy-side costs, per share


@dataclass(frozen=True)
class Realised:
    isin: str
    buy_date: date
    sell_date: date
    qty: int
    proceeds: float  # net of sell-side costs
    cost: float      # incl. buy-side costs
    long_term: bool

    @property
    def gain(self) -> float:
        return self.proceeds - self.cost


@dataclass
class CarriedLoss:
    origin_fy: int
    long_term: bool
    amount: float  # positive


@dataclass
class FYTax:
    fy: int
    stcg_realised: float
    ltcg_realised: float
    stcg_taxable: float
    ltcg_taxable: float  # after set-off, before exemption
    dividends: float
    tax_capital: float
    tax_dividend: float
    total: float
    carried_forward: List[CarriedLoss]
    interest: float = 0.0
    tax_interest: float = 0.0


def _net(stcg: float, ltcg: float, carried: List[CarriedLoss], fy: int, p: TaxPolicy):
    """Statutory order: current-year set-off (STCL vs STCG then LTCG; LTCL vs
    LTCG only), then brought-forward losses oldest first, then exemption."""
    st, lt = stcg, ltcg
    if st < 0 and lt > 0:
        use = min(-st, lt)
        st += use
        lt -= use
    remaining: List[CarriedLoss] = []
    for c in sorted(carried, key=lambda c: c.origin_fy):
        amt = c.amount
        if c.long_term:
            if lt > 0:
                use = min(amt, lt)
                lt -= use
                amt -= use
        else:
            if st > 0:
                use = min(amt, st)
                st -= use
                amt -= use
            if amt > 0 and lt > 0:
                use = min(amt, lt)
                lt -= use
                amt -= use
        if amt > 1e-9:
            remaining.append(CarriedLoss(c.origin_fy, c.long_term, amt))
    if st < 0:
        remaining.append(CarriedLoss(fy, False, -st))
        st = 0.0
    if lt < 0:
        remaining.append(CarriedLoss(fy, True, -lt))
        lt = 0.0
    tax = st * p.stcg_rate + max(0.0, lt - p.ltcg_exemption) * p.ltcg_rate
    return st, lt, tax, remaining


class LotBook:
    def __init__(self, policy: TaxPolicy):
        self.policy = policy
        self._lots: Dict[str, Deque[Lot]] = defaultdict(deque)
        self.realised: List[Realised] = []
        self._dividends: Dict[int, float] = defaultdict(float)
        self._interest: Dict[int, float] = defaultdict(float)
        # Fractional entitlements awaiting cash in lieu, and holdings written
        # to zero while suspended (E1 §15, 2026-09-27). Neither is a position.
        self.fractions: List[Fraction] = []
        self.written_down: Dict[str, List[Lot]] = {}
        self._carried: List[CarriedLoss] = []
        self.settled: Dict[int, FYTax] = {}

    # --- positions -------------------------------------------------------
    def buy(self, isin: str, d: date, qty: int, price: float, costs: float = 0.0) -> Lot:
        if qty <= 0:
            raise ValueError("qty must be positive")
        lot = Lot(isin, d, qty, (qty * price + costs) / qty)
        self._lots[isin].append(lot)
        return lot

    def sell(self, isin: str, d: date, qty: int, price: float, costs: float = 0.0) -> List[Realised]:
        if qty <= 0:
            raise ValueError("qty must be positive")
        if qty > self.holdings(isin):
            raise ValueError(f"cannot sell {qty} of {isin}; holding {self.holdings(isin)}")
        lots = self._lots[isin]
        net_ps = (qty * price - costs) / qty
        out: List[Realised] = []
        remaining = qty
        while remaining > 0:
            lot = lots[0]
            take = min(lot.qty, remaining)
            r = Realised(isin, lot.buy_date, d, take, take * net_ps, take * lot.cost_per_share,
                         is_long_term(lot.buy_date, d, self.policy.long_term_months))
            out.append(r)
            self.realised.append(r)
            lot.qty -= take
            remaining -= take
            if lot.qty == 0:
                lots.popleft()
        return out

    # --- corporate actions on held lots (charter E1 §9) -------------------
    def adjust_shares(self, isin: str, factor: float) -> int:
        """A split or consolidation (or an unnamed PREVCLOSE factor that snaps
        to a standard ratio). Shares scale by 1/factor; buy dates are kept and
        each lot's basis moves with its shares, so total basis is conserved.
        Not a sale.

        Lots are walked in FIFO order, carrying the fractional units a lot
        cannot make whole into the next, so a whole share formed from several
        small lots carries their pooled basis and is dated by the lot that
        completes it (the later date: the conservative reading). The
        holding's final fraction (< 1 share) goes to `self.fractions` for
        cash in lieu. Lots 1, 1, 3 at 4-for-1 become one share and a 0.25
        fraction, not three shares (audit 2026-09-27, defect 4).

        Returns the whole-share count added (negative for a consolidation).
        """
        if factor <= 0:
            raise ValueError(f"factor must be positive, got {factor}")
        before = self.holdings(isin)
        if before == 0:
            return 0
        new: Deque[Lot] = deque()
        carry_u, carry_b, last_date = 0.0, 0.0, None
        for lot in self._lots[isin]:
            units = carry_u + lot.qty / factor
            basis = carry_b + lot.qty * lot.cost_per_share
            last_date = lot.buy_date
            whole = math.floor(units + _WHOLE_TOL)
            if whole > 0:
                share_basis = basis * min(1.0, whole / units)
                new.append(Lot(isin, lot.buy_date, whole, share_basis / whole))
                carry_u, carry_b = max(0.0, units - whole), basis - share_basis
            else:
                carry_u, carry_b = units, basis
        if carry_u > _WHOLE_TOL:
            self.fractions.append(Fraction(isin, carry_u, carry_b, last_date))
        elif carry_b and new:
            # rounding dust: keep total basis exact on the last lot
            new[-1].cost_per_share += carry_b / new[-1].qty
        self._lots[isin] = new
        return self.holdings(isin) - before

    def bonus(self, isin: str, factor: float, d: date) -> int:
        """A bonus issue, `factor` = b / (a + b) for a:b. The held lots keep
        their shares, dates and cost; the bonus shares are a NEW lot dated at
        allotment `d` with nil cost (Income Tax Department: holding period
        from allotment, nil cost for post-2001 bonuses). Allotment is taken as
        the ex-date, declared. The entitlement is on the whole holding; its
        fraction goes to `self.fractions` at nil basis.

        Returns the bonus shares added.
        """
        if not 0 < factor < 1:
            raise ValueError(f"bonus factor must be in (0, 1), got {factor}")
        before = self.holdings(isin)
        if before == 0:
            return 0
        units = before * (1.0 / factor - 1.0)
        whole = math.floor(units + _WHOLE_TOL)
        if whole > 0:
            self._lots[isin].append(Lot(isin, d, whole, 0.0))
        if units - whole > _WHOLE_TOL:
            self.fractions.append(Fraction(isin, units - whole, 0.0, d))
        return whole

    def settle_fraction(self, fr: Fraction, d: date, proceeds: float) -> "Realised":
        """Cash in lieu of a fractional entitlement: a disposal realised
        against the fraction's own basis and date. `qty` is 0 on the record
        because no whole share changed hands."""
        self.fractions.remove(fr)
        r = Realised(fr.isin, fr.buy_date, d, 0, proceeds, fr.basis,
                     is_long_term(fr.buy_date, d, self.policy.long_term_months))
        self.realised.append(r)
        return r

    def reduce_basis(self, isin: str, factor: float) -> None:
        """A cash-credit action: a demerger or capital reduction, where the
        holder receives cash instead of shares. The share count is unchanged
        and the cost per share falls in the same proportion as the price
        (charter §9). Not a sale: nothing is realised.
        """
        if not 0 < factor <= 1:
            raise ValueError(f"cash-credit factor must be in (0, 1], got {factor}")
        for lot in self._lots.get(isin, ()):
            lot.cost_per_share *= factor

    def write_down(self, isin: str) -> int:
        """E1 §15 (2026-09-17, corrected 2026-09-27): a holding suspended for
        the confirm window is valued at zero. A valuation, not a disposal: the
        shares are still owned, so nothing is realised and no capital loss is
        created. The lots wait in `written_down` until the name trades again.
        Returns the share count written down."""
        lots = list(self._lots.pop(isin, ()))
        if lots:
            self.written_down.setdefault(isin, []).extend(lots)
        return sum(l.qty for l in lots)

    def recover(self, isin: str) -> int:
        """A written-down name trades again: its lots return to the book with
        their dates and basis, so the engine can sell them at a real quote."""
        lots = self.written_down.pop(isin, [])
        self._lots[isin].extend(lots)
        return sum(l.qty for l in lots)

    def interest(self, d: date, amount: float) -> None:
        """Cash-sleeve interest, taxed at slab in the FY it accrues."""
        self._interest[fy_of(d)] += amount

    def dividend(self, d: date, amount: float) -> None:
        self._dividends[fy_of(d)] += amount

    def holdings(self, isin: str) -> int:
        return sum(l.qty for l in self._lots.get(isin, ()))

    def lots(self, isin: str) -> List[Lot]:
        return list(self._lots.get(isin, ()))

    def positions(self) -> Dict[str, int]:
        return {isin: q for isin in list(self._lots) if (q := self.holdings(isin)) > 0}

    # --- tax ---------------------------------------------------------------
    def settle_fy(self, fy: int) -> FYTax:
        """Compute and record the liability for `fy`. Call once per FY, in order."""
        if fy in self.settled:
            raise ValueError(f"FY{fy} already settled")
        p = self.policy
        rs = [r for r in self.realised if fy_of(r.sell_date) == fy]
        stcg = sum(r.gain for r in rs if not r.long_term)
        ltcg = sum(r.gain for r in rs if r.long_term)
        carried = [c for c in self._carried if fy - c.origin_fy <= p.loss_carry_years]
        st, lt, tax_cap, remaining = _net(stcg, ltcg, carried, fy, p)
        div = self._dividends.get(fy, 0.0)
        tax_div = div * p.dividend_rate
        intr = self._interest.get(fy, 0.0)
        tax_int = intr * p.interest_rate
        total = (tax_cap + tax_div + tax_int) * (1.0 + p.cess)
        res = FYTax(fy, stcg, ltcg, st, lt, div, tax_cap * (1 + p.cess),
                    tax_div * (1 + p.cess), total, remaining,
                    interest=intr, tax_interest=tax_int * (1 + p.cess))
        self._carried = remaining
        self.settled[fy] = res
        return res

    def simulate_liquidation(self, d: date, prices: Dict[str, float],
                             sell_cost: Callable[[float], float]) -> FYTax:
        """Tax due for FY(d) if every position were sold on `d` at `prices`,
        including what FY(d) has already realised, received and accrued -- so
        an all-cash book still owes its FY's tax. Written-down holdings have
        no quote and are not sold. `sell_cost` must return the DEDUCTIBLE
        cost (no STT, s.48). Does not mutate this book. Prior FYs must
        already be settled."""
        book = copy.deepcopy(self)
        for isin, qty in book.positions().items():
            px = prices[isin]
            book.sell(isin, d, qty, px, sell_cost(qty * px))
        return book.settle_fy(fy_of(d))
