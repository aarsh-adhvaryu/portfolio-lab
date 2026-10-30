"""S54d: the inbox. The overlay of documents beside sources.toml, recognising files, the dry run before the ledger is
written (one transaction; a failure writes nothing), screenshots read on this PC and their images deleted, the endpoints."""
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import tomllib
from pflab.app import chat as ch
from pflab.app import inbox as ib
from pflab.app import runtime, server
from pflab.ingest import sources as srcs
from pflab.pm import store

NOW = datetime(2026, 10, 23, 10, 0)
SOURCES = """[zerodha]
account = "zer"
tradebooks = ["new/tradebook-A.csv"]
funds_ledger = "new/ledger-A.xlsx"

[cas]
files = ["new/cas-1.pdf"]

[[bank]]
account = "bank1"
file = "new/bank1-old.xls"
password_env = "BANK1_PW"

[accounts.zer]
kind = "broker"

[accounts.bank1]
kind = "bank"
"""


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    (tmp_path / "pm" / "sources.toml").write_text(SOURCES, encoding="utf-8")
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(ib, "_start", lambda rt, iid: ib._process(rt, iid))     # the work runs inline in tests
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def fake_builder(checks=(("all good", True, ""),), fail_write=False):
    seen = {}

    def build(src, root):
        seen["src"] = src
        return ["e1", "e2"], None, list(checks), ["a note"], src

    def write(con, log, led, src):
        con.execute("INSERT INTO app_notes (note_id, text, done, deleted, created_at) VALUES (999, 'written', false, false, ?)",
                    [NOW])
        if fail_write:
            raise RuntimeError("disk full")
    return SimpleNamespace(build=build, write=write, seen=seen)


def test_overlay_extends_lists_and_adds_a_second_funds_ledger_and_a_second_bank_statement(tmp_path):
    base = tomllib.loads(SOURCES)
    over = srcs.with_document({}, "tradebook", "new/tradebook-B.csv")
    over = srcs.with_document(over, "tradebook", "new/tradebook-B.csv")              # no repeats
    over = srcs.with_document(over, "funds_ledger", "new/ledger-B.xlsx")
    over = srcs.with_document(over, "bank", "new/bank1-new.xls", "bank1")
    over = srcs.with_document(over, "cas", "new/cas-2.pdf")
    m = srcs.merge(base, over)
    assert m["zerodha"]["tradebooks"] == ["new/tradebook-A.csv", "new/tradebook-B.csv"]
    assert m["zerodha"]["funds_ledger"] != "new/ledger-B.xlsx" and m["zerodha"]["funds_ledgers"] == ["new/ledger-B.xlsx"] and m["zerodha"]["account"] == "zer"   # added, not swapped
    assert m["bank"] == [{"account": "bank1", "file": "new/bank1-old.xls", "files": ["new/bank1-old.xls", "new/bank1-new.xls"], "password_env": "BANK1_PW"}]
    assert m["cas"]["files"] == ["new/cas-1.pdf", "new/cas-2.pdf"]
    assert base["zerodha"]["tradebooks"] == ["new/tradebook-A.csv"]                  # the base is not touched
    p = tmp_path / "sources.toml"
    p.write_text(SOURCES, encoding="utf-8")
    srcs.save_overlay(p, over)
    assert srcs.load_overlay(p) == over and srcs.load(p) == m                        # the TOML round-trips
    assert p.read_text(encoding="utf-8") == SOURCES                                  # the investor's file is never rewritten
    with pytest.raises(ValueError):
        srcs.with_document({}, "bank", "x.xls")
    with pytest.raises(ValueError):
        srcs.with_document({}, "screenshot", "x.png")


@pytest.mark.parametrize("name,kind", [
    ("tradebook-AB1234-EQ.csv", "tradebook"), ("ledger-AB1234.xlsx", "funds_ledger"),
    ("AB1234_2026-04-01_2026-09-30.xlsx", "contract_note"), ("NSDL_CAS_Sep2026.pdf", "cas"),
    ("Screenshot 2026-10-23.png", "screenshot"), ("photo.JPG", "screenshot"), ("tijori_export.xlsx", "market"),
    ("notes.txt", "other")])
def test_classify(name, kind):
    assert ib.classify(name) == kind


def test_a_statement_is_checked_then_written_only_on_ok(rt, monkeypatch):
    b = fake_builder()
    monkeypatch.setattr(ib, "_builder", lambda rt: b)
    r = ib.receive(rt, "tradebook-B.csv", b"a,b\n1,2\n")
    it = ib._item(rt, r["id"])
    assert r["kind"] == "tradebook" and it["status"] == "ready" and it["result"]["events"] == 2
    assert (rt.repo / "new" / "tradebook-B.csv").exists()
    assert b.seen["src"]["zerodha"]["tradebooks"] == ["new/tradebook-A.csv", "new/tradebook-B.csv"]
    assert not srcs.overlay_path(rt.pm_dir / "sources.toml").exists()                # a dry run writes nothing
    assert ib.receive(rt, "copy.csv", b"a,b\n1,2\n", hint="tradebook")["duplicate"]  # the same bytes: not twice
    out = ib.apply(rt, r["id"])
    assert out["events"] == 2 and ib._item(rt, r["id"])["status"] == "in the ledger"
    assert rt.cursor().execute("SELECT text FROM app_notes WHERE note_id=999").fetchone() == ("written",)
    assert srcs.load_overlay(rt.pm_dir / "sources.toml")["zerodha"]["tradebooks"] == ["new/tradebook-B.csv"]
    with pytest.raises(ValueError):
        ib.remove(rt, r["id"])                                                       # part of the ledger now


