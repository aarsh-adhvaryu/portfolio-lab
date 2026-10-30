"""S65 Phase 7 item 2: Setup writes sources.toml from his answers, lists what is still needed, and a first setup fills up file by file."""
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from pflab.agents import questions
from pflab.app import inbox as ib
from pflab.app import runtime, server
from pflab.ingest import setup_sources as su
from pflab.ingest import sources as srcs
from pflab.pm import store

NOW = datetime(2026, 10, 28, 10, 0)
ANSWERS = {"start": "2026-04-01", "broker": {"account": "zer", "cas_dp": "in300001"},
           "demats": [{"name": "family", "provider": "HDFC", "cas_dp": "12012300", "read_only": True}],
           "banks": [{"name": "main", "bank": "sbi", "last4": "5678", "password_name": "SBI_PW"}, {"name": "savings", "bank": "HDFC", "last4": "9012"}],
           "cas_password_name": "CAS_PW"}


def test_answers_become_sources_that_the_ledger_tools_read(tmp_path):
    p = tmp_path / "sources.toml"
    su.write(p, ANSWERS)
    src = srcs.load(p)                                                              # the same loader build_pm_ledger uses
    assert src["start"] == date(2026, 4, 1) and src["zerodha"] == {"account": "zer", "tradebooks": [], "contract_notes_xlsx": []}
    assert src["accounts"]["zer"] == {"kind": "broker", "provider": "Zerodha", "cas_dp": "IN300001"}
    assert src["accounts"]["family"]["read_only"] is True and src["accounts"]["family"]["dormant"] is False
    assert src["accounts"]["main"] == {"kind": "bank", "bank": "SBI", "last4": "5678"}
    assert src["bank"][0] == {"account": "main", "password_env": "SBI_PW"} and src["cas"]["password_env"] == "CAS_PW"
    assert srcs.bank_accounts(p) == ["main", "savings"]


def test_it_never_replaces_his_file_and_refuses_bad_answers(tmp_path):
    p = tmp_path / "sources.toml"
    p.write_text("# his own file\n", encoding="utf-8")
    with pytest.raises(su.SetupError, match="never replaces"):
        su.write(p, ANSWERS)
    assert p.read_text(encoding="utf-8") == "# his own file\n"
    for bad in ({**ANSWERS, "start": "April"}, {**ANSWERS, "banks": []},
                {**ANSWERS, "banks": [{"name": "main", "bank": "SBI", "last4": "123456789012"}]},       # a full account number is refused
                {**ANSWERS, "banks": [{"name": "my bank", "bank": "SBI", "last4": "1234"}]},
                {**ANSWERS, "broker": {"account": "zer", "cas_dp": "123"}},
                {**ANSWERS, "demats": [{"name": "main", "provider": "x"}]}):                             # a name used twice
        with pytest.raises(su.SetupError):
            su.normalise(bad)


def test_what_is_still_needed_is_listed_in_his_words_and_filed_once(tmp_path):
    p = tmp_path / "sources.toml"
    su.write(p, ANSWERS)
    need = su.needed(srcs.load(p))
    assert need[0] == "Console tradebook(s) from 2026-04-01" and "Console funds ledger from 2026-04-01" in need
    assert any(n.startswith("depository CAS from 2026-04-01") and "IN300001" in n and "12012300" in n for n in need)
    assert "bank statement for SBI account ending 5678 from 2026-04-01" in need and any("HDFC account ending 9012" in n for n in need)
    assert not any("contract notes" in n for n in need)                                                       # no tradebook yet
    over = srcs.with_document({}, "tradebook", "new/t.csv")
    over = srcs.with_document(over, "funds_ledger", "new/l.xlsx")
    over = srcs.with_document(over, "cas", "new/c.pdf")
    over = srcs.with_document(over, "bank", "new/main.xlsx", "main")
    merged = srcs.merge(srcs.base(p), over)
    assert su.needed(merged) == ["Console contract notes (xlsx) for the days you traded", "bank statement for HDFC account ending 9012 from 2026-04-01"]
    assert su.needed(merged, optional=False) == ["bank statement for HDFC account ending 9012 from 2026-04-01"]
    con = store.connect(tmp_path / "l.duckdb")
    first = su.ask_needed(con, srcs.load(p), NOW)
    assert first == len(need) and su.ask_needed(con, srcs.load(p), NOW) == 0                                  # once
    assert len(questions.open_questions(con)) == first


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(ib, "_start", lambda rt, iid: ib._process(rt, iid))
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def test_the_setup_endpoints(rt):
    c = TestClient(server.create_app(rt))
    assert c.get("/api/setup").json()["exists"] is False
    assert c.post("/api/setup", json={**ANSWERS, "start": "soon"}).status_code == 400
    got = c.post("/api/setup", json=ANSWERS).json()
    assert got["asked"] == len(got["needed"]) > 0
    after = c.get("/api/setup").json()
    assert after["exists"] and after["start"] == "2026-04-01" and after["accounts"]["main"]["last4"] == "5678"
    assert c.post("/api/setup", json=ANSWERS).status_code == 400                                              # not replaced


def test_a_first_file_is_recognised_without_building_and_the_build_comes_once_per_burst(rt, monkeypatch):
    """(2026-10-30) Dropping a file never runs a build of its own (a burst of files would build again and again); the ledger job builds
    once from everything, and a missing file is a difference, not a wait."""
    su.write(rt.pm_dir / "sources.toml", ANSWERS)
    monkeypatch.setattr(ib, "_builder", lambda rt: (_ for _ in ()).throw(AssertionError("built on drop")))
    tb = b"symbol,isin,trade_date,trade_type,quantity,price,trade_id\nABC,INE0,2026-01-01,buy,1,2,3\n"
    got = ib.receive(rt, "download.csv", tb)                                                                   # recognised by content
    assert got["kind"] == "tradebook"
    item = ib._item(rt, got["id"])
    assert item["status"] == "ready" and "rebuilt with it" in item["result"]["note"]
    assert not srcs.overlay_path(rt.pm_dir / "sources.toml").exists()                                           # nothing written on drop
