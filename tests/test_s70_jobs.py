"""S70: a lost connection is not a failure of a job that repeats every few minutes (it is offline and runs again at its next slot);
a bug, or a daily job, still fails. Synthetic jobs."""
from __future__ import annotations

from datetime import datetime

import pytest
import requests

from pflab.pm import store
from pflab.service import jobs
from pflab.service.schedule import Daily, Interval

NOW = datetime(2026, 11, 2, 12, 5)            # a Monday


@pytest.fixture
def ctx(tmp_path):
    con = store.connect(tmp_path / "l.duckdb")
    (tmp_path / "locks").mkdir()
    return jobs.Ctx(con, NOW, tmp_path, tmp_path, tmp_path)


def _run(ctx, schedule, fn):
    return jobs.run_job(ctx, jobs.Job("t", schedule, fn))


def _raise(e):
    def fn(c):
        raise e
    return fn


DNS = requests.exceptions.ConnectionError("HTTPSConnectionPool(host='api.kite.trade', port=443): Max retries exceeded (NameResolutionError)")


def test_a_lost_connection_in_a_repeating_job_is_offline_not_failed(ctx):
    r = _run(ctx, Interval(15), _raise(DNS))
    assert r.status == "skipped" and r.detail.startswith("offline:")
    assert ctx.con.execute("SELECT status FROM job_runs").fetchone()[0] == "skipped"


def test_parts_that_all_lost_their_connection_are_offline(ctx):
    r = _run(ctx, Interval(15), lambda c: {"board": 0, "failed": {"phone": "ConnectionError: HTTPSConnectionPool(host='api.telegram.org'): getaddrinfo failed"}})
    assert r.status == "skipped" and '"offline"' in r.detail and '"failed"' not in r.detail


def test_one_real_failure_among_them_still_fails(ctx):
    r = _run(ctx, Interval(15), lambda c: {"failed": {"phone": "ConnectionError: getaddrinfo failed", "brain": "KeyError: 'isin'"}})
    assert r.status == "failed" and "KeyError" in r.detail


def test_a_bug_is_never_offline(ctx):
    assert _run(ctx, Interval(15), _raise(KeyError("isin"))).status == "failed"
    assert _run(ctx, Interval(15), _raise(ZeroDivisionError("x"))).status == "failed"


def test_a_daily_job_still_fails_so_that_it_cools_down_and_tries_again(ctx):
    r = _run(ctx, Daily(19, 30), _raise(DNS))
    # S79b (A42, found by the drills): a lost connection is 'offline', not 'failed': it still cools down and tries again (the slot is not done), but raises no job-failure alert
    assert r.status == "offline"


def test_offline_by_class_and_by_words():
    assert jobs.offline(DNS) and jobs.offline(TimeoutError("x")) and jobs.offline(ConnectionResetError())
    assert jobs.offline("ConnectionError: HTTPSConnectionPool(host='x'): Max retries exceeded")
    assert not jobs.offline(ValueError("bad")) and not jobs.offline("KeyError: 'isin'")


def test_s79b_a_daily_job_that_lost_its_connection_is_offline_not_failed(tmp_path):
    """Found by the drills: collect/global/nav (Daily) were recorded failed when the laptop had no network: an alert per job and 'failed' on the World. Now 'offline': retried after the cooldown, no alert,
    and not counted as done for its slot."""
    import duckdb
    from datetime import datetime
    from pathlib import Path
    from pflab.pm import store
    from pflab.service import jobs
    from pflab.service.schedule import Daily
    con = duckdb.connect(":memory:")
    store.migrate(con)
    now = datetime(2026, 11, 9, 21, 0)
    ctx = jobs.Ctx(con, now, tmp_path, tmp_path, tmp_path)

    def down(c):
        raise ConnectionError("getaddrinfo failed")

    job = jobs.Job("downjob", Daily(20, 0), down)
    r = jobs.run_job(ctx, job)
    assert r.status == "offline" and r.detail.startswith("offline:")
    assert jobs.is_due(ctx, job)[0] is False                                           # cooling down, not hot-looping
    later = jobs.Ctx(con, datetime(2026, 11, 9, 21, 45), tmp_path, tmp_path, tmp_path)
    assert jobs.is_due(later, job)[0] is True                                           # and not done for the slot: it tries again

    job2 = jobs.Job("partsdown", Daily(20, 0), lambda c: {"failed": {"a": "ConnectionError: Max retries exceeded with url: /x", "b": "getaddrinfo failed"}})
    assert jobs.run_job(jobs.Ctx(con, datetime(2026, 11, 9, 22, 0), tmp_path, tmp_path, tmp_path), job2).status == "offline"
    job3 = jobs.Job("bug", Daily(20, 0), lambda c: {"failed": {"a": "KeyError: 'x'"}})
    assert jobs.run_job(jobs.Ctx(con, datetime(2026, 11, 9, 22, 5), tmp_path, tmp_path, tmp_path), job3).status == "failed"        # a bug is still a failure


def test_s79b_a_network_error_wrapped_in_another_error_is_still_offline():
    """Found by the drills: collect_daily re-raises the network error inside a RuntimeError; a real bug with other words is still a failure."""
    assert jobs.offline(RuntimeError("collect_daily: bhavcopy: ConnectionError: HTTPSConnectionPool(host='nsearchives.nseindia.com', port=443)"))
    assert jobs.offline(RuntimeError("no series downloaded: ConnectionError('getaddrinfo failed')"))
    assert not jobs.offline(RuntimeError("collect_daily: bhavcopy: KeyError: 'isin'"))
