"""S67 local: the World screen's data. Every state is computed from the store (never typed), one failing section is named and the rest still show,
nothing is written, a fresh profile reads honestly (nothing is claimed), a paused or not-yet-launched profile says so. Synthetic data; no network."""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from pflab import activation
from pflab.app import runtime, world
from pflab.hq import cases, roster
from pflab.pm import store

NOW = datetime(2026, 10, 29, 21, 30)


@pytest.fixture
def rt(tmp_path, monkeypatch):
    (tmp_path / "pm").mkdir()
    monkeypatch.setenv("PFLAB_CHANNEL", "stable")
    con = store.connect(tmp_path / "l.duckdb")
    r = runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=lambda: NOW)
    r.con_ = con
    return r


def _run(con, rid, job, status, mins_ago, detail=None):
    t0 = NOW - timedelta(minutes=mins_ago)
    con.execute("INSERT INTO job_runs (run_id, job, slot, started_at, finished_at, status, detail) VALUES (?,?,?,?,?,?,?)",
                [rid, job, t0, t0, None if status == "running" else t0 + timedelta(seconds=30), status, detail])


def _task(con, tid, to, status, text="work", mins_ago=10):
    con.execute("INSERT INTO hq_tasks (task_id, created_at, from_agent, to_agent, text, status, hops, started_at, finished_at) VALUES (?,?,?,?,?,?,0,?,?)",
                [tid, NOW - timedelta(minutes=mins_ago), "investor", to, text, status, NOW - timedelta(minutes=mins_ago),
                 None if status in ("running", "queued", "waiting") else NOW - timedelta(minutes=2)])


def test_a_fresh_profile_shows_every_agent_and_claims_nothing(rt):
    w = world.build(rt, NOW)
    assert w["errors"] == {}
    names = {a["id"] for a in w["agents"]}
    assert names == {a["name"] for a in roster.listing()}                                      # every agent has a place in the world
    assert w["counts"]["working"] == 0 and w["counts"]["down"] == 0 and w["counts"]["done_today"] == 0
    assert w["feed"] == [] and w["looking_into"] == {"investigations": [], "experiments": []}
    assert {n["id"] for n in w["senses"]} == {"markets", "filings", "broker", "mail", "us"}
    assert all(j["group"] != "other" for j in w["jobs"])                                       # every routine belongs to a node
    assert w["pulse"]["tone"] in ("late", "waiting", "ok") and "failed" not in w["pulse"]["verdict"]


def test_states_come_from_what_actually_happened(rt):
    con = rt.cursor()
    _run(con, 1, "collect", "ok", 600)
    _run(con, 2, "prices", "ok", 590)
    _run(con, 3, "tradecheck", "failed", 12, "TokenException: no login")
    _run(con, 4, "mail", "running", 1)
    _task(con, 1, "research", "running", "Read AAA results")
    _task(con, 2, "calc", "done")
    _task(con, 3, "portfolio", "failed", "Refresh from Kite")
    _task(con, 4, "quant", "queued")
    w = world.build(rt, NOW)
    by = {n["id"]: n for n in w["senses"]}
    assert by["mail"]["state"] == "working" and by["broker"]["state"] == "down"
    assert by["markets"]["state"] in ("ok", "late") and by["markets"]["done_today"] >= 2
    ag = {a["id"]: a for a in w["agents"]}
    assert ag["research"]["state"] == "working" and ag["research"]["doing"] == "Read AAA results"
    assert ag["calc"]["state"] == "ok" and ag["portfolio"]["state"] == "down" and ag["quant"]["state"] == "waiting"
    assert w["counts"]["working"] >= 2 and w["counts"]["down"] >= 2
    assert "failed" in w["pulse"]["verdict"] and w["pulse"]["tone"] == "down"
    f = w["feed"]
    assert f == sorted(f, key=lambda e: e["at"], reverse=True) and any(e["tone"] == "down" for e in f)       # newest first, failures marked


def test_the_checklist_says_done_or_not_for_each_round_and_names_what_failed(rt):
    con = rt.cursor()
    _run(con, 1, "collect", "ok", 100)
    _run(con, 2, "tradecheck", "failed", 5, "TokenException: no login")
    rows = {r["name"]: r for r in world.build(rt, NOW)["checks"] if r["group"] == "Today's rounds"}
    assert rows["collect"]["state"] == "ok" and rows["collect"]["done"] is True
    assert rows["tradecheck"]["state"] == "down" and "TokenException" in rows["tradecheck"]["detail"] and rows["tradecheck"]["done"] is False


def test_one_failing_section_is_named_and_the_rest_still_show(rt, monkeypatch):
    monkeypatch.setattr(world, "jobs_view", lambda rt_, now: (_ for _ in ()).throw(RuntimeError("the schedule broke")))
    _task(rt.cursor(), 1, "research", "running")
    w = world.build(rt, NOW)
    assert "schedule broke" in w["errors"]["jobs"] and w["jobs"] == []
    assert {a["id"]: a for a in w["agents"]}["research"]["state"] == "working"                  # agents, work and memory are still there
    assert w["memory_nodes"] and w["guard_nodes"]


def test_a_profile_waiting_for_its_icon_and_a_paused_one_say_so(rt, tmp_path):
    activation.write_pending(rt.pm_dir)
    w = world.build(rt, NOW)
    assert w["pulse"]["tone"] == "waiting" and "first launch" in w["pulse"]["verdict"]
    assert all(j["state"] in ("waiting", "working") for j in w["jobs"])                           # nothing is called due or failed before the launch
    activation.activate(rt.pm_dir, via="icon")
    rt.set_settings({"scheduler": False})
    w2 = world.build(rt, NOW)
    assert w2["pulse"]["paused"] and "Paused" in w2["pulse"]["verdict"]


def test_it_reads_and_never_writes(rt):
    con = rt.cursor()
    _run(con, 1, "collect", "ok", 100)
    _task(con, 1, "research", "running")
    cases.open_case(con, NOW, "A question", subject="AAA")

    def counts():
        return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for (t,) in
                con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE'").fetchall()}
    before = counts()
    world.build(rt, NOW)
    world.build(rt, NOW + timedelta(minutes=1))
    assert counts() == before


def test_the_api_serves_the_world_and_pause_and_resume_work(rt):
    from fastapi.testclient import TestClient
    from pflab.app.server import create_app
    c = TestClient(create_app(rt))
    assert c.get("/api/world").json()["pulse"]["paused"] is False
    assert c.post("/api/world/pause", json={"paused": True}).json() == {"paused": True}
    w = c.get("/api/world").json()
    assert w["pulse"]["paused"] and rt.settings["scheduler"] is False
    c.post("/api/world/pause", json={"paused": False})
    assert c.get("/api/world").json()["pulse"]["paused"] is False and rt.settings["scheduler"] is True