def test_failing_checks_or_a_failed_write_change_nothing(rt, monkeypatch):
    monkeypatch.setattr(ib, "_builder", lambda rt: fake_builder(checks=[("cash = statement", False, "off by 5")]))
    r = ib.receive(rt, "ledger-B.xlsx", b"x")
    it = ib._item(rt, r["id"])
    assert it["status"] == "checks failed" and it["result"]["failed"] == 1
    assert [s["state"] for s in it["steps"]][:3] == ["done", "done", "failed"]
    with pytest.raises(ValueError):
        ib.apply(rt, r["id"])
    monkeypatch.setattr(ib, "_builder", lambda rt: fake_builder(fail_write=True))
    r = ib.receive(rt, "ledger-C.xlsx", b"y")
    with pytest.raises(RuntimeError):
        ib.apply(rt, r["id"])
    assert rt.cursor().execute("SELECT count(*) FROM app_notes").fetchone()[0] == 0   # rolled back
    assert not srcs.overlay_path(rt.pm_dir / "sources.toml").exists()


def test_a_file_already_in_place_is_never_deleted(rt, monkeypatch):
    monkeypatch.setattr(ib, "_builder", lambda rt: fake_builder(checks=[("x", False, "")]))
    (rt.repo / "new").mkdir()
    old = rt.repo / "new" / "tradebook-A.csv"
    old.write_bytes(b"old rows")
    r = ib.receive(rt, "tradebook-A.csv", b"old rows")                             # the same file dropped again
    assert ib._item(rt, r["id"])["path"] == str(old)
    ib.remove(rt, r["id"])
    assert old.read_bytes() == b"old rows"
    r = ib.receive(rt, "tradebook-A.csv", b"new rows")                             # same name, other bytes: beside it
    assert ib._item(rt, r["id"])["path"] != str(old) and old.read_bytes() == b"old rows"
    ib.remove(rt, r["id"])
    assert not Path(ib._item(rt, r["id"])["path"]).exists()


def test_a_bank_statement_needs_its_account(rt, monkeypatch):
    b = fake_builder()
    monkeypatch.setattr(ib, "_builder", lambda rt: b)
    with pytest.raises(ValueError):
        ib.receive(rt, "statement.xls", b"z", hint="bank")
    ib.receive(rt, "statement.xls", b"z", hint="bank", account="bank1")
    assert "new/statement.xls" in b.seen["src"]["bank"][0]["files"]


def test_a_screenshot_is_read_summarised_and_its_image_deleted_later(rt, monkeypatch):
    text = "IPO allotment\n15 shares allotted on 3 Oct 2026"
    monkeypatch.setattr(ib, "ocr", lambda rt, path: text)
    cid = ch.create(rt.cursor(), NOW)
    r = ib.receive(rt, "Screenshot 1.png", b"\x89PNG", chat_id=cid)
    it = ib._item(rt, r["id"])
    assert it["status"] == "read" and it["text"] == text
    msgs = ch.messages(rt.cursor(), cid)
    assert msgs[0]["role"] == "me" and "Attached Screenshot 1.png" in msgs[0]["text"]
    assert msgs[-1]["role"] == "ai" and "15 shares" in msgs[-1]["text"]
    res = ib.summarise(rt, r["id"], llm=lambda p: "The IPO allotted 15 shares on 3 Oct 2026 [S1].")
    assert res["checked"] and "15 shares" in res["summary"]
    path = rt.pm_dir / "inbox" / "screens" / "Screenshot 1.png"
    assert path.exists()
    assert ib.cleanup(rt, NOW + timedelta(days=ib.IMAGE_DAYS - 1)) == []
    done = ib.cleanup(rt, NOW + timedelta(days=ib.IMAGE_DAYS + 1))
    assert len(done) == 1 and not path.exists()
    it = ib._item(rt, r["id"])
    assert it["cleaned"] is not None and it["text"] == text                         # the text stays


def test_a_failure_is_shown_on_the_item(rt, monkeypatch):
    def broken(rt, path):
        raise RuntimeError("no OCR language installed")
    monkeypatch.setattr(ib, "ocr", broken)
    r = ib.receive(rt, "s.png", b"img")
    it = ib._item(rt, r["id"])
    assert it["status"] == "failed" and "no OCR language" in it["result"]["error"]
    assert [s["state"] for s in it["steps"]][:2] == ["done", "failed"]


def test_endpoints(rt, monkeypatch):
    monkeypatch.setattr(ib, "ocr", lambda rt, path: "hello")
    c = TestClient(server.create_app(rt))
    r = c.post("/api/inbox/upload", content=b"img", headers={"X-Filename": "Screen%20shot.png"})
    assert r.status_code == 200 and r.json()["kind"] == "screenshot"
    assert c.post("/api/inbox/upload", content=b"", headers={"X-Filename": "a.png"}).status_code == 400
    assert c.post("/api/inbox/upload", content=b"q", headers={"X-Filename": "s.xls", "X-Kind": "bank"}).status_code == 400
    v = c.get("/api/inbox").json()
    assert v["items"][0]["name"] == "Screen shot.png" and v["accounts"] == ["bank1"] and v["needs"] == []
    iid = v["items"][0]["id"]
    assert c.post(f"/api/inbox/{iid}/apply").status_code == 400                   # not a ledger document
    assert c.post(f"/api/inbox/{iid}/nonsense").status_code == 404
    assert c.delete(f"/api/inbox/{iid}").json() == {"ok": True}
    assert c.get("/api/inbox").json()["items"] == []
