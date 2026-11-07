"""S79b items 7b and 18D tools: `volume_profile` and `lenses`. Both read only, both work with {} and return a harmless dict when the data is missing.

volume_profile result keys (stable; agent S reads them):
    call_ref, market, key, symbol, as_of, basis ("kite feed trade volume" | "minute bars" | "daily approximation" | "time at price (index has no volume)" | "close only"),
    mode ("minute" | "daily rolling composite"), last_session, close,
    session {poc, val, vah, hvn[], lvn[], volume, va_share, low, high, developing_poc[{after_bar, poc}]}   (minute mode only),
    composite {poc, val, vah, hvn[], lvn[], sessions, from, to},
    poc_migration {direction up|down|flat, change, change_va_heights, lookback_sessions, dead_band, session_pocs[]},
    naked_pocs [{date, poc, sessions_ago, distance_pct, side}] (minute mode only),
    features {close_vs_poc_pct, position_vs_value_area (above|inside|below), distance_from_value_area_pct, migration, nearest_naked_poc, naked_pocs_above, naked_pocs_below,
              low_volume_gap_above, low_volume_gap_below, close_outside_prior_value_area (daily mode: +1/-1/0)}, note, off.
lenses result keys: call_ref, market, on, min_live_sessions, lenses [{lens, markets, protocol, replay_ok, about, horizons {1|5|20: {n_live, n_replay, pinball_vs_naive_live,
    pinball_vs_naive_replay, state (shadow|admitted), reason, weight}}}]."""
from __future__ import annotations

from datetime import date

from pflab.hq.tools import Tool, _s

try:                                                  # the lenses of this module register themselves; a late plugins module never blocks the tool
    from pflab.quant import volume_profile as _vp
    _vp.register_lens()
except Exception:                                     # pragma: no cover
    _vp = None


def _market(a: dict) -> str:
    from pflab import markets
    m = str(a.get("market") or "IN").upper()
    return m if m in markets.codes() else "IN"


def volume_profile(ctx, a: dict) -> dict:
    from pflab import markets
    from pflab.hq import tools as tl
    from pflab.quant import volume_profile as vp
    head = {"call_ref": ctx.call_ref}
    try:
        if not vp.is_on():
            return {**head, "off": True}
        market = _market(a)
        m = markets.get(market)
        d = date.fromisoformat(str(a["date"])[:10]) if a.get("date") else m.session_closed_by(ctx.now)
        if d > ctx.now.date():
            return {**head, "note": f"{d} is in the future"}
        sym = (a.get("symbol") or "").strip()
        up = sym.upper()
        if not sym or up in {m.index.upper(), m.benchmark.upper()} or up.startswith("NIFTY"):
            key, symbol = vp.INDEX_PREFIX + (up if up.startswith("NIFTY") else m.index.upper()), None
        else:
            key, symbol = tl._isin(ctx, sym), up
        root = getattr(ctx.rt, "data_root", None)
        rep = vp.report(ctx.con, market, key, d, root=root, symbol=symbol, sessions=a.get("sessions"), name=(symbol or key))
        out = {**head, **rep}
        out["source_note"] = "quant/volume_profile.py: each bar's volume spread over its high-low range; value area 70%; the basis says what the volume came from"
        return out
    except LookupError as e:
        return {**head, "note": str(e)}
    except Exception as e:
        return {**head, "error": repr(e)[:200], "note": "the volume profile could not be worked"}


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
    Tool("volume_profile", "read", "Where the business was done in a name or an index, by code: each bar's volume spread over its high-low range, per session and as a composite: "
         "the busiest price (POC), the value area holding 70% of the volume, high- and low-volume nodes, the developing POC, how the POC has migrated, prior POCs no later session "
         "has touched (naked), and where the close sits against all that. The basis says whether the volume is the Kite feed's trades, minute bars, or a daily approximation "
         "(then there are no naked POCs). Quote figures exactly as given and cite the call_ref.",
         {"market": _s("the market, IN or US (default IN)", 4), "symbol": _s("a held or watched stock's symbol, or the index (default: the market's index)", 24),
          "date": _s("the session, YYYY-MM-DD (default: the last session that has closed)", 10),
          "sessions": {"type": "integer", "description": "sessions in the composite (default 20)", "minimum": 3, "maximum": 60}}, (), volume_profile),
    Tool("lenses", "read", "The plug-in lenses (extra indicators run as forecasters in shadow): each one's protocol, how many live and replay sessions it has been scored on, "
         "whether it is still in shadow or admitted to the combined forecast, its Hedge weight, and its pinball loss against the naive forecast. A lens is admitted only by its "
         "live score (60 sessions and a better combined forecast with it than without). Quote figures exactly as given and cite the call_ref.",
         {"market": _s("the market, IN or US (default IN)", 4)}, (), lenses),
]
