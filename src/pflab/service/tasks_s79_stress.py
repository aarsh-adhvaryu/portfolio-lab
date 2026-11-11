"""S83 L7 job `stress_daily`: the five stress scenarios on what the book holds (India book, US sub-book, the whole) are worked out and stored (`stress_s83`) with the holdings they were
made on. Code only, free, idempotent for a day. Due when the close loop (or the US close) finished after its last run (`service/ondemand.AFTER`, set here)."""
from __future__ import annotations

from pflab.service import ondemand
from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval

ondemand.AFTER["stress_daily"] = ("core_loop", "us_close")


def _run(ctx) -> dict:
    from pflab.core import stress
    from pflab.paper import book
    if not book.started(ctx.con):
        return {"waiting": "the paper book has not started"}
    day = ctx.con.execute("SELECT max(day) FROM paper_days").fetchone()[0] or ctx.now.date()
    res = stress.run_and_store(ctx.con, day, "ALL", ctx.data_root)
    return {"day": str(day), "stored": res["stored"], "whole_book_source": res["whole_book_source"],
            "falls": {s: {r["scenario"]: r["book_fall_pct"] for r in v["scenarios"]} for s, v in res["scopes"].items()}}


register(Job("stress_daily", Interval(120, weekdays_only=False), _run, "stress scenarios on the holdings: AI bubble, 2008, 2020, a 10% fall of the dollar (code, free)", cooldown_minutes=30))
