"""New-money steering and sale proposals (PLAN S17).

Rules (PLAN §1):
  * New money fills underweights first. Each month's contribution is split across buckets in
    proportion to how far each sits below its target after the contribution lands; no sale is
    ever part of steering, so nothing inside the bands is sold.
  * A sale is proposed only for a bucket still beyond target + hard_band AFTER that month's
    steering, and never below `min_trade`: a smaller tidy-up is blocked and says so.
  * A sale proposal always carries the tax of the sale by lot (both regimes), the charges, and the
    alternatives side by side: doing nothing, and steering alone (months to cure, an Estimate that
    assumes flat prices).
The allocator refuses to run with unset targets, unpriced holdings, or holdings in a bucket that
has no target: weights built on those would be guesses. It proposes; the investor decides and places
every order himself.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

import pandas as pd

from pflab.calc.valuation import Valuation
from pflab.pm import estimate as est
from pflab.plan.targets import BucketTarget, Targets
from pflab.risk import exposure

MAX_MONTHS = 120
FeeFn = Callable[[str, str, str, float], Tuple[float, bool]]     # (isin, bucket, side, amount) -> (fee, known)
TaxFn = Callable[[str, str, float, float, date], dict]            # (account, isin, qty, price, date) -> tax dict


class PlanError(RuntimeError):
    pass


def zero_fees(isin: str, bucket: str, side: str, amount: float) -> Tuple[float, bool]:
    """No charges modelled: reported as unknown, never as free."""
    return 0.0, False


@dataclass(frozen=True)
class BuyLine:
    bucket: str
    isin: str
    target_amount: float
    units: float
    cost: float
    fee: float
    fee_known: bool


@dataclass
class SaleProposal:
    bucket: str
    isin: str
    account: str
    qty: float
    price: float
    gross: float
    fee: float
    fee_known: bool
    extra_tax_new: float
    extra_tax_old: float
    net_after_tax_cheaper: float
    weight_before: float
    weight_after: float
    restore_to: float
    lots: list
    months_to_cure: Optional[est.Estimate]
    do_nothing: str
    blocked: Optional[str] = None


@dataclass
class Plan:
    asof: date
    contribution: float
    total_before: float
    weights_before: Dict[str, float]
    weights_after: Dict[str, float]
    status_after: Dict[str, str]                  # in-band | soft-breach | hard-breach
    buys: List[BuyLine]
    cash_retained: float
    unspent: float
    sales: List[SaleProposal] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def evidence(self) -> dict:
        """JSON-able record of everything the plan used and produced (hashed when logged)."""
        d = {"asof": str(self.asof), "contribution": self.contribution, "total_before": self.total_before,
             "weights_before": self.weights_before, "weights_after": self.weights_after,
             "status_after": self.status_after, "cash_retained": self.cash_retained, "unspent": self.unspent,
             "buys": [b.__dict__ for b in self.buys], "notes": self.notes,
             "sales": [{k: (v.render() if isinstance(v, est.Estimate) else v) for k, v in s.__dict__.items()
                        if k != "lots"} for s in self.sales]}
        return d


# --- values ---------------------------------------------------------------------------------------------

def bucket_values(v: Valuation, instruments: pd.DataFrame, targets: Targets,
                  extra: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Value by bucket (cash included, less the cash floor). `extra`: holdings outside the ledger (fixed
    deposits as debt). Refuses unpriced holdings and holdings with no target."""
    if v.unpriced:
        raise PlanError(f"{len(v.unpriced)} position(s) have no price {[u[1] for u in v.unpriced]}: "
                        "weights would be wrong, so no plan is made")
    e = exposure.exposures(v, instruments)["bucket"]
    vals = {r.bucket: float(r.value) for r in e.itertuples()}
    missing = [b for b, x in vals.items() if x > 1e-9 and b not in targets.buckets]
    if missing:
        raise PlanError(f"holdings in {missing} but no target is set for them "
                        "(add a bucket table in configs/targets.toml, or resolve 'unclassified' instruments)")
    for b, x in (extra or {}).items():
        vals[b] = vals.get(b, 0.0) + x
    if targets.cash_floor:
        vals["cash"] = max(vals.get("cash", 0.0) - targets.cash_floor, 0.0)
    for b in targets.buckets:
        vals.setdefault(b, 0.0)
    return vals


