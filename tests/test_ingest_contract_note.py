"""S4 contract note parser. Every note below is SYNTHETIC text in the layout of a real Zerodha contract note
(pypdf extraction of the 2026-09-29 sample: header, per-ISIN summary, levies block, Annexure A); the real
note itself is not in the repo."""
from datetime import date

import pytest

from pflab.ingest import contract_note as cn
from pflab.ingest import tradebook as tb
from pflab.ledger.book import Ledger
from pflab.ledger.events import Event, EventLog

HEADER = """CONTRACT NOTE CUM TAX INVOICE
Contract Note No: CNT-26/27-000000001 NCL-Cash NCL-F&O
Settlement No: 2026001Trade Date: 01/10/2026
Settlement Date: 03/10/2026
"""

# buy 10 AAA @ 100 (two executions: 6 + 4), sell 5 BBB @ 200
SUMMARY = """INE111A01011 AAA 10 100.0000 0.0000 100.0000 1000.00 0 0.0000 0.0000 0.0000 0.00 10 −1000.00
INE222B01022 BBB 0 0.0000 0.0000 0.0000 0.00 5 200.0000 0.0000 200.0000 1000.00 −5 1000.00
"""
LEVIES = """NCL-Cash NCL-F&O NET TOTAL
Pay in/Pay out obligation (₹) 0.00 0.00 0.00
Taxable value of Supply (Brokerage) (₹)2 (0.40) (0.40)
Exchange transaction charges (₹)4 (0.06) (0.06)
Clearing charges (₹)
IGST (@18% of Brok, SEBI, Trans & Clearing Charges) (₹)3 (0.08) (0.08)
Securities transaction tax (₹) (2.00) (2.00)
SEBI turnover fees (₹) (0.02) (0.02)
Stamp duty (₹) (0.15) (0.15)
Net amount receivable/(payable by client) (₹) (2.71) 0.00 (2.71)
"""
ANNEX = """Annexure A
Equity
1000000000000000001 10:00:00 5001 10:00:01 AAA-A/INE111A01011 B NSE 6 0.0000 100.00 (600.00)
1000000000000000001 10:00:00 5002 10:00:02 AAA-A/INE111A01011 B NSE 4 0.0000 100.00 (400.00)
1000000000000000002 11:00:00 5003 11:00:01 BBB-A/INE222B01022 S BSE 5 0.0000 200.00 1000.00
"""
NOTE = HEADER + SUMMARY + LEVIES + ANNEX


def test_parse_header_trades_levies_and_checks():
    n = cn.parse_text(NOTE)
    assert n.number == "CNT-26/27-000000001" and n.trade_date == date(2026, 10, 1) and n.settlement_date == date(2026, 10, 3)
    assert list(n.trades["trade_id"]) == ["5001", "5002", "5003"] and list(n.trades["side"]) == ["buy", "buy", "sell"]
    assert n.trades["exchange"].tolist() == ["NSE", "NSE", "BSE"] and n.trades["value"].tolist() == [600.0, 400.0, 1000.0]
    assert n.levies == {"brokerage": 0.40, "exchange_txn": 0.06, "igst": 0.08, "stt": 2.00, "sebi": 0.02, "stamp_duty": 0.15}
    assert n.obligation == 0.0 and n.net_amount == -2.71
    assert [s["net_qty"] for s in n.summary] == [10, -5]


def test_allocation_sums_exactly_and_stamp_duty_goes_to_buys_only():
    n = cn.parse_text(NOTE)
    a = cn.allocate(n)
    for key, total in n.levies.items():
        assert sum(f.get(key, 0.0) for f in a.values()) == pytest.approx(total, abs=1e-9)
    assert "stamp_duty" not in a["5003"] and a["5001"]["stamp_duty"] == 0.09 and a["5002"]["stamp_duty"] == 0.06
    assert a["5003"]["stt"] == 1.0 and a["5001"]["stt"] == 0.6 and a["5002"]["stt"] == 0.4      # by value


@pytest.mark.parametrize("mutate,msg", [
    (lambda s: s.replace("B NSE 4 0.0000 100.00 (400.00)", "B NSE 3 0.0000 100.00 (300.00)"), "do not add up"),
    (lambda s: s.replace("Stamp duty (₹) (0.15) (0.15)", "Stamp duty (₹) (0.95) (0.95)"), "is not the net amount"),
    (lambda s: s.replace("Contract Note No: CNT-26/27-000000001", "Statement"), "not a Zerodha contract note"),
    (lambda s: s.split("Annexure A")[0], "no trades"),
    (lambda s: s.replace("5002 10:00:02", "5001 10:00:02"), "appears twice"),
])
def test_a_note_that_does_not_reconcile_is_refused(mutate, msg):
    with pytest.raises(cn.ContractNoteError, match=msg):
        cn.parse_text(mutate(NOTE))


def test_buy_only_levy_with_no_buy_is_refused():
    n = cn.parse_text(NOTE)
    n.trades = n.trades[n.trades["side"] == "sell"]
    with pytest.raises(cn.ContractNoteError, match="no buy trade"):
        cn.allocate(n)


CSV = """symbol,isin,trade_date,exchange,segment,series,trade_type,auction,quantity,price,trade_id,order_id,order_execution_time
BBB,INE222B01022,2026-09-01,BSE,EQ,EQ,buy,false,5,150,4001,O0,2026-09-01T10:00:00
AAA,INE111A01011,2026-10-01,NSE,EQ,EQ,buy,false,6,100,5001,O1,2026-10-01T10:00:01
AAA,INE111A01011,2026-10-01,NSE,EQ,EQ,buy,false,4,100,5002,O1,2026-10-01T10:00:02
BBB,INE222B01022,2026-10-01,BSE,EQ,EQ,sell,false,5,200,5003,O2,2026-10-01T11:00:01
"""


