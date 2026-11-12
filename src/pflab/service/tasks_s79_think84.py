"""S84 job `think_loop`: the thinking loop's single entry for the app's scheduler (T1/T7, A65). It watches every session that has not been watched (the India close, the US morning and any gap
since, each missed session once, point-in-time), thinks the new cases through up to the daily cap and runs the follow-up of the open cases (`pflab/think/wire.py`). It is due the moment the close
loop, the US step or the catch-up has finished (`service/ondemand.py`), never at a time the laptop must be on for. A failure inside it is a visible "thinking failed: ..." line, not a job failure;
the kill switch (`[core] kill`, `[think] on = false`) skips it."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _enabled(ctx):
    from pflab import core, think
    if core.killed():
        return False, "the kill switch is set (configs/core.toml [core] kill)"
    if not think.on():
        return False, "the thinking loop is OFF (configs/core.toml [think] on = false)"
    return True, ""


def _run(ctx) -> dict:
    from pflab.think import wire
    r = wire.sweep(ctx.con, ctx.now, ctx.data_root)
    if r.get("off"):
        return {"skipped": "switched off"}
    if r.get("skipped"):
        return {"skipped": r["skipped"]}
    out = {"sessions": r.get("sessions") or {}, "cases_opened": len(r.get("cases_opened") or []), "thought": len(r.get("thought") or [])}
    if r.get("failed"):                                     # visible in the job's detail and in the session log; not a job failure (the next pass tries again)
        out["thinking_problems"] = [str(x)[:200] for x in r["failed"][:4]]
    if not (out["sessions"] or out["thought"] or out.get("thinking_problems")):
        out["skipped"] = "nothing new to watch or think through"
    return out


register(Job("think_loop", Interval(30, weekdays_only=False), _run,
             "the thinking loop (S84): watch every unwatched session (India close, US morning, any gap, each once), think the new cases through up to 3 a day, follow up the open ones (paid parts inside his cap)",
             cooldown_minutes=15, enabled_fn=_enabled))
