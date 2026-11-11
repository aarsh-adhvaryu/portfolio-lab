"""S82 C8 job `fills_calibrate`: refits the fill-cost model (`core/fills.py [fills]`: the two half spreads and the impact) from the session's REAL fills (`core/fills_cal.py`).

Free (code, no model). It waits, saying "waiting: N of 30 real fills", until 30 real fills from live Kite quotes exist; then it fits at once and again at most monthly. The job's own cheap
check runs every few hours whenever the app is open, so a missed day costs nothing (A42: no waiting on a schedule). It skips under the kill switch or `[core] on = false`.
"""
from __future__ import annotations

from pflab.service.jobs import Ctx, Job, register
from pflab.service.schedule import Interval


def _enabled(ctx: Ctx):
    from pflab import core
    if core.killed():
        return False, "the kill switch is set (configs/core.toml [core] kill)"
    return (True, "") if core.on() else (False, "switched off in configs/core.toml [core]")


def _calibrate(ctx: Ctx) -> dict:
    from pflab.core import fills_cal
    return fills_cal.run(ctx.con, ctx.now, "IN")


register(Job("fills_calibrate", Interval(180, weekdays_only=False), _calibrate,
             "refits the fill-cost model (spread and impact) from the real session fills once 30 exist, then monthly (code, free); until then the defaults stand and it says how many fills it has",
             cooldown_minutes=60, enabled_fn=_enabled))
