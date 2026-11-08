"""S79 item 12: resolve the bear's open warnings by code once their target session's close is in (no model, no cost)."""
from __future__ import annotations

from pflab.service.jobs import Ctx, Daily, Job, register


def _resolve(ctx: Ctx) -> dict:
    from pflab.agents import debate

    class _Rt:                                               # default_feed wants a runtime with a cursor and the data folder
        data_root = ctx.data_root

        @staticmethod
        def cursor():
            return ctx.con.cursor()

    return debate.resolve_open(ctx.con, ctx.now, lambda market: debate.default_feed(_Rt, market))


register(Job("bear_resolve", Daily(21, 15), _resolve, "resolves the bear's warnings from the debates on later prices (code only)", cooldown_minutes=60))
