"""The inbox: any dropped file into the knowledge graph, figures as facts from the file. SYNTHETIC files."""
from datetime import datetime

import pandas as pd
import pytest

from pflab.agents import inbox
from pflab.pm import store

NOW = datetime(2026, 10, 17, 22, 0)


def _store(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    for isin, sym, name in (("INE000A01011", "AAA", "Aaa Pharma Limited"), ("INE000B01011", "BBB", "Bbb Power Limited"),
                            ("INE000C01011", "CCC", "Ccc Cement Limited")):
        con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                       VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, ?, ?, 'synthetic', now())""", [isin, sym, name])
    return con


def test_a_tijori_style_metrics_by_period_sheet_becomes_facts(tmp_path):
    con = _store(tmp_path)
    box = tmp_path / "inbox"
    box.mkdir()
    rows = [["Aaa Pharma Limited - Segment revenue (Rs crore)", None, None, None],
            [None, None, None, None],
            ["Segment", "Q1FY26", "Q2FY26", "Q3FY26"],
            ["US generics", "1,200.5", "1,310.0", "1,280.25"],
            ["India branded", 900, 950, "(12)"],
            ["Notes", None, None, None]]
    with pd.ExcelWriter(box / "tijori_aaa_segments.xlsx") as w:
        pd.DataFrame(rows).to_excel(w, sheet_name="Revenue Mix", header=False, index=False)
    reads = inbox.run(con, box, tmp_path / "data", model=None, now=NOW)
    assert len(reads) == 1 and reads[0].shape == "metrics x periods" and reads[0].isins == ["INE000A01011"]
    assert reads[0].facts == 6 and reads[0].kind == "segments"
    f = con.execute("SELECT metric, period, value, source FROM dataset_facts ORDER BY metric, period").fetchall()
    assert ("India branded", "Q3FY26", -12.0, "Tijori export") in f and ("US generics", "Q1FY26", 1200.5, "Tijori export") in f
    doc = con.execute("SELECT kind, title FROM kg_docs").fetchone()
    assert doc[0] == "dataset" and "Revenue Mix" in doc[1]
    assert con.execute("SELECT count(*) FROM kg_edges WHERE dst='company:INE000A01011'").fetchone()[0] == 1
    assert (box / "done" / "2026-10-17" / "tijori_aaa_segments.xlsx").exists()
    assert inbox.facts_for(con, "INE000A01011", "how did US generics do?")["file.US_generics.Q1FY26"] == 1200.5


def test_a_screener_list_links_every_row_and_a_text_file_is_kept_whole(tmp_path):
    con = _store(tmp_path)
    box = tmp_path / "inbox"
    box.mkdir()
    (box / "screen.csv").write_text("Name,Market Cap,P/E,ROCE %\nAaa Pharma,5000,22.5,18\nBBB,1200,9.1,11\n"
                                    "Unknown Co,300,40,5\n", encoding="utf-8")
    (box / "notes.txt").write_text("Thoughts on CCC and its kiln capacity after the plant visit.", encoding="utf-8")
    reads = {r.file: r for r in inbox.run(con, box, tmp_path / "data", model=None, now=NOW)}
    s = reads["screen.csv"]
    assert s.shape == "one row per company" and set(s.isins) == {"INE000A01011", "INE000B01011"} and s.facts == 6
    assert s.kind == "screener"
    t = reads["notes.txt"]
    assert t.shape == "sheet" and t.isins == ["INE000C01011"] and t.facts == 0
    assert con.execute("SELECT count(*) FROM kg_docs WHERE kind='dataset'").fetchone()[0] == 2


def test_same_file_is_not_read_twice_and_a_broken_file_stays_with_a_note(tmp_path):
    con = _store(tmp_path)
    box = tmp_path / "inbox"
    box.mkdir()
    (box / "a.csv").write_text("Name,P/E\nAAA,10\nBBB,12\n", encoding="utf-8")
    inbox.run(con, box, tmp_path / "data", now=NOW)
    (box / "a.csv").write_text("Name,P/E\nAAA,10\nBBB,12\n", encoding="utf-8")       # dropped again
    assert inbox.run(con, box, tmp_path / "data", now=NOW) == []
    (box / "bad.xlsx").write_bytes(b"not a workbook")
    inbox.run(con, box, tmp_path / "data", now=NOW)
    assert (box / "bad.xlsx").exists() and (box / "bad.xlsx.error.txt").exists()


def test_market_exports_go_to_the_analyst_but_never_a_portfolio_or_a_personal_file(tmp_path):
    from pflab.agents import analyst as an
    con = _store(tmp_path)
    box = tmp_path / "inbox"
    (box / "market").mkdir(parents=True)
    (box / "market" / "aaa_revenue_mix.csv").write_text("Aaa Pharma segment,Q1FY26,Q2FY26\nUS generics,1200,1310\n"
                                                        "India branded,900,950\n", encoding="utf-8")
    (box / "tijori_portfolio.csv").write_text("Name,Quantity,Avg Cost,Current Value\nAAA,10,1000,11000\nBBB,5,200,1100\n",
                                              encoding="utf-8")
    (box / "my_notes.txt").write_text("Thoughts on AAA after the plant visit, call me on 9876543210.", encoding="utf-8")
    inbox.run(con, box, tmp_path / "data", now=NOW)
    share = {r[0]: r[1] for r in con.execute(
        "SELECT title, json_extract(attrs_json, '$.shareable')::BOOLEAN FROM kg_docs WHERE kind='dataset'").fetchall()}
    assert [v for k, v in share.items() if "revenue_mix" in k] == [True]
    assert [v for k, v in share.items() if "portfolio" in k] == [False]                  # holdings columns: never sent
    assert [v for k, v in share.items() if "my_notes" in k] == [False]                   # a loose personal file
    docs = an.dataset_docs(con, "INE000A01011")
    assert len(docs) == 1 and "US generics,1200,1310" in docs[0].text and docs[0].kind == "dataset"


def test_model_labels_only_from_the_fixed_list():
    class R:
        def __init__(self, t):
            self.text = t
    chat = lambda model, messages, **kw: R('{"kind": "operational"}')
    assert inbox.kind_by_model("Stores, footfall", chat, "m") == "operational"
    bad = lambda model, messages, **kw: R('{"kind": "made up"}')
    assert inbox.kind_by_model("x", bad, "m") is None and inbox.kind_by_model("x", chat, None) is None
