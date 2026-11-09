"""swing_momentum_continuation (S81 B5, registered in docs/protocols/s81_selling_swing_protocol.md section 4): a lab candidate for the swing sleeve; it never acts without the A50 promotion.

Idea: a liquid share that closes at a new 55-session high while its 126-session return is positive tends to run a little further. Buy the strongest such names, with a stop, a target
and a time exit, all measured from the fill. The parameters are FIXED by the protocol (no grid: one variant, one trial).
"""
RULE = {"high_window": 55, "trend_window": 126, "stop": 0.08, "target": 0.16, "max_days": 30}
CADENCE = "daily"
PARAMS = {}


def decide(state, forecasts, sims, storylines, params=None):
    p = dict(RULE, weight=0.09)
    p.update(params or {})
    out = {"entries": [], "exits": []}
    slots = int(state.get("slots", 0))
    prices = state["prices"]
    if slots <= 0 or len(prices) <= p["trend_window"]:
        return out
    meta = state["meta"]
    held = set(state.get("positions", {}))
    names = [k for k in state["universe"] if not meta[k]["etf"] and k not in held]
    if not names:
        return out
    px = prices[names]
    last = px.iloc[-1]
    high = px.tail(p["high_window"]).max()
    ret = last / px.iloc[-1 - p["trend_window"]] - 1.0
    cand = {}
    for k in names:
        if last[k] >= high[k] and ret[k] > 0:
            cand[k] = float(ret[k])
    for k in sorted(cand, key=lambda x: (-cand[x], x))[:slots]:
        out["entries"].append({"key": k, "weight": p["weight"], "stop": p["stop"], "target": p["target"], "max_days": p["max_days"]})
    return out
