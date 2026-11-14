"""S86b C5: links printed inside a file are followed (free) and said plainly; spreadsheets and PDFs end as read-with-a-fact or the TRUE reason; synthetic fixtures only."""
from __future__ import annotations

import hashlib
import io

import pytest

from pflab.entrance import readers


class _Raw:
    def __init__(self, b):
        self._b = b

    def read(self, n, decode_content=True):
        return self._b[:n]


class _Resp:
    def __init__(self, body, url="https://example.invalid/final.pdf", code=200, ct="application/pdf"):
        self.raw, self.url, self.status_code, self.headers = _Raw(body), url, code, {"Content-Type": ct}


def test_links_printed_in_a_file_are_found():
    assert readers.links_in("Read now: https://go.example.invalid/abc. And (https://x.example.invalid/p).") == ["https://go.example.invalid/abc", "https://x.example.invalid/p"]
    assert readers.links_in("no links here") == []


def test_a_link_that_leads_to_the_same_file_is_said_so(monkeypatch):
    body = b"%PDF-1.7 the same bytes"
    monkeypatch.setattr(readers, "_private_host", lambda h: False)
    r = readers.resolve_link("https://go.example.invalid/abc", hashlib.sha256(body).hexdigest(), getter=lambda url, **k: _Resp(body))
    assert r["same_file"] is True and r["error"] is None and r["final_url"].endswith("final.pdf")
    r2 = readers.resolve_link("https://go.example.invalid/abc", hashlib.sha256(b"other").hexdigest(), getter=lambda url, **k: _Resp(body))
    assert r2["same_file"] is False and r2["error"] is None


def test_a_private_or_failing_link_says_why(monkeypatch):
    assert "not a public web address" in readers.resolve_link("http://127.0.0.1/x", "0")["error"]
    monkeypatch.setattr(readers, "_private_host", lambda h: False)
    assert "404" in readers.resolve_link("https://x.example.invalid/", "0", getter=lambda url, **k: _Resp(b"", code=404))["error"]

    def boom(url, **k):
        raise ConnectionError("login wall")
    assert "ConnectionError" in readers.resolve_link("https://x.example.invalid/", "0", getter=boom)["error"]


# ------------------------------------------------------------------ every unreadable file ends in a TRUE reason, a readable one in none

def _pdf_with_text(tmp_path, text="Annual note of a synthetic company. Revenue rose and the board approved a dividend of three rupees."):
    body = f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(body) + body + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, x)
    p = tmp_path / "text.pdf"
    p.write_bytes(out)
    return p


def test_a_pdf_with_text_has_no_reason_a_scan_a_blank_and_a_protected_one_each_say_why(tmp_path):
    from PIL import Image
    import pypdf
    assert readers.why_unreadable(_pdf_with_text(tmp_path)) is None
    scan = tmp_path / "scan.pdf"
    Image.new("RGB", (200, 200), "white").save(scan, "PDF")
    assert "a scan with no text layer" in readers.why_unreadable(scan)
    blank = tmp_path / "blank.pdf"
    w = pypdf.PdfWriter()
    w.add_blank_page(200, 200)
    w.write(blank.open("wb"))
    assert "is empty" in readers.why_unreadable(blank)
    prot = tmp_path / "prot.pdf"
    w2 = pypdf.PdfWriter()
    w2.add_blank_page(200, 200)
    w2.encrypt("pw")
    w2.write(prot.open("wb"))
    assert "password-protected" in readers.why_unreadable(prot)


def test_spreadsheets_each_end_read_or_with_the_true_reason(tmp_path):
    import openpyxl
    ok = tmp_path / "ok.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["metric", "value"])
    wb.active.append(["revenue", 120])
    wb.save(ok)
    assert readers.why_unreadable(ok) is None
    empty = tmp_path / "empty.xlsx"
    openpyxl.Workbook().save(empty)
    assert "every cell is empty" in readers.why_unreadable(empty)
    hidden = tmp_path / "hidden.xlsx"
    wb = openpyxl.Workbook()
    wb.active.sheet_state = "hidden"
    wb.create_sheet("second").sheet_state = "visible"
    wb.save(hidden)
    assert "1 hidden" in readers.why_unreadable(hidden)
    formulas = tmp_path / "formulas.xlsx"
    wb = openpyxl.Workbook()
    wb.active["A1"] = "=1+2"
    wb.save(formulas)
    assert "formula cell" in readers.why_unreadable(formulas) and "never saved" in readers.why_unreadable(formulas)
    prot = tmp_path / "prot.xlsx"
    prot.write_bytes(b"\xd0\xcf\x11\xe0" + b"\x00" * 100)
    assert "password-protected" in readers.why_unreadable(prot)
    notxls = tmp_path / "x.xls"
    notxls.write_bytes(b"plain text, not excel")
    assert "not an Excel file" in readers.why_unreadable(notxls)
    csv = tmp_path / "e.csv"
    csv.write_text("  \n", encoding="utf-8")
    assert readers.why_unreadable(csv) == "this file is empty"
    assert readers.why_unreadable(tmp_path / "gone.pdf") == "the file is no longer on this PC"


def test_the_chats_file_list_never_says_nothing_readable(tmp_path):
    import duckdb
    from pflab.app import context
    from pflab.pm import store
    c = duckdb.connect(":memory:")
    store.migrate(c)
    scan = tmp_path / "old.pdf"
    from PIL import Image
    Image.new("RGB", (100, 100), "white").save(scan, "PDF")
    c.execute("INSERT INTO inbox_items (item_id, name, kind, account, path, sha, status, steps_json, text, result_json, chat_id, created_at, updated_at) VALUES (1,'old.pdf','other',NULL,?,'s','in the graph','[]','', '{}', 1, now(), now())", [str(scan)])
    t = context._files(c, 1)
    assert "nothing readable was extracted" not in t and "a scan with no text layer" in t


def test_a_quote_that_differs_only_in_commas_and_line_breaks_is_kept_a_different_figure_is_not():
    pages = [(1, "The company holds a sizeable networth of Rs 4,610 crore as on\nJune 30, 2021 and revenue grew by 49% year-on-\nyear."), (2, "other text")]
    src = " ".join(t for _, t in pages)
    ok, notes = readers.check_facts([{"claim": "Networth was Rs 4,610 crore on June 30, 2021.", "quote": "sizeable networth of Rs 4610 crore as on June 30, 2021", "page": 1},
                                     {"claim": "Revenue grew 49% year on year.", "quote": "revenue grew by 49% year-on-year", "page": 1}], pages, src)
    assert len(ok) == 2 and notes == []
    bad, notes = readers.check_facts([{"claim": "Networth was Rs 4,160 crore.", "quote": "sizeable networth of Rs 4160 crore as on June 30, 2021", "page": 1}], pages, src)
    assert bad == [] and notes
