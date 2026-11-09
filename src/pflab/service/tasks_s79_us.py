"""S81 B8 job `us_close`: the paper US sub-book's close (`pflab/us/adapter.close_us`) on the latest US session, in the IST morning or whenever the app is next open. Code only, free.
Skips while `[us] on = false` in configs/core.toml; the adapter itself says "waiting" when the US bars are not current and "skipped" when the session is already done."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _enabled(ctx):
    from pflab import core, us
    if core.killed():
        return False, "the kill switch is set (configs/core.toml [core] kill)"
    return (True, "") if us.on() else (False, "the paper US sub-book is OFF (configs/core.toml [us] on = false)")


def _run(ctx) -> dict:
    from pflab.us import adapter
    return adapter.close_us(ctx.con, ctx.now, ctx.data_root)


register(Job("us_close", Interval(120, weekdays_only=False), _run, "the paper US sub-book's close on the latest US session (S81; code, free; OFF until switched on)", cooldown_minutes=60, enabled_fn=_enabled))
