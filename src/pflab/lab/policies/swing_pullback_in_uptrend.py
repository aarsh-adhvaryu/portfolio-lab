"""swing_pullback_in_uptrend (S81 B5, registered in docs/protocols/s81_selling_swing_protocol.md section 4): a lab candidate for the swing sleeve; it never acts without the A50 promotion.

Idea: in a share that is in an uptrend (above its 200-session average, its 50-session average above the 200-session one) a sharp 5-session fall tends to be bought back. Buy the most
oversold relative to the share's own daily volatility, with a stop, a target and a time exit measured from the fill. The parameters are FIXED by the protocol (no grid).
"""
RULE = {"sma_fast": 50, "sma_slow": 200, "pullback_days": 5, "pullback": -0.05, "stop": 0.07, "target": 0.10, "max_days": 15}
CADENCE = "daily"
PARAMS = {}


def decide(state, forecasts, sims, storylines, params=None):
    p = dict(RULE, weight=0.09)
    p.update(params or {})
    out = {"entries": [], "exits": []}
    slots = int(state.get("slots", 0))
    prices = state["prices"]
    if slots <= 0 or len(prices) <= p["sma_slow"]:
        return out
    meta = state["meta"]
    held = set(state.get("positions", {}))
    names = [k for k in state["universe"] if not meta[k]["etf"] and k not in held]
    if not names:
        return out
    px = prices[names]
    last = px.iloc[-1]
    slow = px.tail(p["sma_slow"]).mean()
    fast = px.tail(p["sma_fast"]).mean()
    ret = last / px.iloc[-1 - p["pullback_days"]] - 1.0
    vol = px.pct_change().tail(20).std()
    cand = {}
    for k in names:
        if last[k] > slow[k] and fast[k] > slow[k] and ret[k] <= p["pullback"] and vol[k] > 0:
            cand[k] = float(ret[k] / vol[k])
    for k in sorted(cand, key=lambda x: (cand[x], x))[:slots]:
        out["entries"].append({"key": k, "weight": p["weight"], "stop": p["stop"], "target": p["target"], "max_days": p["max_days"]})
    return out
