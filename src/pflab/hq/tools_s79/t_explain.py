"""S79 item 7: explain a move with explicit, tested tools. Four read tools; each returns figures worked by code and its own `call_ref` (the id the tool loop journals the
call under in `hq_tool_calls`). An agent that writes a number must cite that id; `hq/explain.py` checks it, and the tool loop's own `_checked` already drops a sentence
whose numbers are not in anything read this pass (the results are in `ctx.source`)."""
from __future__ import annotations

from datetime import date, datetime, time

from pflab.hq.tools import Tool, _n, _s

INDEX_PREFIX = "INDEX:"


def _day(ctx, market: str, a: dict):
    from pflab import markets
    m = markets.get(market)
    if a.get("date"):
        d = date.fromisoformat(str(a["date"])[:10])
    else:
        d = m.session_closed_by(ctx.now)
    return m, d


def _target(ctx, a: dict):
    """(market code, Market, day, isin or INDEX key, symbol label) or a harmless dict when the input is not enough."""
    from pflab import markets
    from pflab.hq import tools as tl
    market = str(a.get("market") or "IN").upper()
    if market not in markets.codes():
        return {"note": f"unknown market {market!r}; known: {', '.join(markets.codes())}"}
    sym = (a.get("symbol") or "").strip()
    if not sym:
        return {"note": "give a symbol (a held or watched name, or the market's index)"}
    m, d = _day(ctx, market, a)
    if d > ctx.now.date():
        return {"note": f"{d} is in the future"}
    if sym.upper() in {m.index.upper(), m.benchmark.upper()} or sym.upper().startswith("NIFTY"):
        return market, m, d, INDEX_PREFIX + (sym.upper() if sym.upper().startswith("NIFTY") else m.index.upper()), sym.upper()
    return market, m, d, tl._isin(ctx, sym), sym.upper()


def _head(ctx, market: str, sym: str, d: date) -> dict:
    return {"call_ref": ctx.call_ref, "market": market, "symbol": sym, "day": str(d)}


def _prior_close(ctx, m, isin: str, d: date):
    from pflab.quant import decompose
    if isin.startswith(INDEX_PREFIX):                          # an index has no bhavcopy row: the last bar of the previous session, if it was recorded
        from pflab.quant import trajectory as tj
        prev = tj.load_bars(ctx.con, m.code, isin, m.previous_session(d))
        return float(prev["close"].iloc[-1]) if len(prev) else None
    return decompose.prior_close(ctx.rt.data_root, isin, d)


def trajectory(ctx, a: dict) -> dict:
    from pflab.quant import trajectory as tj
    t = _target(ctx, a)
    if isinstance(t, dict):
        return {"call_ref": ctx.call_ref, **t}
    market, m, d, isin, sym = t
    bars = tj.load_bars(ctx.con, market, isin, d, asof=ctx.now)
    out = _head(ctx, market, sym, d)
    if bars.empty:
        return {**out, "n_bars": 0, "note": "no minute bars recorded for that name and day (the bars_1m job records them after each session when Kite is logged in); "
                                              "nothing is inferred about the day's path"}
    res = tj.trajectory(bars, _prior_close(ctx, m, isin, d), m.open, m.close, k=float(a.get("k") or tj.K_DEFAULT), asof=ctx.now)
    return {**out, "source": "bars_1m: the broker's 1-minute bars, as recorded", **res}


def decompose_move(ctx, a: dict) -> dict:
    from pflab.quant import decompose
    t = _target(ctx, a)
    if isinstance(t, dict):
        return {"call_ref": ctx.call_ref, **t}
    market, m, d, isin, sym = t
    if isin.startswith(INDEX_PREFIX):
        return {**_head(ctx, market, sym, d), "note": "an index is the market: there is nothing to split it from"}
    return {**_head(ctx, market, sym, d), **decompose.decompose(ctx.rt.data_root, isin, d, market)}


