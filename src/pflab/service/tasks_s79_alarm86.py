"""S86 job `alarm`: the alarm lane (`pflab/think/alarm.py`, A73). Every 15 minutes, day and night, both markets, while the app is open: fast headlines on what the book is exposed to, classified by
code, the serious ones heard on Telegram and thought through at once. Code only and free until a case is thought through. The pass runs on its OWN thread (the scheduler thread is shared with the
5-minute session loop and is never held); after a gap the backlog pass runs first from `catch_up` and `think_loop` (`alarm.first`). The kill switch and `[think] alarm = false` skip it."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _enabled(ctx):
    from pflab.think import alarm
    return (True, "") if alarm.on() else (False, "the alarm lane is OFF (configs/core.toml [think] alarm = false, or the kill switch)")


def _run(ctx) -> dict:
    from pflab.think import alarm
    try:
        return alarm.start_background(ctx.con, ctx.now, ctx.data_root)
    except Exception as e:                       # visible, never a failed job: the next pass asks again
        return {"problems": [f"alarm: {type(e).__name__}: {str(e)[:160]}"]}


register(Job("alarm", Interval(15, weekdays_only=False), _run, "the alarm lane: fast headlines on the names the book is exposed to, serious ones heard on Telegram and thought through at once (S86; code, free)",
             cooldown_minutes=5, enabled_fn=_enabled))
