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
    """The 13 US ETFs, SPY and (S83) every held and every picked or skipped US stock: their last 10 days appended to `data/us/raw` (a name with no file yet is downloaded whole; network; a failure is reported, never fatal)."""
    from pflab.data import us_prices
    out = us_prices.collect(us_prices.tracked_symbols(getattr(ctx, "con", None)), ctx.data_root, recent_days=10)
    bad = {k: v for k, v in out.items() if isinstance(v, str)}
    res = {"symbols": len(out), "problems": len(bad)}
    try:                                                    # S83: the SEC ticker file (CIKs, names, the screen's universe) once a week; a failure (e.g. no contact in the secrets file) is reported, never fatal
        import time
        from pathlib import Path
        from pflab.lab import screen
        p = Path(ctx.data_root).joinpath(*screen.UNIVERSE_FILE)
        if not p.exists() or time.time() - p.stat().st_mtime > 7 * 86400:
            res["sec_universe"] = screen.refresh_us_universe(ctx.data_root)
    except Exception as e:
        res["sec_universe"] = f"not refreshed ({type(e).__name__}: {str(e)[:100]})"
    if len(bad) == len(out):
        res["failed"] = {"us_prices": "no symbol could be refreshed: " + next(iter(bad.values()))[:160]}
    return res


register(Job("us_prices_daily", Interval(360, weekdays_only=False), _prices, "the US sub-book's ETF prices, last days appended (S81; network)", cooldown_minutes=120, enabled_fn=_enabled))
