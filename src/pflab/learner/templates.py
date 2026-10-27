"""The learner's tests (S62, PLAN A22; protocol docs/research/learner_protocol.md): a claim from outside reading is
tested only through one of these templates, with parameters from closed lists; the decision rule is fixed here, in
code, before any claim is run. A claim that fits no template is recorded as untestable on this system's data.

    cross_section   a stock signal from prices (momentum, reversal, low volatility, 52-week high, lottery, illiquidity):
                    at each month end the point-in-time Nifty 500 members with a year of history are ranked; the claimed
                    quintile's equal-weighted total return over the next h months against all members', after the
                    round-trip charges on the names that changed
    event_study     a kind of exchange filing (S46 template): the market-adjusted move over 1, 5 or 20 sessions after it
    calendar        a calendar effect on the Nifty 500 TRI (turn of the month, Mondays, Fridays, January, first half of
                    the month): returns on the effect's days against the other days
    holder_event    S63 (amendment 3): who buys and sells: insider / SAST disclosures, bulk and block deals by side, a
                    quarter's promoter holding up or down, pledges up; the market-adjusted move after each
    sector_reversion S64 (docs/research/s64_reversion_protocol.md): a stock cointegrated with its sector index and cheap
                    against it (bottom quintile of the spread's z) against the sector's next-month return, long only
    rule_filter     S64 (docs/research/s64_rules_protocol.md): a yes/no rule (P/E above 50, near the 52-week low, below the
                    200-day average, ...): the group that meets it against all members the next month

Periods (as every study here; 2022-2025 are spent, CLAUDE.md 2): development 2010-2017 and validation 2018-2021 (filings:
2015-2018 and 2019-2021, BSE announcements start in 2015). The rule, the same for every claim: the claimed direction in
both periods, t >= T_DEV in development and >= T_VAL in validation (the direction is fixed before the run: one-sided),
each period with at least MIN_MONTHS months or MIN_EVENTS events, and the effect larger than its trading cost.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from pflab import _duck

DEV, VAL = ("2010-01-01", "2017-12-31"), ("2018-01-01", "2021-12-31")
EV_DEV, EV_VAL = ("2015-01-01", "2018-12-31"), ("2019-01-01", "2021-12-31")
T_DEV, T_VAL = 2.0, 1.65
MIN_MONTHS, MIN_EVENTS = 36, 20
HISTORY = 252
ETF_ROUND_TRIP_PCT = 0.10          # an index ETF bought and sold (brokerage nil, STT, exchange charges, spread): stated

SIGNALS = {
    "momentum_12_1": "total return from 12 months to 1 month before",
    "momentum_6_1": "total return from 6 months to 1 month before",
    "reversal_1m": "total return over the last month",
    "volatility_12m": "standard deviation of daily returns over the last year",
    "high_52w": "close as a share of the year's highest close",
    "max_day_1m": "largest daily return in the last month",
    "illiquidity": "average absolute daily return per crore traded over the last year (Amihud)",
}
EVENT_KINDS = ("RATING_DOWNGRADE", "DEFAULT", "AUDITOR_RESIGNATION", "INSOLVENCY", "FRAUD", "RESULTS_DELAY",
               "PROMOTER_ENCUMBRANCE", "FORENSIC_AUDIT", "REGULATORY_ACTION", "Financial Results", "Credit Rating",
               "Acquisition", "Award of Order / Receipt of Order", "Dividend", "Change in Management",
               "Resignation of Director")
EFFECTS = ("turn_of_month", "monday", "friday", "january", "first_half_month")
# S63 (protocol amendment 3): who buys and sells. Thresholds fixed here, before any claim on them is run.
HOLDER_KINDS = ("insider_sast", "bulk_buy", "bulk_sell", "block_buy", "block_sell", "promoter_up", "promoter_down",
                "pledge_up")
PROMOTER_STEP_PP, PLEDGE_STEP_PP, FILING_LAG_DAYS = 0.5, 1.0, 21

SCHEMA = {
    "cross_section": {"signal": list(SIGNALS), "direction": ["high", "low"], "months": [1, 3]},
    "event_study": {"kind": list(EVENT_KINDS), "direction": ["up", "down"], "sessions": [1, 5, 20]},
    "calendar": {"effect": list(EFFECTS), "direction": ["high", "low"]},
    "holder_event": {"kind": list(HOLDER_KINDS), "direction": ["up", "down"], "sessions": [1, 5, 20]},
    "sector_reversion": {"direction": ["low", "high"]},
    "rule_filter": {"rule": ["pe_above_50", "pe_below_15", "near_52w_low_5", "below_sma200", "volume_spike_2", "ath_fall_40",
                             "rsi_below_30"], "direction": ["out", "under"], "months": [1]},
}

# S64 protocol (fixed before the run): the sector TRI of an industry, by the sector map's taxonomy at the month end.
_A = {"COMPUTERS - SOFTWARE": "IT", "BANKS": "BANK", "AUTOMOBILES - 2 AND 3 WHEELERS": "AUTO",
      "AUTOMOBILES - 4 WHEELERS": "AUTO", "AUTO ANCILLARIES": "AUTO", "PHARMACEUTICALS": "PHARMA", "PERSONAL CARE": "FMCG",
      "FOOD AND FOOD PROCESSING": "FMCG", "CIGARETTES": "FMCG", "BREW/DISTILLERIES": "FMCG", "REFINERIES": "OIL_GAS",
      "OIL EXPLORATION/PRODUCTION": "OIL_GAS", "GAS": "OIL_GAS", "STEEL AND STEEL PRODUCTS": "METAL", "ALUMINIUM": "METAL",
      "METALS": "METAL", "MINING": "METAL", "FINANCE": "FIN_SERVICES", "FINANCE - HOUSING": "FIN_SERVICES",
      "FINANCIAL INSTITUTION": "FIN_SERVICES", "MEDIA & ENTERTAINMENT": "MEDIA", "CONSUMER DURABLES": "CONSUMER_DURABLES",
      "CHEMICALS - INORGANIC": "CHEMICALS", "CHEMICALS - ORGANIC": "CHEMICALS", "CHEMICALS - SPECIALITY": "CHEMICALS"}
_B = {"AUTOMOBILE": "AUTO", "IT": "IT", "PHARMA": "PHARMA", "CONSUMER GOODS": "FMCG", "FINANCIAL SERVICES": "FIN_SERVICES",
      "OIL & GAS": "OIL_GAS", "METALS": "METAL", "MEDIA & ENTERTAINMENT": "MEDIA", "CHEMICALS": "CHEMICALS"}
SECTOR_OF = {"A": {k: f"SECTOR_{v}_TRI" for k, v in _A.items()}, "B": {k: f"SECTOR_{v}_TRI" for k, v in _B.items()}}
REV_HISTORY, REV_MIN_KEPT, REV_P = 756, 10, 0.05     # 36 months of sessions; names needed in a month; the EG level


def check_params(template: str, params: dict) -> Optional[str]:
    """None when the parameters are from the template's closed lists; else what is wrong."""
    if template not in SCHEMA:
        return f"unknown template {template!r}"
    want = SCHEMA[template]
    if set(params) != set(want):
        return f"{template} takes exactly {sorted(want)}"
    for k, allowed in want.items():
        if params[k] not in allowed:
            return f"{k} must be one of {allowed}"
    return None


