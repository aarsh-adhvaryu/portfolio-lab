"""S86 job `us_session`: the US session loop (`pflab/core/us_session.py`, A77, H4). Every 5 minutes while the app is open (the loop itself looks at pre-market and after-hours only every 15 and does
nothing while the US market is closed): live quotes with their delay, the watch on live quotes, and in regular hours the stops, a case's sale or trim, a reserve buy part and the morning plan's pending
orders at the first quote after the decision. Switch: configs/core.toml [us] session_loop. A closed laptop in US hours keeps the old path (the next open). Bounded: 8 seconds a quote."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _enabled(ctx):
    from pflab.core import us_session
    return (True, "") if us_session.on() else (False, "the US session loop is OFF (configs/core.toml [us] session_loop = false, or [us] on = false, or the kill switch)")


def _run(ctx) -> dict:
    from pflab.core import us_session
    r = us_session.tick(ctx.con, ctx.now, ctx.data_root)
    if r.get("off") or r.get("skipped"):
        return {"skipped": r.get("skipped") or "switched off"}
    return {k: r[k] for k in ("phase", "quotes", "median_delay_min", "signals", "cases", "fills", "stops", "problems") if k in r}


register(Job("us_session", Interval(5, weekdays_only=False), _run, "the US session loop: live quotes with their delay, the watch, stops and fills at the first quote after the decision (S86; code, free)",
             cooldown_minutes=2, enabled_fn=_enabled))
