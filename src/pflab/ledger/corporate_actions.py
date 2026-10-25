"""Corporate actions applied to ledger lots (PLAN S11).

An action is an ordinary event of kind `corp_action` whose `params["action"]` names it,
so replay is deterministic and a restore re-applies it. `account_id="*"` means every
account that holds the ISIN. Holding period and cost basis follow the tax treatment:

  split / consolidation   units change, total cost kept, dates kept; fractions -> cash in lieu
  bonus a:b               new nil-cost lot dated at allotment (ex-date), old lots untouched
  merger (amalgamation)   units x ratio, cost and acquisition date carried to the new ISIN
  demerger                cost split by the announced fraction; new shares keep the old date
  isin_change             lots re-keyed, nothing realised
  cash_credit             cost scaled down, cash received, units unchanged (not a sale)
  buyback (tender)        a disposal at the buy-back price; supported from 2026-04-01 only
  cash_in_lieu            settles pending fractions as a disposal
  rights                  `rights_issue()` builds a buy event: new lot dated at allotment

Pre-2026-04-01 buy-backs were taxed as deemed dividend with a separate loss rule; that
regime is not modelled and raises rather than guessing.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from pflab.ledger.events import Event
from pflab.ledger.lots import EPS, Lot

BUYBACK_FROM = date(2026, 4, 1)   # Finance Act 2026: buy-back proceeds are capital gains (PLAN §6)


class ActionError(ValueError):
    pass


# --- builders ------------------------------------------------------------------

def split(isin: str, ex: date, factor: float, *, account: str = "*", whole: bool = True,
          source_doc_sha: str = "") -> Event:
    """`factor` = new face value / old face value (a 1:5 split is 0.2)."""
    return Event("corp_action", account, ex, isin=isin, source_doc_sha=source_doc_sha,
                 params={"action": "split", "factor": factor, "whole": whole})


def bonus(isin: str, ex: date, a: int, b: int, *, account: str = "*", whole: bool = True,
          source_doc_sha: str = "") -> Event:
    """a new shares for every b held."""
    return Event("corp_action", account, ex, isin=isin, source_doc_sha=source_doc_sha,
                 params={"action": "bonus", "a": a, "b": b, "whole": whole})


def merger(isin: str, effective: date, to_isin: str, ratio: float, *, account: str = "*",
           whole: bool = True, source_doc_sha: str = "") -> Event:
    """`ratio` new units of `to_isin` per old unit."""
    return Event("corp_action", account, effective, isin=isin, source_doc_sha=source_doc_sha,
                 params={"action": "merger", "to_isin": to_isin, "ratio": ratio, "whole": whole})


def demerger(isin: str, ex: date, to_isin: str, ratio: float, cost_fraction: float, *,
             account: str = "*", whole: bool = True, source_doc_sha: str = "") -> Event:
    """`ratio` new units of `to_isin` per old unit; `cost_fraction` of cost moves to them."""
    return Event("corp_action", account, ex, isin=isin, source_doc_sha=source_doc_sha,
                 params={"action": "demerger", "to_isin": to_isin, "ratio": ratio,
                         "cost_fraction": cost_fraction, "whole": whole})


def isin_change(isin: str, effective: date, to_isin: str, *, account: str = "*",
                source_doc_sha: str = "") -> Event:
    return Event("corp_action", account, effective, isin=isin, source_doc_sha=source_doc_sha,
                 params={"action": "isin_change", "to_isin": to_isin})


def cash_credit(isin: str, ex: date, cost_factor: float, cash_per_unit: float, *,
                account: str = "*", source_doc_sha: str = "") -> Event:
    return Event("corp_action", account, ex, isin=isin, source_doc_sha=source_doc_sha,
                 params={"action": "cash_credit", "cost_factor": cost_factor,
                         "cash_per_unit": cash_per_unit})


def buyback(account: str, isin: str, d: date, qty: float, price: float, fees: Optional[dict] = None,
            source_doc_sha: str = "") -> Event:
    return Event("corp_action", account, d, isin=isin, qty=qty, price=price, fees=fees or {},
                 source_doc_sha=source_doc_sha, params={"action": "buyback"})


def cash_in_lieu(account: str, isin: str, d: date, proceeds: float, source_doc_sha: str = "") -> Event:
    return Event("corp_action", account, d, isin=isin, amount=proceeds, source_doc_sha=source_doc_sha,
                 params={"action": "cash_in_lieu", "proceeds": proceeds})


def rights_issue(account: str, isin: str, allotment: date, qty: float, price: float,
                 fees: Optional[dict] = None, tax_class: Optional[str] = None) -> Event:
    """Rights taken up: a purchase dated at allotment (holding period starts then)."""
    return Event("buy", account, allotment, isin=isin, qty=qty, price=price, fees=fees or {},
                 ref="rights", tax_class=tax_class)


# --- application ----------------------------------------------------------------

def _accounts(led, e: Event) -> List[str]:
    if e.account_id != "*":
        return [e.account_id]
    return sorted({a for (a, i), q in led.lots.positions().items() if i == e.isin})


def apply(led, e: Event) -> None:
    """Apply one `corp_action` event to a `Ledger`."""
    p, lots = e.params, led.lots
    act = p["action"]
    accounts = _accounts(led, e)
    if act == "split":
        for a in accounts:
            lots.scale_whole(a, e.isin, p["factor"]) if p.get("whole", True) \
                else lots.scale_units(a, e.isin, 1.0 / p["factor"])
    elif act == "bonus":
        factor = p["b"] / (p["a"] + p["b"])
        for a in accounts:
            lots.bonus(a, e.isin, factor, e.date, whole=p.get("whole", True), event_id=e.event_id)
    elif act == "merger":
        for a in accounts:
            _convert(lots, a, e.isin, p["to_isin"], p["ratio"], 1.0, p.get("whole", True), e)
    elif act == "demerger":
        if not 0 < p["cost_fraction"] < 1:
            raise ActionError("demerger cost_fraction must be in (0, 1)")
        for a in accounts:
            _convert(lots, a, e.isin, p["to_isin"], p["ratio"], p["cost_fraction"], p.get("whole", True),
                     e, keep_old=True)
    elif act == "isin_change":
        for a in accounts:
            lots.rekey(a, e.isin, p["to_isin"])
            lots.fractions[:] = [f.__class__(f.account_id, p["to_isin"], f.units, f.basis, f.acq_date)
                                 if (f.account_id == a and f.isin == e.isin) else f
                                 for f in lots.fractions]
    elif act == "cash_credit":
        if not 0 < p["cost_factor"] <= 1:
            raise ActionError("cash_credit cost_factor must be in (0, 1]")
        for a in accounts:
            units = lots.holdings(a, e.isin)
            lots.scale_cost(a, e.isin, p["cost_factor"])
            if p["cash_per_unit"] and units:
                led.cash.post(a, e.date, units * p["cash_per_unit"], "corp_action", e.isin, e.event_id)
    elif act == "buyback":
        if e.date < BUYBACK_FROM:
            raise ActionError(f"buy-back on {e.date}: pre-{BUYBACK_FROM} deemed-dividend regime "
                              "is not modelled")
        if e.account_id == "*":
            raise ActionError("a buy-back is for one account")
        fee = e.fee_total
        lots.sell(e.account_id, e.isin, e.date, e.qty, e.price, e.cost_fee_total, e.event_id)
        led.cash.post(e.account_id, e.date, e.qty * e.price - fee, "buyback", e.isin, e.event_id)
        led._fees(e)
    elif act == "cash_in_lieu":
        if e.account_id == "*":
            raise ActionError("cash in lieu is for one account")
        lots.settle_fractions(e.account_id, e.isin, e.date, p["proceeds"], e.event_id)
        led.cash.post(e.account_id, e.date, p["proceeds"], "corp_action", e.isin, e.event_id)
    else:
        raise ActionError(f"unknown corporate action {act!r}")
    led.actions_applied.append((e.isin, e.date, act, dict(p), e.event_id, ",".join(accounts)))


def _convert(lots, account, old_isin, new_isin, ratio, cost_fraction, whole, e, keep_old=False):
    """Move `cost_fraction` of each lot's cost into `ratio` new units per old unit of `new_isin`,
    keeping acquisition dates. `keep_old` (demerger): old lots stay with the remaining cost;
    otherwise (merger) all of the lot moves."""
    old = lots.lots(account, old_isin)
    if not old:
        return
    for lot in old:
        if lot.qty <= EPS:
            continue
        new = Lot(lots._new_id(), account, new_isin, lot.acq_date, lot.qty * ratio,
                  lot.cost * cost_fraction / (lot.qty * ratio), lot.tax_class, e.event_id)
        lots._q[(account, new_isin)].append(new)
        lots.history.append((new.lot_id, "convert", {"from": old_isin, "from_lot": lot.lot_id,
                                                      "ratio": ratio, "cost_fraction": cost_fraction}))
    if keep_old:
        lots.scale_cost(account, old_isin, 1.0 - cost_fraction)
    else:
        lots._q[(account, old_isin)].clear()
    if whole:
        lots.scale_whole(account, new_isin, 1.0)


def from_nse_feed(raw, isins, since: Optional[date] = None) -> List[Event]:
    """Split and bonus events for `isins` from the NSE corporate-actions feed (the frame
    `pflab.data.nse_corporate_actions.load_raw` returns). Only what the feed states
    exactly is built: sub-divisions and bonus issues. Mergers, demergers, rights and
    buy-backs need a human to enter the ratio. A bonus ratio is recovered from the
    factor b/(a+b) as the nearest small integer pair."""
    from fractions import Fraction as Fr

    from pflab.data import nse_corporate_actions as nse

    isins = set(isins)
    out: List[Event] = []
    for r in raw.itertuples(index=False):
        if r.isin not in isins or (since and r.ex_date < since):
            continue
        for kind, f in nse.parse_purpose(r.subject):
            if kind == "split":
                out.append(split(r.isin, r.ex_date, f, source_doc_sha="nse_corporate_actions"))
            else:
                ratio = Fr(1 / f - 1).limit_denominator(20)       # a / b
                out.append(bonus(r.isin, r.ex_date, ratio.numerator, ratio.denominator,
                                 source_doc_sha="nse_corporate_actions"))
    return out
