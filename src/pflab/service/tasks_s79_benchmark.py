"""S79b item 18B/18E job: `benchmark_attr` extends the recorded benchmark to every marked day of the system's book and recomputes the monthly attribution (code, free). Due when
the paper book has a day newer than the benchmark's last (redo_fn) and after the `paper` job (service/ondemand.py). Skips when `[benchmark] on = false`."""
from __future__ import annotations

from typing import Optional

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _enabled(ctx):
    from pflab.paper import benchmark
    return (True, "") if benchmark.on() else (False, "switched off in configs/s79b.toml [benchmark]")


def _run(ctx) -> dict:
    from pflab.paper import benchmark, book
    if not book.started(ctx.con):
        return {"waiting": "the paper book has not started"}
    return benchmark.refresh(ctx.con, "IN", ctx.now.date(), ctx.now, root=ctx.data_root)


def _redo(ctx) -> Optional[str]:
    try:
        last = ctx.con.execute("SELECT max(day) FROM paper_days").fetchone()[0]
        mine = ctx.con.execute("SELECT max(as_of) FROM blended_benchmark_s79 WHERE market='IN'").fetchone()[0]
        if last is not None and (mine is None or mine < last):
            return f"the book was marked {last}, the benchmark runs to {mine}"
    except Exception:
        pass
    return None


register(Job("benchmark_attr", Interval(120, weekdays_only=False), _run,
             "the book against its own benchmark: the blended benchmark extended and the monthly attribution recomputed (code, free)", cooldown_minutes=20, enabled_fn=_enabled, redo_fn=_redo))
