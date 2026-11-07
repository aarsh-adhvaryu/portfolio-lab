"""The registered comparison (S79b item 18A, `docs/protocols/s79_construct_protocol.md`): `construct`'s sizes against the current sizing rules, replayed point in time on a
monthly rebalance over 2012-2021 only, net of Zerodha charges and the estimated FIFO tax, on the workshop's market data.

    run(con, now, root=None)     the ONE run for the record: refuses if the protocol is not registered, changed since, or a verdict is already stored
    simulate(...)                the engine (pure: takes the price panel, so the tests can feed a synthetic one)

Both arms get the same BUY list (the team's direction is replaced by a stated momentum stand-in) and the same costs, taxes and cash rate; they differ only in the sizes.
2022-2025 is spent: the panel is cut at 2021-12-31 inside the query and `simulate` refuses a panel that reaches beyond it.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pflab.construct import costs, optimiser as O, risk

START, END = date(2010, 1, 1), date(2021, 12, 31)           # the panel read (two years of history before the first signal)
FIRST_SIGNAL, LAST_SIGNAL = date(2012, 1, 1), date(2021, 11, 30)
ETFS = {"NIFTYBEES": "EQUITY", "JUNIORBEES": "EQUITY", "BANKBEES": "EQUITY", "GOLDBEES": "LISTED_NONEQUITY"}      # symbol -> tax class
PARAMS = {"capital": 500_000.0, "cash_rate": 0.07, "n_liquid": 60, "n_picks": 20, "min_history": 300, "mom_long": 252, "mom_skip": 21, "turn_window": 250,
          "risk_aversion": 2.5, "equity_premium": 0.05, "tilt_cap": 0.30, "horizon": 20, "window": 250, "vol_blend": 0.5, "fallback_vol": 0.30, "turnover_penalty": 0.0005,
          "max_stock": 0.10, "max_etf": 0.35, "max_sector": 0.25, "jump": 0.60, "min_trade": 0.001, "block": 21, "resamples": 2000, "seed": 79,
          "adopt_dS": 0.10, "adopt_p": 0.05, "adopt_dd_pts": 2.0, "adopt_liq_pts": 0.5}
FORECASTERS = ("naive", "volatility", "momentum", "reversion")        # the code forecasters a stock has; uniform Hedge weights in the replay


# --- data -------------------------------------------------------------------------------------------------------------------------
def load_panel(root=None) -> pd.DataFrame:
    """Long panel date, key, kind ('stock'|'etf'), symbol, adj_close, turnover for stocks (series EQ) and the four ETFs, 2010-2021 only."""
    from pflab import _duck
    from pflab.data import data_dir
    root = Path(root) if root else data_dir()
    p = (root / "panel" / "prices.parquet").as_posix()
    etf = ",".join(repr(s) for s in ETFS)
    df = _duck.sql(f"SELECT date, isin, symbol, instrument_type AS kind, adj_close, turnover FROM '{p}' WHERE date >= DATE '{START}' AND date <= DATE '{END}' AND adj_close > 0 "
                   f"AND ((instrument_type = 'STK' AND series = 'EQ') OR (instrument_type = 'ETF' AND symbol IN ({etf}))) ORDER BY date").df()
    df["date"] = pd.to_datetime(df["date"])
    df["key"] = np.where(df["kind"] == "ETF", "ETF:" + df["symbol"].astype(str), df["isin"].astype(str))
    return df


def to_wide(df: pd.DataFrame, jump: float = PARAMS["jump"]) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, dict]]:
    """(cleaned price frame, turnover frame, meta {key: {symbol, etf}}). A daily move beyond +-`jump` is a data break and is removed from the price path (both arms see the same)."""
    assert df["date"].max() <= pd.Timestamp(END), "2022-2025 is spent: the panel must end 2021-12-31"
    px = df.pivot_table(index="date", columns="key", values="adj_close", aggfunc="last").sort_index()
    to = df.pivot_table(index="date", columns="key", values="turnover", aggfunc="last").sort_index()
    px = px.ffill()                      # a halted or delisted name keeps its last close (both arms alike; stated in the protocol's limitations)
    return clean(px, jump), to, {k: {"symbol": s, "etf": k.startswith("ETF:")} for k, s in df.drop_duplicates("key").set_index("key")["symbol"].items()}


def clean(px: pd.DataFrame, jump: float) -> pd.DataFrame:
    r = px.pct_change(fill_method=None)
    bad = r.abs() > jump
    cum = np.log1p(r.where(bad, 0.0).fillna(0.0)).cumsum()
    return px * np.exp(-cum)


def ensemble_inputs(close: pd.Series, h: int, cap: float) -> pd.DataFrame:
    """Per date, point in time: the annual tilt and dispersion of the uniform-weight combination of the code forecasters (`fcast.forecasters`)."""
    from pflab.fcast import forecasters as F
    close = close.dropna()
    close = close[close > 0]
    fr = [F.FORECASTERS[n](close, h) for n in FORECASTERS]
    q = {lv: sum(f[lv] for f in fr) / len(fr) for lv in (0.1, 0.5, 0.9)}
    ann = 252.0 / h
    tilt = (np.log1p(q[0.5]) * ann).clip(-cap, cap)
    sig = (np.log1p(q[0.9]) - np.log1p(q[0.1])) / (2 * 1.2815515655446004) * math.sqrt(ann)
    return pd.DataFrame({"tilt": tilt, "sigma": sig})


# --- the sizes --------------------------------------------------------------------------------------------------------------------
def rule_weights(keys: List[str], etf: Dict[str, bool], sector: Dict[str, Optional[str]], P: dict = PARAMS) -> Dict[str, float]:
    """The current rules on a BUY list: equal weight, a share cut to 10%, an ETF to 35%, a sector scaled to 25%; the rest stays cash."""
    if not keys:
        return {}
    w = {k: min(1.0 / len(keys), P["max_etf"] if etf[k] else P["max_stock"]) for k in keys}
    sec: Dict[str, List[str]] = {}
    for k in keys:
        if sector.get(k) and not etf[k]:
            sec.setdefault(sector[k], []).append(k)
    for s, ks in sec.items():
        tot = sum(w[k] for k in ks)
        if tot > P["max_sector"]:
            for k in ks:
                w[k] *= P["max_sector"] / tot
    return w


@dataclass
class Book:
    cash: float
    lots: Dict[str, List[list]] = field(default_factory=dict)         # key -> [[acq_date, qty, cost_per_unit, tax_class], ...] oldest first
    gains: Dict[int, Dict[str, float]] = field(default_factory=dict)  # financial year -> gains by bucket
    charges: float = 0.0
    tax: float = 0.0
    bought: float = 0.0

    def qty(self, k: str) -> float:
        return sum(l[1] for l in self.lots.get(k, []))

    def value(self, prices: Dict[str, float]) -> float:
        return self.cash + sum(self.qty(k) * prices.get(k, 0.0) for k in self.lots)

    def sell(self, k: str, qty: float, px: float, day: date, ac: str, tc: str) -> None:
        from pflab.paper import book as pb
        qty = min(qty, self.qty(k))
        if qty <= 1e-12:
            return
        fy = pb._fy(day)
        t, g = costs.lots_tax([tuple(l) for l in self.lots[k]], px, qty, day, ac, tc, costs.charge(ac, "sell", qty * px), self.gains.get(fy, {}))
        fee = costs.charge(ac, "sell", qty * px)
        left = qty
        for l in self.lots[k]:
            take = min(l[1], left)
            l[1] -= take
            left -= take
            if left <= 1e-12:
                break
        self.lots[k] = [l for l in self.lots[k] if l[1] > 1e-9]
        gy = self.gains.setdefault(fy, {})
        for b, v in g.items():
            gy[b] = gy.get(b, 0.0) + v
        t = max(0.0, t)
        self.cash += qty * px - fee - t
        self.charges += fee
        self.tax += t

    def buy(self, k: str, rupees: float, px: float, day: date, ac: str, tc: str) -> None:
        fee = costs.charge(ac, "buy", rupees)
        if rupees + fee > self.cash:
            rupees = max(0.0, (self.cash - 2.0) / 1.002)
            fee = costs.charge(ac, "buy", rupees)
        if rupees < 1.0:
            return
        q = rupees / px
        self.lots.setdefault(k, []).append([day, q, (rupees + fee) / q, tc])
        self.cash -= rupees + fee
        self.charges += fee
        self.bought += rupees

    def liquidation(self, prices: Dict[str, float], day: date, ac_of, tc_of) -> float:
        """Value after selling everything on `day` (charges and tax), without changing this book."""
        import copy
        b = copy.deepcopy(self)
        for k in list(b.lots):
            b.sell(k, b.qty(k), prices[k], day, ac_of(k), tc_of(k))
        return b.cash


def _tc_ac(k: str, meta: Dict[str, dict]) -> Tuple[str, str]:
    if meta[k]["etf"]:
        return "etf", ETFS[meta[k]["symbol"]]
    return "equity", "EQUITY"


# --- the engine -------------------------------------------------------------------------------------------------------------------
def month_ends(dates: pd.DatetimeIndex, a: date, b: date) -> List[pd.Timestamp]:
    s = pd.Series(dates, index=dates)
    s = s[(s >= pd.Timestamp(a)) & (s <= pd.Timestamp(b))]
    return [pd.Timestamp(x) for x in s.groupby([s.index.year, s.index.month]).last().values]


def simulate(px: pd.DataFrame, to: pd.DataFrame, meta: Dict[str, dict], sector_fn, P: dict = PARAMS, verbose: bool = False) -> dict:
    """Run both arms over `px` (cleaned adjusted closes by key) and return {'rule': {...}, 'construct': {...}, 'benchmark': {...}, ...}. `sector_fn(keys, day) -> {key: label|None}`."""
    assert px.index.max() <= pd.Timestamp(END), "2022-2025 is spent"
    cal = px["ETF:NIFTYBEES"].dropna().index
    signals = month_ends(cal, FIRST_SIGNAL, LAST_SIGNAL)
    pos = {d: i for i, d in enumerate(cal)}
    trade_day = {d: cal[pos[d] + 1] for d in signals if pos[d] + 1 < len(cal)}
    arms = {"rule": Book(P["capital"]), "construct": Book(P["capital"])}
    path: Dict[str, List[Tuple[pd.Timestamp, float]]] = {a: [] for a in arms}
    fcache: Dict[str, pd.DataFrame] = {}
    fails, log_n = 0, 0
    start_day = min(trade_day.values())
    rf_d = (1 + P["cash_rate"]) ** (1 / 252) - 1
    cnt = px.notna().cumsum()
    by_trade = {v: k for k, v in trade_day.items()}
    etf_keys = [k for k in px.columns if meta[k]["etf"]]
    ac_of = lambda k: _tc_ac(k, meta)[0]
    tc_of = lambda k: _tc_ac(k, meta)[1]
    for D in cal[cal >= start_day]:
        pr = px.loc[D].dropna().to_dict()
        day = D.date()
        for a, b in arms.items():
            b.cash *= (1 + rf_d)
        if D in by_trade:                                                     # trade at this close the signal made at the previous month end
            d = by_trade[D]
            hist = px.loc[:d]
            n_hist = cnt.loc[d]
            etfs = [k for k in etf_keys if n_hist[k] >= P["min_history"] and k in pr]
            tmed = to.loc[:d].tail(P["turn_window"]).median()
            ok = (n_hist >= P["min_history"]) & tmed.notna() & ~px.columns.isin(etf_keys)
            liquid = tmed[ok & (px.loc[d].notna())].nlargest(P["n_liquid"]).index.tolist()
            iloc = hist.index.get_loc(d)
            mom = (hist.iloc[iloc - P["mom_skip"]] / hist.iloc[iloc - P["mom_long"]] - 1.0) if iloc >= P["mom_long"] else pd.Series(dtype=float)
            ranked = mom.reindex(liquid).dropna()
            picks = ranked[ranked > 0].nlargest(P["n_picks"]).index.tolist()
            buy_list = [k for k in etfs + picks if k in pr]
            held_keys = [k for b in arms.values() for k in b.lots]
            sec = sector_fn(list(dict.fromkeys(buy_list + held_keys)), day)
            isetf = {k: meta[k]["etf"] for k in sec}
            # --- RULE arm
            targets = {"rule": rule_weights(buy_list, isetf, sec, P)}
            # --- CONSTRUCT arm
            b = arms["construct"]
            targets["construct"], ok_c = construct_weights(b, buy_list, hist, d, pr, px, meta, sec, isetf, fcache, P, ac_of, tc_of)
            if not ok_c:
                fails += 1
                targets["construct"] = dict(targets["rule"])
            for a, bk in arms.items():
                rebalance(bk, targets[a], pr, day, meta, P)
            log_n += 1
            if verbose and log_n % 12 == 0:
                print("  rebalanced", day, {a: round(bk.value(pr)) for a, bk in arms.items()}, "fails", fails, flush=True)
        for a, bk in arms.items():
            path[a].append((D, bk.value(pr)))
    last = cal[-1]
    pr_last = px.loc[last].dropna().to_dict()
    out = {"n_rebalances": log_n, "optimiser_failures": fails, "first_trade": str(start_day.date()), "last_day": str(last.date())}
    for a, bk in arms.items():
        s = pd.Series([v for _, v in path[a]], index=[d for d, _ in path[a]])
        liq = bk.liquidation(pr_last, last.date(), ac_of, tc_of)
        out[a] = metrics(s, P) | {"charges": round(bk.charges, 2), "tax": round(bk.tax, 2), "turnover_per_year": round(bk.bought / ((len(s) / 252) * float(s.mean())), 3),
                                  "liquidation_value": round(liq, 2), "liquidation_cagr": round(_cagr(liq, P["capital"], len(s)), 5)}
        out[a + "_path"] = s
    nb = px["ETF:NIFTYBEES"].reindex(out["rule_path"].index).ffill()
    out["benchmark"] = metrics(nb / nb.iloc[0] * P["capital"], P) | {"note": "NIFTYBEES bought on the first day and held; no charges or tax"}
    return out


def _cagr(end: float, start: float, n_days: int) -> float:
    return (end / start) ** (252.0 / max(n_days, 1)) - 1.0


def metrics(v: pd.Series, P: dict) -> dict:
    r = v.pct_change().dropna()
    ex = r - ((1 + P["cash_rate"]) ** (1 / 252) - 1)
    dd = (v / v.cummax() - 1).min()
    sd = ex.std()
    return {"sharpe": round(float(ex.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0, 4), "cagr": round(_cagr(float(v.iloc[-1]), float(v.iloc[0]), len(v)), 5),
            "vol": round(float(r.std() * math.sqrt(252)), 4), "max_drawdown": round(float(dd), 4), "end_value": round(float(v.iloc[-1]), 2)}


def rebalance(b: Book, w: Dict[str, float], pr: Dict[str, float], day: date, meta: Dict[str, dict], P: dict) -> None:
    """Whole-book trades at today's close toward the weights `w` (sells first; a change under 0.1% of the book is not traded)."""
    V = b.value(pr)
    cur = {k: b.qty(k) * pr.get(k, 0.0) for k in b.lots}
    for k in sorted(cur):                                                      # sells (including every name not in w)
        if k not in pr:
            continue
        want = w.get(k, 0.0) * V
        diff = cur[k] - want
        if diff > P["min_trade"] * V or (w.get(k, 0.0) == 0.0 and cur[k] > 0):
            ac, tc = _tc_ac(k, meta)
            b.sell(k, min(b.qty(k), diff / pr[k]), pr[k], day, ac, tc)
    for k in sorted(w, key=lambda k: -w[k]):                                    # buys
        if k not in pr:
            continue
        have = b.qty(k) * pr[k]
        diff = w[k] * V - have
        if diff > P["min_trade"] * V:
            ac, tc = _tc_ac(k, meta)
            b.buy(k, diff, pr[k], day, ac, tc)


