"""CAS import through `casparser` (PLAN S5): CAMS/KFintech detailed statements -> mutual fund events;
CDSL/NSDL statements -> demat accounts and holdings snapshots (the dormant demat included).

`casparser` (1.4.1) does the PDF parsing and returns typed models; this module maps them onto the
ledger and checks them against the statement's own totals. It never fetches email (manual download,
PLAN §10). A folio is modelled as an account whose cash is always zero: each purchase is funded by a
`deposit` of the same amount and each redemption pays out by a `withdrawal`, so XIRR sees the bank
flows and the folio never holds cash.

Mapped transaction types: PURCHASE, PURCHASE_SIP, SWITCH_IN (buy); REDEMPTION, SWITCH_OUT (sell);
DIVIDEND_PAYOUT (income, paid out); DIVIDEND_REINVEST (income, bought back in). The cost of a buy is
the statement's AMOUNT (so stamp duty is in the cost) and the proceeds of a sale are its amount. STT,
stamp-duty and TDS rows are informational and are not double counted. Anything else (scheme mergers,
segregation, gifts, reversals, misc/unknown) is NOT imported: the scheme is reported in `manual` and
left out whole, because a half-imported scheme would be wrong silently.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

import pandas as pd

from pflab.ledger.events import Event

BUY = {"PURCHASE", "PURCHASE_SIP", "SWITCH_IN"}
SELL = {"REDEMPTION", "SWITCH_OUT"}
INFO = {"STT_TAX", "STAMP_DUTY_TAX", "TDS_TAX"}
UNIT_TOL = 0.001                    # statements print units to 3 decimals


@dataclass
class CasImport:
    events: List[Event] = field(default_factory=list)
    accounts: List[dict] = field(default_factory=list)
    manual: List[str] = field(default_factory=list)          # schemes left out, with why
    unmapped: List[str] = field(default_factory=list)        # schemes with no ISIN
    warnings: List[str] = field(default_factory=list)
    skipped_existing: int = 0


def parse_pdf(path, password: str):
    """casparser's typed result for a CAS PDF (CASData for CAMS/KFin, NSDLCASData for CDSL/NSDL)."""
    import casparser
    return casparser.read_cas_pdf(str(path), password)


def _d(v) -> date:
    if isinstance(v, date):
        return v
    s = str(v)
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable CAS date {v!r}")


def _type(t) -> str:
    """A transaction's type as its plain name, whether casparser gave an enum member or a string."""
    ty = t.type
    return getattr(ty, "name", None) or str(ty).split(".")[-1]


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def folio_account(amc: str, folio: str) -> str:
    return f"{amc.strip()}:{folio.strip()}"


def amfi_isin_lookup(con) -> Callable[[str], Optional[str]]:
    """AMFI scheme code -> ISIN from the PM store (the scheme's first ISIN)."""
    rows = con.execute("SELECT scheme_code, isin_1, isin_2 FROM amfi_schemes").fetchall()
    m = {r[0]: (r[1] or r[2]) for r in rows}
    return lambda code: m.get(str(code))


def scheme_isin(sch, by_amfi: Optional[Callable[[str], Optional[str]]]) -> Optional[str]:
    if getattr(sch, "isin", None):
        return sch.isin
    if by_amfi and getattr(sch, "amfi", None):
        return by_amfi(sch.amfi)
    return None


