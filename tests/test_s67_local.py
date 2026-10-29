"""S67 local repairs of the audited candidate: the sandbox result boundary, effects that stop halfway, and a live task no wake may reap.
Synthetic data; no network, no Docker."""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from pflab.agents import sandbox as sb
from pflab.hq import board, cases
from pflab.pm import store

NOW = datetime(2026, 10, 29, 16, 30)


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


# --- E: the result file a run hands back --------------------------------------------------------------------------------------------

def test_a_plain_small_json_object_is_read_back(tmp_path):
    f = tmp_path / "out.json"
    f.write_text('{"test_ok": true, "result": {"x": 1.5}}', encoding="utf-8")
    assert sb.read_result(f) == {"test_ok": True, "result": {"x": 1.5}}
    assert sb.read_result(tmp_path / "missing.json") == {}                       # no result file: the caller reports "no result"


@pytest.mark.parametrize("body", [b"[1, 2]", b"not json", b"\xff\xfe\x00", b'"text"', b"123"])
def test_a_result_that_is_not_a_json_object_is_refused_not_guessed(tmp_path, body):
    f = tmp_path / "out.json"
    f.write_bytes(body)
    r = sb.read_result(f)
    assert list(r) == ["error"] and "refused" in r["error"]


def test_an_oversized_result_is_refused_without_reading_it_whole(tmp_path):
    f = tmp_path / "out.json"
    f.write_bytes(b'{"a": "' + b"x" * 5000 + b'"}')
    r = sb.read_result(f, limit=1000)
    assert "larger than 1000 bytes" in r["error"]


def test_a_link_or_a_folder_in_place_of_the_result_is_refused(tmp_path):
    secret = tmp_path / "secret.json"
    secret.write_text('{"leak": "host file"}', encoding="utf-8")
    link = tmp_path / "out.json"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links need a privilege on this PC")
    assert "plain file" in sb.read_result(link)["error"]
    d = tmp_path / "dir.json"
    d.mkdir()
    assert "plain file" in sb.read_result(d)["error"]


def test_the_docker_run_never_copies_a_link_out_of_the_out_folder(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    secret = tmp_path / "host_secret.json"
    secret.write_text('{"leak": "host file"}', encoding="utf-8")

    def run(cmd, **kw):
        out = Path(cmd[cmd.index("-v", cmd.index("-v") + 1) + 1].split(":/out")[0])
        try:
            os.symlink(secret, out / "out.json")
        except (OSError, NotImplementedError):
            pytest.skip("symbolic links need a privilege on this PC")
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")
    sb.Docker(runner=run).run(work, 5)
    got = json.loads((work / "out.json").read_text(encoding="utf-8"))
    assert "leak" not in got and "plain file" in got["error"]


# --- B: effects that stop halfway ------------------------------------------------------------------------------------------------

def test_an_effect_is_started_then_done_and_not_repeated(con):
    sent = []
    assert board.once(con, 1, "k1", "message", NOW, lambda: sent.append(1)) is True
    assert board.once(con, 1, "k1", "message", NOW, lambda: sent.append(2)) is False
    assert sent == [1]
    assert con.execute("SELECT state FROM hq_effects WHERE effect_key='k1'").fetchone()[0] == "done"
    assert board.uncertain(con) == []


def test_an_effect_killed_midway_is_listed_as_uncertain_and_never_repeated_blindly(con):
    class Killed(BaseException):                                  # a process death: not an Exception, so no clean-up code runs
        pass

    def die():
        raise Killed()
    with pytest.raises(Killed):
        board.once(con, 7, "told:7", "message", NOW, die)
    again = []
    assert board.once(con, 7, "told:7", "message", NOW, lambda: again.append(1)) is False and again == []
    u = board.uncertain(con)
    assert [x["key"] for x in u] == ["told:7"] and u[0]["task"] == 7


def test_a_failed_effect_that_did_not_happen_may_be_tried_again(con):
    def boom():
        raise RuntimeError("no network")
    with pytest.raises(RuntimeError):
        board.once(con, 1, "k2", "message", NOW, boom)
    assert board.uncertain(con) == [] and board.once(con, 1, "k2", "message", NOW, lambda: None) is True


def test_a_store_effect_and_its_marker_commit_together_or_not_at_all(con):
    con.execute("CREATE TABLE side (v INTEGER)")
    assert board.once_db(con, 1, "db1", "note", NOW, lambda: con.execute("INSERT INTO side VALUES (1)")) is True
    assert board.once_db(con, 1, "db1", "note", NOW, lambda: con.execute("INSERT INTO side VALUES (2)")) is False

    def half():
        con.execute("INSERT INTO side VALUES (3)")
        raise RuntimeError("stopped after the write")
    with pytest.raises(RuntimeError):
        board.once_db(con, 1, "db2", "note", NOW, half)
    assert con.execute("SELECT v FROM side ORDER BY v").fetchall() == [(1,)]              # the write was rolled back with the marker
    assert con.execute("SELECT count(*) FROM hq_effects WHERE effect_key='db2'").fetchone()[0] == 0


def test_the_reap_note_tells_what_stopped_halfway(con):
    tid = board.post(con, "calc", "q", NOW)
    con.execute("UPDATE hq_tasks SET status='running', attempts=1 WHERE task_id=?", [tid])
    con.execute("INSERT INTO hq_effects (effect_key, task_id, kind, done_at, detail, state) VALUES ('a', ?, 'message', ?, '', 'done')", [tid, NOW])
    con.execute("INSERT INTO hq_effects (effect_key, task_id, kind, done_at, detail, state) VALUES ('b', ?, 'message', ?, '', 'started')", [tid, NOW])
    assert board.reap(con, NOW) == 1
    p = board.get(con, tid)["progress"]
    assert "1 effect(s) already done" in p and "1 effect(s) stopped halfway" in p


# --- B: a task a live worker owns is not reaped ------------------------------------------------------------------------------------

def test_a_wake_does_not_reap_a_task_this_process_is_still_running_but_does_reap_a_dead_ones(con):
    live = board.post(con, "calc", "slow", NOW)
    dead = board.post(con, "calc", "left by a dead process", NOW)
    con.execute("UPDATE hq_tasks SET status='running', attempts=1 WHERE task_id IN (?, ?)", [live, dead])
    with board._LIVE_LOCK:
        board._LIVE.add(live)
    try:
        assert board.reap(con, NOW) == 1
        assert board.get(con, live)["status"] == "running" and board.get(con, dead)["status"] == "retry"
    finally:
        with board._LIVE_LOCK:
            board._LIVE.discard(live)
    assert board.reap(con, NOW) == 1 and board.get(con, live)["status"] == "retry"      # once its worker is gone it is no longer owned


def test_run_one_owns_its_task_while_the_agent_runs(con, tmp_path):
    from pflab.hq.desk import Desk
    rt = Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, {"brain": "economy", "preset": "full"}, clock=lambda: NOW)
    tid = board.post(con, "calc", "slow", NOW)
    seen = {}

    def agent(rt_, task):
        seen["live"] = tid in board.live_ids()
        seen["reaped"] = board.reap(rt_.cursor(), NOW)               # a wake arrives while the agent is still working
        return board.Reply("done")
    out = board.run_one(rt, {"calc": agent})
    assert seen == {"live": True, "reaped": 0} and out["status"] == "done" and tid not in board.live_ids()


