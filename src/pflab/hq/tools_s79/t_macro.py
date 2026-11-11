"""S79b item 15 tool: `macro_attribution` (what part of the index move was crude, the rupee, US yields, Nasdaq, foreign flows, Asia). (`wave_detector` was deleted in A60: its
study found no reliable follow-through.) Read only; works with {} and returns a harmless dict when data is missing or the switch is off
(`configs/s79b.toml [waves] on = false` gives {"off": true}). The result carries `call_ref`: a figure quoted from it cites that id.

macro_attribution result keys: call_ref, market, session, index, total_pct (the index move, %), parts {crude|currency|us10y|nasdaq|flows|asia: {label, unit, pct (this part of
  the move, in index percent, or null when unavailable), beta (index % per unit of the factor), factor_move, n (paired observations), note}}, explained_pct,
  unexplained_pct (total minus the parts: parts + unexplained == total), dominant (the largest part or 'unexplained'), r2_window, n_fit, window, method, checks_out,
  recent (the last sessions' total, dominant part), note, source. A null pct is "unavailable" (never zero): flows appear only after the next day's NSDL report."""
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
    from pflab.quant import macro_attr as MA
    return not MA.is_on()


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


TOOLS = [
    Tool("macro_attribution", "read",
         "Splits one session's index move (Nifty 500 for IN, S&P 500 for US) into parts that add up: crude (Brent), the rupee (USDINR), the US 10-year yield, "
         "the Nasdaq overnight, foreign flows (FII) and the Asian peers (Kospi, Taiex, Nikkei, Hang Seng), plus 'unexplained'. Betas are a ridge regression over the 250 sessions "
         "BEFORE the day. A part that is null is unavailable (never zero); under 20 observations the count is given and no conclusion. Result keys: call_ref, market, session, "
         "total_pct, parts{name:{pct,beta,factor_move,n,note}}, explained_pct, unexplained_pct (parts + unexplained = total), dominant, r2_window, recent. An association, "
         "not a proof of cause. Quote figures exactly and cite the call_ref.",
         {"market": MARKET, "date": DATE}, (), macro_attribution),
]
