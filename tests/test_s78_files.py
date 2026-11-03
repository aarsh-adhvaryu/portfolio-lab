"""S78: a dropped file is read and can be read back. A PDF is kept whole, page by page; a company is recognised from the whole listed universe and from the file's own name; the files
read before the master existed are read again; the agents have tools to list, read and quote what was dropped. Synthetic data only."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from pflab.agents import inbox as ag
from pflab.hq import tools as tl
from pflab.pm import instruments as ins
from pflab.pm import store

NOW = datetime(2026, 11, 3, 12, 0)
ZETA = "INE000Z01011"


def _pdf(path: Path, pages) -> None:
    """A minimal real PDF with text on each page (so pypdf can read it)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for n, text in enumerate(pages):
        c = 4 + 2 * n
        kids.append(f"{c} 0 R")
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {c + 1} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>"
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF\n".encode()
    path.write_bytes(out)


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "f.duckdb")


def _zeta(con):
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, 'ZETAMOT', 'Zeta Motors Limited', 's', now())", [ZETA])


def _sheet(path: Path) -> None:
    rows = [["dates", "Mar 2025", "Mar 2026", "Jun 2026"], ["Net Sales", 2255.0, 3671.8, 4244.1], ["Operating Profit", -200.0, -150.5, -33.1]]
    with pd.ExcelWriter(path) as w:
        pd.DataFrame(rows).to_excel(w, sheet_name="Profit&Loss", header=False, index=False)


def test_a_pdf_is_kept_whole_page_by_page_and_linked_to_the_company_it_is_about(con, tmp_path):
    _zeta(con)
    f = tmp_path / "inbox" / "Zeta Motors.pdf"
    f.parent.mkdir()
    _pdf(f, ["RISK REPORT Zeta Motors first page about debt and interest cover", "Second page: revenue estimate 4244 crore and margins"])
    reads = ag.ingest_file(con, f, tmp_path / "out", NOW)
    assert reads[0].pages == 2 and reads[0].chars > 80 and reads[0].isins == [ZETA]
    assert con.execute("SELECT count(*) FROM file_pages").fetchone()[0] == 2
    ctx = SimpleNamespace(con=con)
    r = tl.files_tool(ctx, {})["files"][0]
    assert r["pdf_pages"] == 2 and r["companies"] == ["ZETAMOT"]
    assert "4244 crore" in tl.read_file(ctx, {"name": "zeta", "page": 2})["text"]
    found = tl.read_file(ctx, {"name": "zeta", "find": "interest cover"})["found"]
    assert found[0]["page"] == 1
    assert tl.read_file(ctx, {"name": "no-such"})["note"].startswith("no received file")


def test_the_company_comes_from_the_files_own_name_and_a_sheet_gives_figures_by_company(con, tmp_path):
    _zeta(con)
    f = tmp_path / "Zeta_Motors_stand_58348.xlsx"                                          # a Tijori export is named after its company
    _sheet(f)
    reads = ag.ingest_file(con, f, tmp_path / "out", NOW)
    assert reads[0].isins == [ZETA] and reads[0].facts == 6
    ctx = SimpleNamespace(con=con)
    fig = tl.file_figures(ctx, {"symbol": "ZETAMOT", "metric": "net sales", "period": "Mar 2026"})["figures"]
    assert fig == [{"metric": "Net Sales", "period": "Mar 2026", "value": 3671.8}]
    sheet = tl.read_file(ctx, {"name": "zeta_motors_stand", "find": "operating"})["sheets"][0]
    assert sheet["table"][0][0] == "Operating Profit"


def test_stem_words_and_the_one_held_company_when_several_names_start_alike(con):
    assert ag.stem_words(Path("Ather_Energy_stand_58348.xlsx")) == "Ather Energy"
    assert ag.stem_words(Path("Ather Energy _1_.pdf")) == "Ather Energy"
    for isin, sym, name in (("INE000M01011", "MUTHOOTFIN", "Muthoot Finance Limited"), ("INE000M02011", "MUTHOOTCAP", "Muthoot Capital Services Limited")):
        con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES (?, 'isin', 'equity', 'EQUITY', TRUE, ?, ?, 's', now())", [isin, sym, name])
    sym_, isins, names = ag.name_index(con)
    assert ag.company_from_name(con, "muthoot", names) == []                                # two companies start so and he holds neither: no guess
    con.execute("INSERT INTO lots (lot_id, account_id, isin, acq_date, qty, cost_per_unit, tax_class) VALUES (1, 'A', 'INE000M01011', '2026-01-01', 5, 100, 'EQUITY')")
    assert ag.company_from_name(con, "muthoot", names) == ["INE000M01011"]                  # he holds one of them: that one


