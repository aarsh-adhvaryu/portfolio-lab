"""S79b: the app's own check of its first week. Arms on its first run, evaluates once the week is over, sends the verdict on Telegram once (code, free)."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Daily


def _week(ctx) -> dict:
    from pflab import release
    from pflab.service import week_check
    try:
        rel = str(getattr(release, "current_tag", lambda: "")() or "")
    except Exception:
        rel = ""
    return week_check.run(ctx.con, ctx.now, rel)


register(Job("week_check", Daily(21, 50, weekdays_only=False), _week,
             "the app checks its own first week (catch-ups after every gap, every mode reached, forecasts made and scored, no failure, cost within the cap) and tells him once on Telegram (code, free)", cooldown_minutes=60))