def construct_weights(b: Book, buy_list: List[str], hist: pd.DataFrame, d: pd.Timestamp, pr: Dict[str, float], px: pd.DataFrame, meta, sec, isetf, fcache, P, ac_of, tc_of
                      ) -> Tuple[Dict[str, float], bool]:
    """The CONSTRUCT arm's target weights at signal day d, or (.., False) when the optimiser failed."""
    day = d.date()
    prd = px.loc[d].dropna().to_dict()
    held = [k for k in b.lots if k in prd]
    names = list(dict.fromkeys(buy_list + held))
    if not names:
        return {}, True
    V = b.value(prd)
    w0 = np.array([b.qty(k) * prd.get(k, 0.0) / V for k in names])
    ex = hist[names].tail(P["window"] + 1)
    rets = risk.daily_returns(ex, day, P["window"])
    mu, fvol = np.zeros(len(names)), {}
    for i, k in enumerate(names):
        if k not in fcache:
            fcache[k] = ensemble_inputs(px[k], P["horizon"], P["tilt_cap"])
        row = fcache[k].loc[:d].iloc[-1] if len(fcache[k].loc[:d]) else None
        if row is not None and np.isfinite(row["tilt"]) and np.isfinite(row["sigma"]):
            mu[i] = P["equity_premium"] + float(row["tilt"])
            fvol[k] = float(row["sigma"])
    cov, _, _ = risk.cov_for(names, rets, fvol, P["vol_blend"], P["fallback_vol"])
    n = len(names)
    ub = np.array([P["max_etf"] if isetf.get(k, meta[k]["etf"]) else P["max_stock"] for k in names])
    no_buy = np.array([k not in buy_list for k in names])
    groups = {}
    for s in {sec.get(k) for k in names if sec.get(k) and not meta[k]["etf"]}:
        m = np.array([1.0 if (sec.get(k) == s and not meta[k]["etf"]) else 0.0 for k in names])
        groups[f"sector {s}"] = (m, max(P["max_sector"], float(m @ w0)))
    buy_c = np.array([costs.rate(ac_of(k), "buy") for k in names])
    sell_c = np.zeros(n)
    for i, k in enumerate(names):
        lots = [tuple(l) for l in b.lots.get(k, [])]
        sell_c[i] = costs.rate(ac_of(k), "sell") + (costs.tax_rate(lots, prd[k], day, ac_of(k), tc_of(k)) if lots else 0.0)
    p = O.Problem(names=names, w0=w0, mu=mu, cov=cov, ub=ub, buy_cost=buy_c, sell_cost=sell_c, risk_aversion=P["risk_aversion"], turnover_penalty=P["turnover_penalty"],
                  groups=groups, no_buy=no_buy, frozen=np.zeros(n, bool), budget=1.0)
    res = O.solve(p)
    if not res["ok"]:
        return {}, False
    return {k: float(x) for k, x in zip(names, res["weights"]) if x > 1e-6}, True


