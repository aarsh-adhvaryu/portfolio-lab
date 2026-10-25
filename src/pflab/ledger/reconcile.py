"""Reconciliation of the ledger against an outside source (PLAN S7; first cut with S4 for Kite holdings).

A break is a row, never an exception: `holdings_breaks` compares quantities by ISIN and returns every
difference above the tolerance. S7 adds the other sources (CDSL, CAMS, bank), opening balances and the
accounting invariants; the `recon_breaks` table is shared.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

import pandas as pd

COLUMNS = ["source_a", "source_b", "isin", "account", "field", "a_value", "b_value", "status", "note"]


def holdings_breaks(source: str, source_qty: Dict[str, float], ledger_positions: Dict[tuple, float],
                    account: Optional[str] = None, tol: float = 1e-6) -> pd.DataFrame:
    """Ledger quantity by ISIN (summed over `account` if given, else all accounts) against `source_qty`
    {isin: qty}. One row per ISIN whose quantities differ by more than `tol`; none if they agree."""
    led: Dict[str, float] = {}
    for (acc, isin), q in ledger_positions.items():
        if account is None or acc == account:
            led[isin] = led.get(isin, 0.0) + q
    rows = []
    for isin in sorted(set(led) | set(source_qty)):
        a, b = led.get(isin, 0.0), float(source_qty.get(isin, 0.0))
        if abs(a - b) > tol:
            note = "in the ledger, not at the source" if b == 0 else "at the source, not in the ledger" if a == 0 \
                else f"quantities differ by {a - b:+g}"
            rows.append(dict(source_a="ledger", source_b=source, isin=isin, account=account, field="qty",
                             a_value=a, b_value=b, status="open", note=note))
    return pd.DataFrame(rows, columns=COLUMNS)


def save_breaks(con, breaks: pd.DataFrame, run_id: str, now: Optional[datetime] = None) -> int:
    now = now or datetime.now()
    for r in breaks.itertuples(index=False):
        con.execute("INSERT INTO recon_breaks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [run_id, r.source_a, r.source_b, r.isin, r.account, r.field, r.a_value, r.b_value, r.status,
                     r.note, now])
    return len(breaks)
