"""S79 item 8 job: `forecast_loop`, the predict-score-correct loop after each market's close (fcast/run.py). Idempotent: it does the sessions not done yet, in order,
and nothing when the data has not moved. Due again when a market has a closed session without a forecast (redo_fn)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pflab.service.jobs import Ctx, Job, register
from pflab.service.schedule import Interval


def _forecast(ctx: Ctx) -> dict:
    from pflab import markets
    from pflab.fcast import run
    out, failed = {}, {}
    for m in markets.codes():
        try:
            upto = markets.get(m).session_closed_by(ctx.now)
            r = run.catch_up(ctx.con, m, upto, now=ctx.now)
            out[m] = {"sessions_done": r["sessions_done"], "stopped": r["stopped"]}
        except Exception as e:
            failed[m] = f"{type(e).__name__}: {str(e)[:160]}"
    if failed:
        out["failed"] = failed
    return out


def _redo(ctx: Ctx) -> Optional[str]:
    from pflab import markets
    for m in markets.codes():
        try:
            closed = markets.get(m).session_closed_by(ctx.now)
            last = ctx.con.execute("SELECT max(as_of) FROM forecasts_s79 WHERE market=? AND source='live'", [m]).fetchone()[0]
            if last is None or last < closed:
                return f"{m}: session {closed} closed, last forecast {last}"
        except Exception:
            continue
    return None


register(Job("forecast_loop", Interval(180, weekdays_only=False), _forecast,
             "predict, score, correct: quantile forecasts of each market's index, scored when they mature, Hedge weights by code", cooldown_minutes=30, redo_fn=_redo))
