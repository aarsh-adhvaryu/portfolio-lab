"""S80 job `core_loop` (the v2 close loop, `pflab/core`): after the `paper` job has marked the book for a closed session, the champion policy decides the target weights, the
rails clip them and the orders are placed (code, free, seconds). Due when the paper job or the prices are newer than its last run (service/ondemand.py). Skips when
`[core] on = false` in configs/core.toml."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _enabled(ctx):
    from pflab import core
    return (True, "") if core.on() else (False, "switched off in configs/core.toml [core]")


def _run(ctx) -> dict:
    from pflab.core import loop
    return loop.run(ctx.con, ctx.now, ctx.data_root)


def _redo(ctx):
    try:
        marked = ctx.con.execute("SELECT max(day) FROM paper_days").fetchone()[0]
        mine = ctx.con.execute("SELECT max(day) FROM core_runs_s80").fetchone()[0]
        if marked is not None and (mine is None or mine < marked):
            return f"the book was marked {marked}, the loop ran to {mine}"
    except Exception:
        pass
    return None


ADVISOR_JOBS = ("review", "companion")            # the daily review's and the companion's proposals to him: advisor layers (the redesign retires them)


def _retire_advisor_jobs() -> None:
    """Wrap the advisor jobs' `enabled_fn` so they skip while `[core] advisors_off` holds (switched off, not deleted)."""
    from dataclasses import replace
    from pflab.service.jobs import REGISTRY
    for name in ADVISOR_JOBS:
        job = REGISTRY.get(name)
        if job is None:
            continue
        prev = job.enabled_fn

        def fn(ctx, _prev=prev):
            from pflab import core
            if core.advisors_off():
                return False, "advisor layer retired (S80): configs/core.toml [core] advisors_off"
            return _prev(ctx) if _prev else (True, "")
        REGISTRY[name] = replace(job, enabled_fn=fn)


_retire_advisor_jobs()

register(Job("core_loop", Interval(60, weekdays_only=False), _run,
             "the close loop: the champion policy's target weights, the rails, the paper orders (code, free, seconds)", cooldown_minutes=15, enabled_fn=_enabled, redo_fn=_redo))
