"""S65 Phase 7 item 5: IPO and opening-cost entries on the dashboard: validated, kept in sources.app.toml, dry run before a write."""
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from pflab.app import inbox as ib
from pflab.app import runtime, server
from pflab.ingest import sources as srcs
from pflab.pm import store

NOW = datetime(2026, 10, 28, 10, 0)
BASE = """start = 2026-04-01

[zerodha]
account = "zer"
tradebooks = ["new/t.csv"]
funds_ledger = "new/l.xlsx"
contract_notes_xlsx = ["new/n.xlsx"]

[cas]
files = ["new/c.pdf"]

[[bank]]
account = "main"
file = "new/main.xlsx"

[accounts.zer]
kind = "broker"

[accounts.main]
kind = "bank"
"""
IPO = dict(ipo_id="NSE-IPO-2026-X", funding_account="main", demat_account="zer", isin="INE123A01012", qty=12, price=105.5,
           allot_date="2026-10-01", bank_date="2026-09-26", bank_amount=1266.0, symbol="ABC")


def test_an_ipo_entry_is_validated():
    e = srcs.ipo_entry(**IPO)
    assert e["isin"] == "INE123A01012" and e["bank_line"] == {"date": date(2026, 9, 26), "amount": 1266.0} and e["allot_date"] == date(2026, 10, 1)
    for bad in ({"isin": "INE123"}, {"qty": 0}, {"price": -1}, {"allot_date": "1 Oct"}, {"ipo_id": "x"}, {"bank_amount": 0}):
        with pytest.raises(ValueError):
            srcs.ipo_entry(**{**IPO, **bad})


def test_an_opening_cost_must_say_its_basis():
    e = srcs.cost_entry("zer", "ine123a01012", 4662.0, "2021-03-09", "issue price")
    assert e["isin"] == "INE123A01012" and e["acquired"] == date(2021, 3, 9)
    with pytest.raises(ValueError, match="based on"):
        srcs.cost_entry("zer", "INE123A01012", 1.0, "2021-03-09", " ")
    with pytest.raises(ValueError):
        srcs.cost_entry("zer", "INE123A01012", 0.0, "2021-03-09", "x")


def test_entries_round_trip_through_the_overlay_and_replace_their_own(tmp_path):
    p = tmp_path / "sources.toml"
    p.write_text(BASE, encoding="utf-8")
    over = srcs.with_entry({}, "ipo", srcs.ipo_entry(**IPO))
    over = srcs.with_entry(over, "ipo", srcs.ipo_entry(**{**IPO, "qty": 15}))                       # same id: replaced
    over = srcs.with_entry(over, "opening_cost", srcs.cost_entry("zer", "INE123A01012", 4662.0, "2021-03-09", "issue price"))
    over = srcs.with_entry(over, "opening_cost", srcs.cost_entry("zer", "INE123A01012", 4700.0, "2021-03-09", "revised"))
    srcs.save_overlay(p, over)
    got = srcs.load(p)                                                                              # base + the overlay, as the build reads it
    assert len(got["ipo"]) == 1 and got["ipo"][0]["qty"] == 15 and got["ipo"][0]["bank_line"]["date"] == date(2026, 9, 26)
    assert got["ipo"][0]["allot_date"] == date(2026, 10, 1) and got["ipo"][0]["price"] == 105.5
    assert len(got["opening_cost"]) == 1 and got["opening_cost"][0]["cost_per_unit"] == 4700.0 and got["opening_cost"][0]["basis"] == "revised"
    assert got["zerodha"]["tradebooks"] == ["new/t.csv"]                                            # his file's own lists are untouched


def fake_builder(checks=(("all good", True, ""),)):
    seen = {"written": 0}

    def build(src, root):
        seen["src"] = src
        return ["e1"], None, list(checks), ["a note"], src

    def write(con, log, led, src):
        seen["written"] += 1
    return SimpleNamespace(build=build, write=write, seen=seen)


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    (tmp_path / "pm" / "sources.toml").write_text(BASE, encoding="utf-8")
    con = store.connect(tmp_path / "l.duckdb")
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def test_a_dry_run_writes_nothing_and_a_press_writes_once_all_checks_pass(rt, monkeypatch):
    fb = fake_builder()
    monkeypatch.setattr(ib, "_builder", lambda rt: fb)
    e = srcs.ipo_entry(**IPO)
    r = ib.add_entry(rt, "ipo", e, write=False)
    assert r["failed"] == 0 and not r["written"] and fb.seen["written"] == 0 and fb.seen["src"]["ipo"][0]["ipo_id"] == IPO["ipo_id"]
    assert "ipo" not in srcs.load_overlay(rt.pm_dir / "sources.toml")
    r = ib.add_entry(rt, "ipo", e, write=True)
    assert r["written"] and fb.seen["written"] == 1 and srcs.load_overlay(rt.pm_dir / "sources.toml")["ipo"][0]["qty"] == 12


def test_a_failing_check_blocks_the_write_and_keeps_the_overlay_clean(rt, monkeypatch):
    monkeypatch.setattr(ib, "_builder", lambda rt: fake_builder((("bank cash = statement", False, "off by 1,266"),)))
    e = srcs.cost_entry("zer", "INE123A01012", 4662.0, "2021-03-09", "issue price")
    assert ib.add_entry(rt, "opening_cost", e, write=False)["failed"] == 1
    with pytest.raises(ValueError, match="nothing written"):
        ib.add_entry(rt, "opening_cost", e, write=True)
    assert srcs.load_overlay(rt.pm_dir / "sources.toml") == {}


def test_the_endpoints_answer_a_bad_entry_with_a_message(rt, monkeypatch):
    monkeypatch.setattr(ib, "_builder", lambda rt: fake_builder())
    c = TestClient(server.create_app(rt))
    bad = c.post("/api/ledger/ipo", json={"fields": {**IPO, "isin": "nope"}})
    assert bad.status_code == 400 and "ISIN" in bad.json()["detail"]
    ok = c.post("/api/ledger/ipo", json={"fields": {**IPO, "qty": "12"}, "write": False}).json()
    assert ok["failed"] == 0 and ok["written"] is False
    cost = c.post("/api/ledger/opening-cost", json={"fields": {"account": "zer", "isin": "INE123A01012", "cost_per_unit": "4662",
                                                               "acquired": "2021-03-09", "basis": "issue price"}, "write": True}).json()
    assert cost["written"] is True