def cams_events(cas, *, by_amfi: Optional[Callable[[str], Optional[str]]] = None,
                tax_class_of: Optional[Callable[[str], Optional[str]]] = None,
                existing_refs: Optional[Set[str]] = None, source_doc_sha: str = "") -> CasImport:
    """Events for every importable scheme of a CAMS/KFin CAS. Idempotent: refs already present are skipped."""
    existing_refs = existing_refs or set()
    out = CasImport()
    for w in getattr(cas, "parse_warnings", []) or []:
        out.warnings.append(w)
    for folio in cas.folios:
        acc = folio_account(folio.amc, folio.folio)
        out.accounts.append(dict(account_id=acc, kind="folio", provider=folio.amc, dp_or_folio=folio.folio))
        for sch in folio.schemes:
            isin = scheme_isin(sch, by_amfi)
            label = f"{folio.amc} {folio.folio} {sch.scheme}"
            if not isin:
                out.unmapped.append(label)
                continue
            odd = sorted({_type(t) for t in sch.transactions} - BUY - SELL - INFO - {"DIVIDEND_PAYOUT", "DIVIDEND_REINVEST"})
            if odd:
                out.manual.append(f"{label}: transaction types {odd} need a manual decision")
                continue
            tc = tax_class_of(isin) if tax_class_of else None
            evs: List[Event] = []
            for n, t in enumerate(sch.transactions):
                typ, d = _type(t), _d(t.date)
                ref = f"cas:{acc}:{isin}:{d}:{typ}:{n}:{_f(t.units):.4f}:{_f(t.amount):.2f}"
                if typ in INFO:
                    continue
                units, amt = abs(_f(t.units)), abs(_f(t.amount))
                if typ in BUY:
                    evs += [Event("deposit", acc, d, amount=amt, ref=ref + ":fund", source_doc_sha=source_doc_sha),
                            Event("buy", acc, d, isin=isin, qty=units, price=amt / units, ref=ref,
                                  source_doc_sha=source_doc_sha, tax_class=tc)]
                elif typ in SELL:
                    evs += [Event("sell", acc, d, isin=isin, qty=units, price=amt / units, ref=ref,
                                  source_doc_sha=source_doc_sha, tax_class=tc),
                            Event("withdrawal", acc, d, amount=amt, ref=ref + ":payout", source_doc_sha=source_doc_sha)]
                elif typ == "DIVIDEND_PAYOUT":
                    evs += [Event("dividend", acc, d, isin=isin, amount=amt, ref=ref, source_doc_sha=source_doc_sha),
                            Event("withdrawal", acc, d, amount=amt, ref=ref + ":payout", source_doc_sha=source_doc_sha)]
                elif typ == "DIVIDEND_REINVEST":
                    # paid out and bought back in: same-day deposit and withdrawal of the same amount cancel as an
                    # external flow, and the ledger's same-day order (deposit before buy) never sees a negative balance
                    evs += [Event("dividend", acc, d, isin=isin, amount=amt, ref=ref, source_doc_sha=source_doc_sha),
                            Event("withdrawal", acc, d, amount=amt, ref=ref + ":payout", source_doc_sha=source_doc_sha),
                            Event("deposit", acc, d, amount=amt, ref=ref + ":reinvest_fund", source_doc_sha=source_doc_sha),
                            Event("buy", acc, d, isin=isin, qty=units, price=amt / units, ref=ref + ":reinvest",
                                  source_doc_sha=source_doc_sha, tax_class=tc)]
            fresh = [e for e in evs if e.ref not in existing_refs]
            out.skipped_existing += len(evs) - len(fresh)
            out.events += fresh
    return out


def verify_against_statement(cas, ledger, by_amfi: Optional[Callable[[str], Optional[str]]] = None,
                             tol: float = UNIT_TOL) -> pd.DataFrame:
    """Per scheme: the statement's closing units against the ledger's units in that folio account. One row
    per scheme with `ok`; a scheme the importer left out (manual/unmapped) shows as not ok with a note."""
    rows = []
    for folio in cas.folios:
        acc = folio_account(folio.amc, folio.folio)
        for sch in folio.schemes:
            isin = scheme_isin(sch, by_amfi)
            have = ledger.holdings(isin, acc) if isin else None
            want = _f(sch.close)
            ok = have is not None and abs(have - want) <= tol
            rows.append(dict(account=acc, isin=isin, scheme=sch.scheme, statement_close=want,
                             statement_close_calculated=_f(sch.close_calculated), ledger_units=have, ok=ok,
                             note="" if ok else ("no ISIN" if isin is None else f"differ by {(have or 0) - want:+.4f}")))
    return pd.DataFrame(rows, columns=["account", "isin", "scheme", "statement_close", "statement_close_calculated",
                                       "ledger_units", "ok", "note"])


# --- depository CAS (CDSL / NSDL): accounts and holdings snapshot --------------------------------------------

def demat_account_id(acc) -> str:
    return f"{acc.type}:{acc.dp_id or ''}:{acc.client_id or ''}"


