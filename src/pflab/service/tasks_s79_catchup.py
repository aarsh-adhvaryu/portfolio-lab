"""S79 item 3: the catch-up job. Due when prices or global data arrived (service/ondemand.py), so on open it runs as soon as the data jobs have; it waits for data
(a state shown on the World screen), never fails for it. Sends the one away digest once the catch-up has settled."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _catch_up(ctx) -> dict:
    from pflab.service import away, catchup
    from pflab.think import alarm
    alarm.first(ctx)                                    # S86: after a gap the alarm lane's backlog and the fast-forward come BEFORE the catch-up and the live book
    out = catchup.run(ctx.con, ctx.data_root, ctx.now)
    failed = {m: v["failed"] for m, v in out.items() if isinstance(v, dict) and "failed" in v}
    res: dict = {"markets": out}
    waiting = any("waiting" in v for v in out.values() if isinstance(v, dict))
    if not waiting and not failed:
        did = away.maybe_send(ctx.con, ctx.now)
        if did:
            res["digest"] = did
    if failed:
        res["failed"] = failed
    elif not any(isinstance(v, dict) and v.get("new") for v in out.values()) and "digest" not in res:
        # nothing was caught up this time: a run that did nothing is 'skipped', so the jobs that follow `catch_up` are not started again every 5 minutes (found by the drills)
        res["skipped"] = "waiting for the exchange's closes (data arrival)" if waiting else "nothing new to catch up"
        if waiting:
            res["waiting"], res["why"] = True, res["skipped"]
    return res


register(Job("catch_up", Interval(5, weekdays_only=False), _catch_up,
             "on open: each market's missed sessions scored in order by code, then the one 'while you were away' digest (code, free)", cooldown_minutes=5))