def test_a_case_in_a_pass_is_not_reaped_by_a_wake(con):
    cid = 1
    con.execute("""INSERT INTO hq_cases (case_id, subject_key, opened_at, updated_at, origin, question, status, attempts, max_attempts, steps)
                   VALUES (1, 'k', ?, ?, 'test', 'q', 'queued', 0, 3, 0)""", [NOW, NOW])
    cases.start_pass(con, [cid], 5, NOW)
    assert cases.reap(con, NOW) == 0 and cases.get(con, cid)["status"] == "running"
    cases.end_pass(con, [cid], 5, NOW, True)
    con.execute("UPDATE hq_cases SET status='running' WHERE case_id=1")                 # now an orphan: nothing in this process owns it
    assert cases.reap(con, NOW) == 1


# --- D: each recommendation is current on its own instruments ------------------------------------------------------------------------

def test_one_fresh_stock_does_not_make_a_suggestion_on_another_stock_current(con, tmp_path):
    from datetime import date
    from pflab.app import runtime, system
    A, B = "INE000A01011", "INE000B01012"
    now = datetime(2026, 11, 2, 10, 0)                                       # a Monday: the last closed session is Friday 30 Oct
    for isin, sym in ((A, "AAA"), (B, "BBB")):
        con.execute("""INSERT INTO instruments (isin, key_kind, asset_class, tax_class, listed, symbol, name, source, built_at)
                       VALUES (?, 'isin', 'equity', 'listed_equity', TRUE, ?, ?, 'synthetic', now())""", [isin, sym, sym])
    con.execute("INSERT INTO prices VALUES (?,?,?,?,?,?)", [B, date(2026, 10, 30), 100.0, "EQ", "nse", now])        # B is current
    con.execute("INSERT INTO prices VALUES (?,?,?,?,?,?)", [A, date(2026, 10, 20), 100.0, "EQ", "nse", now])        # A is twelve days old
    for sid, isin, sym in ((1, A, "AAA"), (2, B, "BBB")):
        con.execute("INSERT INTO hq_suggestions (sug_id, pass_id, model, made_at, kind, isin, symbol, text, reasoning, horizon_days, shadow, answer) "
                    "VALUES (?, 1, 'm', ?, 'add', ?, ?, 'a', 'r', 30, false, 'none')", [sid, now, isin, sym])
    (tmp_path / "pm").mkdir()
    rt = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: now)
    rec = system.recommendations(rt, now)
    by = {i["id"]: i for i in rec["items"]}
    assert by[1]["current"] is False and A in by[1]["why"] and by[1]["depends_on"] == [A]
    assert by[2]["current"] is True and by[2]["why"] is None
    assert rec["current"] is False and "1 of 2" in rec["say"]                      # the picture as a whole is not called current
    con.execute("INSERT INTO prices VALUES (?,?,?,?,?,?)", [A, date(2026, 10, 30), 100.0, "EQ", "nse", now])
    assert system.recommendations(rt, now)["current"] is True