def nw_t(x: Sequence[float], lags: int = 0) -> Tuple[float, float, int]:
    """(mean, Newey-West t, n) of a series; t is nan under 3 observations."""
    import statsmodels.api as sm
    y = np.asarray([v for v in x if v is not None and math.isfinite(v)], dtype=float)
    if len(y) < 3 or np.allclose(y, y[0]):
        return (float(y.mean()) if len(y) else float("nan")), float("nan"), int(len(y))
    fit = sm.OLS(y, np.ones(len(y))).fit(cov_type="HAC", cov_kwds={"maxlags": int(lags)})
    return float(y.mean()), float(fit.tvalues[0]), int(len(y))


def decide(dev: dict, val: dict, sign: int, minimum: int, cost: float, unit: str,
           threshold_dev: float = T_DEV) -> Tuple[str, str]:
    """The one rule for every template: ('pass' | 'fail', why). `cost` in the effect's own units. `threshold_dev` is the
    development bar: counter.t_needed(N) since protocol amendment 4 (never under T_DEV)."""
    threshold_dev = max(threshold_dev, T_DEV)
    for name, d, t_min in (("development", dev, threshold_dev), ("validation", val, T_VAL)):
        if d["n"] < minimum:
            return "fail", f"{name}: {d['n']} {unit}, fewer than {minimum} (small numbers: no conclusion)"
        if not math.isfinite(d["t"]) or sign * d["mean"] <= 0:
            return "fail", f"{name}: the effect went the other way (mean {d['mean']:+.4f})"
        if sign * d["t"] < t_min:
            return "fail", f"{name}: t {d['t']:+.2f}, under {t_min}"
        if sign * d["mean"] <= cost:
            return "fail", f"{name}: mean {d['mean']:+.4f} does not cover the cost {cost:.4f}"
    return "pass", (f"both periods in the claimed direction: development mean {dev['mean']:+.4f} (t {dev['t']:+.2f}, "
                    f"n {dev['n']}), validation {val['mean']:+.4f} (t {val['t']:+.2f}, n {val['n']})")


# --- cross section -------------------------------------------------------------------------------------------------------

def members(root: Path) -> pd.DataFrame:
    m = _duck.sql(f"select isin, from_date, coalesce(to_date, DATE '2099-01-01') to_date "
                  f"from '{root}/index_membership/NIFTY500.parquet'").df()
    m["from_date"], m["to_date"] = pd.to_datetime(m["from_date"]), pd.to_datetime(m["to_date"])
    return m


