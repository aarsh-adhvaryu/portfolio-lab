"""S80 phase 2 jobs (the strategy lab, `pflab/lab`):

`lab_close`   after the close loop: the challengers and the champion's stand-in decide in shadow on the day's inputs (sandbox), yesterday's shadow rows are scored, and any challenger that
              has cleared the history screen, the 20-session shadow record and the one final check is promoted (code, free)
`strategist`  the lab session (Opus) when there is a reason (weekly, a challenger ready, the fall gauge, the book behind its benchmark) and room in the budget; also the automatic
              rollback of a champion that fell below its own history range. Paid only inside the cap; the workshop makes no paid call unless told.
Both skip when `[core] on = false` or the kill switch is set (configs/core.toml).
"""
from __future__ import annotations

from datetime import timedelta

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _enabled(ctx):
    from pflab import core
    if core.killed():
        return False, "the kill switch is set (configs/core.toml [core] kill)"
    return (True, "") if core.on() else (False, "switched off in configs/core.toml [core]")


def _strategist_enabled(ctx):
    from pflab import core
    if core.killed():
        return False, "the kill switch is set (configs/core.toml [core] kill)"
    return (True, "") if core.strategist_on() else (False, "switched off in configs/core.toml [strategist]")


def _lab_close(ctx) -> dict:
    from pflab import markets
    from pflab.lab import promotion, shadow
    con = ctx.con
    if not con.execute("SELECT count(*) FROM core_policies_s80 WHERE status='challenger'").fetchone()[0]:
        return {"skipped": "no challenger to watch"}
    day = markets.get("IN").session_closed_by(ctx.now)
    if not con.execute("SELECT 1 FROM core_runs_s80 WHERE day=?", [day]).fetchone():
        return {"waiting": f"the close loop has not run for {day}"}
    from pflab.agents import sandbox as sb
    try:
        out = shadow.run_shadow(con, ctx.pm_dir, ctx.data_root, ctx.now, day)
    except sb.SandboxUnavailable as e:             # drill docker_down (S81): Docker not running is a state to wait in, not a failure that alerts him at every cooldown; the champion decides all the same
        return {"skipped": f"the sandbox is not available, so the challengers wait ({str(e)[:160]})", "waiting": True}
    if not out.get("error"):
        out["promotion"] = promotion.promote_ready(con, ctx.pm_dir, ctx.data_root, ctx.now)        # S81 (A50): a variant that cleared history and the final check is granted a probation slice
        try:
            from pflab.lab import probation
            out["probation"] = probation.review(con, ctx.now, day)                                  # slices grow or are withdrawn by their live record
        except Exception as e:
            out["probation"] = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    return out


def _lab_close_redo(ctx):
    try:
        last = ctx.con.execute("SELECT max(started_at) FROM job_runs WHERE job='lab_close'").fetchone()[0]
        if last is not None and ctx.now - last < timedelta(minutes=15):          # a run that waited (the sandbox is down) is not started again every tick
            return None
        from pflab import markets
        day = markets.get("IN").session_closed_by(ctx.now)
        ran = ctx.con.execute("SELECT 1 FROM core_runs_s80 WHERE day=?", [day]).fetchone()
        done = ctx.con.execute("SELECT 1 FROM core_shadow_s80 WHERE day=? LIMIT 1", [day]).fetchone()
        if ran and not done and ctx.con.execute("SELECT count(*) FROM core_policies_s80 WHERE status='challenger'").fetchone()[0]:
            return f"the close of {day} has no shadow decisions yet"
    except Exception:
        pass
    return None


def _strategist(ctx) -> dict:
    from pflab.hq import desk, llm
    from pflab.lab import strategist
    rt = desk.from_ctx(ctx)
    return strategist.tick(ctx.con, ctx.pm_dir, ctx.data_root, ctx.now, lambda: llm.client(rt.secrets if hasattr(rt, "secrets") else ctx.secrets))


register(Job("lab_close", Interval(60, weekdays_only=False), _lab_close, "challengers in shadow on the day's inputs, scored daily; a challenger that cleared everything is promoted (code, free)",
             cooldown_minutes=15, enabled_fn=_enabled, redo_fn=_lab_close_redo))
register(Job("strategist", Interval(120, weekdays_only=False), _strategist, "the strategist's lab session (Opus) when there is a reason and room in the budget; the champion's automatic rollback",
             cooldown_minutes=60, enabled_fn=_strategist_enabled))