# --- statistics -------------------------------------------------------------------------------------------------------------------
def bootstrap_dS(a: pd.Series, b: pd.Series, P: dict = PARAMS) -> dict:
    """Paired moving-block (circular) bootstrap of the Sharpe difference of two value paths on the same days: construct (a) minus rule (b)."""
    rf = (1 + P["cash_rate"]) ** (1 / 252) - 1
    ea, eb = (a.pct_change().dropna() - rf).to_numpy(), (b.pct_change().dropna() - rf).to_numpy()
    n = len(ea)
    L = P["block"]
    rng = np.random.default_rng(P["seed"])
    nb = int(math.ceil(n / L))
    starts = rng.integers(0, n, size=(P["resamples"], nb))
    idx = ((starts[:, :, None] + np.arange(L)[None, None, :]) % n).reshape(P["resamples"], -1)[:, :n]
    A, B = ea[idx], eb[idx]
    sa, sb = A.mean(1) / A.std(1, ddof=1), B.mean(1) / B.std(1, ddof=1)
    d = (sa - sb) * math.sqrt(252)
    obs = float(ea.mean() / ea.std(ddof=1) - eb.mean() / eb.std(ddof=1)) * math.sqrt(252)
    return {"dS": round(obs, 4), "p_one_sided": round(float(np.mean(d <= 0)), 4), "ci90": [round(float(np.percentile(d, 5)), 4), round(float(np.percentile(d, 95)), 4)],
            "resamples": P["resamples"], "block": L}


