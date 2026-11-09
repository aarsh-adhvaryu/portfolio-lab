"""S81 job `autonomy_check`: the autonomy check (`core/autonomy.py`) sent to him on Telegram after the FIFTH real close (with the phase 1 gate: five closes, each under 2 minutes), then weekly.
Code only, free. A frozen system is said to be frozen (NOT AUTONOMOUS, with the reason). Skips when `[core] on = false`."""
from __future__ import annotations

from datetime import datetime

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval

GATE_CLOSES = 5
GATE_SECONDS = 120.0


def _enabled(ctx):
    from pflab import core
    return (True, "") if core.on() and not core.killed() else (False, "switched off in configs/core.toml [core]")


def gate_text(con) -> str:
    rows = con.execute("SELECT day, seconds, status FROM core_runs_s80 ORDER BY day LIMIT ?", [GATE_CLOSES]).fetchall()
    if len(rows) < GATE_CLOSES:
        return ""
    slow = [str(d) for d, sec, _ in rows if (sec or 0) >= GATE_SECONDS]
    traded = sum(1 for _, _, st in rows if st == "traded")
    return (f"Phase 1 gate: {GATE_CLOSES} real closes run by the loop ({traded} traded), " + ("all under 2 minutes: PASSED." if not slow else f"too slow on {', '.join(slow)}: NOT passed."))


def run_once(con, now: datetime) -> dict:
    from pflab.core import autonomy
    from pflab.service import telegram as tgm
    n = con.execute("SELECT count(*) FROM core_runs_s80").fetchone()[0]
    out: dict = {"closes": int(n)}
    if n < GATE_CLOSES:
        return {**out, "waiting": f"{n} of {GATE_CLOSES} real closes so far"}
    rep = autonomy.report(con, now)
    txt = autonomy.text(rep)
    first = tgm.enqueue(con, (gate_text(con) + "\n" if gate_text(con) else "") + txt, "summary", dedup_key="autonomy:fifth-close", now=now)
    if first is not None:
        return {**out, "sent": "after the fifth close", "autonomous": rep["verdict"]["autonomous"]}
    iso = now.isocalendar()
    wk = tgm.enqueue(con, txt, "summary", dedup_key=f"autonomy:week:{iso[0]}-{iso[1]:02d}", now=now) if now.weekday() == 0 and now.hour >= 9 else None
    return {**out, "sent": "weekly" if wk is not None else None, "autonomous": rep["verdict"]["autonomous"]}


def _run(ctx) -> dict:
    return run_once(ctx.con, ctx.now)


register(Job("autonomy_check", Interval(180, weekdays_only=False), _run, "the autonomy check on Telegram after the fifth real close, then weekly (code, free)", cooldown_minutes=60, enabled_fn=_enabled))