def wide_panel(root: Path, isins: Sequence[str], start: str, end: str) -> Dict[str, pd.DataFrame]:
    """Wide daily frames (sessions x isin): tr (total-return index), adj (adjusted close), r (daily total return),
    turnover (rupees)."""
    px = _duck.sql(f"""select date, isin, close, adj_close, dividend, turnover from '{root}/panel/prices.parquet'
                        where isin in ({','.join(repr(i) for i in isins) or "''"})
                          and date between DATE '{start}' and DATE '{end}'""").df()
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values(["isin", "date"]).drop_duplicates(["isin", "date"])
    r = px.groupby("isin")["adj_close"].pct_change()
    px["r"] = (1 + r) * (1 + (px["dividend"].fillna(0.0) / px["close"]).where(px["close"] > 0, 0.0)) - 1
    out = {k: px.pivot(index="date", columns="isin", values=v) for k, v in
           (("adj", "adj_close"), ("r", "r"), ("turnover", "turnover"), ("close", "close"))}
    out["tr"] = (1 + out["r"].fillna(0.0)).cumprod().where(out["adj"].notna())
    return out


def signal_at(w: Dict[str, pd.DataFrame], i: int, signal: str) -> pd.Series:
    """The signal for every column at session index i, from sessions <= i only (point in time)."""
    tr, adj, r = w["tr"], w["adj"], w["r"]
    if signal == "momentum_12_1":
        return tr.iloc[i - 21] / tr.iloc[i - HISTORY] - 1
    if signal == "momentum_6_1":
        return tr.iloc[i - 21] / tr.iloc[i - 126] - 1
    if signal == "reversal_1m":
        return tr.iloc[i] / tr.iloc[i - 21] - 1
    if signal == "volatility_12m":
        return r.iloc[i - HISTORY + 1:i + 1].std()
    if signal == "high_52w":
        return adj.iloc[i] / adj.iloc[i - HISTORY + 1:i + 1].max()
    if signal == "max_day_1m":
        return r.iloc[i - 20:i + 1].max()
    if signal == "illiquidity":
        to = w["turnover"].iloc[i - HISTORY + 1:i + 1] / 1e7
        return (r.iloc[i - HISTORY + 1:i + 1].abs() / to.where(to > 0)).mean()
    raise ValueError(signal)


def month_ends(sessions: pd.DatetimeIndex, start: str, end: str) -> list:
    s = pd.Series(range(len(sessions)), index=sessions)
    s = s[(s.index >= pd.Timestamp(start)) & (s.index <= pd.Timestamp(end))]
    return list(s.groupby([s.index.year, s.index.month]).max())


def cross_section_series(w: Dict[str, pd.DataFrame], mem: pd.DataFrame, signal: str, direction: str, months: int,
                         start: str, end: str, round_trip_pct: float) -> pd.Series:
    """Excess total return of the claimed quintile over all members, per formation month, after charges."""
    sessions = w["tr"].index
    every = month_ends(sessions, str(sessions[0].date()), str(sessions[-1].date()))
    tr_f = w["tr"].ffill()                                  # a name that stops trading keeps its last value
    out, prev = {}, {}
    for k, i in enumerate(every):
        t = sessions[i]
        if i < HISTORY or k + months >= len(every) or not pd.Timestamp(start) <= t <= pd.Timestamp(end):
            continue
        j = every[k + months]
        live = set(mem[(mem["from_date"] <= t) & (mem["to_date"] > t)]["isin"]) & set(w["tr"].columns)
        cols = sorted(live)
        hist = w["adj"].iloc[i - HISTORY + 1:i + 1][cols].notna().sum()
        cols = [c for c in cols if hist[c] >= 200 and pd.notna(w["tr"].iloc[i][c])]
        if len(cols) < 50:
            continue
        sig = signal_at({k2: v[cols] for k2, v in w.items()}, i, signal).dropna()
        if len(sig) < 50:
            continue
        fwd = (tr_f.iloc[j][sig.index] / w["tr"].iloc[i][sig.index] - 1).dropna()
        sig = sig[fwd.index]
        q = sig.rank(pct=True)
        pick = set(q[q > 0.8].index) if direction == "high" else set(q[q <= 0.2].index)
        if not pick:
            continue
        last = prev.get(k - months, set())
        changed = len(pick - last) / len(pick) if last else 1.0
        prev[k] = pick
        out[t] = float(fwd[list(pick)].mean() - fwd.mean()) - changed * round_trip_pct / 100
    return pd.Series(out, dtype=float)


def cross_section(root: Path, signal: str, direction: str, months: int, round_trip_pct: float,
                  periods=(DEV, VAL), threshold_dev: float = T_DEV) -> dict:
    mem = members(root)
    w = wide_panel(root, sorted(set(mem["isin"])), "2008-06-01", "2022-06-30")
    res = {}
    for name, (a, b) in zip(("development", "validation"), periods):
        s = cross_section_series(w, mem, signal, direction, months, a, b, round_trip_pct)
        m, t, n = nw_t(s.values, lags=max(1, months))
        res[name] = {"mean": m, "t": t, "n": n, "per": f"{months}-month excess after charges"}
        if name == "development":
            res[name]["_returns"] = [float(v) for v in s.values]       # for the deflated Sharpe ratio (counter.py)
    d, why = decide(res["development"], res["validation"], 1, MIN_MONTHS, 0.0, "months", threshold_dev)
    return {"decision": d, "why": why, **res}


