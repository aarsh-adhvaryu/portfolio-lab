"""S66 the system as one picture (app/system.py): connectors, data freshness, work in plain words, needs grouped; the assistant's two new tools;
a stopped process's "running" row is released at the next start; Bank Nifty is refreshed daily. Synthetic data; no network."""
from datetime import date, datetime, timedelta

import pytest

from pflab.agents import questions
from pflab.app import runtime, system
from pflab.hq import tools as tl
from pflab.pm import store
from pflab.service import jobs

NOW = datetime(2026, 11, 4, 21, 0)


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    con = store.connect(tmp_path / "l.duckdb")
    monkeypatch.setattr(system, "_ollama", lambda: {"up": True, "models": ["qwen3:8b-q8_0", "nomic-embed-text:latest"]})
    monkeypatch.setattr(system, "_docker", lambda: "running")
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)


def test_freshness_is_ok_inside_the_normal_lag_late_after_it_and_down_when_stale():
    exp = date(2026, 11, 4)
    assert system._state(date(2026, 11, 3), exp) == system.OK                        # one session behind is normal
    assert system._state(date(2026, 11, 1), exp) == system.WARN
    assert system._state(date(2026, 9, 22), exp) == system.DOWN                      # Bank Nifty a month old
    assert system._state(None, exp) == system.WARN                                   # nothing yet is waiting, not broken


def test_job_results_are_said_in_plain_words_not_json():
    assert system.say_job("filings", '{"alerts_queued": 0, "filings": 22, "names": 15}') == "checked company filings: 22 for 15 of your names; 0 alert(s)"
    assert system.say_job("hq", '{"brain": "{\'pass\': None, \'why\': \'nothing new\'}"}') == "the brain thought: nothing new"
    assert "{" not in system.say_job("some_new_job", '{"rows": 5, "nested": {"a": 1}}')
    assert system.say_job("some_new_job", "not json at all") == "some new job: nothing new"


def test_needs_groups_the_same_kind_of_request(rt):
    con = rt.cursor()
    for sym in ("AAA", "BBB", "CCC"):
        questions.ask(con, "needs", f"tijori:INE{sym}:2026-11", f"Please drop the Tijori sheet for {sym} (missing: quarters). It stays on this PC.", NOW)
    questions.ask(con, "mail", "mail:connect", "Connect Gmail so your statements arrive by themselves. More words.", NOW)
    n = system.needs(con)
    assert n["total"] == 4 and n["groups"] == 2
    tij = [i for i in n["items"] if i["count"] == 3][0]
    assert "3 company sheets" in tij["title"] and "AAA" in tij["title"] and "CCC" in tij["title"]


def test_the_picture_reads_the_whole_system(rt, monkeypatch):
    from pflab.ingest import gmail                                                    # the real keys folder must not decide this test
    monkeypatch.setattr(gmail, "connected", lambda: False)
    monkeypatch.setattr(gmail, "has_client", lambda: True)
    con = rt.cursor()
    con.execute("INSERT INTO job_runs (run_id, job, started_at, finished_at, status, detail) VALUES (1, 'filings', ?, ?, 'ok', "
                "'{\"filings\": 3, \"names\": 2, \"alerts_queued\": 0}')", [NOW - timedelta(minutes=5), NOW - timedelta(minutes=4)])
    con.execute("INSERT INTO job_runs (run_id, job, started_at, status) VALUES (2, 'collect', ?, 'running')", [NOW - timedelta(minutes=1)])
    p = system.picture(rt, NOW)
    names = {c["id"]: c for c in p["connectors"]}
    assert set(names) == {"kite", "gmail", "telegram", "local", "api", "sandbox", "release"}
    assert names["local"]["state"] == system.OK and names["kite"]["state"] == system.WARN and names["kite"]["action"] == "kite"
    assert names["gmail"]["action"] == "gmail"
    assert p["work"]["running"] == [{"job": "collect", "since": "20:59"}]
    assert p["work"]["recent"][0]["says"].startswith("checked company filings: 3 for 2")
    assert p["tools"]["total"] == len(tl.TOOLS) and p["tools"]["read"] >= 20
    assert p["state"] in (system.WARN, system.DOWN) and p["verdict"]


def test_the_assistant_can_read_the_system_and_the_emails(rt):
    assert {"system_status", "mail_facts"} <= set(tl.TOOLS) and all(tl.TOOLS[n].kind == "read" for n in ("system_status", "mail_facts"))
    from types import SimpleNamespace
    ctx = SimpleNamespace(rt=rt, now=NOW, con=rt.cursor())
    s = tl.system_status(ctx, {})
    assert s["verdict"] and s["connectors"] and "source" in s
    assert tl.mail_facts(ctx, {})["counts"] == {}


def test_a_run_left_running_by_a_stopped_process_is_due_again_at_the_next_start(rt):
    con = rt.cursor()
    job = jobs.REGISTRY.get("collect") or __import__("pflab.service.tasks", fromlist=["x"]) and jobs.REGISTRY["collect"]
    slot = job.schedule.latest_slot(NOW)
    con.execute("INSERT INTO job_runs (run_id, job, started_at, status) VALUES (9, 'collect', ?, 'running')", [slot + timedelta(minutes=11)])
    ctx = jobs.Ctx(con, slot + timedelta(minutes=30), rt.pm_dir, rt.data_root, rt.repo, "python", None)
    assert jobs.is_due(ctx, job)[0] is False                                         # a live run (or one cooling down) holds the slot
    assert jobs.reap_at_start(con, ctx.now) == 1
    assert jobs.is_due(ctx, job)[0] is True                                          # the stopped one no longer blocks today's collection
    assert con.execute("SELECT status FROM job_runs WHERE run_id=9").fetchone()[0] == "failed"


def test_bank_nifty_is_refreshed_every_day():
    from pflab.data import indices
    from pflab.app import views
    assert "SECTOR_BANK_PRICE" in indices.DAILY_KEYS
    assert any(key == "SECTOR_BANK_PRICE" for _, _, key in views.TICKERS)            # the ticker reads the file the daily step now keeps current
