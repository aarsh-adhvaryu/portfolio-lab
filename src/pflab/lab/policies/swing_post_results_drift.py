"""swing_post_results_drift (S81 B5, registered in docs/protocols/s81_selling_swing_protocol.md section 4): a lab candidate for the swing sleeve; it never acts without the A50 promotion.

Idea: a share whose financial results became known today and which rose at least 4% on at least twice its usual traded value tends to keep drifting up for a few weeks. Buy it (the
fill is the next close), with a stop, a target and a time exit measured from the fill. `state["results"]` holds, per name, the sessions on whose close its results were known (the
dissemination time where the file has one, else the news time; empty before 2011, so then no trade). The parameters are FIXED by the protocol (no grid).
"""
RULE = {"react": 0.04, "volume_mult": 2.0, "volume_window": 60, "stop": 0.08, "target": 0.15, "max_days": 30}
CADENCE = "daily"
PARAMS = {}


def decide(state, forecasts, sims, storylines, params=None):
    p = dict(RULE, weight=0.09)
    p.update(params or {})
    out = {"entries": [], "exits": []}
    slots = int(state.get("slots", 0))
    prices = state["prices"]
    turn = state["turnover"]
    if slots <= 0 or len(prices) <= p["volume_window"] + 1:
        return out
    meta = state["meta"]
    held = set(state.get("positions", {}))
    day = state["day"]
    cand = {}
    for k, days in state.get("results", {}).items():
        if k in held or k not in meta or meta[k]["etf"] or not days or days[-1] != day:
            continue
        s = prices[k]
        ret = float(s.iloc[-1] / s.iloc[-2] - 1.0)
        usual = float(turn[k].iloc[-1 - p["volume_window"]:-1].median())
        today = float(turn[k].iloc[-1])
        if ret >= p["react"] and usual > 0 and today >= p["volume_mult"] * usual:
            cand[k] = ret
    for k in sorted(cand, key=lambda x: (-cand[x], x))[:slots]:
        out["entries"].append({"key": k, "weight": p["weight"], "stop": p["stop"], "target": p["target"], "max_days": p["max_days"]})
    return out
