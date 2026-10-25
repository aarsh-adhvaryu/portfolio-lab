"""Realised capital gains per financial year from ledger consumptions (PLAN S12).

Each consumption (one lot, or part of one, sold) is classified by `pflab.tax.rules.lookup`
on its TRANSFER date: short or long term, and the rate class. Gains fall in four buckets:

    ST_111A   short-term, special rate (listed equity / equity fund / business trust, STT paid)
    ST_SLAB   short-term taxed at slab rates (amount only: S13 adds it to income)
    LT_112A   long-term, special rate with the annual exemption
    LT_112    long-term, 12.5% without indexation, no exemption

Set-off, in the statutory order (the same as `india_lots._net`, parity-tested): within short
term, within long term; a net short-term loss against long-term gains; a long-term loss only
against long-term gains. Then brought-forward losses, oldest first (a long-term loss only
against long-term gains; a short-term loss against short then long), unexpired only (8 years
after the loss year); then the exemption on LT_112A. Leftover current-year losses are carried
forward. Where the law leaves the bucket order open, defaults are tax-minimising and settable:
short-term loss goes against ST_111A before ST_SLAB (the flat 20% is the known rate; slab
rates are the investor's own and live in S13), long-term loss against LT_112 before LT_112A (the
exemption may absorb LT_112A anyway).

Tax here is the special-rate tax before surcharge and cess; slab-taxed amounts are returned
as income for S13. A pre-2018-02-01 equity lot needs its 31-Jan-2018 FMV (`fmv_2018`): the
grandfathering row is unverified (PLAN §6), so a missing FMV raises rather than guessing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

from pflab.ledger.lots import Consumption
from pflab.tax import rules
from pflab.tax.india_lots import fy_of

ST_BUCKETS = ("ST_111A", "ST_SLAB")
LT_BUCKETS = ("LT_112A", "LT_112")
LOSS_CARRY_YEARS = 8
GRANDFATHER_BEFORE = date(2018, 2, 1)


class GainsError(ValueError):
    pass


@dataclass
class CarriedLoss:
    origin_fy: int
    long_term: bool
    amount: float  # positive


@dataclass
class FYGains:
    fy: int
    realised: Dict[str, float]            # per bucket, before any set-off
    after_current: Dict[str, float]       # after same-year set-off
    taxable: Dict[str, float]             # after brought-forward losses and exemption
    exemption_used: float
    exemption_available: float
    tax_special: float                    # 20% / 12.5% parts, before surcharge and cess
    slab_income: float                    # ST_SLAB taxable amount, for S13
    carried_in: List[CarriedLoss]
    carried_out: List[CarriedLoss]
    expired: List[CarriedLoss] = field(default_factory=list)

    @property
    def stcg_taxable(self) -> float:
        return sum(self.taxable[b] for b in ST_BUCKETS)

    @property
    def ltcg_taxable_before_exemption(self) -> float:
        return sum(self.taxable[b] for b in LT_BUCKETS)


# --- classification ---------------------------------------------------------------------------------

def classify(c: Consumption, tax_class: str, *, stt_paid: bool = True, listed: bool = True,
             fmv_2018: Optional[Callable[[str], Optional[float]]] = None) -> dict:
    """One consumption -> its rule, holding, bucket and (grandfathered) gain."""
    rule = rules.lookup(tax_class, c.sell_date, c.acq_date, stt_paid=stt_paid, listed=listed)
    holding = rule.holding(c.acq_date, c.sell_date)
    cost = c.cost
    gf = False
    if rule.id == "equity_stt_paid" and c.acq_date < GRANDFATHER_BEFORE and holding == "LT":
        fmv = fmv_2018(c.isin) if fmv_2018 else None
        if fmv is None:
            raise GainsError(f"{c.isin} acquired {c.acq_date} (before 2018-02-01) needs its 2018-01-31 "
                             "FMV for grandfathering; none supplied (rule unverified, PLAN §6)")
        cost = max(c.cost, min(fmv * c.qty, c.proceeds))
        gf = True
    rate = rule.rate(c.acq_date, c.sell_date)
    if holding == "ST":
        bucket = "ST_SLAB" if rate == rules.SLAB else "ST_111A"
    else:
        bucket = "LT_112A" if "112A" in rule.section_old else "LT_112"
    return {"bucket": bucket, "holding": holding, "rate": rate, "rule": rule.id,
            "cost_used": cost, "gain": c.proceeds - cost, "grandfathered": gf}


def detail(consumptions: Iterable[Consumption], tax_class_of: Callable[[str, Optional[str]], str],
           *, stt_paid_of: Optional[Callable[[Consumption], bool]] = None,
           listed_of: Optional[Callable[[str], bool]] = None,
           fmv_2018: Optional[Callable[[str], Optional[float]]] = None) -> pd.DataFrame:
    """Per-consumption audit table with the rule row used."""
    rows = []
    for c in consumptions:
        tc = c.tax_class or tax_class_of(c.isin, None)
        if tc is None or tc == "REVIEW":
            raise GainsError(f"{c.isin}: tax class unresolved ({tc}); decide it before computing gains")
        r = classify(c, tc, stt_paid=True if stt_paid_of is None else stt_paid_of(c),
                     listed=True if listed_of is None else listed_of(c.isin), fmv_2018=fmv_2018)
        rows.append(dict(account=c.account_id, isin=c.isin, tax_class=tc, acq_date=c.acq_date,
                         sell_date=c.sell_date, fy=fy_of(c.sell_date), qty=c.qty, proceeds=c.proceeds,
                         cost=c.cost, **r))
    return pd.DataFrame(rows, columns=["account", "isin", "tax_class", "acq_date", "sell_date", "fy", "qty",
                                       "proceeds", "cost", "bucket", "holding", "rate", "rule", "cost_used",
                                       "gain", "grandfathered"])


# --- set-off ------------------------------------------------------------------------------------------

def net_year(realised: Dict[str, float], carried: List[CarriedLoss], fy: int, *,
             st_order: Sequence[str] = ST_BUCKETS, lt_order: Sequence[str] = ("LT_112", "LT_112A"),
             carry_years: int = LOSS_CARRY_YEARS):
    """Statutory netting for one year. Returns (after_current, taxable_before_exemption,
    carried_out, expired)."""
    b = {k: float(realised.get(k, 0.0)) for k in ST_BUCKETS + LT_BUCKETS}

    # 1. within short term, within long term
    for cat, order in (("ST", st_order), ("LT", lt_order)):
        for k in order:
            if b[k] < 0:
                for g in order:
                    if b[g] > 0:
                        use = min(-b[k], b[g])
                        b[k] += use
                        b[g] -= use
                    if b[k] >= 0:
                        break
    # 2. net short-term loss against long-term gains (never the reverse)
    for k in st_order:
        if b[k] < 0:
            for g in lt_order:
                if b[g] > 0:
                    use = min(-b[k], b[g])
                    b[k] += use
                    b[g] -= use
                if b[k] >= 0:
                    break
    after_current = dict(b)

    expired = [c for c in carried if fy - c.origin_fy > carry_years]
    live = [c for c in carried if fy - c.origin_fy <= carry_years]
    remaining: List[CarriedLoss] = []
    for c in sorted(live, key=lambda c: c.origin_fy):
        amt = c.amount
        targets = list(lt_order) if c.long_term else list(st_order) + list(lt_order)
        for g in targets:
            if amt <= 1e-12:
                break
            if b[g] > 0:
                use = min(amt, b[g])
                b[g] -= use
                amt -= use
        if amt > 1e-9:
            remaining.append(CarriedLoss(c.origin_fy, c.long_term, amt))
    # 3. leftover current-year losses carry forward
    st_left = sum(b[k] for k in ST_BUCKETS if b[k] < 0)
    lt_left = sum(b[k] for k in LT_BUCKETS if b[k] < 0)
    if st_left < 0:
        remaining.append(CarriedLoss(fy, False, -st_left))
    if lt_left < 0:
        remaining.append(CarriedLoss(fy, True, -lt_left))
    taxable = {k: max(v, 0.0) for k, v in b.items()}
    return after_current, taxable, remaining, expired


def settle_year(fy: int, rows: pd.DataFrame, carried: List[CarriedLoss], *,
                st_order: Sequence[str] = ST_BUCKETS, lt_order: Sequence[str] = ("LT_112", "LT_112A"),
                book: Optional[rules.RuleBook] = None) -> FYGains:
    """Settle one FY from the `detail` rows dated in it."""
    book = book or rules.load()
    r = rows[rows["fy"] == fy]
    realised = {k: float(r.loc[r["bucket"] == k, "gain"].sum()) for k in ST_BUCKETS + LT_BUCKETS}
    after_current, taxable, carried_out, expired = net_year(realised, carried, fy, st_order=st_order,
                                                            lt_order=lt_order)
    try:
        ex_avail = rules.exemption(fy, book=book)
    except rules.RuleGap:
        ex_avail = 0.0
    ex_used = min(taxable["LT_112A"], ex_avail)
    taxable_final = dict(taxable)
    taxable_final["LT_112A"] = taxable["LT_112A"] - ex_used
    rate_of = _bucket_rates(r)
    tax = (taxable_final["ST_111A"] * rate_of.get("ST_111A", 0.0)
           + taxable_final["LT_112A"] * rate_of.get("LT_112A", 0.0)
           + taxable_final["LT_112"] * rate_of.get("LT_112", 0.0))
    return FYGains(fy, realised, after_current, taxable_final, ex_used, ex_avail, tax,
                   taxable_final["ST_SLAB"], list(carried), carried_out, expired)


def _bucket_rates(r: pd.DataFrame) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for k in ("ST_111A", "LT_112A", "LT_112"):
        rates = {x for x in r.loc[r["bucket"] == k, "rate"] if x != rules.SLAB}
        if len(rates) > 1:
            raise GainsError(f"bucket {k} mixes rates {sorted(rates)}")
        if rates:
            out[k] = float(next(iter(rates)))
    return out


def settle_all(rows: pd.DataFrame, opening_losses: Sequence[CarriedLoss] = (),
               first_fy: Optional[int] = None, last_fy: Optional[int] = None, **kw) -> List[FYGains]:
    """Settle every FY from first to last in order, carrying losses forward. A bucket's rate is
    constant by construction of the rule table; a year with no sales still ages the losses."""
    if rows.empty and not opening_losses:
        return []
    fys = sorted(set(rows["fy"])) if len(rows) else []
    lo = first_fy if first_fy is not None else (fys[0] if fys else min(c.origin_fy for c in opening_losses))
    hi = last_fy if last_fy is not None else (fys[-1] if fys else lo)
    carried, out = [CarriedLoss(c.origin_fy, c.long_term, c.amount) for c in opening_losses], []
    for fy in range(lo, hi + 1):
        res = settle_year(fy, rows, carried, **kw)
        carried = res.carried_out
        out.append(res)
    return out


def carry_forward_rows(res: FYGains) -> List[Tuple[int, str, float, int]]:
    """(origin_fy, character, amount, expires_fy) for the `carry_forward` table."""
    return [(c.origin_fy, "LT" if c.long_term else "ST", c.amount, c.origin_fy + LOSS_CARRY_YEARS)
            for c in res.carried_out]
