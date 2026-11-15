"""S91 job `investigation_daily`: the day's first saved study (a co-movement study of two of his holdings, code only) once today's complete Kite snapshot is in. Waits, with a stated reason,
before that; never runs twice in a day (`app/investigation.py`)."""
from __future__ import annotations

from pflab.service.jobs import Ctx, Job, register
from pflab.service.schedule import Interval

_RT = {"rt": None}


def bind(rt) -> None:
    _RT["rt"] = rt


def _run(ctx: Ctx) -> dict:
    from types import SimpleNamespace
    from pflab.app import investigation
    rt = _RT["rt"] or SimpleNamespace(data_root=ctx.data_root, bump=lambda *a: None)
    return investigation.run(rt, ctx.con, ctx.now)


register(Job("investigation_daily", Interval(15, weekdays_only=False), _run,
             "S91: the day's first saved study (a co-movement test of two of his holdings, code only, 0 tokens) once today's Kite snapshot is in; kept with its data period and artifact",
             cooldown_minutes=10))
