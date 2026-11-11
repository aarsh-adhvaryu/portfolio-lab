"""The replay side of the S82 C4 studies (protocol `docs/protocols/s82_harvest_stops_protocol.md`). SELF-CONTAINED beside `swing.py`, `engine.py`, `toolkit.py` and `harvest_replay.py`
(numpy, pandas): the same file runs in the Docker sandbox (the lab runner's `mode: "c4"`) and on the host in the tests. It imports nothing from pflab but those siblings.

    BuyHoldBook         the buy-and-hold STOCK book: at the first moment 20 liquid names are eligible (point in time), buy them once, risk-sized (1 / volatility, at most 10% each); never
                        rebalance, never replace a name, no new money. With `stops` each entry carries the live exit plan's risk-sized stop; without, none.
    claim_a(...)        harvesting WITH versus WITHOUT for an arm ("index": the index ETF held; "stocks": the BuyHoldBook), monthly-cadence machinery with `deploy_once`
    claim_b(...)        the BuyHoldBook with versus without stops, daily-cadence machinery (a stop fires on the day's low; the proceeds wait as cash; no re-entry)
    run_all(...)        both claims on one panel: what the lab runner writes to `out.json`
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

try:                                                               # in the sandbox the files sit side by side; on the host they are in the package
    import engine as E
    import swing as S
    import toolkit as T
except ImportError:                                                # pragma: no cover - exercised on the host
    from pflab.lab import engine as E
    from pflab.lab import swing as S
    from pflab.lab import toolkit as T

BOOK = {"n_names": 20, "turnover_window": 250, "min_history": 300, "vol_window": 250, "max_weight": 0.10, "invested": 0.98, "max_positions": 20, "max_new_per_day": 20}
STOPS = {"sigmas": 2.0, "horizon_days": 63, "vol_window": 250, "min_pct": 0.12, "max_pct": 0.35, "fallback_vol": 0.30}
BOOTSTRAP = {"block": 21, "resamples": 5000, "seed": 82}


def stop_distance(prices: pd.Series, p: Optional[dict] = None) -> float:
    """The live exit plan's risk-sized stop distance (`core/exits._levels`): `sigmas` standard deviations of the move over `horizon_days`, from the name's own annual volatility over its last
    `vol_window` sessions (0.30 when it has under 60 returns), never closer than `min_pct`, never further than `max_pct`."""
    p = {**STOPS, **(p or {})}
    x = prices.dropna()
    x = x[x > 0].tail(int(p["vol_window"]) + 1)
    if len(x) < 61:
        vol = float(p["fallback_vol"])
    else:
        vol = float(max(np.std(np.diff(np.log(x.to_numpy())), ddof=1) * math.sqrt(252.0), 0.05))
    return float(min(max(p["sigmas"] * vol * math.sqrt(p["horizon_days"] / 252.0), p["min_pct"]), p["max_pct"]))


def select_weights(state: dict, book: Optional[dict] = None) -> Dict[str, float]:
    """The book's names and weights at this moment, or {} while fewer than `n_names` shares are eligible: the shares of the state's liquid universe (already: at least `min_history`
    sessions and a price today), the `n_names` with the largest median traded value over `turnover_window`, weighted by 1 / volatility and capped (`cap_and_fill`)."""
    b = {**BOOK, **(book or {})}
    meta = state["meta"]
    stocks = [k for k in state["universe"] if not meta[k]["etf"] and k in state["prices"].columns]
    if len(stocks) < b["n_names"]:
        return {}
    med = {k: float(state["turnover"][k].tail(b["turnover_window"]).median()) for k in stocks}
    names = T.rank_top(med, int(b["n_names"]))
    vol = T.volatility(state["prices"][names], b["vol_window"])
    w = T.inverse_vol(names, vol, 1.0)
    return T.cap_and_fill(w, {k: b["max_weight"] for k in names}, b["max_weight"], budget=b["invested"])


class BuyHoldBook:
    """A decide function with a memory of its own (one instance per run): the first time the names are eligible it buys, and never again."""

    def __init__(self, stops: bool = False, book: Optional[dict] = None, stop_params: Optional[dict] = None):
        self.stops, self.book, self.stop_params = stops, {**BOOK, **(book or {})}, {**STOPS, **(stop_params or {})}
        self.done = False
        self.first_day = None
        self.names: Dict[str, float] = {}
        self.stop_pct: Dict[str, float] = {}

    def decide(self, state, forecasts, sims, storylines, params=None):
        if self.done:
            return {}
        w = select_weights(state, self.book)
        if not w:
            return {}
        self.done, self.first_day, self.names = True, str(state["day"]), dict(w)
        return w                                                                # monthly cadence: the target weights (the replay's `deploy_once` makes it the only one)

    def decide_daily(self, state, forecasts, sims, storylines, params=None):
        if self.done:
            return {"entries": [], "exits": []}
        w = select_weights(state, self.book)
        if not w:
            return {"entries": [], "exits": []}
        self.done, self.first_day, self.names = True, str(state["day"]), dict(w)
        entries = []
        for k in sorted(w, key=lambda x: (-w[x], x)):
            stop = stop_distance(state["prices"][k], self.stop_params) if self.stops else 1.0      # 1.0 = a stop at price zero: never fires
            self.stop_pct[k] = stop
            entries.append({"key": k, "weight": float(w[k]), "stop": stop, "target": 1000.0, "max_days": 10 ** 7})
        return {"entries": entries, "exits": []}


# --- the measures ------------------------------------------------------------------------------------------------------------------------------

def worst_fall(v: pd.Series) -> float:
    """Peak to trough of the value path, as a positive share (0.35 = a 35% fall)."""
    return float(-(v / v.cummax() - 1.0).min())


def summary(run: dict, t0, cfg: dict) -> dict:
    L, liq = S.liq_cagr(run, t0, cfg)
    book = run["book"]
    v = run["value"]
    return {"liq_cagr": L, "liq_value": liq["value"], "tax_paid": float(book.tax), "liq_tax": liq["tax"], "charges": float(book.charges + liq["charges"]), "slippage": float(book.slip_paid),
            "end_value": float(v.iloc[-1]), "worst_fall": worst_fall(v), "traded": float(book.traded), "start": str(v.index[0].date()), "end": str(v.index[-1].date()),
            "stops_fired": float(sum(1 for t in run.get("trades", []) if t.get("why") == "stop")), "n_trades": float(len(run.get("trades", [])))}


def arm_cfg(cfg: Optional[dict]) -> dict:
    c = {**E.DEFAULT_CFG, **S.SWING_CFG, **(cfg or {})}
    c["slippage"] = c.get("slippage") or "liquidity"
    return c


def claim_a(arm: str, data: dict, start, end, cfg: Optional[dict] = None, book: Optional[dict] = None) -> dict:
    """Harvesting off versus on for one arm. -> {on, off, dL, tax_saved, extra_costs, accounting_ok, t, p, n, books}. The `t` is the paired block bootstrap of the daily return difference of
    the two LIQUIDATION-MARKED paths (each session's value if everything were sold that session), so a harvest shows on the day it is done."""
    c = {**arm_cfg(cfg), "track_liq": True, "deploy_once": True}
    runs, names = {}, {}
    for flag in (False, True):
        if arm == "index":
            runs[flag] = S.hold_run(data, start, end, c, flag)
        elif arm == "stocks":
            bk = BuyHoldBook(False, book)
            runs[flag] = S.replay_daily(bk.decide, {}, data, start, end, c, None, "monthly", flag)
            names[flag] = {"first_day": bk.first_day, "names": bk.names}
        else:
            raise ValueError(f"unknown arm {arm!r}")
    t0 = max(r["value"].index[0] for r in runs.values())
    res = {flag: summary(r, t0, c) for flag, r in runs.items()}
    on, off = res[True], res[False]
    saved = (off["tax_paid"] + off["liq_tax"]) - (on["tax_paid"] + on["liq_tax"])
    extra = (on["charges"] - off["charges"]) + (on["slippage"] - off["slippage"])
    pt = S.paired_t(runs[True]["liq_path"], runs[False]["liq_path"], BOOTSTRAP["block"], BOOTSTRAP["resamples"], BOOTSTRAP["seed"])
    out = {"arm": arm, "on": on, "off": off, "dL": on["liq_cagr"] - off["liq_cagr"], "tax_saved": saved, "extra_costs": extra, "accounting_ok": bool(saved > extra),
           "t": pt["t"], "p": pt["p"], "n": pt["n"], "mean_daily_diff": pt["mean_daily"]}
    if names:
        out["book"] = names[False]
        out["same_names"] = bool(names[False]["names"] == names[True]["names"])
    return out


def claim_b(data: dict, start, end, cfg: Optional[dict] = None, book: Optional[dict] = None, stop_params: Optional[dict] = None) -> dict:
    """The stock book without stops and with the live exit plan's risk-sized stops (daily cadence). Harvesting is off in both arms (the live default)."""
    c = arm_cfg(cfg)
    c["sizing"] = {"max_positions": int(BOOK["max_positions"]), "max_new_per_day": int(BOOK["max_new_per_day"])}
    c["sleeve"] = "longterm"
    c["harvest"] = False
    runs, names = {}, {}
    for stops in (False, True):
        bk = BuyHoldBook(stops, book, stop_params)
        runs[stops] = S.replay_daily(bk.decide_daily, {}, data, start, end, c, None, "daily", False)
        names[stops] = {"first_day": bk.first_day, "names": bk.names, "stop_pct": bk.stop_pct}
    t0 = max(r["value"].index[0] for r in runs.values())
    res = {flag: summary(r, t0, c) for flag, r in runs.items()}
    return {"with_stops": res[True], "without_stops": res[False], "book": {k: v for k, v in names[False].items() if k != "stop_pct"}, "same_names": bool(names[False]["names"] == names[True]["names"]),
            "stop_distances": names[True].get("stop_pct", {})}


def run_all(data: dict, start, end, cfg: Optional[dict] = None) -> dict:
    out = {"a_index": claim_a("index", data, start, end, cfg), "a_stocks": claim_a("stocks", data, start, end, cfg), "b": claim_b(data, start, end, cfg)}
    out["assumptions"] = {"slippage": S.SLIP, "tax": (cfg or {}).get("tax"), "book": BOOK, "stops": STOPS, "bootstrap": BOOTSTRAP, "capital": (cfg or {}).get("capital", E.DEFAULT_CFG["capital"])}
    return out
