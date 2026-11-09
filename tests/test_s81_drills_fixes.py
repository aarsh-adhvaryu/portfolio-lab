"""S81: fixes found by the drills (tools/drills_s81.py), each with the test that holds it. Synthetic data only; no paid call; no network."""
from __future__ import annotations

from datetime import datetime

import pytest

from pflab.lab import strategist
from pflab.pm import store

from tests.test_s80_core import DAYS, NOW as CORE_NOW, calm_index, con, con as core_con  # noqa: F401  (the synthetic book of the core tests)
from tests.test_s81_session import CCC, MON, bars_dir, db, run_day, write_bars  # noqa: F401  (the session tests' book, bars and replay)

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
def bare_con(tmp_path, monkeypatch):
    monkeypatch.setenv("PFLAB_PM_DIR", str(tmp_path))
    c = store.connect(tmp_path / "l.duckdb")
    c.execute("INSERT INTO core_policies_s80 (policy_id, status, code_hash, created_at, promoted_at) VALUES ('baseline_v1', 'champion', 'x', ?, ?)", [NOW, NOW])
    return c


def test_a_lab_close_with_the_sandbox_down_waits_and_says_why_instead_of_failing_and_alerting_him(bare_con, tmp_path, monkeypatch):
    """Drill docker_down (S81): with a challenger in shadow and Docker not running, `lab_close` raised SandboxUnavailable: the job was recorded failed and a Telegram 'job failed' went out
    at every 15-minute cooldown. Docker being down is a state to wait in: the job is skipped with the reason, is not started again every tick, and tries again after 15 minutes."""
    from datetime import timedelta

    con = bare_con
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


def test_a_strategist_session_with_no_cloud_client_waits_and_says_why_instead_of_failing_the_job(bare_con, tmp_path):
    """The workshop's paid-call guard (or a missing key) used to raise out of `tick` before the session's own budget check: the `strategist` job was recorded failed and a Telegram
    alert went out at every cooldown. Now the job is skipped with the reason."""
    from pflab import guard
    con = bare_con

    def no_client():
        raise guard.OutwardBlocked("the workshop (beta channel) does not send outward: run it with the global --paid flag")
    out = strategist.tick(con, tmp_path, None, NOW, no_client)
    assert out["reasons"] and "skipped" in out and "no cloud client" in out["skipped"] and "OutwardBlocked" in out["skipped"]
    assert "session" not in out
    assert con.execute("SELECT count(*) FROM core_sessions_s80").fetchone()[0] == 0          # nothing was started, nothing half-recorded


def test_a_sale_at_a_loss_after_gains_booked_this_year_fills_with_no_negative_tax(core_con):
    """Merged-tree drill (S81): a stop-loss sale after an earlier taxed gain in the same year adds a NEGATIVE tax (the loss sets off the gain). The ledger's `charge` refuses a negative amount, so the
    fill raised, the `paper` job failed on every run and the loop waited for orders that never filled. The tax is now floored at 0 (no refund is booked: the estimate stays cautious)."""
    from datetime import time
    from pflab.paper import book
    from tests.test_s80_core import BBB, GLD
    d = DAYS[-2]
    core_con.execute("UPDATE prices SET close = 20.0 WHERE isin = ? AND date = ?", [BBB, d])           # BBB bought at 40, now 20: a loss
    at = datetime.combine(d, time(10, 0))
    book.place(core_con, at, None, GLD, "sell", qty=2000.0)                                              # a long-term gain on the gold ETF: taxed
    book.place(core_con, at, None, BBB, "sell", qty=3000.0)                                              # then the loss, which sets it off
    done = book.fill(core_con, DAYS[-1], datetime.combine(DAYS[-1], time(21, 0)))
    assert len(done) == 2 and core_con.execute("SELECT count(*) FROM paper_orders WHERE status='open'").fetchone()[0] == 0
    taxes = dict(core_con.execute("SELECT isin, tax FROM paper_trades WHERE side='sell'").fetchall())
    assert taxes[GLD] > 0 and taxes[BBB] == 0.0


