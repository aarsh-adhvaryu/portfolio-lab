"""S86b job `problems_week`: the Problems list (`service/problems.py`) is refreshed and ONE line a week goes to Telegram when the week had problems. Code only, free."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _run(ctx) -> dict:
    from pflab.service import problems, telegram as tgm
    n = problems.collect(ctx.con, ctx.now, 7)
    line = problems.weekly_line(ctx.con, ctx.now)
    if line:
        tgm.enqueue(ctx.con, line, "summary", dedup_key=f"problems:{ctx.now.isocalendar()[0]}-{ctx.now.isocalendar()[1]}", now=ctx.now)
    return {"problems": n, "told": bool(line)}


register(Job("problems_week", Interval(7 * 24 * 60, weekdays_only=False), _run, "the Problems list refreshed, one line a week on Telegram (S86b; code, free)", cooldown_minutes=60))