def today_quintiles(con, root: Path, signal: str, isins: Sequence[str], asof) -> Dict[str, dict]:
    """A passed signal, live: each name's value from the store's closes up to `asof`, placed against the latest
    month end's breakpoints in the panel (stated with both dates). Prices only; no total return in the store."""
    from pflab.hq import keeper
    mem = members(root)
    last = _duck.sql(f"select max(date) from '{root}/panel/prices.parquet'").fetchone()[0]
    live = sorted(set(mem[(mem["from_date"] <= pd.Timestamp(last)) & (mem["to_date"] > pd.Timestamp(last))]["isin"]))
    w = wide_panel(root, live, str(pd.Timestamp(last) - pd.Timedelta(days=420))[:10], str(last))
    i = len(w["tr"].index) - 1
    if i < HISTORY:
        return {}
    br = signal_at(w, i, signal).dropna().quantile([0.2, 0.4, 0.6, 0.8]).to_list()
    out = {}
    for isin in isins:
        s = keeper.closes(con, isin, asof, days=420)
        if len(s) <= HISTORY:
            continue
        one = {"adj": s.to_frame(isin), "r": s.pct_change().to_frame(isin), "tr": (s / s.iloc[0]).to_frame(isin),
               "turnover": pd.DataFrame(np.nan, index=s.index, columns=[isin])}
        v = signal_at(one, len(s) - 1, signal).get(isin)
        if v is None or not math.isfinite(v):
            continue
        out[isin] = {"value": float(v), "quintile": int(np.searchsorted(br, v) + 1), "breakpoints_at": str(last),
                     "value_at": str(s.index[-1].date())}
    return out


# --- event study and calendar ----------------------------------------------------------------------------------------------

def event_study(root: Path, kind: str, direction: str, sessions: int, round_trip_pct: float,
                threshold_dev: float = T_DEV) -> dict:
    from pflab.agents import quant as qn
    from pflab.data import red_flags
    from pflab.quant import event_study as es
    if kind in qn.FLAG_WORDS:
        args = {"headline_regex": "|".join(p.pattern for p in red_flags._C[kind][0])}
    else:
        args = {"subcategories": [kind]}
    res, sign = {}, 1 if direction == "up" else -1
    for name, (a, b) in (("development", EV_DEV), ("validation", EV_VAL)):
        r = es.run(root, a, b, **args)
        c = r["cars"]
        x = c[f"car_{sessions}"].to_numpy() if len(c) else np.array([])
        m, t, n = nw_t(x, 0)
        res[name] = {"mean": m, "t": t, "n": n, "per": f"CAR[0,{sessions}] per filing"}
    d, why = decide(res["development"], res["validation"], sign, MIN_EVENTS, round_trip_pct / 100, "events", threshold_dev)
    return {"decision": d, "why": why, **res}


def holder_events(root: Path, kind: str, start: str, end: str) -> pd.DataFrame:
    """isin, t (when the market could know it) for one holder kind, in [start, end]:
        insider_sast   BSE announcements in 'Insider Trading / SAST', trading-window notices left out (dissemination)
        bulk_/block_   NSE deals of that kind and side; published after the close, so the next session (t = 16:00)
        promoter_up/down, pledge_up   a quarter's promoter holding up or down by PROMOTER_STEP_PP points, or the pledged
                       share of it up by PLEDGE_STEP_PP; dated FILING_LAG_DAYS after the quarter end (SEBI's deadline)"""
    import glob
    cols = ["isin", "t", "headline"]
    if kind == "insider_sast":
        from pflab.data import bse_scrip_isin
        from pflab.monitor.filings import resolve_isins
        fs = glob.glob(str(root / "bse_announcements" / "**" / "*.parquet"), recursive=True)
        if not fs:
            return pd.DataFrame(columns=cols)
        df = _duck.sql(f"""select scrip_code, headline, subcategory, coalesce(dissem_dt, news_dt) t
                            from read_parquet({fs!r}, union_by_name=true)
                            where category = 'Insider Trading / SAST' and coalesce(subcategory, '') not ilike '%trading window%'
                              and coalesce(dissem_dt, news_dt) between TIMESTAMP '{start}' and TIMESTAMP '{end} 23:59:59'""").df()
        if df.empty:
            return pd.DataFrame(columns=cols)
        df["isin"] = resolve_isins(df, bse_scrip_isin.load(root))
        return df.dropna(subset=["isin"]).drop_duplicates(["isin", "t"])[cols]
    if kind.startswith(("bulk_", "block_")):
        from pflab.data import nse_deals
        k, side = kind.split("_")
        d = nse_deals.load(root)
        d["date"] = pd.to_datetime(d["date"])
        d = d[(d["kind"] == k) & (d["side"] == side.upper()) & (d["date"] >= pd.Timestamp(start))
              & (d["date"] <= pd.Timestamp(end))]
        if d.empty:
            return pd.DataFrame(columns=cols)
        px = _duck.sql(f"""select distinct date, symbol, isin from '{root}/panel/prices.parquet'
                           where date between DATE '{start}' and DATE '{end}'""").df()
        px["date"] = pd.to_datetime(px["date"])
        d = d.merge(px, on=["date", "symbol"], how="inner")          # the symbol as it traded that day: point in time
        d = d.drop_duplicates(["isin", "date"])
        return pd.DataFrame({"isin": d["isin"], "t": d["date"] + pd.Timedelta(hours=16), "headline": d["client"]})
    s = pd.read_parquet(root / "bse_shareholding" / "summary.parquet",
                        columns=["scrip_code", "quarter_end", "status", "promoter_pct", "pledged_pct_of_promoter"])
    s = s[s["status"] == "ok"].sort_values(["scrip_code", "quarter_end"])
    col, step = ("pledged_pct_of_promoter", PLEDGE_STEP_PP) if kind == "pledge_up" else ("promoter_pct", PROMOTER_STEP_PP)
    s["chg"] = s.groupby("scrip_code")[col].diff()
    hit = s[s["chg"] <= -step] if kind == "promoter_down" else s[s["chg"] >= step]
    hit = hit.assign(t=pd.to_datetime(hit["quarter_end"]) + pd.Timedelta(days=FILING_LAG_DAYS, hours=16))
    hit = hit[(hit["t"] >= pd.Timestamp(start)) & (hit["t"] <= pd.Timestamp(end) + pd.Timedelta(hours=23))]
    mp = _duck.sql(f"select scrip_code, isin from '{root}/bse_scrip_isin/map.parquet' where isin like 'INE%'").df()
    mp["scrip_code"] = mp["scrip_code"].astype(str)
    hit = hit.assign(scrip_code=hit["scrip_code"].astype(str)).merge(mp.drop_duplicates("scrip_code"), on="scrip_code")
    return pd.DataFrame({"isin": hit["isin"], "t": hit["t"], "headline": kind})


