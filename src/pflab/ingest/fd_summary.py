"""A bank's "Fixed Deposit Summary" export (HDFC's .xls, and any bank whose sheet has the same columns) -> deposit terms (2026-10-31).

The sheet lists one row per deposit: account number, branch, holder, currency, principal, maturity amount, maturity date, rate and start date,
then a "Total" row. The rows must add up to the Total row or the file is refused. Only the LAST FOUR digits of each account number are kept;
the holder's name, the branch and the full number never leave this module. The summary shows terms, not today's value: a deposit read from it
is valued from its terms (an estimate) until the bank's current value is known (`pm.fd`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Sequence

TOL = 1.0

COLS = {"account": ("account no", "account number", "deposit no", "deposit number", "fd no"),
        "principal": ("principal",),
        "maturity_amount": ("maturity amount", "maturity value"),
        "maturity": ("maturity date",),
        "rate": ("rate of interest", "interest rate", "roi"),
        "start": ("deposit start date", "start date", "opening date", "value date", "deposit date")}


class SummaryError(ValueError):
    pass


@dataclass(frozen=True)
class Deposit:
    last4: str
    principal: float
    maturity_amount: float
    start: date
    maturity: date
    rate_pct: float


def _num(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[,\s]|INR|Rs\.?", "", str(v))
    try:
        return float(s)
    except ValueError:
        return None


def _date(v) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    for fmt in ("%d %b %Y", "%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %B %Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def is_summary(rows: Sequence[Sequence]) -> bool:
    """True when some row carries the summary's columns (principal, maturity amount, maturity date, rate)."""
    return _header(rows) is not None


def _header(rows: Sequence[Sequence]):
    for i, r in enumerate(rows):
        cells = [str(c or "").strip().lower().rstrip(".") for c in r]
        idx = {}
        for key, names in COLS.items():
            j = next((k for k, c in enumerate(cells) if any(c.startswith(n) or c == n for n in names)), None)
            if j is not None:
                idx[key] = j
        if len(idx) == len(COLS):
            return i, idx
    return None


def bank_of(rows: Sequence[Sequence]) -> Optional[str]:
    from pflab.ingest.sniff import BANKS
    text = " ".join(str(c or "").lower() for r in rows[:20] for c in r) + " "
    return next((code for code, names in BANKS.items() if any(n in text for n in names)), None)


def parse_rows(rows: Sequence[Sequence]) -> List[Deposit]:
    """-> the deposits. Refused when no header, no deposit row, or the rows do not add up to the Total row."""
    h = _header(rows)
    if h is None:
        raise SummaryError("not a fixed deposit summary: its columns were not found")
    hi, idx = h
    out, total = [], None
    for r in rows[hi + 1:]:
        cell = lambda k: r[idx[k]] if idx[k] < len(r) else None          # noqa: E731
        if any("total" in str(c or "").lower() for c in r):
            total = (_num(cell("principal")), _num(cell("maturity_amount")))
            break
        acct = re.sub(r"\D", "", str(cell("account") or ""))
        p, m, rate = _num(cell("principal")), _num(cell("maturity_amount")), _num(cell("rate"))
        s, e = _date(cell("start")), _date(cell("maturity"))
        if len(acct) < 6 or None in (p, m, rate, s, e):
            continue                                                   # a separator, a blank or a note line
        out.append(Deposit(acct[-4:], p, m, s, e, rate))
    if not out:
        raise SummaryError("no deposit rows")
    if total is None or None in total:
        raise SummaryError("no Total row: the summary cannot be checked")
    for name, got, want in (("principal", sum(d.principal for d in out), total[0]), ("maturity amount", sum(d.maturity_amount for d in out), total[1])):
        if abs(got - want) > TOL:
            raise SummaryError(f"the rows give a {name} of {got:,.2f}, the Total row says {want:,.2f}")
    if len({d.last4 for d in out}) != len(out):
        raise SummaryError("two deposits share their last four digits: they cannot be told apart")
    return out


def parse(raw: bytes, password: Optional[str] = None) -> tuple:
    """Workbook bytes -> (bank code or None, deposits)."""
    from pflab.ingest import bank
    rows = bank._sheet_rows(raw, password)
    return bank_of(rows), parse_rows(rows)
