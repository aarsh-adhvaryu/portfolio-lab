"""S81 jobs of the market-hours rhythms (A54, `pflab/core/session.py`): they run only while the app is open, by the clock's mode, never by a time the laptop must be on for.

    preopen_job     the day's plan (conditional orders with their triggers, the world's close, the expected gap): built when the next session has none, again once inside the pre-open window
    session_job     every `[session] every_minutes` while the market is in session: live quotes, exit plans, thesis breaks, swing entries, views, fills (needs a Kite login; without one it
                    says so once and does only the work that needs no quotes)
    session_report  the self-report after the close (about 15:45): the plan, the checks, the fills with their quotes and slippage, what did not run; queued on Telegram through the outbox

The jobs skip, with their reason, outside a session; a job that finds nothing to do is a result, not an error.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from pflab.service.jobs import Ctx, Job, register
from pflab.service.schedule import Daily, Interval


def _enabled(ctx: Ctx):
    from pflab import core
    from pflab.core import fills
    if not core.on():
        return False, "switched off in configs/core.toml [core]"
    if not fills.session_settings()["on"]:
        return False, "switched off in configs/core.toml [session]"
    return True, ""


def _kite(ctx: Ctx):
    from pflab.ingest import kite as km
    try:
        return km.client(ctx.secrets, now=ctx.now) if ctx.secrets is not None and ctx.secrets.has("kite", "api_key") else None
    except Exception:
        return None


def _preopen(ctx: Ctx) -> dict:
    from pflab.core import preopen
    return preopen.ensure_plan(ctx.con, ctx.now, "IN", root=ctx.data_root)


def _session(ctx: Ctx) -> dict:
    from pflab import markets
    from pflab.core import session
    if markets.get("IN").mode(ctx.now) != "session":
        return {"skipped": "the market is not in session"}
    kite = None
    try:
        from pflab.app import settings as _st
        if _st.ability("kite_live", current=getattr(ctx, "settings", None)):
            kite = _kite(ctx)
    except Exception:
        kite = _kite(ctx)
    r = session.run_once(ctx.con, ctx.now, kite=kite, data_root=ctx.data_root)
    if r.get("skipped") or r.get("off") or r.get("waiting"):
        return {"skipped": r.get("skipped") or r.get("why") or r.get("waiting")}
    return {"fills": len(r["fills"]), "queued": len(r["queued"]), "waiting": len(r["waiting"]), "degraded": r["degraded"], **r["summary"]["checks"]}


STALE_AFTER = timedelta(hours=3)


def _report(ctx: Ctx) -> dict:
    from pflab import markets
    from pflab.core import session
    from pflab.service import telegram as tgm
    m = markets.get("IN")
    day = ctx.now.date()
    if not m.is_session(day):
        return {"skipped": "no session today"}
    at = datetime.combine(day, m.close) + timedelta(minutes=15)
    if ctx.now > at + STALE_AFTER:
        return {"skipped": f"its time ({at:%H:%M}) passed while the app was off; the away digest covers it"}
    if not ctx.con.execute("SELECT 1 FROM session_log_s81 WHERE day=? LIMIT 1", [day]).fetchone() and not ctx.con.execute("SELECT 1 FROM session_plans_s81 WHERE day=? LIMIT 1", [day]).fetchone():
        return {"skipped": "the session loop and the plan never ran today (the app was not open in the session)"}
    text = session.report_day(ctx.con, day)
    if session.said(ctx.con, ctx.now, "report", text):
        tgm.enqueue(ctx.con, text, "summary", dedup_key=f"session_report:{day}", now=ctx.now)
        return {"queued": True, "lines": text.count("\n") + 1}
    return {"skipped": "already sent today"}


register(Job("preopen_job", Interval(30, start_hour=6, end_hour=16), _preopen, "the pre-open plan: the world's close, the expected gap and the day's conditional orders with their triggers (code, free)",
             cooldown_minutes=10, enabled_fn=_enabled))
register(Job("session_job", Interval(5, start_hour=9, end_hour=16), _session, "the session loop every 5 minutes in market hours: live quotes, exit plans, thesis breaks, swing entries timed by the minute data, views; paper fills at the quote plus slippage",
             cooldown_minutes=2, enabled_fn=_enabled))
register(Job("session_report", Daily(15, 45), _report, "the self-report after the close: the plan, the session checks, the fills with their quotes and slippage, and what did not run (Telegram)",
             cooldown_minutes=15, enabled_fn=_enabled))
