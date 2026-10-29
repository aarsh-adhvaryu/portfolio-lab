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
