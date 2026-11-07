"""S79b item 15 tools: `macro_attribution` (what part of the index move was crude, the rupee, US yields, Nasdaq, foreign flows, Asia) and `wave_detector` (did the whole
market move as one wave, or did money rotate). Read only; both work with {} and return a harmless dict when data is missing or the switch is off
(`configs/s79b.toml [waves] on = false` gives {"off": true}). Each result carries `call_ref`: a figure quoted from it cites that id.

macro_attribution result keys: call_ref, market, session, index, total_pct (the index move, %), parts {crude|currency|us10y|nasdaq|flows|asia: {label, unit, pct (this part of
  the move, in index percent, or null when unavailable), beta (index % per unit of the factor), factor_move, n (paired observations), note}}, explained_pct,
  unexplained_pct (total minus the parts: parts + unexplained == total), dominant (the largest part or 'unexplained'), r2_window, n_fit, window, method, checks_out,
  recent (the last sessions' total, dominant part), note, source. A null pct is "unavailable" (never zero): flows appear only after the next day's NSDL report.
wave_detector result keys: call_ref, market, session, wave (bool), direction ('up'|'down'|null), decided (false while the history is too short), stats {adv_share,
  n_all, xs_disp, med_ret, disp_ratio, dom_share, n_univ}, thresholds {adv_hi, adv_lo, disp_ratio_max, dom_min}, conditions {breadth_extreme, low_dispersion,
  market_dominates}, n_reference, rotation {decided, flag ('in'|'out'|null), flow_k, z, gap_pct, sell_streak, buy_streak, known_on}, breadth (quant/breadth.py's own
  counts for the day), recent_flags (newest first), definition, note, source."""
from __future__ import annotations

import time
from datetime import date

from pflab.hq.tools import Ctx, Tool, _s

MARKET = _s("The market: IN (Nifty 500) or US (S&P 500). Default IN.", enum=("IN", "US"))
DATE = _s("The session, YYYY-MM-DD (default the latest session with data)", 10)
_DESIGNS: dict = {}


def _market(a: dict) -> str:
    m = str(a.get("market") or "IN").upper()
    return m if m in ("IN", "US") else "IN"


def _off() -> bool:
    from pflab.quant import waves
    return not waves.is_on()


def _design(root, market: str):
    from pflab.quant import macro_attr as MA
    key = (str(root), market)
    hit = _DESIGNS.get(key)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    d = MA.Design(root, market, tail=420)
    _DESIGNS[key] = (time.time(), d)
    return d


def macro_attribution(ctx: Ctx, a: dict) -> dict:
    try:
        if _off():
            return {"off": True, "call_ref": ctx.call_ref}
        from pflab.quant import macro_attr as MA
        market = _market(a)
        d = _design(ctx.rt.data_root, market)
        if not d.dates:
            return {"call_ref": ctx.call_ref, "market": market, "note": f"no {MA.INDEX_NAME[market]} history on this PC: nothing to split",
                    "source": "quant/macro_attr.py"}
        if a.get("date"):
            day = date.fromisoformat(str(a["date"])[:10])
        else:
            day = max([x for x in d.dates if x <= ctx.asof] or [d.dates[-1]])
        r = d.attribute(day)
        r["call_ref"] = ctx.call_ref
        if "total_pct" in r:
            r["dominant"] = MA.dominant(r)
            rec = []
            for s in [x for x in d.dates if x < day][-4:] + [day]:
                x = d.attribute(s) if s != day else r
                rec.append({"session": str(s), "total_pct": x.get("total_pct"), "dominant": MA.dominant(x), "unexplained_pct": x.get("unexplained_pct")})
            r["recent"] = rec
            r["note"] = ("an association worked by code (ridge betas over the year before the day), not a proof of cause; foreign flows and the rupee also respond to the "
                         "market; a null part is unavailable, not zero")
        r["source"] = "quant/macro_attr.py"
        return r
    except Exception as e:
        return {"error": repr(e)[:200], "call_ref": ctx.call_ref, "note": "macro attribution could not be computed"}


