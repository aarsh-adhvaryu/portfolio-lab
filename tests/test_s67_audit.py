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
    # executed at the session after each decision (2026-10-30): 3 Feb (100) -> 2 Mar (70) is the first month held
    df = pd.DataFrame({"date": [date(2020, 1, 31), date(2020, 2, 3), date(2020, 2, 28), date(2020, 3, 2), date(2020, 3, 31), date(2020, 4, 1)],
                       "close": [100.0, 100.0, 70.0, 70.0, 70.0, 70.0]})
    s = ex.score_period(df, {"2020-01-31": 1.0, "2020-02-28": 1.0}, ("2020-01-01", "2020-03-31"))
    assert s["n_months"] == 2
    assert s["cand_max_drawdown"] == pytest.approx(-0.30, abs=1e-3) and s["base_max_drawdown"] == pytest.approx(-0.30, abs=1e-3)


def test_a_decision_is_traded_at_the_next_session_not_its_own_close():
    # the price jumps 30% the session after the 28 Feb decision: buying on the 28 Feb close would have caught it; no one could
    df = pd.DataFrame({"date": [date(2020, 1, 31), date(2020, 2, 3), date(2020, 2, 28), date(2020, 3, 2), date(2020, 3, 31), date(2020, 4, 1)],
                       "close": [100.0, 100.0, 100.0, 130.0, 130.0, 130.0]})
    s = ex.score_period(df, {"2020-01-31": -1.0, "2020-02-28": 1.0}, ("2020-01-01", "2020-03-31"))
    assert ex.returns_between(df, [date(2020, 1, 31), date(2020, 2, 28), date(2020, 3, 31)]) == [(date(2020, 1, 31), pytest.approx(0.30)),
                                                                                                (date(2020, 2, 28), pytest.approx(0.0))]
    assert s["cand_mean"] < s["base_mean"]                   # out for the jump (decided on 31 Jan, held from 3 Feb), in only after it
    assert ex.next_day([date(2020, 1, 31)], date(2020, 1, 31)) is None


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
    eid = ex.register(con, tmp_path / "proto", NOW, hypothesis="Momentum", why_it_matters="w", disproof="d", source_kind="investor", contract="index_timing")
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


def _vctx(tmp_path, now):
    from pflab import verify
    pm = tmp_path / "pm"
    (pm / "app").mkdir(parents=True, exist_ok=True)
    return verify.Ctx(tmp_path, tmp_path, pm, tmp_path / "data", now, tmp_path / "t")


def test_acceptance_evidence_adds_up_across_runs_and_a_later_skip_never_erases_a_pass(tmp_path):
    from pflab import verify
    ctx = _vctx(tmp_path, NOW)
    first = verify.Report(started="2026-10-30 18:00")
    first.identity = {"candidate_commit": "abc123"}
    first.add("store", verify.PASS)
    first.add("sandbox (Docker)", verify.PASS)
    first.add(verify.WAKE, verify.NEEDS, "sleep it")
    first.add(verify.HOUR, verify.NEEDS, "an hour")
    c1 = verify.accumulate(ctx, first)
    assert verify.exit_code(c1) == 2
    wake = verify.Report(started="2026-10-30 19:00")
    wake.identity = {"candidate_commit": "abc123"}
    wake.add(verify.WAKE, verify.PASS, "wake seen")
    wake.add("sandbox (Docker)", verify.SKIP, "not checked in this run")
    c2 = verify.accumulate(ctx, wake)
    by = {c.name: c.status for c in c2.checks}
    assert by == {"store": verify.PASS, "sandbox (Docker)": verify.PASS, verify.WAKE: verify.PASS, verify.HOUR: verify.NEEDS}
    hour = verify.Report(started="2026-10-30 20:00")
    hour.identity = {"candidate_commit": "abc123"}
    hour.add(verify.HOUR, verify.PASS, "an hour, working")
    c3 = verify.accumulate(ctx, hour)
    assert verify.exit_code(c3) == 0 and c3.verdict.startswith("ACCEPTED")                       # every piece of evidence, from three runs
    bad = verify.Report(started="2026-10-30 21:00")
    bad.identity = {"candidate_commit": "abc123"}
    bad.add("store", verify.FAIL, "broke")
    assert verify.exit_code(verify.accumulate(ctx, bad)) == 1                                   # a later failure replaces a pass
    other = verify.Report(started="2026-10-30 22:00")
    other.identity = {"candidate_commit": "def456"}
    other.add("store", verify.PASS)
    assert [c.name for c in verify.accumulate(ctx, other).checks] == ["store"]                   # another candidate starts a new record


def test_the_hour_check_reads_uptime_stalls_and_work_from_the_heartbeat(tmp_path):
    import json
    import os
    from datetime import timedelta
    from pflab import verify
    ctx = _vctx(tmp_path, NOW)
    hb = ctx.pm_live / "app" / "heartbeat.json"

    def beat(up_min, gap_s, jobs):
        hb.write_text(json.dumps({"at": NOW.isoformat(), "pid": os.getpid(), "since": (NOW - timedelta(minutes=up_min)).isoformat(),
                                  "max_gap_s": gap_s, "jobs_last_hour": jobs}), encoding="utf-8")
        rep = verify.Report()
        verify.hour_check(ctx, rep)
        return rep.checks[-1]
    assert beat(70, 45, 12).status == verify.PASS
    assert beat(20, 45, 12).status == verify.NEEDS
    assert beat(70, 900, 12).status == verify.FAIL                                              # it stalled (a sleep or a hang)
    assert beat(70, 45, 0).status == verify.FAIL                                                # alive but doing nothing


def test_the_heartbeat_records_its_start_its_longest_pause_and_the_work_done(tmp_path):
    import json
    from datetime import timedelta
    from pflab.app import runtime
    con = store.connect(tmp_path / "l.duckdb")
    (tmp_path / "pm").mkdir()
    t = {"now": NOW}
    rt = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: t["now"])
    con.execute("INSERT INTO job_runs (run_id, job, slot, started_at, finished_at, status) VALUES (1, 'collect', ?, ?, ?, 'ok')", [NOW, NOW, NOW])
    rt._write_beat(NOW, None)
    t["now"] = NOW + timedelta(seconds=90)
    rt._write_beat(t["now"], None)
    d = json.loads((tmp_path / "pm" / "app" / "heartbeat.json").read_text(encoding="utf-8"))
    assert d["since"] == NOW.isoformat(timespec="seconds") and d["beats"] == 2 and d["max_gap_s"] == 90 and d["jobs_last_hour"] == 1
