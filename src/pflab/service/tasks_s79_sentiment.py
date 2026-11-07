"""S79b item 15b job `sentiment`: for each market, the sentiment table of every session not done yet (point in time, by code), the theme exposure of the book, the calendar notes,
and (a limited, resumable step) the local model's tagging of the latest headlines. Due when its inputs are newer (service/ondemand.AFTER) or its slot comes; idempotent.

The tagging step is the only local-model work: at most `tag_limit` headlines per run, one call at a time, only headlines of the last `tag_days` days (the model-read tone is forward-only),
and it stops at the first failure to reach the model. With `[sentiment] on = false` the job skips."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from pflab.service.jobs import Ctx, Job, register
from pflab.service.schedule import Daily


def _sentiment(ctx: Ctx) -> dict:
    from pflab import markets, sentiment as S
    from pflab.sentiment import calendar as cal, compute, exposure, themes as T, tone
    if not S.is_on():
        return {"skipped": "switched off (configs/s79b.toml [sentiment] on = false)"}
    st = S.settings()
    out: dict = {}
    failed: dict = {}
    for m in markets.codes():
        r: dict = {}
        try:
            mk = markets.get(m)
            upto = mk.session_closed_by(ctx.now)
            last = ctx.con.execute("SELECT max(day) FROM sentiment_s79 WHERE market=?", [m]).fetchone()[0]
            start = (last + timedelta(days=1)) if last else (upto - timedelta(days=10))
            if last is not None and (upto - last).days > 60:                                   # a long gap: the last 60 days (the rest is history, not news)
                start = upto - timedelta(days=60)
            days = mk.sessions_between(start, upto)
            if bool(st["tagging"]):
                try:
                    cand = []
                    for k in range(int(st["tag_days"])):
                        d = ctx.now.date() - timedelta(days=k)
                        cand += tone.candidates(ctx.con, ctx.data_root, m, d)
                    r["tags"] = tone.tag_batch(ctx.con, cand, now=ctx.now) if cand else {"tagged": 0, "skipped": 0, "candidates": 0}
                except Exception as e:
                    r["tags"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
            if days:
                df = compute.compute_range(ctx.con, ctx.data_root, m, days)
                r["rows"] = compute.persist(ctx.con, df)
                r["sessions"] = len(days)
            if m == "IN":
                try:
                    ex = exposure.compute(ctx.con, ctx.data_root, upto, m)
                    r["exposure_rows"] = exposure.persist(ctx.con, ex, upto) if ex.get("themes") else 0
                except Exception as e:
                    r["exposure"] = f"{type(e).__name__}: {str(e)[:120]}"
            r["notes"] = cal.run_notes(ctx.con, ctx.data_root, m, upto)
            out[m] = r
        except Exception as e:
            failed[m] = f"{type(e).__name__}: {str(e)[:160]}"
    if failed:
        out["failed"] = failed
    return out


def _redo(ctx: Ctx) -> Optional[str]:
    """Due again when a market has a closed session without sentiment rows."""
    try:
        from pflab import markets, sentiment as S
        if not S.is_on():
            return None
        for m in markets.codes():
            closed = markets.get(m).session_closed_by(ctx.now)
            last = ctx.con.execute("SELECT max(day) FROM sentiment_s79 WHERE market=?", [m]).fetchone()[0]
            if last is None or last < closed:
                return f"{m}: session {closed} closed, last sentiment {last}"
    except Exception:
        return None
    return None


register(Job("sentiment", Daily(23, 25), _sentiment, "news tone, priced fear and positioning per theme (the local model tags the latest headlines), theme exposure of the book, calendar notes",
             cooldown_minutes=60, redo_fn=_redo))
