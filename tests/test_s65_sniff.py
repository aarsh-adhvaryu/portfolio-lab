"""S65 Phase 7 item 3: files are recognised by their content (a PDF's first page, a workbook's header rows), not their name."""
import io
from datetime import datetime

import openpyxl
import pytest

from pflab.app import inbox as ib
from pflab.app import runtime
from pflab.ingest import sniff
from pflab.pm import store

NOW = datetime(2026, 10, 28, 10, 0)


def workbook(rows) -> bytes:
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def pdf(text: str) -> bytes:
    """A one-page PDF whose text is `text` (hand-made; pypdf rebuilds the cross-reference table)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, pos = "%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        pos.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n" + "".join(f"{p:010d} 00000 n \n" for p in pos)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n"
    return out.encode("latin-1")


def test_text_of_a_bank_statement_gives_the_bank_and_the_last_four_digits():
    got = sniff.from_text("State Bank of India  Account Statement  Account Number : 00000012345678  Statement from 01-04-2026")
    assert got["kind"] == "bank" and got["bank"] == "SBI" and got["last4"] == "5678"
    got = sniff.from_text("HDFC Bank Statement of Account  Account No :XXXXXXXX9012  Branch")
    assert (got["kind"], got["bank"], got["last4"]) == ("bank", "HDFC", "9012")


def test_text_of_a_cas_and_of_a_gift_city_statement():
    cas = sniff.from_text("Consolidated Account Statement NSDL  DP ID: IN300001 Client ID 12345678 ; DP ID:12012300 Client")
    assert cas["kind"] == "cas" and cas["dp_ids"] == "12012300,in300001"
    assert sniff.from_text("Zerodha International (IFSC) GIFT City account statement for the quarter")["kind"] == "gift_city"
    assert sniff.from_text("Your electricity bill for September")["kind"] == "other"


def test_workbook_headers_decide_the_kind_whatever_the_file_is_called():
    tb = workbook([["symbol", "isin", "trade_date", "trade_type", "quantity", "price", "trade_id"]])
    assert sniff.sniff(tb, "download (3).xlsx")["kind"] == "tradebook"
    fl = workbook([["Particulars", "Posting Date", "Cost Center", "Voucher Type", "Debit", "Credit", "Net Balance"]])
    assert sniff.sniff(fl, "x.xlsx")["kind"] == "funds_ledger"
    bk = workbook([["Account Number : 00000012345678"], ["Txn Date", "Description", "Ref No", "Debit", "Credit", "Balance"]])
    got = sniff.sniff(bk, "statement.xlsx")
    assert got["kind"] == "bank" and got["last4"] == "5678"
    assert sniff.sniff(workbook([["name", "value"]]), "random.xlsx")["kind"] == "other"
    csv = b"symbol,isin,trade_date,trade_type,quantity,price,trade_id\nABC,INE0,2026-01-01,buy,1,2,3\n"
    assert sniff.sniff(csv, "tradebook-.csv")["kind"] == "tradebook"


def test_a_pdf_is_read_on_its_first_page_and_a_broken_file_is_other():
    got = sniff.sniff(pdf("HDFC Bank Account Statement Account Number 123456789012"), "scan0001.pdf")
    assert got["kind"] == "bank" and got["bank"] == "HDFC" and got["last4"] == "9012"
    assert sniff.sniff(b"not a pdf at all", "x.pdf")["kind"] == "other"
    assert sniff.sniff(b"PK\x03\x04junk", "x.xlsx")["kind"] == "other"


def test_a_statement_is_matched_to_the_account_set_up_by_bank_and_last_four():
    accounts = {"main": {"kind": "bank", "bank": "SBI", "last4": "5678"}, "savings": {"kind": "bank", "bank": "HDFC", "last4": "9012"},
                "zer": {"kind": "broker"}}
    assert sniff.match_account({"kind": "bank", "bank": "HDFC", "last4": "9012"}, accounts) == "savings"
    assert sniff.match_account({"kind": "bank", "bank": "SBI", "last4": "0000"}, accounts) is None
    assert sniff.match_account({"kind": "bank", "bank": None, "last4": "5678"}, accounts) == "main"
    assert sniff.match_account({"kind": "cas", "last4": "5678"}, accounts) is None
    twice = {**accounts, "other": {"kind": "bank", "bank": "SBI", "last4": "5678"}}
    assert sniff.match_account({"kind": "bank", "bank": "SBI", "last4": "5678"}, twice) is None            # two fit: ask


SOURCES = """[accounts.zer]
kind = "broker"

[accounts.main]
kind = "bank"
bank = "SBI"
last4 = "5678"
"""


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    (tmp_path / "pm" / "sources.toml").write_text(SOURCES, encoding="utf-8")
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(ib, "_start", lambda rt, iid: None)
    monkeypatch.setattr(sniff, "passwords_from_secrets", lambda: [])
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def test_a_dropped_statement_finds_its_account_by_content(rt):
    bk = workbook([["State Bank of India"], ["Account Number : 00000012345678"], ["Txn Date", "Description", "Ref No", "Debit", "Credit", "Balance"]])
    got = ib.receive(rt, "Download (7).xlsx", bk)
    assert got["kind"] == "bank"
    assert rt.cursor().execute("SELECT account FROM inbox_items WHERE item_id=?", [got["id"]]).fetchone()[0] == "main"


def test_an_unknown_statement_goes_to_needs_from_you_and_a_gift_city_file_is_recorded(rt):
    bk = workbook([["Account Number : 00000099990000"], ["Txn Date", "Description", "Ref No", "Debit", "Credit", "Balance"]])
    with pytest.raises(ValueError, match="Needs from you"):
        ib.receive(rt, "mystery.xlsx", bk)
    assert any("mystery.xlsx" in t for _, _, t in __import__("pflab.agents.questions", fromlist=["x"]).open_questions(rt.cursor()))
    g = ib.receive(rt, "stmt.pdf", pdf("Zerodha International IFSC GIFT City statement"))
    assert g["kind"] == "gift_city"
    from pflab.agents import needs
    assert needs.deferred_items(rt.cursor(), NOW)["gift_city_parser"]                         # the parser item opens by itself
