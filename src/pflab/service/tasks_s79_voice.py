"""S79 item 6: the voice job. Due whenever the app is open (Interval 5 minutes, every day): defaults whose deadline passed become final; held questions go out."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _voice(ctx) -> dict:
    from pflab.agents import voice
    return voice.sweep(ctx.con, ctx.now)


register(Job("voice", Interval(5, weekdays_only=False), _voice, "questions: defaults whose deadline passed become final; held questions go out within the daily cap (code, free)", cooldown_minutes=5))
