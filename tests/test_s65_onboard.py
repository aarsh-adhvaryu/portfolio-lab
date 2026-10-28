"""S65: the system onboards itself on a fresh install: files dropped before Setup are kept, Setup is proposed from what the files say, one press
accepts it and the files start their checks, one press builds the ledger from all of them (written only when every check passes)."""
import io
from datetime import datetime
from types import SimpleNamespace

import openpyxl
import pytest
from fastapi.testclient import TestClient

from pflab.app import inbox as ib
from pflab.app import runtime, server
from pflab.ingest import setup_sources as su
from pflab.ingest import sniff
from pflab.ingest import sources as srcs
from pflab.pm import store

NOW = datetime(2026, 10, 29, 10, 0)


def workbook(rows) -> bytes:
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


SBI = workbook([["State Bank of India"], ["Account Number : 00000012345678"], ["Txn Date", "Description", "Ref No", "Debit", "Credit", "Balance"]])
HDFC = workbook([["HDFC BANK Ltd"], ["Account No : XXXXXXXX9012"], ["Date", "Narration", "Chq./Ref.No.", "Withdrawal Amt.", "Deposit Amt.", "Closing Balance"]])
TRADEBOOK = b"symbol,isin,trade_date,trade_type,quantity,price,trade_id\nABC,INE0,2026-05-04,buy,1,2,3\n"
LEDGER = workbook([["Particulars", "Posting Date", "Cost Center", "Voucher Type", "Debit", "Credit", "Net Balance"]])


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    started = []
    monkeypatch.setattr(ib, "_start", lambda rt, iid: started.append(iid))
    monkeypatch.setattr(sniff, "passwords_from_secrets", lambda: [])
    r = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)
    r.started = started
    return r


def drop_all(rt):
    return [ib.receive(rt, n, b) for n, b in (("Download (1).xlsx", SBI), ("AccountStatement.xlsx", HDFC), ("tb.csv", TRADEBOOK), ("l.xlsx", LEDGER))]


def test_files_dropped_before_setup_are_kept_not_refused(rt):
    got = drop_all(rt)
    assert all(g["awaiting_setup"] for g in got) and rt.started == []
    st = rt.cursor().execute("SELECT kind, status FROM inbox_items ORDER BY item_id").fetchall()
    assert st == [("bank", "awaiting setup"), ("bank", "awaiting setup"), ("tradebook", "awaiting setup"), ("funds_ledger", "awaiting setup")]


def test_setup_is_proposed_from_the_files(rt):
    drop_all(rt)
    p = su.infer(rt.cursor(), NOW.date())
    assert p["answers"]["start"] == "2026-04-01" and p["answers"]["broker"]["account"] == "ZER"
    assert p["answers"]["banks"] == [{"name": "HDFC_9012", "bank": "HDFC", "last4": "9012"}, {"name": "SBI_5678", "bank": "SBI", "last4": "5678"}]
    assert p["files"] == {"bank": 2, "tradebook": 1, "funds_ledger": 1}
    su.normalise(p["answers"])                                                     # the proposal is valid Setup input as it is


def test_one_press_accepts_the_proposal_and_the_waiting_files_start(rt):
    drop_all(rt)
    c = TestClient(server.create_app(rt))
    prop = c.get("/api/setup").json()["proposal"]
    out = c.post("/api/setup", json=prop["answers"]).json()
    assert sorted(out["files"]["started"]) == sorted(["Download _1_.xlsx", "AccountStatement.xlsx", "tb.csv", "l.xlsx"]) and out["files"]["unknown"] == []
    acc = dict(rt.cursor().execute("SELECT name, account FROM inbox_items WHERE kind='bank'").fetchall())
    assert acc == {"Download _1_.xlsx": "SBI_5678", "AccountStatement.xlsx": "HDFC_9012"} and len(rt.started) == 4
    assert any("depository CAS" in n for n in out["needed"])                        # what is still missing is listed


def fake_builder(checks=(("all good", True, ""),)):
    seen = {"written": 0}

    def build(src, root):
        seen["src"] = src
        return ["e1", "e2"], None, list(checks), [], src

    def write(con, log, led, src):
        seen["written"] += 1
    return SimpleNamespace(build=build, write=write, seen=seen)


def test_one_press_builds_the_ledger_from_every_document_when_all_checks_pass(rt, monkeypatch):
    drop_all(rt)
    ib.receive(rt, "cas.csv", b"x")                                                 # not a ledger file by content: other
    su.write(rt.pm_dir / "sources.toml", su.infer(rt.cursor(), NOW.date())["answers"])
    ib.attach_waiting(rt)
    con = rt.cursor()
    con.execute("UPDATE inbox_items SET status='ready' WHERE status='working'")
    assert ib.apply_all(rt)["waiting_for"] == ["depository CAS from 2026-04-01"]        # nothing written while a document is missing
    iid = con.execute("SELECT max(item_id) FROM inbox_items").fetchone()[0] + 1
    con.execute("INSERT INTO inbox_items (item_id, name, kind, path, sha, status, created_at, updated_at) VALUES (?, 'c.pdf', 'cas', ?, 's', 'ready', ?, ?)",
                [iid, str(rt.repo / "new" / "c.pdf"), NOW, NOW])
    monkeypatch.setattr(ib, "_builder", lambda rt: fake_builder((("bank cash = statement", False, "off"),)))
    r = ib.apply_all(rt)
    assert r["written"] is False and r["failed"] == 1
    fb = fake_builder()
    monkeypatch.setattr(ib, "_builder", lambda rt: fb)
    r = ib.apply_all(rt)
    assert r["written"] and r["documents"] == 5 and fb.seen["written"] == 1
    assert {s for (s,) in con.execute("SELECT status FROM inbox_items WHERE kind IN ('bank','tradebook','funds_ledger','cas')").fetchall()} == {"in the ledger"}
    over = srcs.load_overlay(rt.pm_dir / "sources.toml")
    assert {b["account"] for b in over["bank"]} == {"SBI_5678", "HDFC_9012"} and over["cas"]["files"]


def test_the_name_of_the_password_that_opened_a_file_is_kept_never_the_value(tmp_path):
    msoffcrypto = pytest.importorskip("msoffcrypto")
    try:
        from msoffcrypto.format.ooxml import OOXMLFile
        src, enc = io.BytesIO(SBI), io.BytesIO()
        OOXMLFile(src).encrypt("secret-pw-123", enc)
    except Exception:
        pytest.skip("this msoffcrypto cannot encrypt")
    got = sniff.sniff(enc.getvalue(), "s.xlsx", [("OTHER_PW", "nope"), ("SBI_PW", "secret-pw-123")])
    assert got["kind"] == "bank" and got["password_name"] == "SBI_PW" and "secret-pw-123" not in repr(got)
