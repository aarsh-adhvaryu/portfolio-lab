"""Zerodha Console funds ledger (.xlsx) -> charges not on contract notes, and the checks (PLAN S4).

Rows: Particulars, Posting Date, Cost Center, Voucher Type, Debit, Credit, Net Balance, between an Opening
Balance and a Closing Balance row. Voucher types:
    Bank Receipts / Bank Payments  money in from / out to the investor's bank: the bank statements carry these
                                   (as broker transfers); here they are only checked
    Book Voucher                   net settlement of a trading day: must equal that day's contract note net
    Journal Entry                  charges levied outside the contract note (DP charges on sales, payment
                                   gateway fees, bank-change fees, AMC): these become `charge` events
The running Net Balance is checked row by row: a ledger that does not add up is refused.
"""
from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path
from typing import List, Union

import pandas as pd

from pflab.ledger.events import Event

TOL = 0.01


class ZerodhaLedgerError(ValueError):
    pass


def _d(v) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return datetime.strptime(str(v).strip(), "%Y-%m-%d").date()


def parse(path: Union[str, Path]) -> pd.DataFrame:
    """-> particulars, date, voucher, debit, credit, balance; attrs opening/closing balance."""
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(Path(path).read_bytes()), data_only=True).worksheets[0]
    rows = [[c for c in r] for r in ws.iter_rows(values_only=True)]
    head = next((i for i, r in enumerate(rows) if "Particulars" in r and "Voucher Type" in r), None)
    if head is None:
        raise ZerodhaLedgerError("no header row with Particulars and Voucher Type")
    col = {str(c): j for j, c in enumerate(rows[head]) if c}
    opening = closing = None
    out = []
    for r in rows[head + 1:]:
        part = r[col["Particulars"]]
        if part is None:
            continue
        bal = r[col["Net Balance"]]
        if str(part).strip() == "Opening Balance":
            opening = float(bal or 0.0)
            continue
        if str(part).strip() == "Closing Balance":
            closing = float(bal or 0.0)
            continue
        out.append(dict(particulars=str(part).strip(), date=_d(r[col["Posting Date"]]), voucher=str(r[col["Voucher Type"]]).strip(),
                        debit=float(r[col["Debit"]] or 0.0), credit=float(r[col["Credit"]] or 0.0), balance=float(bal)))
    if opening is None or closing is None:
        raise ZerodhaLedgerError("Opening or Closing Balance row missing")
    df = pd.DataFrame(out, columns=["particulars", "date", "voucher", "debit", "credit", "balance"])
    prev = opening
    for i, x in df.iterrows():
        if abs(prev + x["credit"] - x["debit"] - x["balance"]) > TOL:
            raise ZerodhaLedgerError(f"running balance breaks at row {i + 1} ({x['date']} {x['particulars'][:40]!r})")
        prev = x["balance"]
    if abs(prev - closing) > TOL:
        raise ZerodhaLedgerError(f"rows end at {prev:,.4f}, the Closing Balance row says {closing:,.4f}")
    df.attrs.update(opening=opening, closing=closing)
    return df


def parse_many(paths) -> pd.DataFrame:
    """Several Console ledgers (other years, or overlapping ranges) as one: a row in two files (same date, particulars, voucher, amounts and balance,
    counted per occurrence) is kept once; the opening balance is the earliest file's and the closing balance the latest file's."""
    frames = [parse(p) for p in paths]
    if len(frames) == 1:
        return frames[0]
    key = ["date", "particulars", "voucher", "debit", "credit", "balance"]
    frames.sort(key=lambda f: (f["date"].min() if len(f) else date.max, f["date"].max() if len(f) else date.max))
    tagged = []
    for f in frames:
        t = f.copy()
        t["_n"] = t.groupby(key).cumcount()
        tagged.append(t)
    out = pd.concat(tagged, ignore_index=True).drop_duplicates(key + ["_n"], keep="first").drop(columns="_n").reset_index(drop=True)
    out.attrs.update(opening=frames[0].attrs["opening"], closing=frames[-1].attrs["closing"])
    return out


def charge_events(df: pd.DataFrame, account: str, source_doc_sha: str = "") -> List[Event]:
    """Journal-entry debits as `charge` events (ref names the charge; a credit journal is refused: it would be
    a reversal this importer does not model)."""
    j = df[df["voucher"] == "Journal Entry"]
    if (j["credit"] > 0).any():
        raise ZerodhaLedgerError("a credit journal entry (reversal) is not modelled")
    return [Event("charge", account, r.date, amount=round(r.debit, 2), ref=f"zledger:{r.date}:{n}:{r.particulars[:60]}",
                  source_doc_sha=source_doc_sha) for n, r in enumerate(j.itertuples())]


def bank_flows(df: pd.DataFrame) -> pd.DataFrame:
    """Pay-ins (+) and payouts (-) by date, to check against the bank statements' broker transfers."""
    b = df[df["voucher"].isin(["Bank Receipts", "Bank Payments"])]
    return pd.DataFrame({"date": b["date"], "amount": b["credit"] - b["debit"]}).reset_index(drop=True)


def settlements(df: pd.DataFrame) -> pd.DataFrame:
    """Net settlement per day (+ receivable / - payable), to check against the contract notes."""
    s = df[df["voucher"] == "Book Voucher"]
    return s.groupby("date").apply(lambda g: (g["credit"] - g["debit"]).sum(), include_groups=False) \
        .rename("net").reset_index()