def test_fees_attach_to_tradebook_events_and_flow_to_cash_and_cost():
    events, _ = tb.to_events(tb.parse(CSV), "ZER")
    with_fees, rep = cn.apply_fees(events, [cn.parse_text(NOTE)])
    assert rep["with_fees"] == 3 and rep["without_note"] == [(date(2026, 9, 1), "4001")]
    assert rep["note_trades_not_in_tradebook"] == []
    led = Ledger.replay(EventLog([Event("deposit", "ZER", date(2026, 8, 1), amount=5_000.0), *with_fees]))
    assert led.cash_balance("ZER") == pytest.approx(5_000 - 750 - 1000 + 1000 - 2.71)        # the note's net
    (c,) = led.realised
    stt = cn.allocate(cn.parse_text(NOTE))["5003"]
    assert c.proceeds == pytest.approx(1000 - sum(v for k, v in stt.items() if k != "stt"))  # STT not deductible


def test_a_note_disagreeing_with_the_tradebook_is_refused():
    events, _ = tb.to_events(tb.parse(CSV.replace(",4,100,5002,", ",4,101,5002,")), "ZER")
    with pytest.raises(cn.ContractNoteError, match="disagree"):
        cn.apply_fees(events, [cn.parse_text(NOTE)])


def test_wrong_or_missing_password_is_refused(tmp_path):
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(100, 100)
    w.encrypt("PAN0000000")
    p = tmp_path / "cn.pdf"
    with open(p, "wb") as f:
        w.write(f)
    with pytest.raises(cn.ContractNoteError, match="password"):
        cn.read_text(p)
    with pytest.raises(cn.ContractNoteError, match="password"):
        cn.read_text(p, "WRONG")
    assert cn.read_text(p, "PAN0000000") == ""


def _xlsx_note(path, net="-2.71", stamp="-0.15"):
    """Console's Excel layout: header cells, trade table under 'Order No.', levies with a NET TOTAL column."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "01-10-2026"
    rows = [["CONTRACT NOTE CUM TAX INVOICE"], [], ["CONTRACT NOTE NO: ", "CNT-26/27-000000001", "NCL-Cash"],
            ["Trade Date:", "01-10-2026", "Settlement No.", "2026001"], ["Settlement Date.", "03/10/2026"], [],
            ["Order No.", "Order Time.", "Trade No.", "Trade Time", "Security/Contract Description", "Buy(B) / Sell(S)",
             "Quantity", "Exchange", "Gross Rate / Trade Price Per Unit (Rs)", "Brokerage per Unit (Rs)",
             "Net Rate per Unit (Rs)", "Closing Rate per Unit (Only for Derivatives) (Rs)", "Net Total (Before Levies) (Rs)"],
            ["Equity"],
            ["1000000000000000001", "10:00:00", "5001", "10:00:01", "AAA-A/INE111A01011", "B", "6", "NSE", "100", "0", "0", None, "-600"],
            ["1000000000000000001", "10:00:00", "5002", "10:00:02", "AAA-A/INE111A01011", "B", "4", "NSE", "100", "0", "0", None, "-400"],
            ["1000000000000000002", "11:00:00", "5003", "11:00:01", "BBB-EQ/INE222B01022", "S", "5", "BSE", "200", "0", "0", None, "1000"],
            [], [None] * 7 + ["NCL-Cash", None, None, "NET TOTAL"]]
    for label, v in [("Pay in/Pay out obligation (₹)", "0"), ("Taxable value of Supply (Brokerage) (₹)", "-0.4"),
                     ("Exchange transaction charges (₹)", "-0.06"), ("Clearing charges (₹)", "0"),
                     ("IGST (@18% of Brok, SEBI, Trans & Clearing Charges) (₹)", "-0.08"),
                     ("Securities transaction tax (₹)", "-2"), ("SEBI turnover fees (₹)", "-0.02"),
                     ("Stamp duty (₹)", stamp), ("Net amount receivable/(payable by client) (₹)", net)]:
        rows.append([label] + [None] * 6 + [v, None, None, v])
    for r in rows:
        ws.append(r)
    wb.create_sheet("notes")                                  # a sheet with no contract note is skipped
    wb.save(path)
    return path


def test_console_excel_notes_parse_like_the_pdf(tmp_path):
    (x,) = cn.parse_xlsx(_xlsx_note(tmp_path / "cn.xlsx"))
    pdf = cn.parse_text(NOTE)
    assert (x.number, x.trade_date, x.settlement_date) == (pdf.number, pdf.trade_date, pdf.settlement_date)
    assert x.levies == pdf.levies and x.obligation == pdf.obligation and x.net_amount == pdf.net_amount
    cols = ["trade_id", "order_id", "isin", "side", "exchange", "qty", "price", "value"]
    assert x.trades[cols].equals(pdf.trades[cols])
    assert cn.allocate(x) == cn.allocate(pdf)


def test_excel_note_that_does_not_reconcile_is_refused(tmp_path):
    with pytest.raises(cn.ContractNoteError, match="is not the net amount"):
        cn.parse_xlsx(_xlsx_note(tmp_path / "bad.xlsx", stamp="-0.95"))


def test_tradebook_float_noise_in_price_still_matches():
    events, _ = tb.to_events(tb.parse(CSV.replace(",6,100,5001,", ",6,99.9999,5001,")), "ZER")
    _, rep = cn.apply_fees(events, [cn.parse_text(NOTE)])
    assert rep["with_fees"] == 3
