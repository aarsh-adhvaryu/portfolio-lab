"""S79b item 18C tool: `provenance` (read). For one paper decision: the chain of sources behind it and the credit each earned; with no decision: the source scorecard.

Result keys (stable; agent S's adapters and the weekly review read them):
  overall (no decision_id)  {"market", "horizon_days", "min_n", "scorecard": [{"source_kind", "decision_kind", "n", ("hits", "hit_rate", "skeptical_rate",
                            "mean_outcome_pct" only from min_n credited decisions) | "note"}], "lines": [plain-word sentences made by code], "decisions_with_provenance",
                            "decisions_credited", "call_id"}
  one decision              {"decision_id", "found", "action", "symbol", "status", "made_at", "n_sources", "sources": [{"source_kind", "source_id", "role", "weight",
                            "direction", "supports_decision", "credit": [{"horizon_days", "decision_outcome", "source_was_right", "contribution_pct"}], "detail"}], "call_id"}
  off                       {"off": true}
source_kind is one of tool:<name>, agent:<role>, model:<name>, forecaster:<name>, bear_warning, debate, transmission, chain:<type>, claim:<kind>, situation_report,
allocation_target. Credit is by code on the scored decision (see paper/provenance.py); no model makes a number or a verdict.
"""
from __future__ import annotations

from pflab.hq.tools import Ctx, Tool, _i, _s


def provenance(ctx: Ctx, a: dict) -> dict:
    try:
        from pflab.paper import provenance as pv
        if not pv.on():
            return {"off": True}
        con = ctx.con
        if not pv._has(con, "decision_provenance_s79"):
            return {"note": "no provenance record yet on this install", "call_id": ctx.call_ref}
        if a.get("decision_id"):
            out = pv.chain(con, int(a["decision_id"]))
            out["call_id"] = ctx.call_ref
            return out
        market = str(a.get("market") or "IN").upper()
        h = a.get("horizon_days")
        sc = pv.scorecard(con, market, int(h) if h else None)
        return {"market": market, "horizon_days": sc["horizon_days"], "min_n": sc["min_n"], "scorecard": sc["rows"][:60], "lines": pv.lines(con, market, sc["horizon_days"]),
                "decisions_with_provenance": int(con.execute("SELECT count(DISTINCT decision_id) FROM decision_provenance_s79").fetchone()[0]),
                "decisions_credited": int(con.execute("SELECT count(DISTINCT decision_id) FROM source_credit_s79").fetchone()[0]), "call_id": ctx.call_ref}
    except Exception as e:                                        # a probe or a store without the tables gets a harmless answer
        return {"note": f"provenance is not readable now ({type(e).__name__})", "call_id": getattr(ctx, "call_ref", None)}


TOOLS = [
    Tool("provenance", "read", "Which sources stood behind a paper decision (tool calls, forecasts in force, bear warning, situation claims and chains, agents, model, allocation "
         "target) and how each was credited when the decision was scored; with no decision_id, the running scorecard per source kind with plain-word lines such as 'the bear "
         "was right on 3 of 5 warnings before sells' (counts only under 20 credited decisions). Use it to weigh which sources to trust before deciding.",
         {"decision_id": _i("a paper decision id, optional (omit for the overall scorecard)", 1, 10 ** 9), "market": _s("market code", enum=["IN", "US"]),
          "horizon_days": _i("scoring horizon in days: 7, 28, 84 or 182 (default 28)", 1, 400)}, (), provenance),
]
