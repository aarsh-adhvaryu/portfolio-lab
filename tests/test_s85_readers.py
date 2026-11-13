"""S85 readers (`entrance/screen.py`, `entrance/readers.py`, `kg2/you.py`): the local screen, the readers by kind, the graph door (a). Synthetic data only (rule 7): invented companies, invented
identity terms, a scripted fake in place of the vendor's client (no paid call), a hand-made PDF, recorded pages."""
from __future__ import annotations

import io
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from pflab.agents import analyst as an
from pflab.entrance import readers, screen
from pflab.hq import security
from pflab.kg2 import audit, build as kb, you
from pflab.llm import gateway
from pflab.pm import store

from test_s81_kg import A, ASOF, GROUPS, root  # noqa: F401  (the synthetic raw-file graph; the fixture is used by name)

NOW = datetime(2026, 11, 13, 10, 0)
ALPHA = "INE000A01011"
BETA = "INE000B01029"
HIS_NAME = "zed testperson"
HIS_ACCOUNT = "ACCT-TEST-98765"
PAN_X = "ABC" + "P" + "E1234F"                                      # built here so the repo never carries a PAN-shaped string


def _cfg(cap=2500.0):
    return {"model": "claude-opus-5-5", "cap": cap, "ask_above": 1000.0, "usd_inr": 90.0, "adopted": True, "policy": {}, "acceptance": {}, "paper": {}, "tijori_to_analyst": True, "counted_since": None}


class Fake:
    """A scripted vendor client: `respond(prompt_text, blocks) -> dict` is the JSON the model answers with. Records every request it receives."""
    def __init__(self, respond=None, fail=None):
        self.sent, self.respond, self.fail = [], respond or (lambda text, blocks: {"headline": "x", "summary": "", "facts": []}), fail
        self.messages = SimpleNamespace(count_tokens=lambda **k: SimpleNamespace(input_tokens=3000), create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **p):
        if self.fail:
            raise self.fail
        self.sent.append(p)
        content = p["messages"][-1]["content"]
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
        text = "\n".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        out = self.respond(text, blocks)
        usage = SimpleNamespace(input_tokens=2000, output_tokens=400, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(out))], stop_reason="end_turn", model=p.get("model", "claude-sonnet-5-5"), usage=usage)

    def bodies(self) -> str:
        return json.dumps(self.sent, default=str)


