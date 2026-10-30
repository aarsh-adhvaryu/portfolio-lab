"""S67 release repair (audit of v2026.10.30, received 2026-10-30): the exact failure scenarios it named, on synthetic data in temporary folders.
F1 old inputs outside the profile and a failure before activation; F4 two banks sharing the last four digits; F5 a loss in the first period;
F6 an interruption before a hand-off is saved. (F2 is in test_s67_sandbox.py.)"""
from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from pflab import activation
from pflab.hq import board
from pflab.ingest import coverage
from pflab.learner import experiments as ex
from pflab.pm import fresh, store

NOW = datetime(2026, 10, 30, 17, 0)
TODAY = date(2026, 10, 30)


def _old_install(tmp_path):
    pm = tmp_path / "app" / "pm"
    pm.mkdir(parents=True)
    store.connect(pm / "ledger.duckdb").close()
    (pm / "app.log").write_text("old log", encoding="utf-8")
    repo = tmp_path / "app" / "app"
    (repo / "new").mkdir(parents=True)
    (repo / "new" / "old-statement.pdf").write_bytes(b"OLD STATEMENT")
    (repo / "drop").mkdir()
    (repo / "drop" / "waiting.pdf").write_bytes(b"OLD WAITING FILE")
    data = tmp_path / "app" / "data"
    (data / "kg" / "mail").mkdir(parents=True)
    (data / "kg" / "mail" / "x.txt").write_text("OLD MAIL TEXT", encoding="utf-8")
    (data / "prices.parquet").write_bytes(b"market data stays")
    return pm, repo, data


def test_f1_old_inputs_outside_the_profile_are_moved_aside_and_the_new_profile_is_dormant(tmp_path, monkeypatch):
    monkeypatch.delenv("PFLAB_DROP_DIR", raising=False)
    pm, repo, data = _old_install(tmp_path)
    r = fresh.fresh(pm, tmp_path / "archive", TODAY, fresh.CONFIRM, inputs=fresh.old_inputs(repo, data))
    assert r["done"] and set(r["inputs_moved"]) == {"documents", "drop", "mail_text"}
    assert list((repo / "new").iterdir()) == [] and list((repo / "drop").iterdir()) == [] and list((data / "kg" / "mail").iterdir()) == []
    assert (data / "prices.parquet").exists()                                                     # market data is not an old input
    assert (tmp_path / "archive" / f"inputs_{TODAY:%Y%m%d}" / "documents" / "old-statement.pdf").exists()        # moved beside the archive, never deleted
    assert sorted(p.name for p in repo.iterdir()) == ["drop", "new"]                               # nothing extra in the app's checkout (an update would refuse)
    assert activation.is_pending(pm) and not (pm / "app.log").exists()                           # dormant, and the old log went with the old profile


def test_f1_a_user_chosen_drop_folder_keeps_its_other_content(tmp_path, monkeypatch):
    pm, repo, data = _old_install(tmp_path)
    mine = tmp_path / "MyDownloads"
    (mine / "Photos").mkdir(parents=True)
    (mine / "old.pdf").write_bytes(b"x")
    monkeypatch.setenv("PFLAB_DROP_DIR", str(mine))
    fresh.fresh(pm, tmp_path / "archive", TODAY, fresh.CONFIRM, inputs=fresh.old_inputs(repo, data))
    assert (mine / "Photos").is_dir() and not (mine / "old.pdf").exists() and (mine / f"_before_fresh_{TODAY:%Y%m%d}" / "old.pdf").exists()


@pytest.mark.parametrize("where", ["building the new profile", "verifying the archive"])
def test_f1_a_failure_before_the_switch_leaves_the_old_profile_working_and_no_open_gate(tmp_path, monkeypatch, where):
    monkeypatch.delenv("PFLAB_DROP_DIR", raising=False)
    pm, repo, data = _old_install(tmp_path)
    if where == "building the new profile":
        monkeypatch.setattr(fresh, "new_profile", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))
    else:
        monkeypatch.setattr(fresh, "verify_archive", lambda d: {"ok": False, "files": 0, "problems": ["x"]})
    with pytest.raises(RuntimeError):
        fresh.fresh(pm, tmp_path / "archive", TODAY, fresh.CONFIRM, inputs=fresh.old_inputs(repo, data))
    assert (pm / "ledger.duckdb").exists() and (pm / "app.log").read_text(encoding="utf-8") == "old log"   # the old profile, as it was
    assert not list(pm.parent.glob("pm_new_*"))                                                   # no half-built profile left to be mistaken for one
    assert (repo / "drop" / "waiting.pdf").exists()                                               # inputs untouched when it stops before them


