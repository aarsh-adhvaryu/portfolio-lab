"""S81 B8 job `us_close`: the paper US sub-book's close (`pflab/us/adapter.close_us`) on the latest US session, in the IST morning or whenever the app is next open. Code only, free.
Skips while `[us] on = false` in configs/core.toml; the adapter itself says "waiting" when the US bars are not current and "skipped" when the session is already done."""
from __future__ import annotations

from pflab.service.jobs import Job, register
from pflab.service.schedule import Interval


def _enabled(ctx):
    from pflab import core, us
    if core.killed():
        return False, "the kill switch is set (configs/core.toml [core] kill)"
    return (True, "") if us.on() else (False, "the paper US sub-book is OFF (configs/core.toml [us] on = false)")


def _run(ctx) -> dict:
    from pflab.us import adapter
    return adapter.close_us(ctx.con, ctx.now, ctx.data_root)


register(Job("us_close", Interval(120, weekdays_only=False), _run, "the paper US sub-book's close on the latest US session (S81; code, free; OFF until switched on)", cooldown_minutes=60, enabled_fn=_enabled))


def _prices(ctx) -> dict:
    """The 13 US ETFs the sub-book holds: their last 10 days appended to `data/us/raw` (network; a failure is reported, never fatal)."""
    from pflab.data import us_prices
    out = us_prices.collect(sorted(us_prices.ETFS), ctx.data_root, recent_days=10)
    bad = {k: v for k, v in out.items() if isinstance(v, str)}
    res = {"symbols": len(out), "problems": len(bad)}
    if len(bad) == len(out):
        res["failed"] = {"us_prices": "no symbol could be refreshed: " + next(iter(bad.values()))[:160]}
    return res


register(Job("us_prices_daily", Interval(360, weekdays_only=False), _prices, "the US sub-book's ETF prices, last days appended (S81; network)", cooldown_minutes=120, enabled_fn=_enabled))