def test_the_graph_and_us_jobs_skip_softly_when_their_inputs_are_absent(bare_con, tmp_path, monkeypatch):
    """Merged-tree drill (S81): on a data folder without the graph's raw inputs `kg2_nightly` and `news_s81_topup` raised FileNotFoundError and were recorded failed (and alerted) at every
    cooldown. They skip with the reason. `us_close` waits for its bars and `us_prices_daily` with no network is `offline`, never `failed`."""
    from datetime import datetime as _dt
    from pflab.data import us_prices
    from pflab.service import jobs, tasks  # noqa: F401
    data = tmp_path / "data"
    data.mkdir()
    ctx = jobs.Ctx(bare_con, _dt(2026, 11, 9, 12, 0), tmp_path, data, tmp_path)
    for name in ("kg2_nightly", "news_s81_topup"):
        r = jobs.run_job(ctx, jobs.REGISTRY[name])
        assert r.status == "skipped" and "raw inputs" in r.detail, (name, r)
    r = jobs.run_job(ctx, jobs.REGISTRY["us_close"])
    assert r.status in ("ok", "skipped") and ("waiting" in r.detail or "skipped" in r.detail), r
    monkeypatch.setattr(us_prices, "collect", lambda syms, root, recent_days=10: {s: "ConnectionError: HTTPSConnectionPool(host='query1.finance.yahoo.com'): getaddrinfo failed" for s in syms})
    r = jobs.run_job(ctx, jobs.REGISTRY["us_prices_daily"])
    assert r.status in ("offline", "skipped"), r


def test_a_swing_trigger_stop_and_target_become_the_exit_plans_levels(db, bars_dir, tmp_path):
    """Merged-tree drill (S81): the session loop handed the exit manager `stop_price` / `target_price`, whose override keys are `stop` and `target`: the trigger's own levels were
    ignored and the plan carried the defaults. Both names are passed now."""
    from datetime import datetime as _dt
    from pflab.core import session
    session.add_trigger(db, _dt(2026, 10, 30, 16, 0), CCC, "above", 101.0, amount=50000.0, valid_from=MON, stop_price=97.0, target_price=111.0, reason="breakout above its range")
    write_bars(bars_dir, "CCC", 100.0, {MON: lambda i: 100.0 if i < 3 else 102.0})
    run_day(db, MON, bars_dir, tmp_path, isins=[CCC])
    plan = db.execute("SELECT sleeve, stop, target FROM exit_plans_s81 WHERE isin=? ORDER BY plan_id DESC LIMIT 1", [CCC]).fetchone()
    assert plan is not None and plan[0] == "swing" and plan[1] == 97.0 and plan[2] == 111.0


def test_what_the_exit_manager_trades_counts_against_the_days_turnover_cap_and_the_rebalance_gives_way(core_con):
    """Merged-tree drill (S81): the exit manager's sales (a harvest, a trim) were added AFTER the rails and were never counted, so a close traded 15% of the book against a 10% daily cap
    (and 73% in a month against 40%). `rails.check(used=...)` now takes the cap net of what the exit manager already trades: it is never cut by the cap, the rebalance is."""
    from pflab.core import rails, state as st
    from tests.test_s80_core import AAA, BBB, GLD, calm_index
    s = st.build(core_con, DAYS[-1], None, calm_index())
    s["cfg"]["rails"]["max_cost_share"] = 1.0
    zero = {"weights": {AAA: 0.0, BBB: 0.0, GLD: 0.0}}
    free = rails.check(core_con, s, zero)
    net = rails.check(core_con, s, zero, used=0.06 * s["value"])
    assert sum(o["value"] for o in free["orders"]) <= 0.10 * s["value"] + 1.0
    assert sum(o["value"] for o in net["orders"]) <= 0.04 * s["value"] + 1.0 and net["orders"]
    assert not rails.check(core_con, s, zero, used=0.5 * s["value"])["orders"]                     # the exits alone used the whole day: the rebalance waits