def align_events(ctx, a: dict) -> dict:
    from datetime import timedelta
    from pflab.quant import align, trajectory as tj
    t = _target(ctx, a)
    if isinstance(t, dict):
        return {"call_ref": ctx.call_ref, **t}
    market, m, d, isin, sym = t
    out = _head(ctx, market, sym, d)
    if isin.startswith(INDEX_PREFIX):
        return {**out, "note": "filings and news are about companies; ask for a stock"}
    window = int(a.get("window_minutes") or align.WINDOW_MIN)
    prev_close = datetime.combine(m.previous_session(d), m.close)
    end = datetime.combine(d, m.close)
    events = align.filings(ctx.rt.data_root, isin, prev_close, end) + align.news(ctx.con, isin, prev_close, end)
    events = sorted(events, key=lambda e: e["at"])
    bars = tj.load_bars(ctx.con, market, isin, d, asof=ctx.now)
    brief = [{"at": e["at"].strftime("%d %b %H:%M"), "kind": e["kind"], "what": e["what"], "headline": e["headline"]} for e in events[:8]]
    if bars.empty:
        return {**out, "n_bursts": 0, "note": "no minute bars recorded, so no bursts to line up", "events_since_previous_close": len(events), "events": brief,
                "event_times": "filings at BSE dissemination time, news at published time"}
    res = align.align(tj.burst_events(bars, float(a.get("k") or tj.K_DEFAULT)), events, d, prev_close, m.open, window)
    return {**out, **res, "events_since_previous_close": len(events), "events": brief,
            "event_times": "filings at BSE dissemination time, news at published time (as recorded)"}


def breadth(ctx, a: dict) -> dict:
    from pflab import markets
    from pflab.quant import breadth as br
    market = str(a.get("market") or "IN").upper()
    if market not in markets.codes():
        return {"call_ref": ctx.call_ref, "note": f"unknown market {market!r}"}
    m, d = _day(ctx, market, a)
    if d > ctx.now.date():
        return {"call_ref": ctx.call_ref, "note": f"{d} is in the future"}
    return {"call_ref": ctx.call_ref, **br.breadth(ctx.rt.data_root, d, market)}


_COMMON = {"market": _s("the market, IN or US (default IN)", 4), "date": _s("the session, YYYY-MM-DD (default: the last session that has closed)", 10)}
_SYM = {"symbol": _s("a held or watched stock's symbol, or the market's index (NIFTY 50)", 24)}

TOOLS = [
    Tool("trajectory", "read", "How one session went for one name, from its 1-minute bars, by code: the gap against the prior close, the opening drive (first 30 minutes), trend day or range day "
         "(the rule is in the result), the time of the high and the low, where the close sits in the day's range, and the bursts (minutes far beyond the day's usual moves, with times). "
         "Missing minutes are counted, never filled. Quote figures exactly as given and cite the call_ref.",
         {**_COMMON, **_SYM, "k": _n("burst threshold in standard deviations of the day's minute moves", 2, 10)}, ("symbol",), trajectory),
    Tool("decompose_move", "read", "Split one session's move of a stock into the market's part (beta x Nifty 500), the sector's part beyond the market, and its own part, by code, with betas from "
         "the sessions before the day only. Quote figures exactly as given and cite the call_ref.",
         {**_COMMON, **_SYM}, ("symbol",), decompose_move),
    Tool("align_events", "read", "Line the day's bursts up against what had been published: exchange filings at their dissemination time and news at its published time. Says which events came "
         "before each burst, and which bursts have none (unexplained: the data does not say why). Quote figures exactly as given and cite the call_ref.",
         {**_COMMON, **_SYM, "window_minutes": {"type": "integer", "description": "how far back before a burst an event still counts", "minimum": 5, "maximum": 240}, "k": _n("burst threshold", 2, 10)},
         ("symbol",), align_events),
    Tool("breadth", "read", "How wide the session's move was across the exchange's names: advancers and decliners, the share above their own 20 and 50 day averages, new 50 day highs and lows, "
         "by code from the daily files. Quote figures exactly as given and cite the call_ref.", _COMMON, (), breadth),
]
