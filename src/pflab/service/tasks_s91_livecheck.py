"""S91 job `live_check`: the trading day's automatic acceptance check (`app/livecheck.py`), every 10 minutes between 09:20 and 16:00 once Kite is logged in. Code only."""
from __future__ import annotations

from pflab.service.jobs import Ctx, Job, register
from pflab.service.schedule import Interval


def _run(ctx: Ctx) -> dict:
    from types import SimpleNamespace
    from pflab.app import livecheck
    from pflab.service import tasks_s91_investigation as inv
    rt = inv._RT["rt"] or SimpleNamespace(data_root=ctx.data_root, bump=lambda *a: None)
    return livecheck.run(rt, ctx.con, ctx.now)


register(Job("live_check", Interval(10, start_hour=9, end_hour=16, weekdays_only=True), _run,
             "S91: the trading day's automatic check once Kite is logged in: release, holdings snapshot, operator, new closed candles, no failed job, the day's saved study; told once in the chat",
             cooldown_minutes=7))