def test_files_read_before_the_master_existed_are_read_again_and_linked(con, tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    f = inbox / "Zeta Motors.pdf"
    _pdf(f, ["Zeta Motors report page"])
    first = ag.reingest_unlinked(con, [inbox], tmp_path / "out", NOW)
    assert first["read_new"] == 1 and first["files"][0]["companies"] == 0                    # no instrument yet: read, but linked to no one
    assert ag.reingest_unlinked(con, [inbox], tmp_path / "out", NOW)["read_again"] == 1      # still no company: tried again (and said so)
    _zeta(con)
    again = ag.reingest_unlinked(con, [inbox], tmp_path / "out", NOW)
    assert again["read_again"] == 1 and again["files"][0]["companies"] == 1
    assert ag.reingest_unlinked(con, [inbox], tmp_path / "out", NOW) == {"read_again": 0, "read_new": 0, "files": []}      # linked now: left alone
    assert con.execute("SELECT count(*) FROM datasets").fetchone()[0] == 1                   # the old read was removed, not doubled


def test_the_master_is_rebuilt_from_the_panel_keeping_what_is_held_and_not_in_it(con, monkeypatch, tmp_path):
    con.execute("INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at) VALUES ('IN0020290001', 'isin', 'sgb', 'LISTED_NONEQUITY', TRUE, 'SGBX', 'SGB 2029', 'cas', now())")
    panel = pd.DataFrame([dict(isin=ZETA, symbol="ZETAMOT", series="EQ", instrument_type="STK", valid_from=pd.Timestamp("2025-01-01"), valid_to=pd.Timestamp("2030-01-01"))] +
                         [dict(isin=f"INE00{i:04d}01011", symbol=f"S{i}", series="EQ", instrument_type="STK", valid_from=pd.Timestamp("2025-01-01"), valid_to=pd.Timestamp("2030-01-01")) for i in range(600)])
    monkeypatch.setattr(ins, "panel_instruments", lambda root=None: panel)
    monkeypatch.setattr(ins, "_latest_names", lambda root=None: {ZETA: "Zeta Motors Limited"})
    monkeypatch.setattr(ins, "_latest_sectors", lambda root=None: {})
    monkeypatch.setattr(ins, "fetch_amfi", lambda root=None, session=None: (_ for _ in ()).throw(OSError("offline")))
    assert ins.master_size(con) == 0
    out = ins.refresh_master(con, tmp_path)
    assert out["listed_equities"] >= 600 and out["kept_from_before"] == 1
    assert con.execute("SELECT name FROM instruments WHERE isin = ?", [ZETA]).fetchone()[0] == "Zeta Motors Limited"
    assert con.execute("SELECT count(*) FROM instruments WHERE isin = 'IN0020290001'").fetchone()[0] == 1       # the held bond survives the rebuild
    assert "skipped" in ins.refresh_master(con, tmp_path)                                    # the universe is there: nothing more to do


def test_a_long_document_is_read_part_by_part_and_by_word(con, tmp_path):
    _zeta(con)
    p = tmp_path / "doc.txt"
    p.write_text("[page 1]\n" + "Revenue grew. " * 600 + "\n[page 2]\nThe order book stands at 9,876 crore as of March.\n" + "x " * 3000, encoding="utf-8")
    con.execute("INSERT INTO kg_docs (doc_id, kind, url, title, source, published_at, ingested_at, text_path, text_status) VALUES ('doc:filing:a1', 'filing', 'u', 'Zeta Motors results call transcript', 'BSE', '2026-10-30', now(), ?, 'ok')", [str(p)])
    con.execute("INSERT INTO kg_edges (src, rel, dst, valid_from, source_kind, source_ref, ingested_at) VALUES ('doc:filing:a1', 'about', ?, now(), 'test', 'x', now())", [f"company:{ZETA}"])
    ctx = SimpleNamespace(con=con, rt=SimpleNamespace(data_root=tmp_path), asof=NOW.date(), syms={})
    first = tl.read_document(ctx, {"doc_id": "doc:filing:a1"})
    assert first["parts"] >= 2 and first["part"] == 1 and len(first["text"]) == tl.DOC_PART
    found = tl.read_document(ctx, {"symbol": "ZETAMOT", "title_words": "transcript", "find": "order book"})
    assert "9,876 crore" in found["found"][0]["text"] and found["found"][0]["part"] >= 1
    assert "does not appear" in tl.read_document(ctx, {"doc_id": "doc:filing:a1", "find": "zebra"})["found"][0]
    assert tl.read_document(ctx, {"doc_id": "nope"})["documents"] == []


def test_he_can_say_run_it_now_and_the_day_limits_are_lifted_for_that_investigation_only(con):
    from pflab.hq import cases, missions
    con.execute("INSERT INTO hq_tasks (task_id, created_at, from_agent, to_agent, text, status, hops, role, wait_kind, next_review_at, case_id) VALUES (1, ?, 'x', 'research', 't', 'retry', 0, 'research', 'budget', ?, 5)",
                [NOW, datetime(2026, 11, 4, 0, 5)])
    out = missions.run_now(con, NOW, 5)
    assert out == {"started": True, "woken": 1}
    assert con.execute("SELECT next_review_at FROM hq_tasks WHERE task_id = 1").fetchone()[0] == NOW                  # it starts at once
    assert con.execute("SELECT count(*) FROM hq_case_log WHERE case_id = 5 AND event = 'run now'").fetchone()[0] == 1   # and the workers read this as his order (day limits lifted for case 5 only)
    assert con.execute("SELECT count(*) FROM hq_case_log WHERE case_id = 6 AND event = 'run now'").fetchone()[0] == 0
