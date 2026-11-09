"""The critic's overnight audit (2026-10-30), findings 2-8: Pause holds every autonomous start; the picture is not complete while the record
disagrees with the statements; a long job is not a sleep and a wake settles only on current prices; the hour counts work that finished well;
the learner says when it failed; a decision is traded at the next session; an old option chain is not today's. Synthetic."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from pflab.hq import board
from pflab.hq.desk import Desk
from pflab.pm import store

NOW = datetime(2026, 10, 30, 23, 0)


@pytest.fixture
def con(tmp_path):
    return store.connect(tmp_path / "l.duckdb")


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


# --- 2. Pause ---------------------------------------------------------------------------------------------------------------------------------

def test_the_scheduled_tick_runs_nothing_while_paused(tmp_path, monkeypatch):
    from pflab.app import settings as st
    from pflab.hq import desk, service
    from pflab.service import runner
    pm = tmp_path / "pm"
    pm.mkdir()
    st.save(pm, {"scheduler": False}, st.load(pm))
    assert runner.unattended_jobs(pm) == []
    monkeypatch.setattr(desk, "from_ctx", lambda ctx: Desk(None, pm, tmp_path, tmp_path, None, {"preset": "full", "scheduler": False}))
    assert service.tick_job(object()) == {"skipped": True, "why": "paused"}
    st.save(pm, {"scheduler": True}, st.load(pm))
    assert runner.unattended_jobs(pm)


# --- 3. completeness ----------------------------------------------------------------------------------------------------------------------------

def test_the_picture_stays_partial_while_a_ledger_difference_is_open(con):
    from pflab.app import readiness
    from pflab.ingest import coverage as cv
    con.execute("INSERT INTO accounts (account_id, kind, provider, dp_or_folio) VALUES ('SBI_9001', 'bank', 'SBI', '00009001')")
    con.execute("INSERT INTO statement_periods (account_id, kind, file_sha, first_date, last_date, n_rows, built_at) VALUES "
                "('SBI_9001', 'bank', 'sha', ?, ?, 10, ?)", [date(2026, 4, 1), date(2026, 10, 25), NOW])
    cv.note_account(con, {"kind": "bank", "bank": "SBI", "last4": "9001", "dp_ids": None}, "a file you dropped", NOW, "a")
    cv.confirm_inventory(con, NOW)
    assert cv.status(con, NOW)["label"] == "complete"
    readiness.open_gap(con, "ledger:diff:bank-balance", "ledger", "bank balance: 120.00 apart", NOW)
    s = cv.status(con, NOW)
    assert s["label"] == "partial" and any("difference" in r for r in s["reasons"])
    readiness.close_gap(con, "ledger:diff:bank-balance", NOW)
    assert cv.status(con, NOW)["label"] == "complete"


# --- 4 and 5. sleep, freshness, the hour -----------------------------------------------------------------------------------------------------------

def _rt(con, tmp_path, clock):
    from pflab.app import runtime
    (tmp_path / "pm").mkdir(exist_ok=True)
    return runtime.Runtime(tmp_path / "pm", tmp_path / "data", tmp_path, con=con, clock=clock)


def test_the_heart_has_its_own_thread_so_a_long_job_is_not_taken_for_a_sleep(con, tmp_path):
    from pflab.app import runtime
    rt = _rt(con, tmp_path, Clock(NOW))
    src = open(runtime.__file__, encoding="utf-8").read()
    loop = src[src.index("def _scheduler_loop"):src.index("def _ctx")]
    assert "self.beat()" not in loop                                                       # the scheduler no longer beats: a job it runs cannot delay the beat
    assert hasattr(rt, "_heart_loop") and runtime.HEART_EVERY_S * 2 < runtime.WAKE_GAP.total_seconds()


def test_a_wake_whose_prices_never_come_is_recorded_blocked_and_the_verifier_does_not_pass_it(con, tmp_path):
    from pflab import verify
    clock = Clock(NOW)
    rt = _rt(con, tmp_path, clock)
    rt.beat()
    clock.t = NOW + timedelta(hours=3)                                                     # slept three hours
    assert rt.beat().startswith("woke after")
    clock.t += timedelta(hours=1)
    rt._beat = clock.t - timedelta(seconds=30)                                             # the heart kept beating meanwhile
    assert rt.beat() is not None                                                           # no prices yet: still catching up, never "settled"
    hb = json.loads((tmp_path / "pm" / "app" / "heartbeat.json").read_text(encoding="utf-8"))
    assert "settled_at" not in hb["last_wake"]
    clock.t += timedelta(hours=1, minutes=5)                                               # past the limit: blocked, with what failed
    rt._beat = clock.t - timedelta(seconds=30)
    assert rt.beat() is None
    hb = json.loads((tmp_path / "pm" / "app" / "heartbeat.json").read_text(encoding="utf-8"))
    assert hb["last_wake"]["blocked_at"] and "no prices" in hb["last_wake"]["blocked_by"] and "settled_at" not in hb["last_wake"]
    ctx = verify.Ctx(tmp_path, tmp_path, tmp_path / "pm", tmp_path / "data", clock.t, tmp_path / "t")
    rep = verify.Report()
    verify.wake_check(ctx, rep)
    assert rep.checks[-1].status == verify.FAIL and "not current" in rep.checks[-1].detail


def test_the_hour_counts_jobs_that_finished_well_and_names_the_failures(con, tmp_path):
    from pflab import verify
    rt = _rt(con, tmp_path, Clock(NOW))
    for i, (job, status) in enumerate([("collect", "skipped"), ("prices", "skipped"), ("learner", "failed"), ("kg", "ok")], 1):
        con.execute("INSERT INTO job_runs (run_id, job, slot, started_at, finished_at, status) VALUES (?,?,?,?,?,?)", [i, job, NOW, NOW, NOW, status])
    rt._write_beat(NOW, None)
    hb = json.loads((tmp_path / "pm" / "app" / "heartbeat.json").read_text(encoding="utf-8"))
    assert hb["jobs_last_hour"] == 1 and hb["failed_last_hour"] == ["learner"] and hb["paused"] is False
    ctx = verify.Ctx(tmp_path, tmp_path, tmp_path / "pm", tmp_path / "data", NOW, tmp_path / "t")

    def check(**kw):
        p = tmp_path / "pm" / "app" / "heartbeat.json"
        p.write_text(json.dumps({"at": NOW.isoformat(), "pid": os.getpid(), "since": (NOW - timedelta(minutes=70)).isoformat(), "max_gap_s": 40,
                                 **kw}), encoding="utf-8")
        rep = verify.Report()
        verify.hour_check(ctx, rep)
        return rep.checks[-1]
    assert check(jobs_last_hour=0).status == verify.FAIL                                   # skips only: alive, not working
    c = check(jobs_last_hour=3, failed_last_hour=["learner"])
    assert c.status == verify.FAIL and "learner" in c.detail
    assert check(jobs_last_hour=3, paused=True).status == verify.NEEDS
    c = check(jobs_last_hour=3, failed_last_hour=[])
    assert c.status == verify.PASS and "uptime" in c.detail and "work" in c.detail


# --- 6. the learner -------------------------------------------------------------------------------------------------------------------------------

def test_the_learner_fails_when_a_step_did_not_run_and_is_partial_when_an_experiment_waits_for_data():
    from pflab.learner import run
    ok = run.health({"forward": {"formed": 1}, "experiment": {"idle": "no experiment is registered"}, "tested": {}})
    assert "failed" not in ok and "partial" not in ok
    bad = run.health({"forward": "not run: KeyError: 'close'", "tested": {3: "not run: ValueError: x"}, "experiment": {"idle": "x"}})
    assert set(bad["failed"]) == {"forward", "test 3"}
    box = run.health({"experiment": {"experiment": 2, "status": "waiting", "why": "the sandbox is not running"}})
    assert "experiment" in box["failed"]
    data = run.health({"experiment": {"experiment": 2, "status": "waiting", "why": "not enough history"}})
    assert "failed" not in data and "not enough history" in data["partial"]


# --- 8. options -------------------------------------------------------------------------------------------------------------------------------------

def test_an_old_session_or_an_expired_contract_is_no_current_data(tmp_path):
    from pflab.quant import implied, options
    d = tmp_path / "derived"
    d.mkdir()
    pd.DataFrame({"date": pd.to_datetime([date(2026, 9, 1)]), "atm_iv": [0.14], "pcr": [1.1], "fut_premium_ann": [0.06]}).to_parquet(d / "fo_index.parquet")
    assert options.summary(tmp_path, date(2026, 10, 30)) is None
    assert "no current data" in options.line(tmp_path, date(2026, 10, 30))
    assert options.summary(tmp_path, date(2026, 9, 3))["pcr"] == 1.1                   # two days later it is current
    pd.DataFrame({"date": [date(2026, 10, 29)], "expiry": [date(2026, 10, 28)], "days": [0], "p_below_10": [0.05], "p_below_5": [0.1],
                  "p_above_5": [0.1]}).to_parquet(d / implied.FILE)
    assert implied.latest(tmp_path, date(2026, 10, 30)) is None                            # its contract has expired
    pd.DataFrame({"date": [date(2026, 10, 29)], "expiry": [date(2026, 11, 25)], "days": [27], "p_below_10": [0.05], "p_below_5": [0.1],
                  "p_above_5": [0.1]}).to_parquet(d / implied.FILE)
    assert implied.latest(tmp_path, date(2026, 10, 30))["expiry"] == "2026-11-25"
    pd.DataFrame({"date": pd.to_datetime([date(2026, 9, 1)]), "symbol": ["AAA"], "class": ["long build-up"], "price_change": [0.01],
                  "oi_change_pct": [0.1]}).to_parquet(d / "fo_buildup.parquet")
    assert options.buildup_for(tmp_path, date(2026, 10, 30), ["AAA"]) == {}


def test_the_fall_limit_simulation_leaves_out_what_it_cannot_model_and_a_failure_shows_as_failed(monkeypatch, tmp_path):
    """2026-10-31: an unclassified holding (0.3%) made the weights sum to 0.9971 and the simulation crashed every minute, shown as 'nothing yet'."""
    from pflab.app import sims, system
    from pflab.pm import today
    monkeypatch.setattr(today, "build", lambda con, asof: {"buckets": {"equity": 30.0, "gold": 10.0, "debt": 59.0, "review": 1.0}})
    m = sims.current_mix(None, date(2026, 10, 31))
    assert abs(sum(m.values()) - 1) < 1e-12 and sims.weights(m).sum() == pytest.approx(1.0)
    assert sims.left_out(None, date(2026, 10, 31)) == {"review": 1.0}
    src = open(system.__file__, encoding="utf-8").read()
    assert "rows[-1].update(state=DOWN, line=f\"failed: {err}\"" in src                         # the screen says failed, with the reason


def test_the_hq_row_shows_the_hq_threads_own_rounds_not_a_job_that_never_runs(con, tmp_path):
    """2026-10-31: with the window open the HQ runs every 30 s on its own thread; its job row said 'due' forever and looked stuck."""
    from pflab.app import world
    rt = _rt(con, tmp_path, Clock(NOW))
    rt.hq_last_round = (NOW, [])
    row = next(j for j in world.jobs_view(rt, NOW) if j["job"] == "hq")
    assert row["state"] == "ok" and row["done_today"] and "30 s" in row["when"]
    rt.hq_last_round = (NOW, ["readers"])
    row = next(j for j in world.jobs_view(rt, NOW) if j["job"] == "hq")
    assert row["state"] == "down" and "readers" in row["why"]


@pytest.fixture(autouse=True)
def _v1_advisor_layers(monkeypatch):
    """S80 switches the v1 advisor layers off by default (`configs/core.toml`); these tests are about the v1 hq round, so they run with the close loop off."""
    from pflab import core
    real = core.settings
    monkeypatch.setattr(core, "settings", lambda: {**real(), "core": {**real()["core"], "on": False, "advisors_off": False, "retire_missions": False}})
