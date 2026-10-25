"""Glue for the command line and Task Scheduler: build the context, tick, tell Telegram about failures."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from pflab.data import data_dir
from pflab.pm import secrets as sec
from pflab.pm import store
from pflab.service import jobs, tasks  # noqa: F401  (tasks registers the jobs on import)
from pflab.service import telegram as tgm


def make_ctx(con=None, now: Optional[datetime] = None, secrets=None) -> jobs.Ctx:
    if secrets is None:
        try:
            secrets = sec.load()
        except sec.SecretsError:
            secrets = None
    return jobs.Ctx(con if con is not None else store.connect(), now or datetime.now(), store.pm_dir(), data_dir(),
                    Path(__file__).resolve().parents[3], sys.executable, secrets)


def dashboard_running(pm_dir: Path) -> Optional[str]:
    """The dashboard's lock holder ("pid started-at") while it runs, else None. While it is open it runs the jobs
    itself and holds the ledger, so the scheduled tick stands aside (S58b switch-on)."""
    from pflab._lock import _alive
    p = Path(pm_dir) / "app" / "app.lock"
    try:
        prev = p.read_text(encoding="utf-8").strip() if p.exists() else ""
    except OSError:
        return None
    return prev if prev and _alive(prev.split()[0]) else None


def unattended_jobs(pm_dir: Path) -> List[str]:
    """The jobs a tick may run: the dashboard's settings decide for it too (its preset's jobs; the outbox only when
    Telegram is switched on in Settings), so one switch holds or sends messages whether the window is open or not."""
    from pflab.app import settings as st
    s = st.load(Path(pm_dir))
    return [j for j in st.jobs_for(s.get("preset", "full"), jobs.REGISTRY) if j != "outbox" or s.get("telegram_send")]


def tick_and_notify(ctx: jobs.Ctx, only: Optional[List[str]] = None, send=None) -> List[jobs.RunResult]:
    """Run what is due; queue a Telegram message for each failed job (once per run); try to deliver the outbox."""
    results = jobs.tick(ctx, only)
    done = {r.job for r in results}                  # S58b: what the new data feeds runs in the same tick
    queue = [f for r in results for f in jobs.followers(r)]
    while queue:
        name = queue.pop(0)
        if name in done or name not in jobs.REGISTRY or (only is not None and name not in only):
            continue
        done.add(name)
        r = jobs.run_job(ctx, jobs.REGISTRY[name])
        results.append(r)
        queue += jobs.followers(r)
    for r in results:
        if r.status == "failed" and r.job != "outbox":
            tgm.enqueue(ctx.con, tgm.format_job_failure(r.job, r.detail, ctx.now), "job_failure",
                        dedup_key=f"jobfail:{r.run_id}", now=ctx.now)
    if only is None or "outbox" in only:
        try:
            tgm.flush(ctx.con, send or tgm.make_sender(ctx.secrets), ctx.now)
        except Exception:
            pass                      # an undeliverable outbox shows on the health page; it must not break the tick
    return results