def make_pdf(pages) -> bytes:
    """A small valid PDF with a text layer: `pages` is a list of lists of lines."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")          # noqa: E731
    n = len(pages)
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{' '.join(f'{4 + 2 * i} 0 R' for i in range(n))}] /Count {n} >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    for i, lines in enumerate(pages):
        content = "BT /F1 11 Tf 40 760 Td 14 TL " + " ".join(f"({esc(l)}) Tj T*" for l in lines) + " ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {5 + 2 * i} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        objs.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
    out, offs = b"%PDF-1.4\n", []
    for k, o in enumerate(objs, start=1):
        offs.append(len(out))
        out += f"{k} 0 obj\n{o}\nendobj\n".encode("latin-1")
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "kg").mkdir(parents=True)
    scope = {"version": 1, "built": "2026-06-01", "extra_isins": [], "names": [
        {"isin": ALPHA, "symbol": "ALPHA", "name": "Alpha Industries Limited", "aliases": ["alpha industries"], "text": True, "origin": "stock_list"},
        {"isin": BETA, "symbol": "BETA", "name": "Beta Finance Limited", "aliases": ["beta finance"], "text": False, "origin": "nifty500"}]}
    (data / "kg" / "scope.json").write_text(json.dumps(scope), encoding="utf-8")
    monkeypatch.setenv("PFLAB_DATA_DIR", str(data))
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path / "pm"))
    terms = tmp_path / "terms.json"
    terms.write_text(json.dumps({"ids": [HIS_ACCOUNT], "names": [HIS_NAME], "address": ["testville"], "amounts": [], "symbols": []}), encoding="utf-8")
    monkeypatch.setattr(security, "terms_path", lambda: terms)
    monkeypatch.setattr(an, "config", lambda path=None: _cfg())
    monkeypatch.setattr(screen, "ocr_text", lambda p: None)                       # no OCR in a test unless a test gives one
    return data


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "t.duckdb")


@pytest.fixture
def fake():
    f = Fake()
    gateway.set_client(f)
    yield f
    gateway.set_client(None)


def put(tmp_path, name: str, data: bytes) -> Path:
    p = tmp_path / "in" / name
    p.parent.mkdir(exist_ok=True)
    p.write_bytes(data)
    return p


def stored_rows(con) -> int:
    return con.execute("SELECT count(*) FROM received_docs_s85").fetchone()[0]


def kept_files(data: Path) -> list:
    d = data / "received_s85"
    return [p for p in d.rglob("*") if p.is_file()] if d.exists() else []


STATEMENT = ["Statement of Account", "Account No: 123456789012", "IFSC: ABCD0123456", "Date Narration Debit Credit Balance",
             "01-Nov-2026 UPI payment 1,200.00 0.00 98,800.00", "02-Nov-2026 Salary 0.00 50,000.00 1,48,800.00", "03-Nov-2026 ATM 2,000.00 0.00 1,46,800.00",
             "04-Nov-2026 Interest 0.00 310.50 1,47,110.50", "05-Nov-2026 Rent 15,000.00 0.00 1,32,110.50", "06-Nov-2026 Card 4,250.00 0.00 1,27,860.50"]
CIRCULAR = ["Circular on contract notes", "Securities and Exchange Board of India", "Alpha Industries Limited announced a new plant.", "The plant will make 120 units a day.",
            "Alpha Industries Limited expects first output in the second quarter."]


# --- the local screen: text ---------------------------------------------------------------------------------------------------------------

def test_a_message_that_only_names_a_term_is_masked_and_goes_on(con):
    r = screen.check_text(f"Does {HIS_NAME} hold Alpha Industries? Rs 12,50,000 of ALPHA, {ALPHA}.", con)
    assert r["ok"] and r["refused"] is None and "his name" in r["masked"] and not r["flagged"]
    assert HIS_NAME not in r["text"] and "Rs 12,50,000" in r["text"] and ALPHA in r["text"] and "Alpha Industries" in r["text"]          # his portfolio may go; his name may not


def test_identity_numbers_are_masked_and_flagged_and_money_is_left(con):
    text = f"PAN {PAN_X}, Aadhaar 2345 6789 0123, a/c no 123456789012, IFSC HDFC0001234, card 4111 1111 1111 1111, call 98765 43210, mail a.b@example.com; bought 40 shares for Rs 1,25,000.50"
    r = screen.check_text(text, con)
    assert r["ok"] and r["flagged"]
    for leak in (PAN_X, "2345 6789 0123", "123456789012", "HDFC0001234", "4111 1111 1111 1111", "98765 43210", "a.b@example.com"):
        assert leak not in r["text"]
    assert "Rs 1,25,000.50" in r["text"] and "40 shares" in r["text"]
    assert {"PAN", "Aadhaar number", "card number", "IFSC code"} <= set(r["masked"])


def test_a_pasted_statement_is_refused_as_text(con):
    r = screen.check_text("\n".join(STATEMENT), con)
    assert not r["ok"] and r["refused"] and "personal record" in r["refused"] and r["text"] == ""


def test_his_ledger_id_is_masked_by_the_terms_file(con):
    r = screen.check_text(f"my folio is {HIS_ACCOUNT} and my road is in testville", con)
    assert r["ok"] and HIS_ACCOUNT not in r["text"] and "testville" not in r["text"]


# --- the local screen: files --------------------------------------------------------------------------------------------------------------

def test_a_bank_statement_pdf_is_refused(tmp_path, con):
    v = screen.check_file(put(tmp_path, "stmt.pdf", make_pdf([STATEMENT])), "stmt.pdf", "application/pdf", con)
    assert not v["ok"] and v["kind"] == "statement" and "personal record" in v["refused"]


def test_a_public_circular_that_names_contract_notes_is_not_a_statement(tmp_path, con):
    v = screen.check_file(put(tmp_path, "c.pdf", make_pdf([CIRCULAR])), "c.pdf", "application/pdf", con)
    assert v["ok"] and v["kind"] == "pdf" and not v["mask_needed"]


def test_a_locked_pdf_and_a_scan_without_ocr_fail_closed(tmp_path, con, monkeypatch):
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for pg in PdfReader(io.BytesIO(make_pdf([CIRCULAR]))).pages:
        w.add_page(pg)
    w.encrypt("pw")
    buf = io.BytesIO()
    w.write(buf)
    assert not screen.check_file(put(tmp_path, "l.pdf", buf.getvalue()), "l.pdf", "application/pdf", con)["ok"]
    scan = make_pdf([[]])
    assert not screen.check_file(put(tmp_path, "s.pdf", scan), "s.pdf", "application/pdf", con)["ok"]          # no OCR here: refused, never sent unseen
    monkeypatch.setattr(screen, "ocr_png", lambda png: "Alpha Industries opened a plant")
    v = screen.check_file(put(tmp_path, "s2.pdf", scan), "s2.pdf", "application/pdf", con)
    assert v["ok"] and v["scanned"]


def test_a_bank_statement_sheet_is_refused_by_the_ledgers_own_recogniser(tmp_path, con):
    rows = ["Txn Date,Description,Debit,Credit,Balance", "01-11-2026,UPI,1200.00,,98800.00", "02-11-2026,Salary,,50000.00,148800.00"] + [f"0{k}-11-2026,Rent,100.00,,1.00" for k in range(3, 9)]
    v = screen.check_file(put(tmp_path, "export.csv", "\n".join(rows).encode()), "export.csv", "text/csv", con)
    assert not v["ok"] and v["kind"] == "statement"


def test_an_image_is_checked_by_ocr_and_refused_when_it_shows_a_statement_or_cannot_be_checked(tmp_path, con, monkeypatch):
    png = put(tmp_path, "p.png", b"\x89PNG\r\n\x1a\n" + b"0" * 50)
    assert not screen.check_file(png, "p.png", "image/png", con)["ok"]                         # OCR unavailable: refused
    monkeypatch.setattr(screen, "ocr_text", lambda p: "\n".join(STATEMENT))
    assert not screen.check_file(png, "p.png", "image/png", con)["ok"]
    monkeypatch.setattr(screen, "ocr_text", lambda p: f"Nifty closed at 24,500. Owner {HIS_NAME}")
    v = screen.check_file(png, "p.png", "image/png", con)
    assert not v["ok"] and "details of yours" in v["refused"]                                  # a picture cannot be masked
    monkeypatch.setattr(screen, "ocr_text", lambda p: "Nifty closed at 24,500")
    assert screen.check_file(png, "p.png", "image/png", con)["ok"]


# --- numbers must be in the source ----------------------------------------------------------------------------------------------------------

def test_only_sourced_in_removes_the_sentences_whose_numbers_are_not_in_the_source():
    src = "Revenue rose to 1,234.5 crore in Q2 FY26. Margin was 12.5%."
    out, n = readers.only_sourced_in("Revenue was 1234.50 crore. Margin was 12.5%. Profit was 99 crore.", src)
    assert n == 1 and "99" not in out.split("(")[0] and "1234.50" in out and "removed" in out
    assert readers.only_sourced_in("No numbers here.", src) == ("No numbers here.", 0)
    assert readers.missing_numbers("on 2026-11-12 it rose 5%", "it rose 5% on 12 November") == []              # a date is not an amount


# --- readers ------------------------------------------------------------------------------------------------------------------------------

def test_a_bank_statement_sent_to_the_reader_makes_no_call_and_stores_nothing(tmp_path, con, fake, _env):
    r = readers.read_attachment(con, NOW, put(tmp_path, "stmt.pdf", make_pdf([STATEMENT])), "stmt.pdf", "application/pdf")
    assert r["refused"] and r["facts"] == [] and r["document_id"] is None
    assert fake.sent == [] and stored_rows(con) == 0 and kept_files(_env) == []
    assert not (_env / "kg" / "you_events.jsonl").exists()


def test_a_pdf_is_read_as_a_document_with_the_page_numbers_kept_by_code(tmp_path, con, fake, _env):
    pdf = make_pdf([["Alpha Industries Limited annual note.", "Capacity is 120 units a day."], ["The plant opens in March 2027.", "Alpha Industries Limited hired 300 people."]])

    def respond(text, blocks):
        assert any(b.get("type") == "document" and b["source"]["type"] == "base64" for b in blocks)           # Claude reads the PDF itself
        return {"headline": "Alpha plant note", "summary": "Alpha Industries Limited will open a plant; capacity is 120 units a day.",
                "facts": [{"claim": "Capacity is 120 units a day", "quote": "Capacity is 120 units a day.", "page": 2},        # the model got the page wrong: code corrects it
                          {"claim": "The plant opens in March 2027", "quote": "The plant opens in March 2027.", "page": 2},
                          {"claim": "Alpha hired 450 people", "quote": "Alpha Industries Limited hired 450 people.", "page": 2}]}      # a quote that is not in the file
    fake.respond = respond
    r = readers.read_attachment(con, NOW, put(tmp_path, "note.pdf", pdf), "note.pdf", "application/pdf", chat_id=7, msg_id=11)
    assert r["kind"] == "pdf" and r["pages"] == 2 and r["refused"] is None
    by = {f["claim"]: f["page"] for f in r["facts"]}
    assert by == {"Capacity is 120 units a day": 1, "The plant opens in March 2027": 2}
    assert any("not in the document" in w for w in r["warnings"]) and r["cost_inr"] > 0 and len(fake.sent) == 1
    assert len(kept_files(_env)) == 1 and stored_rows(con) == 1
    assert r["isins"] == [ALPHA] and r["event_id"] and "Linked to ALPHA" in r["summary_text"] and f"company:{ALPHA}" in r["summary_text"]


def test_a_long_pdf_is_read_in_parts_of_30_pages_and_page_numbers_run_on(tmp_path, con, fake):
    pdf = make_pdf([[f"Alpha Industries Limited fact number {k}."] for k in range(1, 66)])
    seen = []

    def respond(text, blocks):
        seen.append(text)
        k = (len(seen) - 1) * 30 + 1
        return {"headline": "Alpha facts", "summary": "", "facts": [{"claim": f"fact number {k}", "quote": f"Alpha Industries Limited fact number {k}.", "page": 1}]}
    fake.respond = respond
    r = readers.read_attachment(con, NOW, put(tmp_path, "long.pdf", pdf), "long.pdf", "application/pdf")
    assert len(fake.sent) == 3 and "pages 1 to 30 of 65" in seen[0] and "pages 61 to 65 of 65" in seen[2]
    assert [f["page"] for f in r["facts"]] == [1, 31, 61]


def test_a_pdf_that_names_his_name_is_not_sent_only_the_masked_text_is(tmp_path, con, fake):
    pdf = make_pdf([[f"Prepared for {HIS_NAME}.", "Alpha Industries Limited makes 5 plants."]])
    fake.respond = lambda text, blocks: {"headline": "h", "summary": "", "facts": []}
    r = readers.read_attachment(con, NOW, put(tmp_path, "n.pdf", pdf), "n.pdf", "application/pdf")
    assert r["refused"] is None and len(fake.sent) == 1
    assert not any(b.get("type") == "document" for b in fake.sent[0]["messages"][-1]["content"]) and HIS_NAME not in fake.bodies() and "[NAME]" in fake.bodies()


def test_a_spreadsheet_is_summarised_by_code_and_claude_sees_only_the_summary(tmp_path, con, fake):
    df = pd.DataFrame({"Company": [f"ROWTOKEN{k}" for k in range(1, 21)], "Revenue": [100 + k for k in range(1, 21)]})
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="Results")
    seen = {}

    def respond(text, blocks):
        seen["text"] = text
        return {"headline": "Results table", "summary": "A table of 20 companies; revenue totals 2,210.", "facts": [{"claim": "Revenue totals 2,210", "quote": "total 2,210", "page": 1},
                                                                                                                    {"claim": "Revenue totals 9,999", "quote": "total 9,999", "page": 1}]}
    fake.respond = respond
    r = readers.read_attachment(con, NOW, put(tmp_path, "res.xlsx", buf.getvalue()), "res.xlsx", "")
    t = seen["text"]
    assert "Sheet 'Results': 20 rows, 2 columns" in t and "total 2,210" in t and "ROWTOKEN1 " in t + " " and "ROWTOKEN12" not in t        # first rows only, totals by code
    assert [f["claim"] for f in r["facts"]] == ["Revenue totals 2,210"] and any("9,999" in w or "not in the document" in w for w in r["warnings"])


def test_a_number_that_is_not_in_the_source_is_dropped_with_a_note(tmp_path, con, fake):
    p = put(tmp_path, "n.txt", b"Alpha Industries Limited reported sales of 500 crore. Alpha Industries Limited plans a plant.")
    fake.respond = lambda text, blocks: {"headline": "Alpha", "summary": "Sales were 500 crore and profit was 77 crore.",
                                         "facts": [{"claim": "Sales were 500 crore", "quote": "reported sales of 500 crore", "page": 1}, {"claim": "Profit was 77 crore", "quote": "reported sales of 500 crore", "page": 1}]}
    r = readers.read_attachment(con, NOW, p, "n.txt", "text/plain")
    assert [f["claim"] for f in r["facts"]] == ["Sales were 500 crore"] and any("77" in w for w in r["warnings"])
    assert "Profit was 77 crore" not in r["summary_text"] and "the number 77 is not in the document" in r["summary_text"]


def test_the_same_file_twice_costs_one_read(tmp_path, con, fake, _env):
    p = put(tmp_path, "n.txt", b"Alpha Industries Limited reported sales of 500 crore. Alpha Industries Limited plans a plant.")
    fake.respond = lambda text, blocks: {"headline": "Alpha", "summary": "", "facts": [{"claim": "Sales were 500 crore", "quote": "reported sales of 500 crore", "page": 1}]}
    a = readers.read_attachment(con, NOW, p, "n.txt", "text/plain")
    b = readers.read_attachment(con, datetime(2026, 11, 14, 9, 0), p, "again.txt", "text/plain")
    assert len(fake.sent) == 1 and b["cached"] and b["cost_inr"] == 0.0 and b["facts"] == a["facts"] and stored_rows(con) == 1 and len(kept_files(_env)) == 1
    assert len(you.load(_env)) == 1                                                                         # and the graph holds one event, not two


def test_an_image_is_read_by_vision_and_its_numbers_are_checked_against_its_ocr(tmp_path, con, fake, monkeypatch):
    monkeypatch.setattr(screen, "ocr_text", lambda p: "Alpha Industries index closed at 24,500 points")
    seen = {}

    def respond(text, blocks):
        seen["image"] = any(b.get("type") == "image" for b in blocks)
        return {"headline": "Close", "summary": "", "facts": [{"claim": "Closed at 24,500", "quote": "closed at 24,500 points", "page": 1}, {"claim": "Closed at 24,900", "quote": "closed at 24,900 points", "page": 1}]}
    fake.respond = respond
    r = readers.read_attachment(con, NOW, put(tmp_path, "c.png", b"\x89PNG\r\n\x1a\n" + b"1" * 64), "c.png", "image/png")
    assert seen["image"] and [f["claim"] for f in r["facts"]] == ["Closed at 24,500"]


def test_the_api_being_down_keeps_the_file_and_says_so_and_sending_it_again_reads_it(tmp_path, con, fake, _env):
    p = put(tmp_path, "n.txt", b"Alpha Industries Limited reported sales of 500 crore. Alpha Industries Limited plans a plant.")
    fake.fail = ConnectionError("api down")
    a = readers.read_attachment(con, NOW, p, "n.txt", "text/plain")
    assert a["facts"] == [] and "could not read it now" in a["summary_text"] and con.execute("SELECT status FROM received_docs_s85").fetchone()[0] == "failed" and len(kept_files(_env)) == 1
    fake.fail = None
    fake.respond = lambda text, blocks: {"headline": "Alpha", "summary": "", "facts": [{"claim": "Sales were 500 crore", "quote": "reported sales of 500 crore", "page": 1}]}
    b = readers.read_attachment(con, NOW, p, "n.txt", "text/plain")
    assert len(b["facts"]) == 1 and stored_rows(con) == 1 and con.execute("SELECT status FROM received_docs_s85").fetchone()[0] == "read"


def test_text_with_his_name_goes_out_masked(tmp_path, con, fake):
    p = put(tmp_path, "n.txt", f"Note by {HIS_NAME}. Alpha Industries Limited plans 3 plants. Alpha Industries Limited is hiring.".encode())
    fake.respond = lambda text, blocks: {"headline": "h", "summary": "", "facts": []}
    readers.read_attachment(con, NOW, p, "n.txt", "text/plain")
    assert HIS_NAME not in fake.bodies() and "[NAME]" in fake.bodies()


# --- door (a): the graph --------------------------------------------------------------------------------------------------------------------

def test_the_event_from_you_is_linked_by_the_confident_rule_only_and_carries_the_received_time(tmp_path, con, fake, _env):
    p = put(tmp_path, "n.txt", b"Alpha Industries Limited reported sales of 500 crore. Alpha Industries Limited plans a plant. Beta mentioned once.")
    fake.respond = lambda text, blocks: {"headline": "Alpha note", "summary": "", "facts": [{"claim": "Sales were 500 crore", "quote": "reported sales of 500 crore", "page": 1}]}
    r = readers.read_attachment(con, NOW, p, "n.txt", "text/plain")
    assert r["isins"] == [ALPHA]                                                                    # Beta is named once, nowhere near the title: not confident, not linked
    ev = you.load(_env)
    assert len(ev) == 1 and ev[0]["source"] == "you" and ev[0]["isin"] == ALPHA and ev[0]["ts"] == ev[0]["received_at"] == NOW.isoformat(timespec="seconds") and ev[0]["ts_rule"] == "received_time"
    assert ev[0]["link_rule"].startswith("you:") and ev[0]["kind"] == "news" and ev[0]["severity"] == "low"
    from pflab.think import recall
    items = recall.recall(con, NOW, isin=ALPHA)["items"]
    assert any(i["source"] == "you" and "500 crore" in i["text"] for i in items)                      # dated evidence "from you" where recall finds it
    assert con.execute("SELECT note_doc FROM received_docs_s85").fetchone()[0]


def test_a_keyword_in_what_he_sent_never_makes_a_thesis_break():
    row = you.row(ALPHA, "you:alias_exact_in_text", "proof", sha="a" * 64, received_at=NOW, headline="Fraud probe at the company and resignation of statutory auditors")
    assert row["kind"] == "news" and row["severity"] == "low"


def test_the_event_goes_into_the_store_at_once_when_the_graph_is_on_and_audited(tmp_path, con, fake, monkeypatch, _env):
    monkeypatch.setenv("PFLAB_KG2", "on")
    con.execute("INSERT INTO kg2_audit VALUES (?,?,?,?)", [NOW.date(), True, "[]", NOW])
    p = put(tmp_path, "n.txt", b"Alpha Industries Limited reported sales of 500 crore. Alpha Industries Limited plans a plant.")
    fake.respond = lambda text, blocks: {"headline": "Alpha note", "summary": "", "facts": []}
    r = readers.read_attachment(con, NOW, p, "n.txt", "text/plain")
    row = con.execute("SELECT source, isin, ts, ts_rule FROM kg2_event WHERE event_id=?", [r["event_id"]]).fetchone()
    assert row[0] == "you" and row[1] == ALPHA and row[2] == NOW and row[3] == "received_time"


def test_the_nightly_graph_counts_these_events_and_point_in_time_holds(root, con):
    """On the synthetic raw-file graph: an event received on the 29th is in the build of the 30th, not in the build of the 28th; the audit counts it and its checks pass."""
    scope = json.loads((root / "kg" / "scope.json").read_text(encoding="utf-8"))
    got = datetime(2026, 6, 29, 10, 30)
    rows = [you.row(A, "you:alias_exact_in_text", "'alpha industries' is named 2 time(s)", sha="b" * 64, received_at=got, headline="Alpha plant note (from you: n.txt)")]
    assert you.add(con, root, rows, got) == 1 and you.add(con, root, rows, got) == 0                 # append-only: the same event is never written twice
    g = kb.build(root, ASOF, groups=GROUPS)
    mine = g["event"][g["event"]["source"] == "you"]
    assert len(mine) == 1 and pd.Timestamp(mine.iloc[0]["ts"]) == pd.Timestamp(got) and mine.iloc[0]["ts_rule"] == "received_time" and g["stats"]["you_events"] == 1
    assert kb.build(root, date(2026, 6, 28), groups=GROUPS)["event"]["source"].eq("you").sum() == 0   # not before it was received
    res = audit.run_audit(con, root, ASOF, graph=g, store=False)
    chk = {c["name"]: c for c in res["checks"]}
    assert chk["you_events_point_in_time"]["passed"] and chk["you_events_point_in_time"]["value"] == {"events_from_you": 1, "bad": 0}
    assert chk["rebuild_identical"]["passed"] and chk["point_in_time"]["passed"] and chk["closed_lists"]["passed"] and chk["every_row_has_isin_source_date"]["passed"]
    bad = g["event"].copy()
    bad.loc[bad["source"] == "you", "ts_rule"] = "release_time"                                      # an event from you that claims another time rule fails the audit
    res_bad = audit.run_audit(con, root, ASOF, graph={**g, "event": bad}, store=False)
    assert not {c["name"]: c for c in res_bad["checks"]}["you_events_point_in_time"]["passed"]


# --- links ---------------------------------------------------------------------------------------------------------------------------------

SEC_URL = "https://www.sec.gov/Archives/edgar/data/0000000000/ex99.htm"
NEWS_URL = "https://news.example.org/story/alpha-plant"
EXCH_URL = "https://www.bseindia.com/xml-data/corpfiling/AttachLive/alpha-plant.pdf"
PAGES = {
    SEC_URL: {"ok": True, "url": SEC_URL, "text": "Alpha Industries Limited said on 2 November 2026 that its new plant will make 120 units a day. Alpha Industries Limited also named a new director.",
              "fetched": "2026-11-13T09:59:00", "date": "Mon, 02 Nov 2026 12:00:00 GMT", "links": []},
    NEWS_URL: {"ok": True, "url": NEWS_URL, "text": "Reports say Alpha Industries Limited will build a plant making 150 units a day, according to its filing.", "fetched": "2026-11-13T09:59:00", "date": None,
               "links": [EXCH_URL, "https://news.example.org/other"]},
    EXCH_URL: {"ok": True, "url": EXCH_URL, "text": "Intimation to the exchange. Alpha Industries Limited: the new plant will make 120 units a day from March 2027.", "fetched": "2026-11-13T09:59:30", "date": None, "links": []},
}


def fetcher(url):
    return PAGES.get(url, {"ok": False, "error": "the site answered 404", "url": url, "fetched": "2026-11-13T09:59:00", "links": [], "text": ""})


def test_a_link_is_checked_against_the_recorded_page_with_citations_and_hands_the_fact_to_the_graph(con, fake, _env):
    def respond(text, blocks):
        assert "[S1] filing source: SEC" in text and "CLAIM TO CHECK: Alpha's new plant makes 120 units a day" in text
        return {"verdict": "supported", "summary": "The filing says the plant will make 120 units a day.",
                "findings": [{"fact": "the plant will make 120 units a day", "quote": "its new plant will make 120 units a day", "source": 1}]}
    fake.respond = respond
    r = readers.check_link(con, NOW, SEC_URL, "Alpha's new plant makes 120 units a day", fetcher=fetcher, web=False)
    assert r["verdict"] == "supported" and r["sources"][0]["kind"] == "filing" and r["sources"][0]["fetched"].startswith("2026-11-13")
    assert "Checked at the original source: supported." in r["answer"] and SEC_URL in r["answer"] and "[S1]" in r["answer"] and f"company:{ALPHA}" in r["answer"]
    assert r["isins"] == [ALPHA] and r["event_id"] and r["node"]["id"] == f"company:{ALPHA}" and r["cost_inr"] > 0
    assert [e["source"] for e in you.load(_env)] == ["you"]
    again = readers.check_link(con, NOW, SEC_URL, "Alpha's new plant makes 120 units a day", fetcher=fetcher, web=False)
    assert again["cached"] and again["cost_inr"] == 0.0 and len(fake.sent) == 1


def test_a_news_link_is_checked_at_the_original_source_it_points_to(con, fake):
    seen = {}

    def respond(text, blocks):
        seen["text"] = text
        return {"verdict": "contradicted", "summary": "The exchange file says 120 units, not 150.",
                "findings": [{"fact": "the plant will make 120 units a day", "quote": "the new plant will make 120 units a day from March 2027", "source": 2}]}
    fake.respond = respond
    r = readers.check_link(con, NOW, NEWS_URL, "The plant makes 150 units a day", fetcher=fetcher, web=False)
    assert "[S1] secondary source" in seen["text"] and "[S2] exchange source: BSE" in seen["text"]
    assert r["verdict"] == "contradicted" and "Checked at the original source: NOT as claimed." in r["answer"] and r["event_id"] is None       # a failed claim is a note, never graph evidence
    assert [s["kind"] for s in r["sources"]] == ["secondary", "exchange"]


def test_a_finding_whose_number_or_quote_is_not_in_the_source_is_refused_and_the_verdict_degrades(con, fake):
    fake.respond = lambda text, blocks: {"verdict": "supported", "summary": "It makes 300 units.", "findings": [
        {"fact": "the plant will make 300 units a day", "quote": "its new plant will make 120 units a day", "source": 1},
        {"fact": "a quote nobody wrote", "quote": "this sentence is not on the page", "source": 1}]}
    r = readers.check_link(con, NOW, SEC_URL, "Alpha's new plant makes 120 units a day", fetcher=fetcher, web=False)
    assert r["findings"] == [] and r["verdict"] == "unclear" and "300" not in r["answer"].split("Note:")[0] and r["event_id"] is None
    assert any("not in source" in w or "not backed" in w for w in r["warnings"])


def test_a_link_that_cannot_be_opened_is_said_plainly_and_private_addresses_are_never_opened(con, fake):
    r = readers.check_link(con, NOW, "https://www.example.org/missing", "a claim", fetcher=fetcher, web=False)
    assert r["verdict"] == "not_found" and "could not open" in r["answer"] and fake.sent == []
    for bad in ("http://localhost:8000/x", "http://192.168.1.5/admin", "file:///C:/secret.txt", "ftp://example.org/x"):
        assert readers.check_link(con, NOW, bad, "c", fetcher=fetcher, web=False)["refused"]
    assert readers._private_host("127.0.0.1") and readers._private_host("10.1.2.3") and not readers._private_host("8.8.8.8")


def test_the_claim_goes_through_the_screen_before_any_call(con, fake):
    fake.respond = lambda text, blocks: {"verdict": "unclear", "summary": "", "findings": []}
    readers.check_link(con, NOW, SEC_URL, f"{HIS_NAME} says the plant makes 120 units, PAN {PAN_X}", fetcher=fetcher, web=False)
    assert HIS_NAME not in fake.bodies() and PAN_X not in fake.bodies()


def test_sources_are_typed_by_domain_in_a_small_code_table():
    assert readers.source_type("https://www.nseindia.com/x") == ("exchange", "NSE") and readers.source_type("https://nsearchives.nseindia.com/a.pdf") == ("exchange", "NSE")
    assert readers.source_type("https://www.bseindia.com/x")[0] == "exchange" and readers.source_type("https://www.sec.gov/a")[0] == "filing"
    assert readers.source_type("https://www.rbi.org.in/a")[0] == "regulator" and readers.source_type("https://www.sebi.gov.in/a")[0] == "regulator"
    assert readers.source_type("https://investors.example.com/results")[0] == "company" and readers.source_type("https://news.example.org/a")[0] == "secondary"
    assert readers.source_type("https://notnseindia.com/a")[0] == "secondary"


def test_the_migration_tables_exist(con):
    for t in ("received_docs_s85", "link_checks_s85"):
        assert con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0
