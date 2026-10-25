"""S4 Console funds ledger: running balance, charges as events, pay-ins/payouts, settlements. SYNTHETIC rows in
the layout of a real Console ledger export."""
from datetime import date

import openpyxl
import pytest

from pflab.ingest import zerodha_ledger as zl


def _xlsx(path, rows, closing):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([None, "Client ID", "ZZ0001"])
    ws.append([None, "Particulars", "Posting Date", "Cost Center", "Voucher Type", "Debit", "Credit", "Net Balance"])
    ws.append([None, "Opening Balance", "", "", "", "", "", 0.0])
    bal = 0.0
    for p, d, v, dr, cr in rows:
        bal += cr - dr
        ws.append([None, p, d, "NSE-EQ - Z", v, dr, cr, bal])
    ws.append([None, "Closing Balance", "", "", "", "", "", closing if closing is not None else bal])
    wb.save(path)
    return path


ROWS = [("Funds added using UPI", "2026-06-14", "Bank Receipts", 0.0, 10_000.0),
        ("Net settlement for Equity", "2026-06-15", "Book Voucher", 9_619.1527, 0.0),
        ("DP Charges for Sale of AAA on 17/06/2026", "2026-06-17", "Journal Entry", 15.34, 0.0),
        ("Net settlement for Equity", "2026-06-17", "Book Voucher", 0.0, 3_948.3404),
        ("Funds transferred back as part of quarterly settlement", "2026-08-07", "Bank Payments", 4_313.85, 0.0)]


def test_parse_charges_flows_and_settlements(tmp_path):
    df = zl.parse(_xlsx(tmp_path / "l.xlsx", ROWS, None))
    assert df.attrs["opening"] == 0.0 and df.attrs["closing"] == pytest.approx(10_000 - 9_619.1527 - 15.34 + 3_948.3404 - 4_313.85)
    (c,) = zl.charge_events(df, "ZER")
    assert (c.kind, c.account_id, c.date, c.amount) == ("charge", "ZER", date(2026, 6, 17), 15.34)
    assert zl.bank_flows(df)["amount"].tolist() == [10_000.0, -4_313.85]
    s = zl.settlements(df)
    assert s["net"].round(4).tolist() == [-9_619.1527, 3_948.3404]


def test_a_ledger_that_does_not_add_up_is_refused(tmp_path):
    with pytest.raises(zl.ZerodhaLedgerError, match="Closing Balance"):
        zl.parse(_xlsx(tmp_path / "bad.xlsx", ROWS, 1.0))
