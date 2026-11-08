"""baseline_lab: the plain rule book the lab measures every challenger against (needs no proven edge).

Hold the most liquid names and the index ETFs, size each by its risk (1 / volatility), keep to the position caps, and cut risk when the fall gauge fires.
It is the lab's reading of the live baseline (`pflab/core/policy.py`): same ideas, but over a point-in-time liquid universe because the replay starts with an empty book.
"""
from toolkit import inverse_vol, volatility, cap_and_fill, fall_gauge, scale, rank_top

PARAMS = {}


def decide(state, forecasts, sims, storylines, params=None):
    p = {"n_stocks": 30, "gauge_cut": 0.25, "invested": 0.95}
    p.update(params or {})
    prices = state["prices"]
    meta = state["meta"]
    stocks = [k for k in state["universe"] if not meta[k]["etf"]]
    etfs = [k for k in state["universe"] if meta[k]["etf"] and meta[k]["symbol"] != "GOLDBEES"]
    liquid = rank_top({k: float(state["turnover"][k].tail(250).median()) for k in stocks}, p["n_stocks"])
    names = liquid + etfs
    if not names:
        return {}
    w = cap_and_fill(inverse_vol(names, volatility(prices[names])), state["caps"], 0.10, budget=p["invested"])
    if fall_gauge(state["index"]):
        w = scale(w, 1.0 - p["gauge_cut"])
    return w
