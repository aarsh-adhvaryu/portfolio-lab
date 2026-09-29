"""E5-A §6 feature store, family (a): price and volume (A0).

One row per (ISIN, M, feature) for every ISIN in U(M), the stack's E1 §2
universe at month-end M, with the §6 columns:

  value             NaN when unavailable -- never 0 (§6 "missing is not zero")
  available         bool
  source            "panel" for prices and volume, "stack:<signal>" for the
                    stack's own score
  source_record_id  "<isin>@<M>": the panel row at M the value is read from
  published_at      M at 15:30 IST -- §6: "price features are published at
                    that session's close"
  usable_from       M (the session)

Every value at M is a function of rows dated <= M: shifts, trailing windows
and the stack's own score standardised within U(M), nothing else.

Conventions (reported in the store's meta, for the lock to confirm):
  * momentum counts MARKET sessions, 21 to a month, exactly as the stack's
    12-1 signal does (`momentum_panel` on the wide adjusted close); the
    12-1 feature IS E1's §3 score;
  * volatility, traded value and the 252-session high count the NAME's own
    rows, as E1 §2's "250 sessions of history" and its 126-session traded
    value do; a window must be full to give a value;
  * a name with no row at M publishes nothing at M: every feature is
    unavailable and the name is unscored (the stack cannot rank it either).
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Dict, List, Sequence

import numpy as np
import pandas as pd

from pflab.backtest import engine
from pflab.signals.momentum import momentum_panel
from pflab.signals.vol_scaled import standardise, vol_scaled_ratios

A0_FEATURES = ("mom_1m", "mom_3m", "mom_6m", "mom_12_1",
               "vol_21", "vol_63", "vol_252",
               "tv_21_126", "tv_126_252", "dist_252_high", "stack_score")
STORE_COLUMNS = ["isin", "month_end", "feature", "value", "available", "source",
                 "source_record_id", "published_at", "usable_from"]
SESSIONS_PER_MONTH = 21
CLOSE_IST = time(15, 30)
TZ = "Asia/Kolkata"


def dated(panel: pd.DataFrame) -> pd.DataFrame:
    """`panel` with `date` as datetime.date, copied only if it is not."""
    if len(panel) and isinstance(panel["date"].iloc[0], date) \
            and not isinstance(panel["date"].iloc[0], datetime):
        return panel
    p = panel.copy()
    p["date"] = pd.to_datetime(p["date"]).dt.date
    return p


def month_ends(panel: pd.DataFrame) -> List[date]:
    """The engine's month-end sessions, in order."""
    return sorted(engine._month_ends(sorted(panel["date"].unique())))


def universe_by_month(panel: pd.DataFrame, config: dict,
                      membership=None) -> Dict[date, pd.Index]:
    """U(M) at every month-end: `engine.eligible_at` on the same precompute
    the engine uses, so the store's universe is the decision's universe."""
    pre = engine.precompute_universe(panel, config, membership)
    u = config.get("universe", {})
    out = {}
    for m in month_ends(panel):
        e = engine.eligible_at(pre, m,
                               min_sessions=int(u.get("min_sessions", 250)),
                               top_n=int(u.get("top_n_by_turnover", 500)),
                               min_price=float(u.get("min_price", 10.0)))
        if len(e):
            out[m] = e
    return out


def _stack_signal(config: dict) -> dict:
    """The stack's ranking signal: E5-A's `fallback_signal` and E1d's knobs."""
    s = config.get("strategy", {})
    sig = s.get("fallback_signal", s.get("signal", "mom_12_1"))
    return {"signal": sig, "skip": int(s.get("skip_sessions", 21)),
            "lookback": int(s.get("lookback_sessions", 252)),
            "windows": tuple(int(w) for w in s.get("score_windows", (126, 252))),
            "order": s.get("score_order", "average_then_z")}


def _own_rows(sub: pd.DataFrame, fn, col: str) -> pd.Series:
    return sub.groupby("isin", sort=False)[col].transform(fn)


