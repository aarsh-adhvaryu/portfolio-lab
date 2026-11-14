"""S87 jobs: `operator_build` (new failures on the Problems list become build requests; one queued build at a time runs to a Yes/No card, at most 2 a day) and `operator_weekly` (the weekly
introspection after the Friday close). Both run only while the plan engine is in use and the plan is signed in; a plan limit makes them wait, never fail."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _enabled(ctx):
    from pflab.llm import claude_plan as cp, gateway as gw
    if gw.current_engine(ctx.con) != "claude_plan" or not cp.settings()["enabled"]:
        return False, "the plan engine is not in use ([engines] force_in_use)"
    return True, ""


def _build(ctx) -> dict:
    from pflab.llm import claude_plan as cp
    from pflab.oper import build
    n = build.scan_problems(ctx.con, ctx.now)
    if cp.paused_until(ctx.con, ctx.now):
        return {"requested": n, "skipped": "thinking is paused (plan limit)"}
    r = build.run_pending(ctx.con, ctx.now)
    return {"requested": n, **({"build": r} if r else {"skipped": "no queued build"})}


def _weekly(ctx) -> dict:
    from pflab.oper import introspect
    if not introspect.due(ctx.con, ctx.now):
        return {"skipped": "written for this week"}
    return introspect.run(ctx.con, ctx.now)


register(Job("operator_build", Interval(30, weekdays_only=False), _build, "S87 O4: new Problems become build requests; one queued build runs on a fix/ branch to a Yes/No card (max 2 a day)",
             cooldown_minutes=20, enabled_fn=_enabled))
register(Job("operator_weekly", Interval(60, weekdays_only=False), _weekly, "S87 O3/O5: the weekly introspection after the Friday close: what worked, what did not, calibration, what to test next",
             cooldown_minutes=50, enabled_fn=_enabled))
