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


register(Job("core_loop", Interval(60, weekdays_only=False), _run,
             "the close loop: the champion policy's target weights, the rails, the paper orders (code, free, seconds)", cooldown_minutes=15, enabled_fn=_enabled, redo_fn=_redo))
