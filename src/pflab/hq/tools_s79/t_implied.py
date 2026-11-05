"""S79 item 11: three read tools. `implied_dist` (what the index options say, and how far they ran from reality), `cascade` (the Hawkes model once a
fall has started, with its registered finding), `simulate` (portfolio paths for a scenario or a shock, in sessions, with the chance of the 35% fall).
Numbers come from code (quant/implied.py, implied_calibration.py, hawkes.py, risk/montecarlo.py); nothing here is model-made."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from pflab.hq.tools import Tool, Ctx, _i, _n, _s

HAWKES_CONFIG = Path(__file__).resolve().parents[4] / "configs" / "hawkes_market.toml"
SCENARIOS_CONFIG = Path(__file__).resolve().parents[4] / "configs" / "scenarios.toml"
FALL_LEVELS = (5.0, 10.0, 15.0, 20.0)

REGISTERED = ("Registered finding (docs/protocols/hawkes_results.md, S40, passed the pre-registered rules): big Nifty 500 falls (a session of -2% or worse) come in clusters: "
              "170 events in the 2005-14 fit (likelihood-ratio test against random arrival p = 1e-25), 19 in the 2015-19 validation (+35 log-likelihood over random), "
              "57 in 2020-26 (spent years, not evidence). The frozen fit is used here. Limits found by the same study: the model cannot foresee the FIRST fall after a calm "
              "spell (it warned before 71% of all falls in 2005-14, 46% in 2020-26); buying the dip while falls clustered did better, not worse, so the state is "
              "information only and changes neither the dip rule nor regular tranches.")


def _no_option_message(root, market: str) -> str:
    if market != "IN":
        return f"No option data for market {market} on this PC (only the Nifty 50 option chain from NSE is collected)."
    return ("No option-chain data on this PC: derived/implied_probs.parquet is missing (it is built from the NSE F&O bhavcopy in data/fo_daily). "
            "The options say nothing here; the realised frequency of the index is given instead.")


def implied_dist(ctx: Ctx, a: dict) -> dict:
    from pflab.quant import implied, implied_calibration as ic
    market = (a.get("market") or "IN").upper()
    root = ctx.rt.data_root
    asof = ctx.asof
    horizon = int(a.get("horizon", 20))
    levels = (float(a["fall_pct"]),) if a.get("fall_pct") else FALL_LEVELS
    out = {"market": market, "asof": str(asof), "kind": "risk-neutral (what insurance costs), not a forecast"}

    def baseline() -> dict:
        return {f"{lv:g}%": ic.baseline_frequency(root, market, asof, horizon, lv) for lv in levels}

    if not ic.has_option_data(root, market):
        return {**out, "option_data": False, "message": _no_option_message(root, market),
                "realised_frequency_baseline": baseline(), "horizon_sessions": horizon,
                "source": "data/indices (realised closes); no option data to use"}
    if not ctx.shadow:
        try:
            ic.refresh(ctx.con, root, market, asof)
        except Exception as e:                                               # a failed refresh never hides the answer
            out["refresh_problem"] = f"{type(e).__name__}: {str(e)[:100]}"
    last = implied.latest(root, asof)
    if last is None:
        return {**out, "option_data": True, "current": False, "horizon_sessions": horizon,
                "message": "Option data exists on this PC but none is current for this date (the latest kept day is old or its contract expired).",
                "realised_frequency_baseline": baseline(), "source": "quant/implied.py"}
    d = date.fromisoformat(last["date"])
    out.update({"option_data": True, "current": True, "option_day": last["date"], "expiry": last["expiry"], "calendar_days_to_expiry": last["days"],
                "atm_iv": last["atm_iv"], "skew_90_110": last["skew_90_110"], "strikes_used": last["strikes"]})
    try:
        from pflab.data import fo_daily, riskfree
        chain = fo_daily.load_day(d, root)
        dist = implied.distribution(chain, d, riskfree.at(riskfree.monthly_table(root), d)[0]) if chain is not None else None
    except Exception:
        dist = None
    if dist is not None:
        out["index_spot"] = round(dist["spot"], 1)
        out["quantiles"] = implied.quantiles(dist)
    else:
        out["quantiles"] = None
        out["quantiles_note"] = "the day's chain could not be read again; only the kept probabilities are shown"
    falls = {}
    for lv in levels:
        c = ic.calibrated_fall_probability(ctx.con, market, asof, horizon, lv, root=None)
        if dist is not None and c["p_implied"] is None:                      # a level the table does not keep: straight from the distribution
            c["p_implied"] = round(implied.p_fall(dist, lv), 4)
            fit = ic.fit_map(ic.resolved(ctx.con, market, asof))
            c["p_calibrated"] = None if fit["k"] is None else round(ic.apply_map(fit["k"], c["p_implied"]), 4)
            c["n"] = fit["n"]
        c["realised_frequency_baseline"] = ic.baseline_frequency(root, market, asof, c.get("horizon_sessions") or horizon, lv)
        falls[f"{lv:g}%"] = {k: c.get(k) for k in ("p_implied", "p_calibrated", "n", "expiries", "horizon_sessions", "note", "realised_frequency_baseline")}
    out["fall_probabilities"] = falls
    fit = ic.fit_map(ic.resolved(ctx.con, market, asof))
    out["calibration"] = {k: fit[k] for k in ("n", "expiries", "min_n", "k", "by_level")}
    out["reading"] = ("p_implied is the chance the options charge for an index end more than X% lower at that expiry (insurance costs extra, so it runs above the real "
                      "frequency); p_calibrated scales it by how far the options ran above what happened, and is shown only from 20 resolved outcomes.")
    out["source"] = "quant/implied.py (Breeden-Litzenberger on the NSE chain) and quant/implied_calibration.py (scored when the expiry passes)"
    return out


# --- cascade -----------------------------------------------------------------------------------------------------------------------

def cascade(ctx: Ctx, a: dict) -> dict:
    from pflab import _toml
    from pflab.data import indices
    from pflab.quant import hawkes as hk
    market = (a.get("market") or "IN").upper()
    lookback = int(a.get("lookback", 5))
    if market != "IN":
        return {"market": market, "available": False, "message": f"No registered cascade fit for market {market}: the Hawkes study covers the Nifty 500 TRI only. Nothing is invented."}
    if not HAWKES_CONFIG.exists():
        return {"market": market, "available": False, "message": "The frozen Hawkes fit (configs/hawkes_market.toml) is not on this install."}
    try:
        df = indices.load("NIFTY500_TRI", ctx.rt.data_root)
    except Exception:
        df = None
    if df is None or not len(df):
        return {"market": market, "available": False, "message": "No Nifty 500 TRI series on this PC: the cascade cannot be read."}
    c = _toml.load(HAWKES_CONFIG)["market"]
    s = df.assign(date=pd.to_datetime(df["date"])).set_index("date")["close"].sort_index()
    r = s[s.index <= pd.Timestamp(ctx.asof)].pct_change().dropna()
    p = hk.Uni(c["mu"], c["alpha"], c["beta"])
    rd = hk.cascade_reading(r, p, float(c["threshold"]), int(a.get("horizon", c["horizon"])), lookback)
    out = {"market": market, "available": True, "shock_definition": f"a Nifty 500 TRI session of {c['threshold']:.0%} or worse", **rd}
    out["normal_chance"] = round(float(1 - np.exp(-c["poisson_rate"] * rd["horizon_sessions"])), 4)
    h = rd["horizon_sessions"]
    if rd["in_progress"]:
        out["reading"] = (f"A fall is under way: {len(rd['shocks_in_window'])} session(s) of {c['threshold']:.0%} or worse in the last {lookback} sessions (latest {rd['last_shock']}). "
                          f"Each such session triggers about {p.alpha:.2f} more on average, and the effect halves in about {p.half_life:.0f} sessions. The model puts the chance of "
                          f"another such session within {h} sessions at {rd['chance_another_shock']:.0%} (the long-run average rate: {out['normal_chance']:.0%}) and expects about "
                          f"{rd['expected_further_shocks']:.1f} further ones (1 time in 10 up to {rd['expected_further_shocks_p90']:.0f}). An estimate from the frozen 2005-2019 fit.")
    else:
        since = f"{rd['sessions_since_last_shock']} sessions ago ({rd['last_shock']})" if rd["last_shock"] else "never in the series"
        out["reading"] = (f"No fall in progress: no session of {c['threshold']:.0%} or worse in the last {lookback} sessions (the last was {since}). The cascade model is for use once "
                          f"a fall has started; for the record it gives {rd['chance_another_shock']:.0%} for another such session within {h} sessions (the long-run average rate: {out['normal_chance']:.0%}).")
    out["registered_finding"] = REGISTERED
    out["fit"] = {"mu": c["mu"], "alpha_branching_ratio": c["alpha"], "beta": c["beta"], "fit_from": str(c["fit_from"]), "fit_to": str(c["fit_to"])}
    out["source"] = "quant/hawkes.py with the frozen fit in configs/hawkes_market.toml; protocol docs/protocols/hawkes_protocol.md, results hawkes_results.md"
    return out


# --- simulate ----------------------------------------------------------------------------------------------------------------------

def _scenario_names() -> list:
    from pflab import _toml
    return sorted((_toml.load(SCENARIOS_CONFIG).get("scenario") or {}).keys()) if SCENARIOS_CONFIG.exists() else []


def portfolio(con, root, asof: date, which: str = "auto") -> dict:
    """The book to simulate: {"source","note","value","stock_weights","mix","hold"} (mix over montecarlo/sims assets); source "index" = the Nifty 500 itself when there is no book."""
    from pflab.app import sims
    book = None
    if which in ("auto", "paper"):
        try:
            from pflab.paper import book as pb, manager
            if pb.started(con):
                v = manager.book_view(con, asof)
                tot = float(v["value"]) or 1.0
                eq = {h["isin"]: h["value"] for h in v["holdings"] if h["kind"] == "equity" and h["value"] > 0}
                etf = sum(h["value"] for h in v["holdings"] if h["kind"] == "etf" and "GOLD" not in (h["symbol"] or "").upper())
                gold = sum(h["value"] for h in v["holdings"] if h["kind"] == "etf" and "GOLD" in (h["symbol"] or "").upper())
                cash = float(v["cash"]) + float(v.get("bank") or 0.0)
                other = max(tot - sum(eq.values()) - etf - gold - cash, 0.0)
                mix = {"mine": sum(eq.values()) / tot, "n500": etf / tot, "gold": gold / tot, "cash": (cash + other) / tot}
                hold = [{"isin": h["isin"], "symbol": h["symbol"], "bucket": "equity" if h["kind"] == "equity" else ("equity_fund" if h["kind"] == "etf" else "other"),
                         "value": float(h["value"])} for h in v["holdings"] if h["value"] > 0]
                book = {"source": "paper", "note": "the paper portfolio (paper_book)", "value": tot, "mix": mix, "hold": hold,
                        "stock_weights": {k: x / sum(eq.values()) for k, x in eq.items()} if eq else {}}
        except Exception:
            book = None
    if book is None and which in ("auto", "main"):
        try:
            total = sims.invested(con, asof)
            if total > 0:
                from pflab.risk import scenarios as sn
                book = {"source": "main", "note": "the main book (the ledger)", "value": float(total), "mix": sims.current_mix(con, asof), "hold": sn.holdings(con, asof),
                        "stock_weights": sims.stock_weights(con, asof)}
        except Exception:
            book = None
    if book is None:
        return {"source": "index", "note": "no book to simulate here (no paper portfolio, no main book): the Nifty 500 index fund itself, 100%, stands in",
                "value": None, "mix": {"n500": 1.0}, "hold": [], "stock_weights": {}}
    return book


def simulate(ctx: Ctx, a: dict) -> dict:
    from pflab import markets
    from pflab.app import sims
    from pflab.risk import montecarlo as mc
    market = (a.get("market") or "IN").upper()
    paths = int(a.get("paths", 5000))
    sessions = int(a.get("horizon", 20))
    seed = int(a.get("seed", 79))
    name, shock_pct = a.get("scenario"), a.get("shock_pct")
    if market != "IN":
        return {"market": market, "available": False, "message": f"No daily history of the portfolio's assets for market {market} on this PC: only the NSE (IN) simulation exists."}
    if name and shock_pct is not None:
        return {"available": False, "message": "Give either a scenario name or a shock_pct, not both."}
    names = _scenario_names()
    if name and name not in names:
        return {"available": False, "message": f"Unknown scenario '{name}'.", "scenarios": names}
    root, asof = ctx.rt.data_root, ctx.asof
    try:
        Rd = mc.history_daily(root)
    except Exception as e:
        return {"market": market, "available": False, "message": f"The daily history of the assets is not on this PC ({type(e).__name__}): nothing to simulate from."}
    Rd = Rd[Rd.index <= pd.Timestamp(asof)]
    if len(Rd) < 500:
        return {"market": market, "available": False, "message": "Too little daily history to simulate."}
    pf = portfolio(ctx.con, root, asof, a.get("portfolio", "auto"))
    try:
        mine, own = sims.mine_daily(root, pf["stock_weights"], Rd["stocks"])
    except Exception:
        mine, own = Rd["stocks"].copy(), 0.0
    Rd = Rd.assign(mine=mine)[list(sims.ASSETS)]
    w = np.array([pf["mix"].get(c, 0.0) for c in Rd.columns], float)
    w = w / w.sum() if w.sum() > 0 else w
    shock = {"kind": "none", "applied": "no first-day shock: the history as it was"}
    market_shock = portfolio_shock = 0.0
    if shock_pct is not None:
        market_shock = float(shock_pct) / 100.0
        shock = {"kind": "market", "applied": f"Nifty 500 {shock_pct:+g}% on the first session; each asset moves by its own daily beta to it"}
    elif name:
        from pflab.risk import scenarios as sn
        if not pf["hold"]:
            return {"market": market, "available": False, "message": f"Scenario '{name}' acts on holdings and there is no book here; give a shock_pct instead.", "scenarios": names}
        r = sn.run(ctx.con, root, asof, name, hold=pf["hold"])
        if "error" in r or r.get("total_pct_of_modelled") is None:
            return {"market": market, "available": False, "message": f"Scenario '{name}' could not be run: {r.get('error', 'no modelled holdings')}"}
        portfolio_shock = float(r["total"]) / float(pf["value"])
        shock = {"kind": "scenario", "name": name, "label": r["label"], "applied": f"{r['chain']}: {r['total_pct_of_modelled']:+.1%} on the modelled holdings, "
                 f"{portfolio_shock:+.1%} of the whole book, taken on the first session", "range_rupees": [round(x) for x in r["total_range"]]}
    v = mc.session_paths(Rd, w, sessions, paths, seed, market_shock, portfolio_shock)
    sm = mc.horizon_summary(v)
    end = markets.get(market).session_after(asof, sessions)
    q = {k: round(x, 4) for k, x in sm["change_quantiles"].items()}
    out = {"market": market, "available": True, "portfolio": pf["source"], "portfolio_note": pf["note"], "mix": {k: round(float(x), 4) for k, x in zip(Rd.columns, w) if x > 0},
           "horizon_sessions": sessions, "horizon_end": str(end), "paths": paths, "seed": seed, "history_sessions": int(len(Rd)),
           "history": f"{Rd.index[0].date()} to {Rd.index[-1].date()}, blocks of 21 sessions, mix rebalanced daily", "shock": shock,
           "value_change_quantiles": q, "chance_of_loss": round(sm["p_loss"], 4),
           "chance_fall_beyond_35pct": round(sm["p_fall_beyond_limit"], 4), "chance_fall_se": round(sm["p_fall_beyond_limit_se"], 4),
           "median_worst_fall": round(sm["worst_fall_median"], 4)}
    if pf["value"]:
        out["book_value_rupees"] = round(pf["value"])
        out["value_change_quantiles_rupees"] = {k: round(x * pf["value"]) for k, x in sm["change_quantiles"].items()}
    out["reading"] = (f"Over {sessions} sessions (to {end}) the middle outcome is {q['p50']:+.1%}; 1 time in 20 it is {q['p05']:+.1%} or worse; the chance of a fall beyond the 35% "
                      f"limit is {sm['p_fall_beyond_limit']:.1%} (+-{sm['p_fall_beyond_limit_se']:.1%}). A resampling of past sessions, an estimate and not a forecast.")
    out["source"] = "risk/montecarlo.py (circular block bootstrap of the daily history) with risk/scenarios.py for a named scenario"
    return out


TOOLS = [
    Tool("implied_dist", "read", "What the NIFTY 50 option chain says: the option-implied (risk-neutral) distribution of the index at the nearest expiry as quantiles and the chance of a "
         "fall of 5/10/15/20% (or a given fall_pct), beside the same chance scaled by how far the options ran above what really happened (the calibration, only from 20 resolved "
         "outcomes) and the realised frequency. If no option data is on this PC it says so and gives the realised frequency. Insurance prices, not forecasts.",
         {"market": _s("IN (default)", 4), "horizon": _i("sessions ahead the question is about (default 20); the options answer for their own nearest expiry and the note says when it differs", 1, 252),
          "fall_pct": _n("one fall size in percent below today's level; omit for 5, 10, 15 and 20", 0.5, 60.0)},
         (), implied_dist),
    Tool("cascade", "read", "The Hawkes cascade model for use ONCE A FALL HAS STARTED: given the recent run of -2% Nifty 500 sessions it returns the branching ratio (how many more each fall triggers), the "
         "chance of another within the horizon, the expected number of further shocks, a plain-word reading and the registered finding with its n. Says so when no fall is in progress.",
         {"market": _s("IN (default)", 4), "lookback": _i("sessions back that count as 'a fall has started' (default 5)", 1, 20), "horizon": _i("sessions ahead (default 10, the registered horizon)", 1, 60)},
         (), cascade),
    Tool("simulate", "read", "Monte Carlo of the portfolio (the paper book if it has started, else the main book, else the Nifty 500 itself) over a number of SESSIONS, with an optional first-day "
         "shock: a named scenario from the scenario list (oil_up_30, rupee_down_10, us_crash) or shock_pct, a Nifty 500 move on the first session. Returns quantiles of the value change "
         "and the chance of a fall beyond the 35% limit. Seeded, so the same question gives the same answer. (`simulation` is the long-run 1-5 year fan of the three mixes.)",
         {"scenario": _s("a scenario name from configs/scenarios.toml (not with shock_pct)", 60), "shock_pct": _n("Nifty 500 move in percent on the first session, e.g. -10", -60.0, 30.0),
          "horizon": _i("sessions (default 20)", 1, 252), "paths": _i("simulated paths (default 5000)", 100, 100_000), "market": _s("IN (default)", 4),
          "portfolio": _s("auto (default), paper or main", enum=["auto", "paper", "main"]), "seed": _i("random seed (default 79)", 0, 2_147_483_647)},
         (), simulate),
]