def decide(res: dict, boot: dict, P: dict = PARAMS) -> dict:
    """The protocol's section 5, in code."""
    c, r = res["construct"], res["rule"]
    dS = boot["dS"]
    dd_pts = (c["max_drawdown"] - r["max_drawdown"]) * 100        # drawdowns are negative: positive here = construct's fall is smaller
    liq_pts = (c["liquidation_cagr"] - r["liquidation_cagr"]) * 100
    conds = {"dS >= 0.10": dS >= P["adopt_dS"], "p <= 0.05": boot["p_one_sided"] <= P["adopt_p"], "drawdown not worse by more than 2 pts": dd_pts >= -P["adopt_dd_pts"],
             "liquidation CAGR not lower by more than 0.5 pt": liq_pts >= -P["adopt_liq_pts"]}
    if all(conds.values()):
        v, why = "adopt", "all four conditions hold"
    elif dS < 0:
        v, why = "loses", f"the Sharpe difference is negative ({dS:+.3f})"
    else:
        v, why = "inconclusive", "failed: " + ", ".join(k for k, ok in conds.items() if not ok)
    return {"verdict": v, "reason": why, "conditions": conds, "drawdown_diff_pts": round(dd_pts, 2), "liquidation_cagr_diff_pts": round(liq_pts, 2)}