def test_f4_two_banks_with_the_same_last_four_digits_stay_two_and_the_picture_is_not_complete(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES ('ALPHA_1111', 'bank', 'Alpha Bank', '0001111')")
    coverage.note_account(con, {"kind": "bank", "bank": "Alpha Bank", "last4": "1111", "dp_ids": None}, "a file you dropped", NOW, "a")
    coverage.note_account(con, {"kind": "bank", "bank": "Beta Bank", "last4": "1111", "dp_ids": None}, "a file you dropped", NOW, "b")
    rows = coverage.matrix(con, NOW)
    assert len(rows) == 2 and any("Beta Bank" in r["account"] and r["state"] == "discovered, not set up" for r in rows)
    coverage.confirm_inventory(con, NOW)
    assert coverage.status(con, NOW)["label"] != "complete"                                       # Beta Bank is not set up


def test_f5_a_loss_in_the_first_period_is_a_drawdown():
    df = pd.DataFrame({"date": [date(2020, 1, 31), date(2020, 2, 28), date(2020, 3, 31)], "close": [100.0, 70.0, 70.0]})
    s = ex.score_period(df, {"2020-01-31": 1.0, "2020-02-28": 1.0}, ("2020-01-01", "2020-03-31"))
    assert s["cand_max_drawdown"] == pytest.approx(-0.30, abs=1e-3) and s["base_max_drawdown"] == pytest.approx(-0.30, abs=1e-3)


def test_f6_an_interruption_before_the_hand_off_is_saved_loses_nothing(tmp_path, monkeypatch):
    from pflab.hq.desk import Desk
    con = store.connect(tmp_path / "l.duckdb")
    rt = Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, {"brain": "economy", "preset": "full"}, clock=lambda: NOW)
    tid = board.post(con, "research", "look into it", NOW)
    real_post = board.post

    def dies(*a, **k):
        if k.get("parent") == tid:
            raise RuntimeError("power cut before the child was saved")
        return real_post(*a, **k)
    monkeypatch.setattr(board, "post", dies)
    with pytest.raises(RuntimeError):
        board.run_one(rt, {"research": lambda rt_, t: board.Reply("found it", then=[("calc", "work the numbers")])})
    assert board.get(con, tid)["status"] == "running"                                            # not marked done without its hand-off
    assert con.execute("SELECT count(*) FROM hq_tasks WHERE parent_id=?", [tid]).fetchone()[0] == 0
    assert board.reap(con, NOW) == 1 and board.get(con, tid)["status"] == "retry"                # and the work is picked up again
    monkeypatch.setattr(board, "post", real_post)
    board.run_one(rt, {"research": lambda rt_, t: board.Reply("found it", then=[("calc", "work the numbers")])})
    assert board.get(con, tid)["status"] == "done" and con.execute("SELECT count(*) FROM hq_tasks WHERE parent_id=?", [tid]).fetchone()[0] == 1


def test_f5_the_next_candidate_never_sees_the_validation_result(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    eid = ex.register(con, tmp_path / "proto", NOW, hypothesis="Momentum", why_it_matters="w", disproof="d", source_kind="investor")
    hist = [{"n": 1, "status": "rejected", "note": "", "error": "", "code": "def compute(data): return {}",
             "result": {"development": {"t": 1.1}, "validation": {"t": 2.7, "mean_excess": 0.004}, "why": "validation t 2.7 under 3.0"}}]
    text = ex.prompt(con, eid, "index:NIFTY50_TRI", hist)
    assert "development {'t': 1.1}" in text and "2.7" not in text and "0.004" not in text and "not kept" in text


def test_f7_a_rollback_store_rebuilds_lots_from_the_merged_events_before_it_is_used(tmp_path):
    from pflab import update
    from pflab.ledger.book import Ledger
    from pflab.ledger.events import Event, EventLog, load, save
    db = tmp_path / "cand.duckdb"
    con = store.connect(db)
    con.execute("INSERT INTO accounts (account_id, kind, provider) VALUES ('ZER', 'demat', 'Zerodha (synthetic)')")
    log1 = EventLog([Event("deposit", "ZER", date(2026, 10, 1), amount=1000.0), Event("buy", "ZER", date(2026, 10, 2), isin="INE000A01011", qty=1, price=100.0, ref="T1")])
    save(con, log1)
    Ledger.replay(log1).write_derived(con)                                                        # the backup's lots: 1 share
    con.execute("UPDATE events SET qty = 2 WHERE ref = 'T1'")                                      # a correction made after the upgrade, merged in
    assert con.execute("SELECT sum(qty) FROM lots").fetchone()[0] == 1
    con.close()
    out = update.rebuild_derived(db)
    con = store.connect(db)
    assert con.execute("SELECT sum(qty) FROM lots").fetchone()[0] == 2 and out["positions"] == 1


def test_verify_returns_success_only_when_accepted():
    from pflab import verify
    rep = verify.Report()
    rep.add("store", verify.PASS)
    assert verify.exit_code(rep) == 0
    rep.add("Kite read", verify.NEEDS, "log in")
    assert verify.exit_code(rep) == 2                                                             # pending is not success
    rep2 = verify.Report()
    rep2.add("sandbox", verify.SKIP, "offline")
    assert verify.exit_code(rep2) == 2
    rep2.add("x", verify.FAIL)
    assert verify.exit_code(rep2) == 1
