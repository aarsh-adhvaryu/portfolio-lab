"""IPO applications: blocked funds, allotment, release, listing (PLAN S19).

The money of an ASBA / UPI application stays in the bank account but cannot be spent: the cash
ledger refuses any outflow that would dip into it. At allotment the block is released and only
the allotted amount is paid, in the same event; shares enter lots dated at ALLOTMENT (holding
period and cost start there; listing changes nothing in the lots). A non-allotment is a release.

Events (all `kind="ipo_*"`, `ref` = the IPO id):
    ipo_block    account, date, amount; params bid_qty, bid_price, category, mandate_ref
    ipo_allot    account (the funding account), date, isin, qty, price, fees;
                 params demat_account (where the shares land)
    ipo_release  account, date: unblock without allotment (non-allotment, withdrawal of bid)
    ipo_list     date, isin: listing day (information; `listed_on` in the application row)
Acquisitions without STT (IPO allotments) and the 112A condition are an open tax item (PLAN §6).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Optional

from pflab.ledger.events import Event


class IpoError(ValueError):
    pass


@dataclass
class Application:
    ipo_id: str
    account: str                    # funding (bank / cash) account
    category: str
    bid_qty: float
    bid_price: float
    amount_blocked: float
    blocked_on: date
    mandate_ref: str = ""
    status: str = "blocked"         # blocked | allotted | released
    allotted_qty: float = 0.0
    allotted_amount: float = 0.0
    isin: Optional[str] = None
    refund_on: Optional[date] = None
    listed_on: Optional[date] = None
    demat_account: Optional[str] = None


class IpoBook:
    def __init__(self):
        self.apps: Dict[str, Application] = {}

    def blocked(self, account: str) -> float:
        return float(sum(a.amount_blocked for a in self.apps.values()
                         if a.account == account and a.status == "blocked"))

    def blocked_by_account(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for a in self.apps.values():
            if a.status == "blocked":
                out[a.account] = out.get(a.account, 0.0) + a.amount_blocked
        return out


# --- builders ------------------------------------------------------------------------------------

def block(ipo_id: str, account: str, d: date, bid_qty: float, bid_price: float, category: str = "retail",
          mandate_ref: str = "", amount: Optional[float] = None, source_doc_sha: str = "") -> Event:
    """Funds blocked for a bid. `amount` defaults to bid_qty x bid_price (retail bids block at the
    cut-off price, the top of the band)."""
    return Event("ipo_block", account, d, ref=ipo_id, amount=amount if amount is not None else bid_qty * bid_price,
                 source_doc_sha=source_doc_sha,
                 params={"bid_qty": bid_qty, "bid_price": bid_price, "category": category, "mandate_ref": mandate_ref})


def allot(ipo_id: str, account: str, d: date, isin: str, qty: float, price: float, demat_account: str,
          fees: Optional[dict] = None, tax_class: Optional[str] = None, source_doc_sha: str = "") -> Event:
    return Event("ipo_allot", account, d, ref=ipo_id, isin=isin, qty=qty, price=price, fees=fees or {},
                 tax_class=tax_class, source_doc_sha=source_doc_sha, params={"demat_account": demat_account})


def release(ipo_id: str, account: str, d: date, source_doc_sha: str = "") -> Event:
    return Event("ipo_release", account, d, ref=ipo_id, source_doc_sha=source_doc_sha, params={})


def listed(ipo_id: str, isin: str, d: date) -> Event:
    return Event("ipo_list", "-", d, ref=ipo_id, isin=isin, params={})


# --- application to a Ledger -----------------------------------------------------------------------------

def apply(led, e: Event) -> None:
    book: IpoBook = led.ipo
    if e.kind == "ipo_block":
        if e.ref in book.apps:
            raise IpoError(f"IPO application {e.ref!r} already exists")
        available = led.cash_available(e.account_id)
        if e.amount > available + 1e-6:
            raise IpoError(f"IPO {e.ref}: blocking Rs {e.amount:,.2f} but only Rs {available:,.2f} is available "
                           f"in {e.account_id}")
        book.apps[e.ref] = Application(e.ref, e.account_id, e.params.get("category", "retail"),
                                       e.params["bid_qty"], e.params["bid_price"], e.amount, e.date,
                                       e.params.get("mandate_ref", ""))
        led.cash.set_blocked(e.account_id, book.blocked(e.account_id))
        return
    app = book.apps.get(e.ref)
    if e.kind == "ipo_list":
        if app is None:
            raise IpoError(f"listing for unknown IPO {e.ref!r}")
        app.listed_on = e.date
        app.isin = app.isin or e.isin
        return
    if app is None:
        raise IpoError(f"{e.kind} for unknown IPO {e.ref!r}")
    if app.status != "blocked":
        raise IpoError(f"IPO {e.ref} is already {app.status}")
    if e.account_id != app.account:
        raise IpoError(f"IPO {e.ref} was funded from {app.account}, not {e.account_id}")
    if e.kind == "ipo_release":
        app.status, app.refund_on = "released", e.date
        led.cash.set_blocked(app.account, book.blocked(app.account))
        return
    if e.kind == "ipo_allot":
        pay = e.qty * e.price + e.fee_total
        if pay > app.amount_blocked + 1e-6:
            raise IpoError(f"IPO {e.ref}: allotment costs Rs {pay:,.2f}, more than the Rs {app.amount_blocked:,.2f} blocked")
        if e.qty > app.bid_qty + 1e-9:
            raise IpoError(f"IPO {e.ref}: allotted {e.qty} but bid for {app.bid_qty}")
        app.status, app.refund_on = "allotted", e.date
        app.allotted_qty, app.allotted_amount, app.isin = e.qty, pay, e.isin
        app.demat_account = e.params["demat_account"]
        led.cash.set_blocked(app.account, book.blocked(app.account))          # release first ...
        led.cash.post(app.account, e.date, -pay, "ipo_allot", e.ref, e.event_id)   # ... then pay the allotted part
        led.lots.buy(app.demat_account, e.isin, e.date, e.qty, e.price, e.cost_fee_total, e.tax_class, e.event_id)
        led._fees(e)
        return
    raise IpoError(f"unhandled IPO event {e.kind}")