def holder_event(root: Path, kind: str, direction: str, sessions: int, round_trip_pct: float,
                 threshold_dev: float = T_DEV) -> dict:
    from pflab.quant import event_study as es
    res, sign = {}, 1 if direction == "up" else -1
    mkt = es.market(root)
    for name, (a, b) in (("development", EV_DEV), ("validation", EV_VAL)):
        ev = holder_events(root, kind, a, b)
        x = np.array([])
        if len(ev):
            rets = es.returns(root, sorted(set(ev["isin"])), a, b)
            c = es.cars(ev, rets, mkt, (sessions,)) if len(rets) else pd.DataFrame()
            x = c[f"car_{sessions}"].to_numpy() if len(c) else np.array([])
        m, t, n = nw_t(x, 0)
        res[name] = {"mean": m, "t": t, "n": n, "per": f"CAR[0,{sessions}] per event"}
    d, why = decide(res["development"], res["validation"], sign, MIN_EVENTS, round_trip_pct / 100, "events", threshold_dev)
    return {"decision": d, "why": why, **res}


def effect_days(dates: pd.DatetimeIndex, effect: str) -> np.ndarray:
    s = pd.Series(range(len(dates)), index=dates)
    if effect == "turn_of_month":
        ym = dates.year * 100 + dates.month
        first = pd.Series(ym).groupby(ym).cumcount().to_numpy()
        last = pd.Series(ym[::-1]).groupby(ym[::-1]).cumcount().to_numpy()[::-1]
        return (first < 3) | (last == 0)
    if effect == "monday":
        return dates.weekday == 0
    if effect == "friday":
        return dates.weekday == 4
    if effect == "january":
        return dates.month == 1
    if effect == "first_half_month":
        return dates.day <= 15
    raise ValueError(effect)


WINDOW_DAYS = {"turn_of_month": 4, "monday": 1, "friday": 1, "january": 21, "first_half_month": 10}


def calendar(root: Path, effect: str, direction: str, threshold_dev: float = T_DEV) -> dict:
    from pflab.data import indices
    df = indices.load("NIFTY500_TRI", root)
    s = df.assign(date=pd.to_datetime(df["date"])).set_index("date")["close"].sort_index()
    r = s.pct_change().dropna()
    res, sign = {}, 1 if direction == "high" else -1
    for name, (a, b) in (("development", DEV), ("validation", VAL)):
        x = r[(r.index >= pd.Timestamp(a)) & (r.index <= pd.Timestamp(b))]
        on = effect_days(x.index, effect)
        e, o = x[on], x[~on]
        diff = float(e.mean() - o.mean()) if len(e) and len(o) else float("nan")
        se = math.sqrt(e.var(ddof=1) / len(e) + o.var(ddof=1) / len(o)) if len(e) > 1 and len(o) > 1 else float("nan")
        months = len({(d.year, d.month) for d in x.index})
        res[name] = {"mean": diff * WINDOW_DAYS[effect], "t": diff / se if se and se > 0 else float("nan"), "n": months,
                     "per": f"excess over a {WINDOW_DAYS[effect]}-session window"}
    d, why = decide(res["development"], res["validation"], sign, MIN_MONTHS, ETF_ROUND_TRIP_PCT / 100, "months", threshold_dev)
    return {"decision": d, "why": why, **res}


# --- sector reversion (S64) ------------------------------------------------------------------------------------------------

