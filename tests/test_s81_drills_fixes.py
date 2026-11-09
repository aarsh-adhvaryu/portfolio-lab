"""S81: fixes found by the drills (tools/drills_s81.py), each with the test that holds it. Synthetic data only; no paid call; no network."""
from __future__ import annotations

from datetime import datetime

import pytest

from pflab.lab import strategist
from pflab.pm import store

from tests.test_s80_core import DAYS, NOW as CORE_NOW, calm_index, con as core_con  # noqa: F401  (the synthetic book of the core tests)

NOW = datetime(2026, 11, 9, 1, 0)


def test_a_close_killed_between_two_orders_leaves_none_of_it_and_is_decided_again(core_con, monkeypatch):
    """Drill kill9 (S81): a process killed after the first order of a close left that decision and order with no `core_runs_s80` row. The restarted loop then waited on orders of a close
    it had no record of, and never wrote the day. Placing the orders and writing the run row are now one transaction: the kill (here an exception between two orders) leaves nothing."""
    from pflab.core import loop
    from pflab.paper import allocation, book
    t = allocation.propose_allocation(core_con, {"equity": 12, "gold": 40, "international": 0, "cash": 48}, "x" * 60, CORE_NOW)
    allocation.review_target(core_con, t["target_id"], "approve", "ok", CORE_NOW)
    real_place, n = book.place, {"n": 0}

    def dies_on_the_second(*a, **k):
        n["n"] += 1
        if n["n"] == 2:
            raise KeyboardInterrupt("killed here")                   # not an Exception: nothing in the loop may swallow it, as with a kill
        return real_place(*a, **k)
    monkeypatch.setattr(book, "place", dies_on_the_second)
    with pytest.raises(KeyboardInterrupt):
        loop.run(core_con, CORE_NOW, None, calm_index())
    assert n["n"] == 2, "the drill needs a close with at least two orders"
    q = lambda sql: core_con.execute(sql).fetchone()[0]
    assert q("SELECT count(*) FROM paper_decisions") == 0 and q("SELECT count(*) FROM paper_orders") == 0 and q("SELECT count(*) FROM paper_claims") == 0
    assert q("SELECT count(*) FROM core_runs_s80") == 0
    monkeypatch.setattr(book, "place", real_place)
    r = loop.run(core_con, CORE_NOW, None, calm_index())             # the restarted app decides the close again, whole
    assert r.get("status") == "traded" and len(r["orders"]) >= 2, r
    assert q("SELECT count(*) FROM core_runs_s80") == 1
    assert q("SELECT count(*) FROM paper_decisions") == q("SELECT count(*) FROM paper_orders") == len(r["orders"])


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("INSERT INTO core_policies_s80 (policy_id, status, code_hash, created_at, promoted_at) VALUES ('baseline_v1', 'champion', 'x', ?, ?)", [NOW, NOW])
    return c


def test_a_lab_close_with_the_sandbox_down_waits_and_says_why_instead_of_failing_and_alerting_him(con, tmp_path, monkeypatch):
    """Drill docker_down (S81): with a challenger in shadow and Docker not running, `lab_close` raised SandboxUnavailable: the job was recorded failed and a Telegram 'job failed' went out
    at every 15-minute cooldown. Docker being down is a state to wait in: the job is skipped with the reason, is not started again every tick, and tries again after 15 minutes."""
    from datetime import timedelta

    from pflab import markets
    from pflab.agents import sandbox as sb
    from pflab.lab import shadow
    from pflab.service import jobs, tasks  # noqa: F401  (importing tasks registers the jobs)
    con.execute("INSERT INTO core_policies_s80 (policy_id, status, code_hash, created_at) VALUES ('chal_one', 'challenger', 'h', ?)", [NOW])
    day = markets.get("IN").session_closed_by(NOW)
    con.execute("INSERT INTO core_runs_s80 VALUES (?,?,?,?,?,?,?,?,?,?,?)", [day, NOW, "baseline_v1", "held", 0.1, "{}", "{}", "{}", "[]", "[]", ""])

    def down(*a, **k):
        raise sb.SandboxUnavailable("Docker Desktop is not running")
    monkeypatch.setattr(shadow, "run_shadow", down)
    ctx = jobs.Ctx(con, NOW, tmp_path, tmp_path, tmp_path)
    r = jobs.run_job(ctx, jobs.REGISTRY["lab_close"])
    assert r.status == "skipped" and "Docker Desktop is not running" in r.detail and "challengers wait" in r.detail
    soon = jobs.Ctx(con, NOW + timedelta(minutes=2), tmp_path, tmp_path, tmp_path)
    assert jobs.is_due(soon, jobs.REGISTRY["lab_close"])[0] is False                              # not every tick
    later = jobs.Ctx(con, NOW + timedelta(minutes=20), tmp_path, tmp_path, tmp_path)
    assert jobs.is_due(later, jobs.REGISTRY["lab_close"])[0] is True                              # tried again when Docker may be back


def test_a_strategist_session_with_no_cloud_client_waits_and_says_why_instead_of_failing_the_job(con, tmp_path):
    """The workshop's paid-call guard (or a missing key) used to raise out of `tick` before the session's own budget check: the `strategist` job was recorded failed and a Telegram
    alert went out at every cooldown. Now the job is skipped with the reason."""
    from pflab import guard

    def no_client():
        raise guard.OutwardBlocked("the workshop (beta channel) does not send outward: run it with the global --paid flag")
    out = strategist.tick(con, tmp_path, None, NOW, no_client)
    assert out["reasons"] and "skipped" in out and "no cloud client" in out["skipped"] and "OutwardBlocked" in out["skipped"]
    assert "session" not in out
    assert con.execute("SELECT count(*) FROM core_sessions_s80").fetchone()[0] == 0          # nothing was started, nothing half-recorded
