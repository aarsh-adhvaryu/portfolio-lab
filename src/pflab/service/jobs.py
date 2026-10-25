"""Job engine: run a job under a lock, record it, decide what is due, catch up after sleep (PLAN S9).

`tick` is the only entry point Task Scheduler needs: it runs every job whose latest slot has no
success since, once each. A failed job is not retried for `cooldown_minutes` (no hot loop); a job
whose run died with the process is marked abandoned after `ABANDON_AFTER`. Jobs are idempotent
(re-running them is safe) and report what they did in a small dict.
"""
from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic as _monotonic
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from pflab._lock import FileLock, LockBusy
from pflab.service.schedule import Daily, Interval

ABANDON_AFTER = timedelta(hours=2)


@dataclass
class Ctx:
    con: Any
    now: datetime
    pm_dir: Path
    data_root: Path
    repo: Path
    python: str = "python"
    secrets: Any = None                      # a pflab.pm.secrets.Secrets or None
    extra: Dict[str, Any] = field(default_factory=dict)

    def lookback_days(self, job: str, minimum: int = 3, cap: int = 40) -> int:
        """Days to look back: since the last success, plus a margin, between `minimum` and `cap`."""
        last = last_success(self.con, job)
        if last is None:
            return cap
        return max(minimum, min(cap, (self.now - last).days + 2))


@dataclass(frozen=True)
class Job:
    name: str
    schedule: Union[Daily, Interval]
    fn: Callable[[Ctx], dict]
    description: str = ""
    cooldown_minutes: int = 30
    enabled_fn: Optional[Callable[[Ctx], Tuple[bool, str]]] = None


@dataclass(frozen=True)
class RunResult:
    job: str
    status: str                  # ok | failed | skipped
    detail: str
    run_id: Optional[int] = None


REGISTRY: Dict[str, Job] = {}


def register(job: Job) -> Job:
    REGISTRY[job.name] = job
    return job


# --- state ----------------------------------------------------------------------------------------------

def last_success(con, job: str) -> Optional[datetime]:
    r = con.execute("SELECT max(started_at) FROM job_runs WHERE job=? AND status='ok'", [job]).fetchone()[0]
    return r


def _redact(ctx: Ctx, text: str) -> str:
    return ctx.secrets.redact(text) if ctx.secrets is not None else text


def reap_abandoned(con, now: datetime) -> int:
    """A `running` row older than ABANDON_AFTER belongs to a process that died: mark it failed."""
    rows = con.execute("SELECT run_id FROM job_runs WHERE status='running' AND started_at < ?",
                       [now - ABANDON_AFTER]).fetchall()
    for (rid,) in rows:
        con.execute("UPDATE job_runs SET status='failed', finished_at=?, detail='abandoned: the process died' "
                    "WHERE run_id=?", [now, rid])
    return len(rows)


def is_due(ctx: Ctx, job: Job) -> Tuple[bool, str]:
    if job.enabled_fn is not None:
        ok, why = job.enabled_fn(ctx)
        if not ok:
            return False, f"disabled: {why}"
    slot = job.schedule.latest_slot(ctx.now)
    if slot is None:
        return False, "no slot yet"
    done = ctx.con.execute("SELECT 1 FROM job_runs WHERE job=? AND status IN ('ok','skipped') AND started_at >= ? LIMIT 1",
                           [job.name, slot]).fetchone()
    if done:
        return False, f"done for slot {slot:%Y-%m-%d %H:%M}"
    cool = ctx.con.execute("SELECT max(started_at) FROM job_runs WHERE job=? AND status IN ('failed','running') "
                           "AND started_at >= ?", [job.name, slot]).fetchone()[0]
    if cool is not None and ctx.now - cool < timedelta(minutes=job.cooldown_minutes):
        return False, f"cooling down after a failed or running attempt at {cool:%H:%M}"
    return True, f"due for slot {slot:%Y-%m-%d %H:%M}"


# --- run ----------------------------------------------------------------------------------------------------

def run_job(ctx: Ctx, job: Job, slot: Optional[datetime] = None) -> RunResult:
    """Run one job now, under its lock, recording the outcome. Never raises for a job's own failure."""
    con = ctx.con
    if job.enabled_fn is not None:
        ok, why = job.enabled_fn(ctx)
        if not ok:
            return RunResult(job.name, "skipped", f"disabled: {why}")
    lock = FileLock(ctx.pm_dir / "locks" / f"{job.name}.lock", job.name)
    try:
        lock.__enter__()
    except LockBusy as e:
        return RunResult(job.name, "skipped", str(e))
    from pflab.pm.store import next_id
    rid = next_id(con, "job_runs", "run_id")
    slot = slot or job.schedule.latest_slot(ctx.now)
    con.execute("INSERT INTO job_runs VALUES (?,?,?,?,?,?,?)", [rid, job.name, slot, ctx.now, None, "running", None])
    t0 = _monotonic()
    done = lambda: ctx.now + timedelta(seconds=round(_monotonic() - t0, 3))   # S58: the real finish (ctx.now is the tick's)
    try:
        out = job.fn(ctx) or {}
        detail = json.dumps(out, default=str, sort_keys=True)
        status = "skipped" if out.get("skipped") else "ok"
        con.execute("UPDATE job_runs SET status=?, finished_at=?, detail=? WHERE run_id=?",
                    [status, done(), detail, rid])
        return RunResult(job.name, status, detail, rid)
    except Exception as e:   # a job failing is recorded, never fatal to the tick
        msg = _redact(ctx, f"{type(e).__name__}: {e}")
        con.execute("UPDATE job_runs SET status='failed', finished_at=?, detail=? WHERE run_id=?", [done(), msg, rid])
        return RunResult(job.name, "failed", msg, rid)
    finally:
        lock.__exit__(None, None, None)


# S58b (The investor 2026-10-24: the system works then and there, not only at its times): a job that brought something new
# starts the jobs that use it at once. Schedules stay for when the data appears (NSE's files after the close, AMFI's
# NAVs at night); what follows from new data does not wait for its own slot.
FOLLOWS = {"collect": ("prices",), "prices": ("guards", "plans"), "nav": ("plans",)}


def followers(r: RunResult) -> List[str]:
    """The jobs to start now because `r` finished with something new."""
    if r.status != "ok":
        return []
    out = list(FOLLOWS.get(r.job, ()))
    try:
        d = json.loads(r.detail or "{}")
    except ValueError:
        d = {}
    if r.job == "filings" and d.get("alerts_queued"):        # a material filing on a held or watched name
        out.append("research")
    if r.job == "research" and d.get("opus_queued"):         # notes for Opus: submitted now, not at 1 AM
        out.append("analyst")
    return out


def tick(ctx: Ctx, only: Optional[List[str]] = None) -> List[RunResult]:
    """Run everything due, once each, in registry order."""
    reap_abandoned(ctx.con, ctx.now)
    out = []
    for name, job in REGISTRY.items():
        if only and name not in only:
            continue
        due, _why = is_due(ctx, job)
        if due:
            out.append(run_job(ctx, job))
    return out


def plan(ctx: Ctx) -> List[dict]:
    """What a tick would do right now, per job, with the reason."""
    rows = []
    for name, job in REGISTRY.items():
        due, why = is_due(ctx, job)
        rows.append({"job": name, "due": due, "why": why, "last_success": last_success(ctx.con, name),
                     "schedule": job.schedule})
    return rows
