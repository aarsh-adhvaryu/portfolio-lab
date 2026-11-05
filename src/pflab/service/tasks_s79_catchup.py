"""S79 item 3: the catch-up job. Due when prices or global data arrived (service/ondemand.py), so on open it runs as soon as the data jobs have; it waits for data
(a state shown on the World screen), never fails for it. Sends the one away digest once the catch-up has settled."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _catch_up(ctx) -> dict:
    from pflab.service import away, catchup
    out = catchup.run(ctx.con, ctx.data_root, ctx.now)
    failed = {m: v["failed"] for m, v in out.items() if isinstance(v, dict) and "failed" in v}
    res: dict = {"markets": out}
    if not any("waiting" in v for v in out.values() if isinstance(v, dict)) and not failed:
        did = away.maybe_send(ctx.con, ctx.now)
        if did:
            res["digest"] = did
    if failed:
        res["failed"] = failed
    return res


register(Job("catch_up", Interval(5, weekdays_only=False), _catch_up,
             "on open: each market's missed sessions scored in order by code, then the one 'while you were away' digest (code, free)", cooldown_minutes=5))