def sector_index_key(taxonomy: Optional[str], industry: Optional[str]) -> Optional[str]:
    """The sector TRI key of an industry label under its taxonomy (A, B or C), or None when the industry has none."""
    if taxonomy == "C":
        from pflab.quant.comove import SECTOR_INDEX
        return SECTOR_INDEX.get(industry)
    return SECTOR_OF.get(taxonomy or "", {}).get(industry)


def spread_z(la: np.ndarray, lb: np.ndarray) -> Tuple[float, float]:
    """(Engle-Granger p, z of today's spread) of two aligned log-price windows: spread = a - beta b, beta by OLS on the
    window; z = (last spread - window mean) / window standard deviation."""
    from statsmodels.tsa.stattools import coint
    if np.std(la) == 0 or np.std(lb) == 0:
        return 1.0, float("nan")
    p = float(coint(la, lb, trend="c", autolag="aic")[1])
    beta = float(np.polyfit(lb, la, 1)[0])
    sp = la - beta * lb
    sd = float(sp.std(ddof=1))
    return p, ((float(sp[-1]) - float(sp.mean())) / sd if sd > 0 else float("nan"))


def sector_reversion_series(root: Path, direction: str, start: str, end: str, round_trip_pct: float) -> pd.Series:
    """Per formation month: the equal-weighted quintile (cheapest z for 'low', dearest for 'high') of the names
    cointegrated with their sector TRI (EG p < 0.05 over 36 months), next month's return less their sector's, after
    charges on the names that changed."""
    from pflab.data import indices, sector_map
    from pflab.quant.comove import SECTOR_INDEX
    mem = members(root)
    w = wide_panel(root, sorted(set(mem["isin"])), "2007-01-01", "2022-06-30")
    sessions = w["tr"].index
    table = sector_map.load(root)
    keys = {k for m in SECTOR_OF.values() for k in m.values()} | set(SECTOR_INDEX.values())
    sec = {}
    for k in keys:
        d = indices.load(k, root)
        sec[k] = d.assign(date=pd.to_datetime(d["date"])).set_index("date")["close"].sort_index().reindex(sessions).ffill()
    every = month_ends(sessions, str(sessions[0].date()), str(sessions[-1].date()))
    tr_f = w["tr"].ffill()
    out, prev = {}, set()
    for k, i in enumerate(every):
        t = sessions[i]
        if i < REV_HISTORY or k + 1 >= len(every) or not pd.Timestamp(start) <= t <= pd.Timestamp(end):
            continue
        j = every[k + 1]
        live = sorted(set(mem[(mem["from_date"] <= t) & (mem["to_date"] > t)]["isin"]) & set(w["tr"].columns))
        have = w["tr"].iloc[i - REV_HISTORY + 1:i + 1][live].notna().sum()
        live = [c for c in live if have[c] >= REV_HISTORY - 20 and pd.notna(w["tr"].iloc[i][c])]
        lab = sector_map.sector_at(table, live, t.date(), allow_later=False).set_index("isin")
        z, fwd_ex = {}, {}
        for c in live:
            key = sector_index_key(lab.at[c, "taxonomy"], lab.at[c, "industry"])
            if not key or key not in sec:
                continue
            sx = sec[key].iloc[i - REV_HISTORY + 1:i + 1]
            lx = w["tr"].iloc[i - REV_HISTORY + 1:i + 1][c].ffill()
            if sx.isna().any() or lx.isna().any() or (sx <= 0).any() or (lx <= 0).any():
                continue
            p, zz = spread_z(np.log(lx.to_numpy(float)), np.log(sx.to_numpy(float)))
            f_s = tr_f.iloc[j][c] / w["tr"].iloc[i][c] - 1
            f_x = sec[key].iloc[j] / sec[key].iloc[i] - 1
            if p < REV_P and math.isfinite(zz) and math.isfinite(f_s) and math.isfinite(f_x):
                z[c], fwd_ex[c] = zz, float(f_s - f_x)
        if len(z) < REV_MIN_KEPT:
            continue
        r = pd.Series(z).rank(pct=True)
        pick = set(r[r <= 0.2].index) if direction == "low" else set(r[r > 0.8].index)
        if not pick:
            continue
        changed = len(pick - prev) / len(pick) if prev else 1.0
        prev = pick
        out[t] = float(np.mean([fwd_ex[c] for c in pick])) - changed * round_trip_pct / 100
    return pd.Series(out, dtype=float)


def sector_reversion(root: Path, direction: str, round_trip_pct: float, periods=(DEV, VAL),
                     threshold_dev: float = T_DEV) -> dict:
    res = {}
    for name, (a, b) in zip(("development", "validation"), periods):
        s = sector_reversion_series(root, direction, a, b, round_trip_pct)
        m, t, n = nw_t(s.values, lags=1)
        res[name] = {"mean": m, "t": t, "n": n, "per": "1-month excess over the sector after charges"}
        if name == "development":
            res[name]["_returns"] = [float(v) for v in s.values]
    d, why = decide(res["development"], res["validation"], 1, MIN_MONTHS, 0.0, "months", threshold_dev)
    return {"decision": d, "why": why, **res}