def test_a_plan_is_judged_on_the_isins_in_its_stored_inputs(con):
    from pflab.app import system
    assert system._ISIN.findall('{"buy": "INE000A01011", "x": "ZZ0001234567", "n": "XINE000A01011Y"}') == ["INE000A01011", "ZZ0001234567"]


# --- A: a rollback keeps changes and deletions made after the upgrade, or changes nothing ---------------------------------------------

def _two_stores(tmp_path):
    import duckdb
    from datetime import date
    from pflab.ledger.events import Event, EventLog, save
    old = [m for m in store.MIGRATIONS if m[0] <= 42]
    bk, kept = tmp_path / "bk.duckdb", tmp_path / "kept.duckdb"
    con = duckdb.connect(str(bk))
    store.migrate(con, old)
    save(con, EventLog([Event("deposit", "ZER", date(2026, 10, 1), amount=1000.0), Event("buy", "ZER", date(2026, 10, 2), isin="INE000A01011", qty=1, price=10.0, ref="T1")]))
    for k in (1, 2, 3):
        con.execute("INSERT INTO questions VALUES (?, ?, 'x', ?, 'q', 'open', NULL, NULL)", [k, NOW, f"k{k}"])
    con.close()
    kept.write_bytes(bk.read_bytes())
    c = store.connect(kept)                                                  # the app on the newer release
    c.execute("UPDATE questions SET status='answered', answer='yes' WHERE q_id=1")             # an old row changed
    c.execute("DELETE FROM questions WHERE q_id=2")                                             # an old row removed
    c.execute("DELETE FROM events WHERE ref='T1'")                                              # a transaction corrected: the old version goes ...
    c.execute("INSERT INTO events (event_id, kind, account_id, trade_date, isin, qty, price, ref, ingested_at) SELECT max(event_id) + 1, 'buy', 'ZER', "
              "DATE '2026-10-02', 'INE000A01011', 2, 10.0, 'T1', now() FROM events")                 # ... and the fixed one stands
    c.close()
    return bk, kept


def test_merge_carries_over_changed_rows_and_deletions_and_a_corrected_event_replaces_the_old_one(tmp_path):
    import duckdb
    from pflab import update as up
    bk, kept = _two_stores(tmp_path)
    r = up.merge_new_rows(kept, bk)
    assert r["errors"] == {} and r["updated"].get("questions") == 1 and r["deleted"].get("questions") == 1
    con = duckdb.connect(str(bk), read_only=True)
    q = dict(con.execute("SELECT q_id, status FROM questions").fetchall())
    assert q == {1: "answered", 3: "open"}                                       # the change stands, the deletion is not undone
    assert con.execute("SELECT ref, qty FROM events WHERE ref='T1'").fetchall() == [("T1", 2.0)]     # the corrected version only, not both
    con.close()
    again = up.merge_new_rows(kept, bk)
    assert again["rows"] == 0 and again["updated"] == {} and again["deleted"] == {}


def test_a_rollback_that_cannot_prepare_the_older_store_changes_nothing(tmp_path, monkeypatch):
    from pflab import release, update as up
    from tests.test_s65_update import g, ok_install, publish
    origin, work, folder = tmp_path / "origin.git", tmp_path / "work", tmp_path / "PortfolioLabApp"
    g(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    g(tmp_path, "clone", "-q", str(origin), str(work))
    g(work, "checkout", "-q", "-b", "main")
    (work / ".gitignore").write_text("release.toml\n", encoding="utf-8")
    publish(work, "one", "v2026.10.01")
    app = folder / "app"
    folder.mkdir()
    g(folder, "clone", "-q", str(origin), str(app))
    g(app, "checkout", "-q", "--detach", "v2026.10.01")
    release.write(app, folder, "v2026.10.01")
    pm = folder / "pm"
    bk, _kept = _two_stores(tmp_path)
    pm.mkdir()
    (pm / "ledger.duckdb").write_bytes(bk.read_bytes())
    publish(work, "two", "v2026.10.15")
    r = up.update(app, pm, install=ok_install, selftest=lambda root: (True, "ok"), now=NOW)
    assert r["updated"]
    before = (pm / "ledger.duckdb").read_bytes()
    monkeypatch.setattr(up, "merge_new_rows", lambda k, l: {"errors": {"questions": "ConstraintException: cannot represent"}, "added": {}, "only_in_kept": []})
    with pytest.raises(up.UpdateError) as e:
        up.rollback(app, pm, install=ok_install, now=NOW)
    assert "Nothing was changed" in str(e.value) and "could not be reconciled" in str(e.value)
    assert (pm / "ledger.duckdb").read_bytes() == before                        # the complete current store is still in service
    assert not (pm / "ledger.rollback_candidate.duckdb").exists()
    assert up.checked_out(app) == "v2026.10.15"                                 # and the code was not switched back
