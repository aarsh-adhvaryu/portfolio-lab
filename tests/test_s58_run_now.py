"""S58 (The investor 2026-10-24): the schedule is for when the system is not in use. Any job runs on request, one at a time;
while the window is open, notes the research job queues for Opus are submitted straight after it and a submitted batch
is collected every 30 minutes."""
import threading
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from pflab.app import runtime, server, views
from pflab.pm import store
from pflab.service import jobs, tasks  # noqa: F401  (registers the jobs)
from pflab.service.schedule import Daily

NOW = datetime(2026, 10, 24, 15, 0)       # a Saturday afternoon: research's slot is Friday 23:30


@pytest.fixture
def rt(tmp_path, monkeypatch):
    con = store.connect(tmp_path / "l.duckdb")
    r = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)
    ran = []
    r.ran = ran
    queued = {"n": 2}

    def research(ctx):
        ran.append("research")
        return {"opus_queued": queued["n"]}
    monkeypatch.setitem(jobs.REGISTRY, "research", jobs.Job("research", Daily(23, 30), research, "test"))
    monkeypatch.setitem(jobs.REGISTRY, "analyst", jobs.Job("analyst", Daily(1, 0, weekdays_only=False),
                                                           lambda ctx: ran.append("analyst") or {}, "test"))
    r.queued = queued
    return r


def test_run_now_runs_the_job_once_and_research_hands_its_notes_to_the_analyst(rt):
    assert rt.request_run("research") == ["research"] and rt.request_run("research") == ["research"]   # asked twice
    out = rt.run_wanted()
    assert [x.job for x in out] == ["research", "analyst"] and rt.ran == ["research", "analyst"]
    assert rt.wanted == [] and rt.asked["research"].startswith("ok at 15:00")
    row = rt.cursor().execute("SELECT slot FROM job_runs WHERE job='research'").fetchone()
    assert row[0] == datetime(2026, 10, 23, 23, 30)                  # counts for the slot it caught up
    rt.queued["n"] = 0                                               # nothing queued: no analyst run
    rt.request_run("research")
    assert [x.job for x in rt.run_wanted()] == ["research"]


def test_with_the_scheduler_off_only_what_was_asked_runs(rt):
    rt.set_settings({"scheduler": False})
    rt.request_run("research")
    assert [x.job for x in rt.run_wanted()] == ["research"]


def test_held_messages_stay_held_and_unknown_jobs_are_refused(rt):
    c = TestClient(server.create_app(rt))
    assert c.post("/api/jobs/outbox/run").status_code == 409
    assert c.post("/api/jobs/nothing/run").status_code == 404
    assert c.post("/api/jobs/research/run").json() == {"queued": ["research"]}


def test_a_submitted_batch_is_collected_every_30_minutes(rt):
    con = rt.cursor()
    assert rt.poll_batches() is False                                # nothing submitted
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, "
                "status) VALUES (1, ?, 'batch', 'm', 'AAA', 'q', 'x', '{}', 'submitted')", [NOW])
    con.execute("INSERT INTO job_runs VALUES (1, 'analyst', ?, ?, ?, 'ok', '{}')",
                [NOW, NOW - timedelta(minutes=10), NOW - timedelta(minutes=9)])
    assert rt.poll_batches() is False and rt.wanted == []            # collected 10 minutes ago
    rt.clock = lambda: NOW + timedelta(minutes=25)
    assert rt.poll_batches() is True and rt.wanted == ["analyst"]


def test_the_schedule_shows_each_jobs_last_run_and_what_waits(rt):
    rt.request_run("research")
    rt.run_wanted()
    rt.request_run("research")
    d = views.schedule(rt)
    r = {x["job"]: x for x in d["jobs"]}
    assert r["research"]["last_run"]["status"] == "ok" and r["research"]["last_run"]["seconds"] is not None
    assert r["research"]["queued"] is True and d["wanted"] == ["research"]
    assert r["outbox"]["runnable"] is False and r["prices"]["last_run"] is None


def test_a_news_day_missed_by_a_failed_run_is_fetched_by_the_next(tmp_path, monkeypatch):
    import importlib.util
    import json
    from datetime import date
    from pathlib import Path
    from pflab.data import gdelt_gkg
    spec = importlib.util.spec_from_file_location("collect_daily", Path(__file__).parents[1] / "tools" / "collect_daily.py")
    cd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cd)
    (tmp_path / "al.json").write_text(json.dumps({"INE000A01001": ["acme"]}), encoding="utf-8")
    monkeypatch.setenv("PFLAB_GKG_ALIASES", str(tmp_path / "al.json"))
    asked = []
    monkeypatch.setattr(gdelt_gkg, "collect_day", lambda d, al, root: asked.append(d) or {"skipped": True})
    today = date.today()
    cd._gkg(today - timedelta(days=3), today, tmp_path)                 # the job's window is 3 days
    assert asked[0] == today - timedelta(days=14) and asked[-1] == today - timedelta(days=1) and len(asked) == 14


def test_a_note_in_flight_is_not_bought_twice(tmp_path, monkeypatch):
    from pflab.agents import analyst as an
    from pflab.agents import researcher as rs
    con = store.connect(tmp_path / "l.duckdb")
    con.execute("INSERT INTO api_calls (call_id, created_at, mode, model, topic, question, request_sha, request_json, "
                "status) VALUES (1, ?, 'batch', 'm', 'AAA', 'q', 'x', '{}', 'submitted')", [NOW])
    for i, sym in enumerate(("AAA", "BBB"), start=1):
        con.execute("INSERT INTO research_flags VALUES (?,?,?,?,?,?,?,?)",
                    [i, f"INE000{sym[0]}01001", sym, "results", NOW, NOW, f"r{i}", "d"])
    rung = []
    monkeypatch.setattr(an, "public_docs", lambda con, isins, asof: [])
    monkeypatch.setattr(an, "ring", lambda con, req, client, now, reuse=True, cfg=None: rung.append(req.topic) or an.Outcome("queued"))
    lst = [{"symbol": "AAA", "isin": "INE000A01001"}, {"symbol": "BBB", "isin": "INE000B01001"}]
    assert rs.deep_queue(con, NOW.date(), lst, client=object(), now=NOW) == {"AAA": "in flight", "BBB": "queued"}
    assert rung == ["BBB"]


def test_a_click_wakes_the_scheduler_and_closing_stops_it_at_once(rt):
    rt.set_settings({"scheduler": False})
    t = threading.Thread(target=rt._scheduler_loop, daemon=True)
    t.start()
    time.sleep(0.2)
    rt.request_run("research")
    for _ in range(50):
        if rt.ran:
            break
        time.sleep(0.05)
    assert rt.ran == ["research"]                                    # not after the 60-second wait
    t0 = time.time()
    rt.stop.set()
    rt._wake.set()
    t.join(5)
    assert not t.is_alive() and time.time() - t0 < 2