# --- rule_filter (S64, docs/research/s64_rules_protocol.md): a yes/no rule on a stock against the other members -----------------

RULES = ("pe_above_50", "pe_below_15", "near_52w_low_5", "below_sma200", "volume_spike_2", "ath_fall_40", "rsi_below_30")
RULE_TEXT = {
    "pe_above_50": "price over trailing-twelve-month EPS above 50", "pe_below_15": "that ratio above 0 and below 15",
    "near_52w_low_5": "within 5% above the 250-session low", "below_sma200": "below the 200-session average",
    "volume_spike_2": "month-end traded value over twice the prior 20 sessions' average",
    "ath_fall_40": "40% or more below the highest close since 2008-06", "rsi_below_30": "Wilder RSI(14) below 30",
}
RULE_SCAN = {"near_52w_low_5": "near_52w_low:5.0", "below_sma200": "price_below_sma:200", "volume_spike_2": "volume_spike:2.0",
             "ath_fall_40": "ath_fall_at_least:40.0", "rsi_below_30": "rsi_below:30.0"}
RULE_MIN_GROUP, RULE_MIN_UNIVERSE = 10, 50
EPS_USABLE_DAYS, EPS_STALE_DAYS, ADJ_TOLERANCE = 60, 450, 0.02


def eps_ttm_frame(root: Path, w: Dict[str, pd.DataFrame], load=None) -> pd.DataFrame:
    """Trailing-twelve-month basic EPS for every isin on every session, point in time: four consecutive filed quarters (80-100
    days apart), usable 60 days after the latest quarter ended; left out (NaN) when older than 15 months or when the adjustment
    factor has moved more than 2% since (a split or bonus: the old EPS is another unit). `load(scrip)` -> DataFrame with
    quarter_end and eps_basic (default: the filed history in data/bse_results)."""
    from pflab.fundamentals import pit
    load = load or (lambda scrip: pit.load_history(scrip, root))
    cols = list(w["tr"].columns)
    sessions = w["tr"].index
    m = _duck.sql(f"select scrip_code, isin from '{root}/bse_scrip_isin/map.parquet' where isin is not null and isin <> ''").df()
    m = m[m["isin"].isin(cols)].drop_duplicates(["scrip_code", "isin"])
    eps = pd.DataFrame(np.nan, index=sessions, columns=cols)
    born = pd.DataFrame(np.nan, index=sessions, columns=cols)          # the adjustment factor on the day the EPS became usable
    qend = pd.DataFrame(np.nan, index=sessions, columns=cols)
    fac = (w["adj"] / w["close"]) if "close" in w else None
    for scrip, g in m.groupby("scrip_code"):
        try:
            h = load(str(scrip))
        except Exception:
            continue
        if h is None or len(h) < 4:
            continue
        h = h.sort_values("quarter_end").drop_duplicates("quarter_end")
        qe = pd.to_datetime(h["quarter_end"]).reset_index(drop=True)
        e = h["eps_basic"].astype(float).reset_index(drop=True)
        gap = qe.diff().dt.days
        ok = gap.between(80, 100).rolling(3).sum().eq(3) & e.rolling(4).count().eq(4)
        ttm = e.rolling(4).sum().where(ok)
        usable = qe + pd.Timedelta(days=EPS_USABLE_DAYS)
        pos = sessions.searchsorted(usable.to_numpy())
        for isin in g["isin"]:
            for p, v, q in zip(pos, ttm.to_numpy(), qe.to_numpy()):
                if p >= len(sessions) or not np.isfinite(v):
                    continue
                eps.iat[p, cols.index(isin)] = v
                qend.iat[p, cols.index(isin)] = q.astype("datetime64[D]").astype("int64")
                if fac is not None:
                    born.iat[p, cols.index(isin)] = fac.iat[p, cols.index(isin)]
    eps, born, qend = eps.ffill(), born.ffill(), qend.ffill()
    age = sessions.to_numpy().astype("datetime64[D]").astype("int64")[:, None] - qend.to_numpy()
    out = eps.where(age <= EPS_STALE_DAYS)
    if fac is not None:
        out = out.where(((fac / born) - 1.0).abs() <= ADJ_TOLERANCE)
    return out


