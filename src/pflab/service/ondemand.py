"""Jobs that run when their input is newer than their last run, never at their slot (S79 item 3, A42).

A job listed in AFTER is due when any job it follows has a success that finished after this job's last run; a job in MAX_AGE_H is also due when it has no
success inside that many hours (it runs on open). Data-arrival jobs (collect, prices, nav, instruments, filings, global) keep their slots: NSE's files
exist only after the close. `STALE_SLOT_H`: a message tied to a time of day (the Telegram summaries) is not sent hours late after the app was off; the
"while you were away" digest (`service/away.py`) says it once.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

AFTER: Dict[str, Tuple[str, ...]] = {
    "guards": ("prices",), "plans": ("prices", "nav"), "forecast": ("prices",), "twin": ("prices",), "scans": ("prices",), "review": ("prices",),
    "paper": ("prices",), "kg2_nightly": ("filings", "collect"), "us_close": ("us_prices_daily",), "core_loop": ("paper", "prices"), "lab_close": ("core_loop",), "story_daily": ("prices", "global", "flows", "macro_attribution", "kg2_nightly"), "strategist": ("core_loop", "lab_close"), "companion": ("prices",), "comove": ("prices",), "kg": ("filings", "collect"), "research": ("kg",),
    "catch_up": ("prices", "global"), "think_loop": ("core_loop", "us_close", "catch_up"), "bars_1m": ("prices",), "forecast_loop": ("prices", "global"), "benchmark_attr": ("paper", "prices"),
    "macro_attribution": ("prices", "global", "flows"),
}
MAX_AGE_H: Dict[str, float] = {"kg2_nightly": 26, "news_s81_topup": 26, "selfcheck": 24, "sandbox": 24, "learner": 24, "paper_daily": 20, "backup": 26, "catch_up": 12, "voice": 1, "data_s79b": 20, "week_check": 20, "think_loop": 20}
STALE_SLOT_H: Dict[str, float] = {"summary_morning": 6, "summary_evening": 6}


def _last_run(con, job: str) -> Optional[datetime]:
    return con.execute("SELECT max(started_at) FROM job_runs WHERE job=? AND status='ok'", [job]).fetchone()[0]


def _last_attempt(con, job: str) -> Optional[datetime]:
    return con.execute("SELECT max(started_at) FROM job_runs WHERE job=? AND status IN ('failed','skipped','running','offline') "
                       "AND detail IS DISTINCT FROM 'abandoned: the process stopped before it finished'", [job]).fetchone()[0]


def reason(ctx, job) -> Optional[str]:
    """Why `job` is due now although its slot says it is done (None: it is not)."""
    con, name = ctx.con, job.name
    if name not in AFTER and name not in MAX_AGE_H:
        return None
    attempt = _last_attempt(con, name)
    if attempt is not None and ctx.now - attempt < timedelta(minutes=job.cooldown_minutes):
        return None
    mine = _last_run(con, name)
    for up in AFTER.get(name, ()):
        r = con.execute("SELECT max(finished_at) FROM job_runs WHERE job=? AND status='ok'", [up]).fetchone()[0]
        if r is not None and (mine is None or r > mine):
            return f"input newer: {up} finished {r:%a %d %b %H:%M}" + (f", last run {mine:%a %d %b %H:%M}" if mine else ", never run")
    age = MAX_AGE_H.get(name)
    if age is not None and (mine is None or ctx.now - mine > timedelta(hours=age)):
        return f"no run in the last {age:g} h" + (f" (last {mine:%a %d %b %H:%M})" if mine else "")
    return None


def stale_slot(ctx, job, slot: datetime) -> Optional[str]:
    h = STALE_SLOT_H.get(job.name)
    if h is not None and ctx.now - slot > timedelta(hours=h):
        return f"stale: its time ({slot:%a %H:%M}) passed while the app was off; the away digest covers it"
    return None
