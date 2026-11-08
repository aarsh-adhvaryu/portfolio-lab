"""S79 item 10 tools: `transmission` (what the other side's last session means for the open here) and `lead_lag` (who moves first).
Both read only; both work with {} and return a harmless dict when data is missing."""
from __future__ import annotations

from datetime import date

from pflab.hq.tools import Ctx, Tool, _i, _s


def _day(ctx: Ctx, a: dict, market: str) -> date:
    from pflab import markets
    if a.get("date"):
        return date.fromisoformat(str(a["date"]))
    return markets.get(market).last_session_on_or_before(ctx.asof)


def transmission(ctx: Ctx, a: dict) -> dict:
    try:
        from pflab.quant import transmission as tr
        market = a.get("market") or "IN"
        out = tr.expected_open_gap(ctx.con, _day(ctx, a, market), market, root=ctx.rt.data_root)
        out["source"] = "quant/transmission.py (one-factor OLS on the last 250 sessions; legs for reading)"
        return out
    except Exception as e:
        return {"error": repr(e)[:200], "expected_gap_pct": None, "note": "transmission could not be computed"}


def lead_lag(ctx: Ctx, a: dict) -> dict:
    try:
        from pflab import markets
        from pflab.quant import leadlag
        market = a.get("market") or "IN"
        asof = _day(ctx, a, market) if a.get("date") else ctx.asof
        window = int(a.get("window") or 500)
        root = ctx.rt.data_root
        if a.get("sector"):
            out = leadlag.lead_lag_sector(root, a["sector"], asof, window)
        else:
            x, y = a.get("symbol_a") or "US_SP500", a.get("symbol_b") or "NIFTY50_PRICE"
            out = leadlag.lead_lag(root, x, y, asof, window)
            if a.get("minutes"):
                out["minute_level"] = leadlag.minute_lead_lag(ctx.con, x, y, asof)
        out["market"] = market
        out["source"] = "quant/leadlag.py (cross-correlation at -5..+5 sessions, Bartlett and shuffle rule)"
        return out
    except Exception as e:
        return {"error": repr(e)[:200], "reliable": False, "verdict": "lead-lag could not be computed"}


TOOLS = [
    Tool("transmission", "read",
         "What the US session that just closed means for the Indian open: the expected opening gap of the Nifty 50 (percent, with its "
         "standard deviation), from the S&P 500 move and a one-year regression; plus the other drivers as legs (Nasdaq, VIX, dollar, crude, "
         "Indian ADRs, India fund), sector links (US sector ETF to Indian sector index, each with its reason) and ADR to NSE-name links. "
         "Point in time: only US closes before the NSE open. Under 20 sessions: the count, no conclusion. An estimate, not a promise.",
         {"market": _s("the market whose open is forecast", enum=("IN", "US")), "date": _s("the session morning, YYYY-MM-DD (default the last session)", 10)},
         (), transmission),
    Tool("lead_lag", "read",
         "Who moves first: cross-correlation of daily returns at lags -5..+5 sessions between two series (a global key such as US_SP500 or "
         "ADR_INFY, an index key such as NIFTY50_PRICE or SECTOR_IT_PRICE, or an NSE symbol), or between a sector and its links. Says 'no "
         "reliable lead' when nothing passes the Bartlett, shuffle, size and two-halves rule. With {} it asks whether the S&P 500 leads the Nifty 50.",
         {"symbol_a": _s("first series", 40), "symbol_b": _s("second series", 40), "sector": _s("a sector such as IT, PHARMA, PRIVATE_BANK, METAL", 30),
          "market": _s("the market of the as-of date", enum=("IN", "US")), "window": _i("common sessions to use", 60, 2500),
          "date": _s("as-of date YYYY-MM-DD (default today)", 10), "minutes": {"type": "boolean", "description": "also test 1-minute bars when the store has them"}},
         (), lead_lag),
]
