"""S58 drill 1 findings, fixed: settings saved from two clicks at once, job runs with their real finish time, a failed
collector step fails the job (and the news step never opens the ledger the job holds), and a company with a material
change since its last note gets a fresh note."""
import json
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from pflab.agents import analyst as an
from pflab.agents import researcher as rs
from pflab.app import settings as st
from pflab.pm import store
from pflab.service import jobs, tasks
from pflab.service.schedule import Daily

NOW = datetime(2026, 10, 23, 16, 21, 58)


def test_settings_survive_saves_at_once(tmp_path):
    errors = []

    def click(i):
        try:
            st.save(tmp_path, {"privacy": i % 2 == 0, "preset": ["light", "full"][i % 2]})
        except Exception as e:
            errors.append(e)
    ts = [threading.Thread(target=click, args=(i,)) for i in range(24)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == [] and st.load(tmp_path)["preset"] in ("light", "full")
    assert list((tmp_path / "app").glob("*.tmp")) == []


def test_a_job_run_records_when_it_really_finished(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    ctx = jobs.Ctx(con, NOW, tmp_path, tmp_path, tmp_path)
    job = jobs.Job("slow", Daily(16, 0), lambda ctx: time.sleep(0.2) or {}, "a slow job")
    r = jobs.run_job(ctx, job)
    started, finished = con.execute("SELECT started_at, finished_at FROM job_runs WHERE run_id=?", [r.run_id]).fetchone()
    assert started == NOW and timedelta(seconds=0.19) <= finished - started < timedelta(seconds=5)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    from pflab.kg import build as kb
    from pflab.plan import guards as gd
    monkeypatch.setattr(gd, "stock_list", lambda: [])
    monkeypatch.setattr(kb, "universe", lambda con, lst: None)
    monkeypatch.setattr(kb, "aliases", lambda u: {"INE000A01001": ["acme"]})
    c = SimpleNamespace(con=None, data_root=tmp_path, repo=tmp_path, python="python", lookback_days=lambda name: 5)
    return c


def test_a_failed_collector_step_fails_the_job_and_the_news_step_gets_its_names(ctx, monkeypatch):
    seen = {}

    def run(cmd, capture_output, text, cwd, env):
        seen["aliases"] = json.loads(open(env["PFLAB_GKG_ALIASES"], encoding="utf-8").read())
        return SimpleNamespace(returncode=0, stderr="", stdout=seen.get("out", "  bhavcopy           ok   {}\n"))
    monkeypatch.setattr(subprocess, "run", run)
    assert tasks._collect(ctx) == {"days": 5} and seen["aliases"] == {"INE000A01001": ["acme"]}
    seen["out"] = ("  bhavcopy           ok   {}\n  gkg                FAIL IOException: IO Error: Cannot open file "
                   "\"ledger.duckdb\": The process cannot access the file\n")
    with pytest.raises(RuntimeError, match="gkg: IOException"):
        tasks._collect(ctx)


def test_a_material_change_since_the_last_note_buys_a_fresh_note(tmp_path, monkeypatch):
    con = store.connect(tmp_path / "l.duckdb")
    for i, sym in enumerate(("AAA", "BBB"), start=1):                 # both have a note from 17 Oct
        con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, "
                    "status) VALUES (?, ?, 'batch', 'm', ?, 'q', 'x', '{}', 'done')", [i, datetime(2026, 10, 17, 22), sym])
    calls = {}
    monkeypatch.setattr(an, "public_docs", lambda con, isins, asof: [])
    monkeypatch.setattr(an, "ring", lambda con, req, client, now, reuse=True, cfg=None: calls.update({req.topic: reuse}) or
                        an.Outcome("queued" if not reuse else "reused"))
    lst = [{"symbol": "AAA", "isin": "INE000A01001"}, {"symbol": "BBB", "isin": "INE000B01001"}]
    for i, (sym, kind) in enumerate((("AAA", "results"), ("BBB", "news_spike"))):
        con.execute("INSERT INTO research_flags VALUES (?,?,?,?,?,?,?,?)",
                    [i + 1, lst[i]["isin"], sym, kind, NOW, NOW, f"r{i}", "d"])
    out = rs.deep_queue(con, NOW.date(), lst, client=object(), now=NOW)
    assert calls == {"AAA": False, "BBB": True} and out == {"AAA": "queued", "BBB": "reused"}


def test_a_cut_ledger_rebuild_leaves_the_old_ledger(tmp_path, monkeypatch):
    """Drill 2 (power cut): the rebuild fails halfway (here: a full disk) and nothing of it stays."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
    import build_pm_ledger as bpl
    from pflab.ledger.events import EventLog
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("INSERT INTO accounts (account_id, kind) VALUES ('OLD', 'bank')")

    def cut(con, log):
        con.execute("INSERT INTO accounts (account_id, kind) VALUES ('HALF', 'bank')")
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(bpl, "save_events", cut)
    led = SimpleNamespace(write_derived=lambda con: None, positions=lambda: {})
    with pytest.raises(OSError):
        bpl.write(con, EventLog(), led, {"accounts": {"NEW": {"kind": "bank"}}, "_names": {}})
    assert con.execute("SELECT list(account_id) FROM accounts").fetchone()[0] == ["OLD"]


def test_transactions_nest_and_roll_back_whole():
    import duckdb
    c = duckdb.connect()
    c.execute("CREATE TABLE t (x INT)")
    with store.transaction(c):
        c.execute("INSERT INTO t VALUES (1)")
        with store.transaction(c):
            c.execute("INSERT INTO t VALUES (2)")
    with pytest.raises(OSError):
        with store.transaction(c):
            c.execute("INSERT INTO t VALUES (3)")
            with store.transaction(c):
                raise OSError(28, "No space left on device")
    with store.transaction(c):
        c.execute("INSERT INTO t VALUES (4)")
    assert c.execute("SELECT list(x ORDER BY x) FROM t").fetchone()[0] == [1, 2, 4]


def test_a_nearly_full_disk_is_asked_about_and_stops_downloads(ctx, tmp_path, monkeypatch):
    """Drill 4 (full disk)."""
    import shutil

    from pflab.conductor import calendar as calm
    from pflab.conductor import sync
    monkeypatch.setattr(shutil, "disk_usage", lambda p: SimpleNamespace(total=500e9, used=499.5e9, free=0.5e9))
    with pytest.raises(RuntimeError, match="only 0.5 GB free"):
        tasks._collect(ctx)
    con = store.connect(tmp_path / "l.duckdb")
    f = [x for x in sync.service_findings(jobs.Ctx(con, NOW, tmp_path, tmp_path, tmp_path), calm.load()) if x.name == "disk"]
    assert f and f[0].status == "ask" and "nearly full" in f[0].ask_text