def weights(values: Dict[str, float]) -> Dict[str, float]:
    tot = sum(values.values())
    return {b: (x / tot if tot > 0 else 0.0) for b, x in values.items()}


def status_of(w: float, t: BucketTarget) -> str:
    dev = w - t.target
    if abs(dev) > t.hard_band + 1e-12:
        return "hard-breach"
    if abs(dev) > t.soft_band + 1e-12:
        return "soft-breach"
    return "in-band"


# --- steering ---------------------------------------------------------------------------------------------

def steer(values: Dict[str, float], targets: Targets, contribution: float) -> Dict[str, float]:
    """Contribution split across buckets in proportion to each bucket's shortfall to target after the
    money lands. Never negative, never above a bucket's shortfall, sums to `contribution`."""
    if contribution < 0:
        raise PlanError("a contribution cannot be negative: sales are proposed separately, never by steering")
    total = sum(values.values()) + contribution
    deficit = {b: max(t.target * total - values.get(b, 0.0), 0.0) for b, t in targets.buckets.items()}
    s = sum(deficit.values())
    if contribution == 0 or s <= 0:
        return {b: 0.0 for b in targets.buckets}
    scale = contribution / s
    return {b: d * scale for b, d in deficit.items()}


def months_to_cure(values: Dict[str, float], targets: Targets, contribution: float, bucket: str,
                   asof: date, goal: Optional[float] = None) -> Optional[est.Estimate]:
    """Months of steering alone (flat prices, same contribution each month, no sales) until `bucket`
    is no longer beyond its hard band (or at `goal` weight). None if it never gets there in 10 years."""
    t = targets.buckets[bucket]
    goal = t.target + t.hard_band if goal is None else goal
    vals = dict(values)
    for m in range(0, MAX_MONTHS + 1):
        w = vals[bucket] / sum(vals.values())
        if w <= goal + 1e-12:
            return est.make(m, "months of new-money steering alone, flat prices, same contribution monthly, no sales",
                            {"values": values, "contribution": contribution, "goal": goal}, asof,
                            horizon="months", unit="months")
        alloc = steer(vals, targets, contribution)
        for b, a in alloc.items():
            vals[b] = vals.get(b, 0.0) + a
    return None


# --- the plan ---------------------------------------------------------------------------------------------------

def plan_contribution(v: Valuation, instruments: pd.DataFrame, targets: Targets, contribution: float,
                      prices: Dict[str, float], asof: date, *, whole: Optional[Dict[str, bool]] = None,
                      fee_fn: FeeFn = zero_fees, min_buy: float = 0.0,
                      extra: Optional[Dict[str, float]] = None) -> Plan:
    """Where this month's `contribution` goes. `prices`: per-unit price of each ISIN named in the
    targets' `buy` lists. Buys under `min_buy` are not placed (their amount stays unspent)."""
    whole = whole or {}
    vals = bucket_values(v, instruments, targets, extra)
    total = sum(vals.values())
    w_before = weights(vals)
    alloc = steer(vals, targets, contribution)
    buys: List[BuyLine] = []
    notes: List[str] = []
    cash_retained, unspent = alloc.get("cash", 0.0), 0.0
    for b, amt in alloc.items():
        if b == "cash" or amt <= 1e-9:
            continue
        t = targets.buckets[b]
        if not t.buy:
            unspent += amt
            notes.append(f"{b}: Rs {amt:,.2f} is due but the bucket has no buy candidates; left unspent")
            continue
        for isin, wt in t.buy:
            tgt = amt * wt
            if isin not in prices or prices[isin] <= 0:
                unspent += tgt
                notes.append(f"{b}: no price for {isin}; Rs {tgt:,.2f} left unspent")
                continue
            if tgt < min_buy:
                unspent += tgt
                notes.append(f"{b}/{isin}: Rs {tgt:,.2f} is under the minimum buy Rs {min_buy:,.0f}; left unspent")
                continue
            units = math.floor(tgt / prices[isin] + 1e-12) if whole.get(isin, True) else tgt / prices[isin]
            cost = units * prices[isin]
            fee, known = fee_fn(isin, b, "buy", cost)
            buys.append(BuyLine(b, isin, tgt, units, cost, fee, known))
            unspent += tgt - cost
    new_vals = dict(vals)
    for bl in buys:
        new_vals[bl.bucket] = new_vals.get(bl.bucket, 0.0) + bl.cost
    # cash after = existing cash + contribution - what the buys and their fees cost
    new_vals["cash"] = new_vals.get("cash", 0.0) + contribution - sum(bl.cost + bl.fee for bl in buys)
    w_after = weights(new_vals)
    status = {b: status_of(w_after.get(b, 0.0), t) for b, t in targets.buckets.items()}
    for b, s in status.items():
        if s != "in-band":
            notes.append(f"{b}: {s} after this month ({w_after[b]:.2%} vs target {targets.buckets[b].target:.2%})")
    return Plan(asof, contribution, total, w_before, w_after, status, buys, cash_retained, unspent, [], notes)