def rule_frame(w: Dict[str, pd.DataFrame], rule: str, eps: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """1.0 where the rule is true, 0.0 where false, NaN where it cannot be told, for every session and isin (rows up to i
    use only sessions <= i)."""
    adj = w["adj"]
    if rule in ("pe_above_50", "pe_below_15"):
        if eps is None:
            raise ValueError("a P/E rule needs the EPS frame")
        pe = (w["close"] / eps).where(eps > 0)
        t = (pe > 50) if rule == "pe_above_50" else ((pe > 0) & (pe < 15))
        return t.astype(float).where(pe.notna())
    if rule == "near_52w_low_5":
        low = adj.rolling(250, min_periods=200).min()
        return (adj <= 1.05 * low).astype(float).where(low.notna() & adj.notna())
    if rule == "below_sma200":
        sma = adj.rolling(200, min_periods=200).mean()
        return (adj < sma).astype(float).where(sma.notna() & adj.notna())
    if rule == "volume_spike_2":
        to = w["turnover"]
        avg = to.rolling(20, min_periods=15).mean().shift(1)
        return (to > 2 * avg).astype(float).where(avg.notna() & to.notna() & (avg > 0))
    if rule == "ath_fall_40":
        ath = adj.cummax()
        ok = adj.expanding().count() >= 250
        return (adj <= 0.6 * ath).astype(float).where(ok & adj.notna())
    if rule == "rsi_below_30":
        d = adj.diff()
        au = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        ad = (-d).clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        rsi = 100 - 100 / (1 + au / ad.replace(0, np.nan))
        rsi = rsi.where(ad != 0, 100.0)
        return (rsi < 30).astype(float).where(rsi.notna())
    raise ValueError(rule)


def rule_filter_series(w: Dict[str, pd.DataFrame], mem: pd.DataFrame, frame: pd.DataFrame, direction: str, months: int,
                       start: str, end: str, round_trip_pct: float) -> pd.Series:
    """Per formation month: the group's next-`months` total return minus all members' (equal weights). For `out` the charges on
    the share of the group that changed are taken off; for `under` the series is the group's excess as it is and the decision
    uses the opposite sign (avoiding a name is not a trade)."""
    sessions = w["tr"].index
    every = month_ends(sessions, str(sessions[0].date()), str(sessions[-1].date()))
    tr_f = w["tr"].ffill()
    out, prev = {}, {}
    for k, i in enumerate(every):
        t = sessions[i]
        if i < HISTORY or k + months >= len(every) or not pd.Timestamp(start) <= t <= pd.Timestamp(end):
            continue
        j = every[k + months]
        live = set(mem[(mem["from_date"] <= t) & (mem["to_date"] > t)]["isin"]) & set(w["tr"].columns)
        cols = sorted(live)
        hist = w["adj"].iloc[i - HISTORY + 1:i + 1][cols].notna().sum()
        cols = [c for c in cols if hist[c] >= 200 and pd.notna(w["tr"].iloc[i][c])]
        if len(cols) < RULE_MIN_UNIVERSE:
            continue
        fwd = (tr_f.iloc[j][cols] / w["tr"].iloc[i][cols] - 1).dropna()
        sig = frame.iloc[i][fwd.index]
        pick = set(sig[sig == 1.0].index)
        if len(pick) < RULE_MIN_GROUP:
            continue
        last = prev.get(k - months, set())
        changed = len(pick - last) / len(pick) if last else 1.0
        prev[k] = pick
        cost = changed * round_trip_pct / 100 if direction == "out" else 0.0
        out[t] = float(fwd[list(pick)].mean() - fwd.mean()) - cost
    return pd.Series(out, dtype=float)


def rule_filter(root: Path, rule: str, direction: str, months: int, round_trip_pct: float, periods=(DEV, VAL),
                threshold_dev: float = T_DEV, load=None) -> dict:
    mem = members(root)
    w = wide_panel(root, sorted(set(mem["isin"])), "2008-06-01", "2022-06-30")
    eps = eps_ttm_frame(root, w, load) if rule.startswith("pe_") else None
    frame = rule_frame(w, rule, eps)
    sign = 1 if direction == "out" else -1
    res = {}
    for name, (a, b) in zip(("development", "validation"), periods):
        s = rule_filter_series(w, mem, frame, direction, months, a, b, round_trip_pct)
        m, t, n = nw_t(s.values, lags=max(1, months))
        res[name] = {"mean": m, "t": t, "n": n, "per": f"{months}-month excess of the group over all members"
                     + (" after charges" if direction == "out" else "")}
        if name == "development":
            res[name]["_returns"] = [float(sign * v) for v in s.values]     # the claimed side, for the deflated Sharpe ratio
    d, why = decide(res["development"], res["validation"], sign, MIN_MONTHS, 0.0, "months", threshold_dev)
    return {"decision": d, "why": why, **res}


def run(root: Path, template: str, params: dict, threshold_dev: float = T_DEV) -> dict:
    """Run a registered claim's template; the decision comes from `decide`, never from a model."""
    from pflab.hq import stocks
    bad = check_params(template, params)
    if bad:
        raise ValueError(bad)
    rt = stocks.round_trip_pct(stocks.DEFAULT_ORDER)
    if template == "cross_section":
        return cross_section(root, params["signal"], params["direction"], int(params["months"]), rt,
                             threshold_dev=threshold_dev)
    if template == "event_study":
        return event_study(root, params["kind"], params["direction"], int(params["sessions"]), rt, threshold_dev)
    if template == "holder_event":
        return holder_event(root, params["kind"], params["direction"], int(params["sessions"]), rt, threshold_dev)
    if template == "sector_reversion":
        return sector_reversion(root, params["direction"], rt, threshold_dev=threshold_dev)
    if template == "rule_filter":
        return rule_filter(root, params["rule"], params["direction"], int(params["months"]), rt, threshold_dev=threshold_dev)
    return calendar(root, params["effect"], params["direction"], threshold_dev)
