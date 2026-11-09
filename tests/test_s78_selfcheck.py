"""S78: does everything work? The self-check runs every check, keeps the rows, groups them for the screen, alerts on a failure, and quarantines a read tool whose probe fails twice running
(and only then, and only until it passes). Synthetic data only."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from pflab.agents import analyst as an
from pflab.hq import egress, selfcheck as sc, tools as tl
from pflab.hq.desk import Desk
from pflab.pm import store

NOW = datetime(2026, 11, 2, 11, 0)
CFG = {"model": an.MODEL, "cap": 1500.0, "ask_above": 100.0, "usd_inr": 90.0, "adopted": True}


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "s.duckdb")


@pytest.fixture
def rt(con, tmp_path, monkeypatch):
    monkeypatch.setattr(an, "config", lambda: CFG)
    (tmp_path / "pm" / "app").mkdir(parents=True)
    return Desk(con, tmp_path / "pm", tmp_path / "data", tmp_path / "repo", None, {"brain": "normal", "preset": "full"}, clock=lambda: NOW)


def test_every_read_tool_is_probed_and_the_run_is_kept_and_grouped(rt, con):
    out = sc.run_all(rt, NOW, quick=True)
    reads = [n for n, t in tl.TOOLS.items() if t.kind == "read"]
    names = {r["name"] for r in out["rows"]}
    assert all(f"probe: {n}" in names for n in reads) and out["total"] == len(out["rows"]) == con.execute("SELECT count(*) FROM selfchecks").fetchone()[0]
    assert out["ok"] + out["warn"] + out["bad"] == out["total"] and out["run_id"] == 1
    got = sc.latest(con)
    assert [g["title"] for g in got["groups"]] == [g for g in sc.GROUPS if any(r["grp"] == g for r in out["rows"])] and got["run"]["id"] == 1
    again = sc.run_all(rt, NOW + timedelta(hours=1), quick=True)
    assert again["run_id"] == 2 and sc.latest(con)["run"]["id"] == 2


def test_the_known_answer_checks_give_their_known_answers(rt, con):
    rows = {r["name"]: r for r in sc.run_all(rt, NOW, quick=True)["rows"]}
    for name in ("Tax maths (known answer)", "Chart facts (known answer)", "No-trading guard", "No order tool", "Number guard", "Definitions", "Worker loop path"):
        assert rows[name]["status"] == sc.OK, (name, rows[name])


def test_checks_that_cannot_run_are_warnings_never_failures_and_a_crash_is_a_failure_with_the_reason(rt, con, monkeypatch):
    from pflab.app import runtime as rtm
    monkeypatch.setattr(rtm, "token_valid", lambda now: False)
    rows = {r["name"]: r for r in sc.run_all(rt, NOW, quick=True)["rows"]}
    assert rows["Calculation sandbox"]["status"] == sc.WARN and rows["Kite live quotes"]["status"] == sc.WARN
    r = sc.Run(con, NOW)
    r.check("Tools", "boom", lambda: (_ for _ in ()).throw(RuntimeError("it broke")))
    assert r.rows[0]["status"] == sc.BAD and "it broke" in r.rows[0]["note"]


def test_a_read_tool_is_quarantined_only_after_two_failures_in_a_row_and_freed_by_a_pass(rt, con):
    def mark(status, k):
        con.execute("INSERT INTO selfchecks VALUES (?, ?, ?, 'Tools', 'probe: findings', ?, 'x', 1)", [k, k, NOW + timedelta(minutes=k), status])
    mark(sc.BAD, 1)
    assert sc.quarantined(con, "findings") is None                                                           # one failure is not enough
    mark(sc.BAD, 2)
    assert "not used until it passes again" in sc.quarantined(con, "findings")
    ctx = tl.Ctx(rt, None, "m", False, {}, egress.Gate(), NOW, role="research", allowed=frozenset(tl.TOOLS))
    text, err = tl.run(ctx, "findings", {})
    assert err and "self-check" in text                                                                     # the agent is told, and does not get a result
    mark(sc.OK, 3)
    assert sc.quarantined(con, "findings") is None
    text2, err2 = tl.run(ctx, "findings", {})
    assert not err2


def test_an_action_tool_is_never_quarantined(rt, con):
    for k in (1, 2):
        con.execute("INSERT INTO selfchecks VALUES (?, ?, ?, 'Tools', 'probe: add_rule', 'bad', 'x', 1)", [k, k, NOW])
    ctx = tl.Ctx(rt, None, "m", False, {}, egress.Gate(), NOW, role="assistant", allowed=frozenset({"add_rule"}))
    text, err = tl.run(ctx, "add_rule", {"kind": "note", "text": "a note for the record"})
    assert "self-check" not in text


def test_the_job_alerts_on_a_failure_once_a_day_and_the_endpoints_work(rt, con, monkeypatch):
    from pflab.service.jobs import Ctx
    monkeypatch.setattr(sc, "run_all", lambda rt, now, quick=False: {"run_id": 9, "ok": 3, "warn": 1, "bad": 1, "total": 5,
                                                                      "rows": [{"grp": "Tools", "name": "probe: x", "status": "bad", "note": "boom"}]})
    sent = []
    from pflab.app import assistant
    monkeypatch.setattr(assistant, "notify", lambda con, now, text, key, route=None: sent.append((text, key)) or True)

    class C:
        pass
    c = C()
    c.con, c.now, c.pm_dir, c.data_root, c.repo, c.secrets, c.settings = con, NOW, rt.pm_dir, rt.data_root, rt.repo, None, rt.settings
    out = sc.job(c)
    assert out["bad"] == 1 and sent and "Tools: probe: x" in sent[0][0] and sent[0][1].startswith("selfcheck:")
