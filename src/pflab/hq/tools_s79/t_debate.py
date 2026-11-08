"""S79 item 12 tools: `debate` (a bull and a bear on the local model argue a contested stock; only the disagreements come back) and `bear_scorecard`."""
from __future__ import annotations

from pflab.hq.tools import Ctx, Tool, _s


def _market(a: dict) -> str:
    m = (a.get("market") or "IN").strip().upper()
    return m if m in ("IN", "US") else "IN"


def debate_tool(ctx: Ctx, a: dict) -> dict:
    sym = (a.get("symbol") or "").strip().upper()
    if not sym:
        return {"skipped": "give a symbol"}
    from pflab.hq import tools as T
    try:
        isin = T._isin(ctx, sym)
    except LookupError as e:
        return {"skipped": str(e)}
    try:
        from pflab.agents import debate
        return debate.debate_symbol(ctx.rt, _market(a), sym, isin, ctx.now, topic=(a.get("topic") or "").strip(), case_id=(ctx.case_ids[0] if ctx.case_ids else None))
    except Exception as e:                                   # a tool in a pass never raises on a missing model or missing data
        return {"skipped": "local model unavailable" if "Ollama" in type(e).__name__ else f"{type(e).__name__}: {str(e)[:160]}"}


def scorecard_tool(ctx: Ctx, a: dict) -> dict:
    from pflab.agents import debate
    try:
        return debate.bear_scorecard(ctx.con, _market(a))
    except Exception as e:
        return {"skipped": f"{type(e).__name__}: {str(e)[:160]}"}


TOOLS = [
    Tool("debate", "read", "A bull and a bear argue a contested stock on the LOCAL model from one block of numbers made by code (every number cited by evidence id, "
         "a draft the numeric guard rejects is dropped). Returns ONLY the points they disagree on, with the evidence ids each side relied on, and the bear's one "
         "testable warning (scored later by code). Use it when the readings conflict before deciding; it writes only its own debate tables.",
         {"market": _s("market code", enum=["IN", "US"]), "symbol": _s("symbol of a held or listed stock", 20), "topic": _s("the question being decided, optional", 200)},
         (), debate_tool),
    Tool("bear_scorecard", "read", "How often the bear's scored warnings came true against the chance rate for the same stocks. Under 20 resolved: the count only, no conclusion.",
         {"market": _s("market code", enum=["IN", "US"])}, (), scorecard_tool),
]
