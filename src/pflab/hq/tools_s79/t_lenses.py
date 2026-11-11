"""S79b item 18D tool: `lenses` (the plug-in lens framework `fcast/plugins.py`). Read only; works with {} and returns a harmless dict when the data is missing.
(`volume_profile` shared this module until A60 deleted it with its failed study; the framework and this tool stay, so a lens that passes a registered study can enter.)

lenses result keys: call_ref, market, on, min_live_sessions, lenses [{lens, markets, protocol, replay_ok, about, horizons {1|5|20: {n_live, n_replay, pinball_vs_naive_live,
    pinball_vs_naive_replay, state (shadow|admitted), reason, weight}}}]."""
from __future__ import annotations

from pflab.hq.tools import Tool, _s


def _market(a: dict) -> str:
    from pflab import markets
    m = str(a.get("market") or "IN").upper()
    return m if m in markets.codes() else "IN"


def lenses(ctx, a: dict) -> dict:
    head = {"call_ref": ctx.call_ref}
    try:
        from pflab.fcast import plugins
        if not plugins.is_on():
            return {**head, "off": True}
        return {**head, **plugins.table(ctx.con, _market(a))}
    except Exception as e:
        return {**head, "error": repr(e)[:200], "note": "the lens table could not be read"}


TOOLS = [
    Tool("lenses", "read", "The plug-in lenses (extra indicators run as forecasters in shadow): each one's protocol, how many live and replay sessions it has been scored on, "
         "whether it is still in shadow or admitted to the combined forecast, its Hedge weight, and its pinball loss against the naive forecast. A lens is admitted only by its "
         "live score (60 sessions and a better combined forecast with it than without). Quote figures exactly as given and cite the call_ref.",
         {"market": _s("the market, IN or US (default IN)", 4)}, (), lenses),
]