def wave_detector(ctx: Ctx, a: dict) -> dict:
    try:
        if _off():
            return {"off": True, "call_ref": ctx.call_ref}
        from pflab import markets
        from pflab.quant import breadth as br, waves
        market = _market(a)
        root = ctx.rt.data_root
        if market != "IN":
            return {"call_ref": ctx.call_ref, "market": market, "wave": False, "decided": False, "note": f"no daily cross-section of names for {market} on this PC: no wave test",
                    "definition": waves.DEFINITION, "source": "quant/waves.py"}
        day = date.fromisoformat(str(a["date"])[:10]) if a.get("date") else markets.get(market).last_session_on_or_before(ctx.asof)
        st = waves.ensure_stats(root, day, market, max_new_sessions=40)
        if st.empty or day not in st.index:
            last = str(st.index[-1]) if len(st) else "none"
            return {"call_ref": ctx.call_ref, "market": market, "session": str(day), "wave": False, "decided": False,
                    "note": f"no wave statistics for {day} (history built to {last}; the job 'wave_scan' extends it from the NSE files)", "definition": waves.DEFINITION,
                    "recent_flags": waves.recent_flags(ctx.con, market), "source": "quant/waves.py"}
        w = waves.wave_flag_at(st, day)
        out = {"call_ref": ctx.call_ref, "market": market, **w}
        try:
            rf = waves.rotation_frame(root, market)
            if len(rf) and day in rf.index:
                r = rf.loc[day]
                f = None if r["rotation"] is None or r["rotation"] != r["rotation"] else r["rotation"]
                out["rotation"] = {"decided": bool(r["thr_z_hi"] == r["thr_z_hi"] and r["thr_g_hi"] == r["thr_g_hi"]), "flag": f, "flow_k": float(r["flow_k"]),
                                   "z": None if r["z"] != r["z"] else float(r["z"]), "gap_pct": None if r["g"] != r["g"] else float(r["g"]),
                                   "sell_streak": int(r["sell_streak"]), "buy_streak": int(r["buy_streak"]), "known_on": str(r["known_on"])}
            else:
                out["rotation"] = {"decided": False, "note": "no foreign-flow row for that session yet (reported the next business day)"}
        except Exception as e:
            out["rotation"] = {"decided": False, "note": f"rotation not worked: {type(e).__name__}"}
        try:
            b = br.breadth(root, day, market)
            out["breadth"] = {k: b.get(k) for k in ("traded", "advancers", "decliners", "advancing_pct", "advance_decline_ratio", "above_sma50", "new_high_50d", "new_low_50d") if k in b}
        except Exception:
            out["breadth"] = {"note": "breadth could not be worked"}
        out["recent_flags"] = waves.recent_flags(ctx.con, market)
        out["definition"] = waves.DEFINITION
        out["source"] = "quant/waves.py (thresholds are percentiles of the 2004-2021 sample, point in time)"
        return out
    except Exception as e:
        return {"error": repr(e)[:200], "call_ref": ctx.call_ref, "wave": False, "note": "the wave test could not be worked"}


TOOLS = [
    Tool("macro_attribution", "read",
         "Splits one session's index move (Nifty 500 for IN, S&P 500 for US) into parts that add up: crude (Brent), the rupee (USDINR), the US 10-year yield, "
         "the Nasdaq overnight, foreign flows (FII) and the Asian peers (Kospi, Taiex, Nikkei, Hang Seng), plus 'unexplained'. Betas are a ridge regression over the 250 sessions "
         "BEFORE the day. A part that is null is unavailable (never zero); under 20 observations the count is given and no conclusion. Result keys: call_ref, market, session, "
         "total_pct, parts{name:{pct,beta,factor_move,n,note}}, explained_pct, unexplained_pct (parts + unexplained = total), dominant, r2_window, recent. An association, "
         "not a proof of cause. Quote figures exactly and cite the call_ref.",
         {"market": MARKET, "date": DATE}, (), macro_attribution),
    Tool("wave_detector", "read",
         "Did the whole market move as one wave, or did foreign money rotate? A WAVE: extreme breadth (advancing share in the top or bottom 2.5% of earlier sessions), low spread "
         "around the common move, and the market part larger than the own part for most of the 500 most-traded names; thresholds are percentiles of the earlier history "
         "(2004-2021 sample, point in time). A ROTATION: foreign flows switch from a selling streak to unusually large buying (or the reverse) while India diverges from "
         "the Asian peers; known the next business day. Result keys: call_ref, market, session, wave, direction, decided, stats, thresholds, conditions, n_reference, rotation, "
         "breadth, recent_flags, definition. On a wave day a holding's move says little about the holding. Cite the call_ref.",
         {"market": MARKET, "date": DATE}, (), wave_detector),
]


def _register_lens() -> None:
    try:
        from pflab.quant import waves
        waves.register_lens()
    except Exception:
        pass


_register_lens()
