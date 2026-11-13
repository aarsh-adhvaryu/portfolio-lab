"""S85 L1 job `think_missed`: "what did I miss" (`think/missed.py`) and the weekly bounded threshold tuning (`think/tuning.py`). It follows the thinking loop (due the moment `think_loop` has finished a
pass, so after each India close and US morning, never at a time the laptop must be on for) and also runs when it has had no success in 20 hours. Code only: no model, no cost. Each market's latest
closed session is looked at once; the tuning does nothing unless `[think] tune_thresholds` is on and its counts and amendment are in place (it says why in the job's detail).

The job registers itself on the on-demand table and on the thinking world node here, so no shared table is edited: `ondemand.AFTER["think_missed"] = ("think_loop",)`, `MAX_AGE_H["think_missed"] = 20`,
`world.GROUP_OF["think_missed"] = "thinking"`.
"""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _enabled(ctx):
    from pflab import core, think
    if core.killed():
        return False, "the kill switch is set (configs/core.toml [core] kill)"
    if not think.on():
        return False, "the thinking loop is OFF (configs/core.toml [think] on = false)"
    if not think.settings().get("missed_job", True):
        return False, "the missed-moves job is OFF (configs/core.toml [think] missed_job = false)"
    return True, ""


def _run(ctx) -> dict:
    from pflab.think import missed, tuning
    out: dict = {}
    r = missed.run(ctx.con, ctx.now, ctx.data_root)
    if r:
        out["missed"] = r
    t = tuning.run_weekly(ctx.con, ctx.now, ctx.data_root)
    if t.get("changed") or t.get("error"):
        out["tuning"] = t
    elif "off" not in str(t.get("why", "")) and "under the counts" not in str(t.get("why", "")):
        out["tuning_note"] = t.get("why")
    if not out:
        out["skipped"] = "nothing new to look at"
    return out


register(Job("think_missed", Interval(60, weekdays_only=False), _run,
             "what did I miss (S85): after each close, the big movers the thinking loop did not notice, with the reason and the threshold that would have caught them; the weekly bounded threshold tuning",
             cooldown_minutes=30, enabled_fn=_enabled))

try:
    from pflab.service import ondemand
    ondemand.AFTER.setdefault("think_missed", ("think_loop",))
    ondemand.MAX_AGE_H.setdefault("think_missed", 20)
    from pflab.app import world
    world.GROUP_OF.setdefault("think_missed", "thinking")
except Exception:                                  # the job still runs on its interval
    pass
