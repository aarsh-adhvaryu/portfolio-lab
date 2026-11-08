"""S79b item 17: the seat manager. Every few minutes (app open) it reads the mode, plans which local seat should be resident and, only when
configs/s79b.toml [seats] manage = true, carries the plan out (Ollama keep_alive; a llama server only after every guard). The plan and what was done are kept
in `seat_event_s79`. With manage = false (the default) it records the plan and touches nothing. Switch: [seats] on."""
from __future__ import annotations

from pflab.service.jobs import Ctx, Interval, Job, register


def _seats(ctx: Ctx) -> dict:
    from pflab import markets
    from pflab.llm import seats, server
    sw = seats.switch()
    if not sw.get("on", True):
        return {"skipped": "seats are off ([seats] on = false)"}
    market, mode = markets.primary(ctx.now)
    free = server.free_ram_gb()
    plan = seats.for_mode(mode)
    events = []
    if sw.get("manage", False) and plan["action"] == "swap":
        events = seats.apply(plan)
    last = ctx.con.execute("SELECT mode, action, reason FROM seat_event_s79 WHERE market=? ORDER BY event_id DESC LIMIT 1", [market]).fetchone()
    same = last is not None and not events and tuple(last) == (mode, plan["action"], (plan.get("reason") or "")[:300])
    n = 0 if same else seats.log_events(ctx.con, market, ctx.now, mode, plan, events, free)     # a repeated 'keep' every 5 minutes is not a new fact
    return {"market": market, "mode": mode, "action": plan["action"], "want": plan.get("want"), "applied": [e["action"] for e in events if e.get("applied")],
            "reason": plan.get("reason", ""), "events": n, "managed": bool(sw.get("manage", False))}


register(Job("seats_mode", Interval(5, weekdays_only=False), _seats, "plans (and, when switched on, performs) the FAST/THINKER local model swap for the mode", cooldown_minutes=5))
