"""S79 item 5: the `agenda` read tool, what the system is working on when nothing urgent is happening (the same picture the World screen shows)."""
from __future__ import annotations

from pflab.hq.tools import Ctx, Tool, _s


def agenda(ctx: Ctx, a: dict) -> dict:
    from pflab.agenda import runner
    market = (a.get("market") or "").strip().upper() or None
    s = runner.snapshot(ctx.con, ctx.now, market)
    return {"source": "agenda (mind_agenda, agenda_kind_stats)", "market_filter": market, **s}


TOOLS = [
    Tool("agenda", "read", "What the system itself is working on when nothing urgent is happening: the item running now and why, the last acts with what each changed "
         "(or did not), what it skipped and why, the next items with their expected value, and how often each kind of work turned out useful.",
         {"market": _s("IN or US; empty for all", 4)}, (), agenda),
]
