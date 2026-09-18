"""India listed-equity capital-gains lot engine (charter E1 §8).

FIFO per ISIN; short/long split at the 12-month boundary (held for MORE
than 12 months is long-term); FY netting with statutory set-off order;
carry-forward by character; LTCG exemption; cess; dividends at slab.
Today's regime is applied to every year: a policy counterfactual.
"""
from __future__ import annotations

import copy
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from typing import Callable, Deque, Dict, List

from dateutil.relativedelta import relativedelta

from pflab import _toml


class FractionalEntitlement(ValueError):
    """A share-count action leaves a holding below one whole share.

    Real life pays cash in lieu of the fraction, which is a disposal and
    therefore a taxable event -- unlike the §9 cash credit, which is not.
    The engine catches this and sells the position at the prevailing price.
    NOT covered by charter §9 as written; flagged for a §15 line.
    """


@dataclass(frozen=True)
class TaxPolicy:
    stcg_rate: float = 0.20
    ltcg_rate: float = 0.125
    ltcg_exemption: float = 125_000.0
    cess: float = 0.04
    dividend_rate: float = 0.30
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
        """A share-count action: bonus, split, or a PREVCLOSE factor that
        snaps to a standard ratio. Shares scale by 1/factor and the cost per
        share by `factor`, so total basis and buy dates are untouched. Not a
        sale: nothing is realised and no tax event occurs.

        Returns the share count added (can be negative for a consolidation).
        """
        if factor <= 0:
            raise ValueError(f"factor must be positive, got {factor}")
        before = self.holdings(isin)
        if before == 0:
            return 0
        # Apply to the HOLDING, not lot by lot. A consolidation of 100 shares
        # at 1/3 is 33 shares; rounding each lot separately compounds the
        # error and can erase a 1-share lot that the holding as a whole keeps.
        after = int(round(before / factor))
        if after <= 0:
            raise FractionalEntitlement(
                f"{isin}: factor {factor} leaves {before} shares below one "
                f"whole share; the holder receives cash in lieu")
        lots = self._lots[isin]
        remaining = after
        for i, lot in enumerate(lots):
            share = (int(round(after * lot.qty / before)) if i < len(lots) - 1
                     else remaining)
            share = max(0, min(share, remaining))
            if share == 0:
                # this lot's entitlement rounded away; fold its basis into the
                # next lot so total cost is preserved
                continue
            lot.cost_per_share = lot.cost_per_share * lot.qty / share
            lot.qty = share
            remaining -= share
        self._lots[isin] = deque(l for l in lots if l.qty > 0)
        return self.holdings(isin) - before

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

    def write_off(self, isin: str, d: date) -> List["Realised"]:
        """§12 S9: the position is a total loss. Realised at zero proceeds, so
        the capital loss is available for set-off like any other."""
        qty = self.holdings(isin)
        return self.sell(isin, d, qty, 0.0, 0.0) if qty else []

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
        total = (tax_cap + tax_div) * (1.0 + p.cess)
        res = FYTax(fy, stcg, ltcg, st, lt, div, tax_cap * (1 + p.cess), tax_div * (1 + p.cess), total, remaining)
        self._carried = remaining
        self.settled[fy] = res
        return res

    def simulate_liquidation(self, d: date, prices: Dict[str, float],
                             sell_cost: Callable[[float], float]) -> FYTax:
        """Tax due for FY(d) if every position were sold on `d` at `prices`.
        Does not mutate this book. Prior FYs must already be settled."""
        book = copy.deepcopy(self)
        for isin, qty in book.positions().items():
            px = prices[isin]
            book.sell(isin, d, qty, px, sell_cost(qty * px))
        return book.settle_fy(fy_of(d))