def demat_accounts(cas, dormant: Iterable[str] = (), read_only: Iterable[str] = ()) -> List[dict]:
    """Account rows for every demat on the statement. `dormant` and `read_only` are the investor's lists of
    account ids (PLAN §10: the old dormant demat is imported read-only, flagged, included in totals)."""
    dormant, read_only = set(dormant), set(read_only)
    return [dict(account_id=demat_account_id(a), kind="demat", provider=a.type, dp_or_folio=f"{a.dp_id}/{a.client_id}",
                 dormant=demat_account_id(a) in dormant, read_only=demat_account_id(a) in (read_only | dormant),
                 holder=a.name) for a in cas.accounts]


def _bond_qty_price(b) -> Tuple[float, float]:
    """(quantity, price) of a CAS bond row. On the older NSDL layout (seen May/June 2026) casparser 1.4.1 reads
    the columns one place off: `num_bonds` holds the face value, `face_value` the market price and
    `maturity_date` the quantity. The reading is accepted only when quantity x price equals the stated value."""
    value = _f(b.value)
    mat = str(b.maturity_date or "").strip()
    if mat.isdigit() and b.face_value is not None and abs(int(mat) * _f(b.face_value) - value) <= 1.0:
        return float(int(mat)), _f(b.face_value)
    qty = _f(b.num_bonds)
    if b.market_price is not None:
        price = _f(b.market_price)
        if abs(qty * price - value) > 1.0:
            raise ValueError(f"CAS bond {b.isin}: {qty} x {price} is not the stated value {value}")
        return qty, price
    return qty, (value / qty if qty else 0.0)


def holdings_snapshot(cas) -> pd.DataFrame:
    """Every holding on a depository CAS: account, isin, kind, qty, price, value."""
    rows = []
    for a in cas.accounts:
        aid = demat_account_id(a)
        for e in a.equities:
            rows.append(dict(account=aid, isin=e.isin, kind="equity", qty=_f(e.num_shares), price=_f(e.price), value=_f(e.value), name=e.name))
        for m in a.mutual_funds:
            rows.append(dict(account=aid, isin=m.isin, kind="mutual_fund", qty=_f(m.balance), price=_f(m.nav), value=_f(m.value), name=m.name))
        for b in a.bonds:
            qty, price = _bond_qty_price(b)
            rows.append(dict(account=aid, isin=b.isin, kind="bond", qty=qty, price=price, value=_f(b.value), name=b.name))
    return pd.DataFrame(rows, columns=["account", "isin", "kind", "qty", "price", "value", "name"])


def opening_events(snapshot: pd.DataFrame, as_of: date, account_alias: Optional[Dict[str, str]] = None,
                   cost_of: Optional[Callable[[str, str], Optional[Tuple[date, float]]]] = None) -> Tuple[List[Event], List[str]]:
    """Opening lots for holdings that have no transaction history in the ledger. A depository CAS carries no
    cost or purchase date, so unless `cost_of(account, isin)` supplies (acquisition date, total cost) the
    lot is created at COST 0 on `as_of`: the highest possible gain, never a silent guess. Every such lot is
    listed so the investor can supply the real figures; a lot dated `as_of` also starts its holding period there."""
    alias = account_alias or {}
    evs, unknown = [], []
    for r in snapshot.itertuples(index=False):
        acc = alias.get(r.account, r.account)
        known = cost_of(r.account, r.isin) if cost_of else None
        if known:
            d, cost = known
            evs.append(Event("deposit", acc, d, amount=cost, ref=f"cas_opening:{r.account}:{r.isin}:fund"))
            evs.append(Event("buy", acc, d, isin=r.isin, qty=r.qty, price=cost / r.qty, ref=f"cas_opening:{r.account}:{r.isin}"))
        else:
            evs.append(Event("buy", acc, as_of, isin=r.isin, qty=r.qty, price=0.0, ref=f"cas_opening:{r.account}:{r.isin}:cost_unknown"))
            unknown.append(f"{acc} {r.isin} x {r.qty:g}: cost and purchase date unknown (lot opened at cost 0 on {as_of})")
    return evs, unknown
