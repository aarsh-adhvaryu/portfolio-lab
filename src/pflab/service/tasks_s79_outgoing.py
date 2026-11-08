"""S79b: the drop folder for messages to him is drained whenever the app is open (Interval 5 min; code, free)."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _outgoing(ctx) -> dict:
    from pflab.service import outgoing
    return {"queued": outgoing.drain(ctx.con, ctx.pm_dir, ctx.now)}


register(Job("outgoing", Interval(5, weekdays_only=False), _outgoing, "messages left in the drop folder (a development session's report) are queued on Telegram once (code, free)", cooldown_minutes=5))
