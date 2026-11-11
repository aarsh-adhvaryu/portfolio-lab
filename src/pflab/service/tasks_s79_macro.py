"""S79b item 15 jobs.

`macro_attribution`: writes the split of each closed session's index move into the `macro_attribution` table, for every market with a history on this PC, and
catches up every session missed (plus, later, the flows part of a session whose foreign-flow report has now arrived). Due when prices or world data arrived (ondemand AFTER).
`wave_scan`: extends the cached cross-section statistics from the NSE files and decides the wave / rotation of each new session, storing any flag as a high-salience
row (`wave_flag`) and a situation claim. The first run builds the 2004-onward history once (minutes); after that a session takes seconds.
Both skip when `configs/s79b.toml [waves] on = false`."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pflab.service.jobs import Ctx, Job, register
from pflab.service.schedule import Interval


def _enabled(ctx: Ctx):
    from pflab.quant import waves
    return (waves.is_on(), "switched off in configs/s79b.toml [waves]")


def _macro(ctx: Ctx) -> dict:
    from pflab import markets
    from pflab.quant import macro_attr as MA, waves
    back = int(waves.settings().get("backfill_sessions", 60))
    out, failed = {}, {}
    for m in markets.codes():
        if m not in MA.FACTORS:
            continue
        try:
            upto = markets.get(m).session_closed_by(ctx.now)
            out[m] = MA.catch_up(ctx.con, ctx.data_root, m, upto, now=ctx.now, backfill=back)
        except Exception as e:
            failed[m] = f"{type(e).__name__}: {str(e)[:160]}"
    if failed:
        out["failed"] = failed
    return out


def _wave_scan(ctx: Ctx) -> dict:
    from pflab import markets
    from pflab.quant import waves
    m = "IN"
    upto = markets.get(m).session_closed_by(ctx.now)
    have = {r[0] for r in ctx.con.execute("SELECT DISTINCT session FROM wave_stats WHERE market=?", [m]).fetchall()}
    st = waves.ensure_stats(ctx.data_root, upto, m)
    todo = [d for d in st.index if d not in have and d <= upto][-30:]
    flagged = []
    for d in todo:
        r = waves.scan_session(ctx.con, ctx.data_root, m, d, now=ctx.now, stats=st)
        for k in ("wave_flag", "rotation_flag"):
            if r.get(k):
                flagged.append(r[k])
    return {"market": m, "stats_through": str(st.index[-1]) if len(st) else None, "sessions_scanned": len(todo), "flags": flagged}


def _redo_macro(ctx: Ctx) -> Optional[str]:
    from pflab.quant import macro_attr as MA
    try:
        idx = MA.index_moves(ctx.data_root, "IN")
        if len(idx) == 0:
            return None
        last = ctx.con.execute("SELECT max(session) FROM macro_attribution WHERE market='IN'").fetchone()[0]
        if last is None or last < idx.index[-1]:
            return f"IN: index through {idx.index[-1]}, last attribution {last}"
    except Exception:
        return None
    return None


def _redo_scan(ctx: Ctx) -> Optional[str]:
    from pflab.quant import macro_attr as MA
    try:
        idx = MA.index_moves(ctx.data_root, "IN")
        last = ctx.con.execute("SELECT max(session) FROM wave_stats WHERE market='IN'").fetchone()[0]
        if len(idx) and (last is None or last < idx.index[-1]):
            return f"IN: index through {idx.index[-1]}, last wave scan {last}"
    except Exception:
        return None
    return None


register(Job("macro_attribution", Interval(180, weekdays_only=False), _macro,
             "splits each closed session's index move into crude, rupee, US yield, Nasdaq, foreign flows and Asia, plus unexplained",
             cooldown_minutes=30, enabled_fn=_enabled, redo_fn=_redo_macro))
register(Job("wave_scan", Interval(180, weekdays_only=False), _wave_scan,
             "flags market-wide waves and foreign-flow rotations from the NSE daily files (thresholds from the earlier history)",
             cooldown_minutes=30, enabled_fn=_enabled, redo_fn=_redo_scan))
