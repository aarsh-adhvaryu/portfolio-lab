"""S79b item 17 tools: `seat_status` (which local model sits in each seat and why) and `cost_per_act` (seconds, tokens and rupees per useful act, by seat).

Result keys (stable, read by the situation adapters):
  seat_status: {"mode", "seats": {"fast"|"thinker": {"key", "model", "backend", "fallback", "reason", "requested"}}, "free_ram_gb", "plan": {"action", "want", "reason"},
                "server": {"running", "model"}, "teacher": {"examples", "scored"}}   or {"off": true}
  cost_per_act: {"market", "days", "useful_acts", "seats": {"fast"|"thinker"|"cloud": {"calls", "seconds", "tokens", "per_useful_act": {"seconds", "tokens", "rupees"}}},
                 "by_kind": [...], "escalations": {...}, "note"}   or {"off": true}
"""
from __future__ import annotations

from pflab.hq.tools import Ctx, Tool, _i, _s


def _market(a: dict) -> str:
    m = (a.get("market") or "IN").strip().upper()
    return m if m in ("IN", "US") else "IN"


def seat_status_tool(ctx: Ctx, a: dict) -> dict:
    from pflab.llm import seats, server, teacher
    if not seats.is_on():
        return {"off": True}
    market = _market(a)
    try:
        from pflab import markets
        _m, mode = markets.primary(ctx.now)
    except Exception:
        mode = "deep"
    out: dict = {"market": market, "mode": mode, "seats": {}}
    for s in seats.SEATS:
        r = seats.seat(s)
        out["seats"][s] = {k: r[k] for k in ("key", "model", "backend", "fallback", "reason", "requested")}
    fr = server.free_ram_gb()
    out["free_ram_gb"] = None if fr != fr else round(fr, 1)
    try:
        p = seats.for_mode(mode, state=dict(seats.STATE))
        out["plan"] = {"action": p["action"], "want": p.get("want"), "reason": p.get("reason", "")}
    except Exception as e:
        out["plan"] = {"action": "none", "want": None, "reason": f"{type(e).__name__}: {str(e)[:100]}"}
    r = server.running()
    out["server"] = {"running": bool(r), "model": (r or {}).get("model")}
    try:
        out["teacher"] = teacher.stats(ctx.con, market)
    except Exception:
        out["teacher"] = {"examples": 0, "scored": 0}
    return out


def cost_tool(ctx: Ctx, a: dict) -> dict:
    from pflab.llm import cost, seats
    if not seats.is_on():
        return {"off": True}
    try:
        return cost.cost_view(ctx.con, _market(a), int(a.get("days") or 7), ctx.now)
    except Exception as e:                                   # a tool in a pass never raises on a missing table
        return {"skipped": f"{type(e).__name__}: {str(e)[:160]}"}


TOOLS = [
    Tool("seat_status", "read", "Which local model sits in the FAST seat (market hours) and the THINKER seat (post-close and deep), whether a seat fell back to qwen3:8b and why "
         "(model missing, RAM under the floor), free RAM, what the mode wants loaded now, and how many cloud answers are kept as teacher examples. Read only; loads nothing.",
         {"market": _s("market code", enum=["IN", "US"])}, (), seat_status_tool),
    Tool("cost_per_act", "read", "What a useful act costs, by seat: seconds of the local card, tokens and rupees (cloud only; the local model has no metered cost) divided by the "
         "useful agenda acts in the window, plus the same by kind of act and how often local answers were enough versus escalated to the cloud. Code only.",
         {"market": _s("market code", enum=["IN", "US"]), "days": _i("window in days", 1, 90)}, (), cost_tool),
]