def sale_proposals(plan: Plan, v: Valuation, instruments: pd.DataFrame, targets: Targets,
                   prices_now: Dict[str, float], tax_fn: TaxFn, *, min_trade: float,
                   fee_fn: FeeFn = zero_fees, restore_to: str = "soft_edge",
                   extra: Optional[Dict[str, float]] = None) -> List[SaleProposal]:
    """Sale proposals for buckets still beyond the HARD band after steering. Each carries the tax by
    lot (both regimes), charges, and the do-nothing and steer-only alternatives. Inside the hard
    band nothing is proposed; under `min_trade` the sale is blocked with a reason."""
    vals = bucket_values(v, instruments, targets, extra)
    total_after = sum(vals.values()) + plan.contribution
    inst = instruments.set_index("isin")
    out: List[SaleProposal] = []
    for b, t in targets.buckets.items():
        if plan.status_after.get(b) != "hard-breach" or plan.weights_after[b] <= t.target:
            continue                                  # underweight breaches are cured by buying, never selling
        goal = t.target + t.soft_band if restore_to == "soft_edge" else t.target
        excess = plan.weights_after[b] * total_after - goal * total_after
        # the instrument to sell from: the largest priced holding in the bucket
        held = v.positions.dropna(subset=["value"]) if len(v.positions) else v.positions
        cand = [(r.value, r.isin, r.account, r.qty) for r in held.itertuples()
                if r.isin in inst.index and exposure.bucket(inst.loc[r.isin, "asset_class"], inst.loc[r.isin, "tax_class"],
                                                             inst.loc[r.isin].get("category"), inst.loc[r.isin].get("name")) == b]
        months = months_to_cure(vals, targets, plan.contribution, b, plan.asof)
        do_nothing = (f"keep {b} at {plan.weights_after[b]:.2%} (hard limit {t.target + t.hard_band:.2%}); "
                      + (f"steering alone brings it inside in about {months.value:.0f} months" if months else
                         "steering alone does not bring it inside within 10 years") + "; no tax, no charges")
        if not cand:
            continue
        _, isin, account, held_qty = max(cand)
        px = prices_now[isin]
        qty = min(math.floor(excess / px + 1e-12), math.floor(held_qty + 1e-9))
        amount = qty * px
        if amount < min_trade:
            out.append(SaleProposal(b, isin, account, qty, px, amount, 0.0, False, 0.0, 0.0, 0.0,
                                    plan.weights_after[b], plan.weights_after[b], goal, [], months, do_nothing,
                                    blocked=f"blocked: Rs {amount:,.0f} is under the minimum trade Rs {min_trade:,.0f} "
                                            "(no tidy-up sales); steer with new money instead"))
            continue
        fee, known = fee_fn(isin, b, "sell", amount)
        tx = tax_fn(account, isin, qty, px, plan.asof)
        cheaper = min(tx["new"]["extra_tax"], tx["old"]["extra_tax"])
        out.append(SaleProposal(b, isin, account, qty, px, amount, fee, known, tx["new"]["extra_tax"],
                                tx["old"]["extra_tax"], amount - fee - cheaper,
                                plan.weights_after[b], plan.weights_after[b] - amount / total_after, goal,
                                [r for r in tx["lots"].to_dict("records")] if hasattr(tx["lots"], "to_dict") else tx["lots"],
                                months, do_nothing))
    return out
