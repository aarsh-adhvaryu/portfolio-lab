"""Tax of a year and of a proposed sale, by lot (PLAN S13).

A proposed sale is replayed as a real `sell` event on a copy of the event log, so the lots it
consumes (FIFO per account), the gains, the holding periods, the set-off and the regime tax
are the very ones the ledger will show after the sale. `proposed_sale` returns the tax before
and after, for both regimes, plus the consumed lots.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import Callable, Dict, List, Optional, Sequence

import pandas as pd

from pflab.ledger.book import Ledger
from pflab.ledger.events import Event, EventLog
from pflab.tax import gains as gn
from pflab.tax import income as inc
from pflab.tax.income import YearInputs
from pflab.tax.india_lots import fy_of

TaxClassOf = Callable[[str, Optional[str]], str]


def _inputs(led: Ledger, fy: int, fy_gains: Optional[gn.FYGains], other_income: float,
            old_regime_deductions: float, advance_tax_paid: float, age: str,
            extra_interest: float = 0.0, extra_tds: float = 0.0) -> YearInputs:
    div = [i for i in led.income if i.kind == "dividend" and fy_of(i.date) == fy]
    intr = [i for i in led.income if i.kind == "interest" and fy_of(i.date) == fy]
    return YearInputs(fy, dividends_gross=sum(i.gross for i in div),
                      interest_gross=sum(i.gross for i in intr) + extra_interest,
                      other_income=other_income, old_regime_deductions=old_regime_deductions,
                      tds_credit=sum(i.tds for i in div + intr) + extra_tds, advance_tax_paid=advance_tax_paid,
                      age=age, gains=fy_gains)


def year_tax(log: EventLog, fy: int, tax_class_of: TaxClassOf, *,
             opening_losses: Sequence[gn.CarriedLoss] = (), other_income: float = 0.0,
             old_regime_deductions: float = 0.0, advance_tax_paid: float = 0.0, age: str = "under60",
             fmv_2018=None, stt_paid_of=None, listed_of=None, extra_interest: float = 0.0,
             extra_tds: float = 0.0) -> dict:
    """Gains, regime tax and credits for FY `fy` from an event log (all events dated up to the FY end).
    `extra_interest` / `extra_tds`: interest earned outside the event log (fixed deposits, S33) and its TDS."""
    led = Ledger.replay(log, upto=date(fy, 3, 31))
    rows = gn.detail(led.realised, tax_class_of, fmv_2018=fmv_2018, stt_paid_of=stt_paid_of, listed_of=listed_of)
    first = min([fy] + [c.origin_fy + 1 for c in opening_losses] + (list(rows["fy"]) if len(rows) else []))
    settled = gn.settle_all(rows, opening_losses, first_fy=first, last_fy=fy)
    this = next((s for s in settled if s.fy == fy), None)
    yi = _inputs(led, fy, this, other_income, old_regime_deductions, advance_tax_paid, age,
                 extra_interest, extra_tds)
    cmp_ = inc.compare(yi)
    return {"fy": fy, "gains": this, "inputs": yi, "regimes": cmp_, "rows": rows[rows["fy"] == fy] if len(rows) else rows,
            "ledger": led}


def proposed_sale(log: EventLog, account: str, isin: str, qty: float, price: float, sell_date: date,
                  tax_class_of: TaxClassOf, fees: Optional[Dict[str, float]] = None, **kw) -> dict:
    """What selling `qty` of `isin` in `account` on `sell_date` at `price` does to the year's tax.

    Returns before/after tax per regime, the increase, and the lots consumed with their gains,
    holding period and rule. Raises the ledger's own errors (oversell) if the sale is impossible."""
    fy = fy_of(sell_date)
    before = year_tax(log, fy, tax_class_of, **kw)
    ev = Event("sell", account, sell_date, isin=isin, qty=qty, price=price, fees=fees or {})
    hypothetical = EventLog(log.raw())
    new = hypothetical.append(ev)
    after = year_tax(hypothetical, fy, tax_class_of, **kw)
    lots = after["rows"]
    lots = lots[(lots["isin"] == isin) & (lots["account"] == account) & (lots["sell_date"] == sell_date)] \
        if len(lots) else lots
    out = {"fy": fy, "sale_event_id": new.event_id, "lots": lots, "after": after, "before": before}
    for reg in ("new", "old"):
        b, a = before["regimes"][reg].total_tax, after["regimes"][reg].total_tax
        out[reg] = {"tax_before": b, "tax_after": a, "extra_tax": a - b}
    out["proceeds"] = qty * price - sum((fees or {}).values())
    out["extra_tax_cheaper_regime"] = min(out["new"]["extra_tax"], out["old"]["extra_tax"])
    return out
