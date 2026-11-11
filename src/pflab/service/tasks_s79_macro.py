"""S79b item 15 job (the `wave_scan` job was deleted in A60: the wave and rotation flags failed their study).

`macro_attribution`: writes the split of each closed session's index move into the `macro_attribution` table, for every market with a history on this PC, and
catches up every session missed (plus, later, the flows part of a session whose foreign-flow report has now arrived). Due when prices or world data arrived (ondemand AFTER).
It skips when `configs/s79b.toml [waves] on = false`. The tables `wave_flag` and `wave_stats` stay as the record."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pflab.service.jobs import Ctx, Job, register
from pflab.service.schedule import Interval


def _enabled(ctx: Ctx):
    from pflab.quant import macro_attr as MA
    return (MA.is_on(), "switched off in configs/s79b.toml [waves]")


def _macro(ctx: Ctx) -> dict:
    from pflab import markets
    from pflab.quant import macro_attr as MA
    back = int(MA.settings().get("backfill_sessions", 60))
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


register(Job("macro_attribution", Interval(180, weekdays_only=False), _macro,
             "splits each closed session's index move into crude, rupee, US yield, Nasdaq, foreign flows and Asia, plus unexplained",
             cooldown_minutes=30, enabled_fn=_enabled, redo_fn=_redo_macro))