def a0_features(panel: pd.DataFrame, config: dict,
                universe: Dict[date, pd.Index]) -> pd.DataFrame:
    """The §6a store, long format (STORE_COLUMNS), sorted (M, isin, feature)."""
    panel = dated(panel)
    names = sorted(set().union(*[set(v) for v in universe.values()])) if universe else []
    sub = panel.loc[panel["isin"].isin(names),
                    ["date", "isin", "adj_close", "turnover"]]
    sub = sub.sort_values(["isin", "date"], kind="mergesort").reset_index(drop=True)
    sessions = sorted(panel["date"].unique())
    mes = [m for m in month_ends(panel) if m in universe]

    # -- market-session features: the stack's own conventions ----------
    adj_w = (sub.pivot_table(index="date", columns="isin", values="adj_close",
                             aggfunc="last").reindex(sessions))
    wide: Dict[str, pd.DataFrame] = {}
    k = SESSIONS_PER_MONTH
    wide["mom_1m"] = (adj_w / adj_w.shift(k) - 1.0).reindex(mes)
    wide["mom_3m"] = (adj_w / adj_w.shift(3 * k) - 1.0).reindex(mes)
    wide["mom_6m"] = (adj_w / adj_w.shift(6 * k) - 1.0).reindex(mes)
    sig = _stack_signal(config)
    wide["mom_12_1"] = momentum_panel(adj_w, lookback=sig["lookback"],
                                      skip=sig["skip"]).reindex(mes)

    # -- own-row features ----------------------------------------------
    is_me = sub["date"].isin(set(mes))
    ret = sub.groupby("isin", sort=False)["adj_close"].pct_change(fill_method=None)
    sub = sub.assign(_ret=ret)
    own = {}
    for w in (21, 63, 252):
        own[f"vol_{w}"] = _own_rows(
            sub, lambda s, w=w: s.rolling(w, min_periods=w).std() * np.sqrt(252.0),
            "_ret")
    tv = {w: _own_rows(sub, lambda s, w=w: s.rolling(w, min_periods=w).mean(),
                       "turnover") for w in (21, 126, 252)}
    own["tv_21_126"] = tv[21] / tv[126].where(tv[126] > 0)
    own["tv_126_252"] = tv[126] / tv[252].where(tv[252] > 0)
    hi = _own_rows(sub, lambda s: s.rolling(252, min_periods=252).max(), "adj_close")
    own["dist_252_high"] = sub["adj_close"] / hi.where(hi > 0) - 1.0
    at = sub.loc[is_me, ["date", "isin"]]
    for f, s in own.items():
        wide[f] = (pd.DataFrame({"date": at["date"].values, "isin": at["isin"].values,
                                 "v": s[is_me].values})
                   .pivot(index="date", columns="isin", values="v")
                   .reindex(index=mes, columns=adj_w.columns))

    # -- the stack's own score at M, standardised within U(M) -----------
    if sig["signal"] == "vol_scaled_6_12":
        parts = vol_scaled_ratios(adj_w, windows=sig["windows"], skip=sig["skip"])
    elif sig["signal"] == "mom_12_1":
        parts = None
    else:
        raise ValueError(f"E5-A: no stack score for signal {sig['signal']!r}")
    present = set(zip(sub["date"], sub["isin"]))
    rows = []
    for m in mes:
        elig = universe[m]
        if parts is None:
            sc = wide["mom_12_1"].loc[m]
            sc = sc[sc.index.isin(elig)].dropna()
        else:
            sc = standardise([p.loc[m][p.columns.isin(elig)] for p in parts],
                             order=sig["order"], clip=3.0)
        rows.append(sc.rename(m))
    wide["stack_score"] = (pd.DataFrame(rows).reindex(index=mes, columns=adj_w.columns)
                           if rows else pd.DataFrame(index=mes, columns=adj_w.columns))

    # -- long format over U(M) -----------------------------------------
    src = {f: "panel" for f in A0_FEATURES}
    src["stack_score"] = f"stack:{sig['signal']}"
    out = []
    for m in mes:
        elig = list(universe[m])
        pub = pd.Timestamp(datetime.combine(m, CLOSE_IST), tz=TZ)
        on = np.array([(m, i) in present for i in elig], dtype=bool)
        for f in A0_FEATURES:
            v = wide[f].loc[m].reindex(elig).to_numpy(dtype=float)
            v = np.where(on, v, np.nan)
            v = np.where(np.isfinite(v), v, np.nan)
            ok = ~np.isnan(v)
            out.append(pd.DataFrame({
                "isin": elig, "month_end": m, "feature": f, "value": v,
                "available": ok, "source": src[f],
                "source_record_id": [f"{i}@{m}" if o else None
                                     for i, o in zip(elig, ok)],
                "published_at": pub, "usable_from": m}))
    if not out:
        return pd.DataFrame(columns=STORE_COLUMNS)
    store = pd.concat(out, ignore_index=True)
    order = {f: k for k, f in enumerate(A0_FEATURES)}
    store = (store.assign(_o=store["feature"].map(order))
                  .sort_values(["month_end", "isin", "_o"], kind="mergesort")
                  .drop(columns="_o").reset_index(drop=True))
    return store[STORE_COLUMNS]


def to_wide(store: pd.DataFrame, features: Sequence[str] = A0_FEATURES) -> pd.DataFrame:
    """(month_end, isin) x feature, NaN where unavailable. The model's input."""
    s = store[store["feature"].isin(features)]
    w = s.pivot(index=["month_end", "isin"], columns="feature", values="value")
    w = w.where(s.pivot(index=["month_end", "isin"], columns="feature",
                        values="available").astype(bool))
    return w.reindex(columns=list(features)).sort_index()


def availability(store: pd.DataFrame) -> dict:
    """Share of (ISIN, M) rows with each feature available: reported in meta."""
    if store.empty:
        return {}
    g = store.groupby("feature")["available"].mean()
    return {f: round(float(g.get(f, 0.0)), 4) for f in A0_FEATURES}
