"""S83 L4 job `pick_score`: the picks sleeve's day against the index is stored (`pick_sleeve_daily_s83`) and every pick, sale and skip whose 1, 3, 6 or 12 months have elapsed is scored
(`pick_scores_s83`). Code only, free, idempotent. Due when the close loop (or the US close) finished after its last run (`service/ondemand.AFTER`, set here so no shared file is edited)."""
from __future__ import annotations

from pflab.service import ondemand
from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval

ondemand.AFTER["pick_score"] = ("core_loop", "us_close")


def _run(ctx) -> dict:
    from pflab.core import pick_score
    sl = pick_score.update_sleeve_daily(ctx.con, ctx.now, ctx.data_root)
    sc = pick_score.score_all(ctx.con, ctx.now, ctx.data_root)
    res = {"sleeve_days": sl, **sc}
    bad = {m: v for m, v in sl.items() if isinstance(v, str)}
    if bad:
        res["failed"] = bad
    return res


def _redo(ctx):
    try:
        marked = ctx.con.execute("SELECT max(day) FROM paper_days").fetchone()[0]
        mine = ctx.con.execute("SELECT max(day) FROM pick_sleeve_daily_s83 WHERE market='IN'").fetchone()[0]
        if marked is not None and (mine is None or mine < marked):
            return f"the book was marked {marked}, the sleeve record runs to {mine}"
    except Exception:
        pass
    return None


register(Job("pick_score", Interval(120, weekdays_only=False), _run,
             "the picks scorecard: the sleeve against the index after tax, picks, sales and skips scored at 1, 3, 6 and 12 months (code, free)", cooldown_minutes=30, redo_fn=_redo))
