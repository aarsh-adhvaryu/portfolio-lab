"""E3-R cautious-gear sell-down: which names, how many shares (§11 (b)).

The investor, 2026-09-27: the sell-down chooses **names and share counts, never
lots**. Within a name the lot book sells FIFO, as Indian demat rules
require, so `tax/india_lots.py` is not touched. Held names are ranked by the
tax cost per rupee raised if the whole position were sold FIFO:

    1. net loss first
    2. then net long-term gain
    3. then short-term gain
    lowest tax per rupee first within each; ties by the weakest current score

and whole names are sold down that ranking, the last one partially in whole
shares, until the month's amount is met.

Readings declared here (for the lock): the ranking is priced at the
decision's close and classifies each lot long- or short-term as of the
decision date; "tax" is `stcg_rate * short-term gain + ltcg_rate *
long-term gain` over the position's lots, before set-off, exemption and
cess, which are properties of the year rather than of one sale; a name with
no score (the gear's ETF) ranks as weakest on ties.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from pflab.tax.india_lots import Lot, TaxPolicy, is_long_term

NET_LOSS, NET_LONG_TERM, SHORT_TERM = 0, 1, 2
CATEGORY_NAMES = {NET_LOSS: "net_loss", NET_LONG_TERM: "net_long_term_gain",
                  SHORT_TERM: "short_term_gain"}


@dataclass(frozen=True)
class Candidate:
    isin: str
    category: int
    tax_per_rupee: float
    score: float
    qty: int
    price: float
    st_gain: float
    lt_gain: float

    @property
    def value(self) -> float:
        return self.qty * self.price


def position_tax(lots: Sequence[Lot], price: float, m: date,
                 policy: TaxPolicy) -> Tuple[float, float, float]:
    """(short-term gain, long-term gain, tax) if every lot were sold at `price`."""
    st = lt = 0.0
    for lot in lots:
        g = lot.qty * (price - lot.cost_per_share)
        if is_long_term(lot.buy_date, m, policy.long_term_months):
            lt += g
        else:
            st += g
    return st, lt, policy.stcg_rate * st + policy.ltcg_rate * lt


def rank(lots_by_isin: Mapping[str, Sequence[Lot]], prices: Mapping[str, float],
         scores: Mapping[str, float], m: date, policy: TaxPolicy) -> List[Candidate]:
    """Every held name with a price, in the order §11 (b) sells them."""
    out = []
    for isin, lots in lots_by_isin.items():
        qty = sum(l.qty for l in lots)
        px = prices.get(isin)
        if qty <= 0 or px is None or not (px > 0):
            continue
        st, lt, tax = position_tax(lots, px, m, policy)
        if st + lt < 0:
            cat = NET_LOSS
        elif st <= 0:
            cat = NET_LONG_TERM
        else:
            cat = SHORT_TERM
        s = scores.get(isin)
        out.append(Candidate(isin, cat, tax / (qty * px),
                             float("-inf") if s is None else float(s),
                             qty, float(px), st, lt))
    # weakest score first on a tie; the ISIN makes the order total
    out.sort(key=lambda c: (c.category, c.tax_per_rupee, c.score, c.isin))
    return out


def plan(ranked: Sequence[Candidate], amount: float) -> List[Tuple[str, int]]:
    """Whole names down the ranking until `amount` is raised; the last one
    partially, in whole shares (rounded up, so the amount is met)."""
    out: List[Tuple[str, int]] = []
    left = float(amount)
    for c in ranked:
        if left <= 0:
            break
        if c.value <= left:
            out.append((c.isin, c.qty))
            left -= c.value
        else:
            q = min(c.qty, math.ceil(left / c.price))
            if q > 0:
                out.append((c.isin, q))
            left = 0.0
    return out