# --- the one run ------------------------------------------------------------------------------------------------------------------
def default_sector_fn():
    from pflab.data import sector_map
    table = sector_map.load()
    cache: Dict[Tuple[str, date], Optional[str]] = {}

    def fn(keys: List[str], day: date) -> Dict[str, Optional[str]]:
        stocks = [k for k in keys if not k.startswith("ETF:")]
        need = [k for k in stocks if (k, day.replace(day=1)) not in cache]
        if need:
            lab = sector_map.sector_at(table, need, day, allow_later=True)
            for i, ind in zip(lab["isin"], lab["industry"]):
                cache[(i, day.replace(day=1))] = ind if isinstance(ind, str) and ind else None
        return {k: (None if k.startswith("ETF:") else cache.get((k, day.replace(day=1)))) for k in keys}
    return fn


def run(con, now: datetime, root=None, allow_rerun: bool = False, verbose: bool = False, panel=None, sector_fn=None, P: dict = PARAMS, write: bool = True) -> dict:
    """THE comparison. Refuses unless the protocol is registered and unchanged; once a verdict is stored it refuses a second run (a changed rerun is a new study)."""
    from pflab import construct as C
    t0 = time.time()
    ok = C.protocol_ok(con)
    if not (ok["registered"] and ok["unchanged"]):
        return {"ran": False, "why": f"protocol not usable: {ok['why']}"}
    if not allow_rerun and C.verdict(con) is not None:
        return {"ran": False, "why": "the comparison was already run once for the record", "verdict": C.verdict(con)}
    df = panel if panel is not None else load_panel(root)
    px, to, meta = to_wide(df, P["jump"])
    res = simulate(px, to, meta, sector_fn or default_sector_fn(), P, verbose)
    boot = bootstrap_dS(res["construct_path"], res["rule_path"], P)
    dec = decide(res, boot, P)
    summary = {"verdict": dec["verdict"], "reason": dec["reason"], "conditions": dec["conditions"], "dS": boot["dS"], "p": boot["p_one_sided"], "ci90": boot["ci90"],
               "drawdown_diff_pts": dec["drawdown_diff_pts"], "liquidation_cagr_diff_pts": dec["liquidation_cagr_diff_pts"],
               "rule": res["rule"], "construct": res["construct"], "benchmark": res["benchmark"], "n_rebalances": res["n_rebalances"],
               "optimiser_failures": res["optimiser_failures"], "period": [res["first_trade"], res["last_day"]], "params": P, "protocol_sha256": C.protocol_sha(),
               "seconds": round(time.time() - t0, 1)}
    if write:
        from pflab.pm.store import next_id
        con.execute("INSERT INTO construct_runs_s85 VALUES (?,?,?,?,?,?,?,?,?)", [next_id(con, "construct_runs_s85", "run_id"), "IN", "compare", date(2021, 12, 31), now, True, False,
                                                                                    json.dumps(summary, default=str), json.dumps({"boot": boot}, default=str)])
    return {"ran": True, **summary}
