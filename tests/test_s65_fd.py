"""S65: fixed deposits by the system: a deposit entered on Setup (checked against the bank's maturity amount) and a dropped interest certificate."""
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from pflab.app import inbox as ib
from pflab.app import runtime, server
from pflab.ingest import sbi_interest_cert as cert
from pflab.ingest import sniff
from pflab.pm import fd as fdm
from pflab.pm import store

NOW = datetime(2026, 10, 29, 10, 0)
S, M = date(2026, 1, 1), date(2027, 1, 1)


def maturity(principal=100_000.0, rate=7.0):
    return round(fdm.contract_value(fdm.FD(fd_id="1234", principal=principal, rate=rate / 100, term_start=S, maturity=M, maturity_amount=0.0,
                                           bank="SBI", instruction="", opened=S), M), 2)


def test_a_deposit_entry_is_checked_against_the_banks_maturity_amount():
    e = fdm.entry("1234", "sbi", 100_000, 7.0, "2026-01-01", "2027-01-01", maturity())
    assert e["bank"] == "SBI" and e["start"] == S and e["id"] == "1234"
    with pytest.raises(fdm.FDError, match="terms give a maturity amount"):
        fdm.entry("1234", "SBI", 100_000, 7.0, "2026-01-01", "2027-01-01", maturity() + 500)       # a typing slip is caught
    with pytest.raises(fdm.FDError, match="LAST FOUR"):
        fdm.entry("12345678", "SBI", 100_000, 7.0, "2026-01-01", "2027-01-01", maturity())         # never the whole number
    with pytest.raises(fdm.FDError):
        fdm.entry("1234", "SBI", 100_000, 7.0, "2027-01-01", "2026-01-01", maturity())


def test_entries_are_appended_to_his_file_and_a_repeat_is_refused(tmp_path):
    p = tmp_path / "fd_holdings.toml"
    fdm.add_to_file(p, fdm.entry("1234", "SBI", 100_000, 7.0, S, M, maturity()))
    fdm.add_to_file(p, fdm.entry("5678", "HDFC", 50_000, 7.0, S, M, maturity(50_000)))
    fds = fdm.from_toml(p)
    assert [(f.fd_id, f.bank) for f in fds] == [("1234", "SBI"), ("5678", "HDFC")]
    with pytest.raises(fdm.FDError, match="already in the file"):
        fdm.add_to_file(p, fdm.entry("1234", "SBI", 100_000, 7.0, S, M, maturity()))
    assert len(fdm.from_toml(p)) == 2


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(ib, "_start", lambda rt, iid: ib._process(rt, iid))
    monkeypatch.setattr(sniff, "passwords_from_secrets", lambda: [("PAN_PW", "secret")])
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def test_the_setup_form_checks_then_writes_the_deposit(rt):
    c = TestClient(server.create_app(rt))
    f = {"id": "1234", "bank": "SBI", "principal": "100000", "rate_pct": "7", "start": "2026-01-01", "maturity": "2027-01-01",
         "maturity_amount": str(maturity())}
    assert c.post("/api/fd", json={"fields": f}).json() == {"ok": True, "written": False}
    assert not (rt.pm_dir / "fd_holdings.toml").exists()
    assert c.post("/api/fd", json={"fields": {**f, "maturity_amount": "1"}}).status_code == 400
    assert c.post("/api/fd", json={"fields": f, "write": True}).json()["deposits"] == 1
    assert c.get("/api/fd").json()["deposits"][0]["id"] == "1234"


def test_a_dropped_interest_certificate_is_recognised_checked_and_kept_on_his_press(rt, monkeypatch):
    got = sniff.from_text("STATE BANK OF INDIA Interest paid by us on the TDR / STDR accounts for the financial year ended 31st March 2026 TOTAL")
    assert got["kind"] == "fd_certificate" and got["bank"] == "SBI"
    seen = {}

    def fake_parse(path, password=None):
        seen["password"] = password
        return 2026, [SimpleNamespace(fd_id="1234", kind="TDR", paid=0.0, accrued=7000.0, tds=700.0)]
    monkeypatch.setattr(cert, "parse", fake_parse)
    monkeypatch.setattr(sniff, "sniff", lambda data, name, pw: {"kind": "fd_certificate", "bank": "SBI", "last4": None, "dp_ids": None,
                                                                "password_name": "PAN_PW"})
    r = ib.receive(rt, "Dep_Interest_Certificate.pdf", b"%PDF-1.4 x")
    it = ib._item(rt, r["id"])
    assert r["kind"] == "fd_certificate" and it["status"] == "ready" and it["result"]["deposits"] == 1 and seen["password"] == "secret"
    assert rt.cursor().execute("SELECT count(*) FROM fd_interest").fetchone()[0] == 0                 # nothing stored before his press
    assert ib.apply(rt, r["id"])["certificate"] is True
    assert rt.cursor().execute("SELECT fd_id, fy, accrued, tds FROM fd_interest").fetchall() == [("1234", 2026, 7000.0, 700.0)]
    assert ib._item(rt, r["id"])["status"] == "in the store"
