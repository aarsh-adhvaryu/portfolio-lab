"""Per-stock facts for the brain (S60, PLAN A18; the investor 2026-10-24: "it analyses each stock, not random things").

For every held and listed stock, facts made by code, never judgement from a model:

    drift    its weight against its own share under the advisor's rule (equal shares of the direct-stock bucket among
             the list names whose guard is OK, each capped at `max_weight`; a held name off the list has no share and
             gets no top-ups), the bucket against its bands, and the price trend (returns, moving averages, 52-week range)
    odds     from the stock's own last 3 years: how often it moved 10% up or down over a month and a quarter (windows,
             with the independent count), the chance of touching 5 / 10 / 20% below today within a month and a quarter
             (block bootstrap of its own daily returns, the mean removed, `plan.buyzone.touch_chance`, with the error),
             and its buy zone (the watch list's, else computed here without the valuation part)
    edge     its mean forward return over a quarter and a year against the Nifty 500 TRI over the same windows (up to 8
             years), the error from non-overlapping windows (n, t), after Zerodha's round-trip charges. A DESCRIPTION:
             no edge acts unless a pre-registered study passed it (CLAUDE.md rule 12); `actionable` only says the
             numbers are large enough to be worth such a study (n >= 20 independent windows and |t| >= 2)

Each result names its source and carries its n (the small-numbers rule, `calc/smalln.py`).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab.calc import smalln

TREND = {"1m": 21, "3m": 63, "6m": 126, "1y": 250}
MOVE_PCT, MOVE_H = 10.0, (21, 63)
FALLS, FALL_H = (5.0, 10.0, 20.0), (21, 63)
ODDS_SESSIONS = 750                     # the stock's own last 3 years (buy zone's HISTORY)
EDGE_H, EDGE_YEARS = (63, 250), 8
PATHS = 20_000                          # tail error at most ~0.35 pp: inside smalln.MAX_SE_PP
DEFAULT_ORDER = 50_000.0                # rupees, for the cost of a round trip when no share is known
T_MIN = 2.0


@dataclass
class Book:
    """What every per-stock tool needs, built once per pass."""
    asof: date
    investable: float
    values: Dict[str, float]                       # isin -> value held now (direct stocks)
    symbols: Dict[str, str]                        # isin -> symbol (held and listed)
    on_list: set
    guards: Dict[str, tuple]                       # isin -> (verdict, reasons)
    zones: Dict[str, dict]
    results: Dict[str, list]
    buckets: Dict[str, float]                      # bucket -> rupees
    bands: Dict[str, tuple]                        # bucket -> (target, soft, hard), fractions
    max_weight: float
    gains: Dict[str, tuple] = field(default_factory=dict)   # isin -> (value, cost)
    qtys: Dict[str, float] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def isin(self, symbol: str) -> Optional[str]:
        s = (symbol or "").strip().upper()
        return next((i for i, x in self.symbols.items() if (x or "").upper() == s), None)

    def candidates(self) -> List[str]:
        return [i for i in self.on_list if self.guards.get(i, ("not checked",))[0] == "ok"]


def book(con, asof: date, watch: Optional[dict] = None) -> Book:
    from pflab import _toml
    from pflab.plan import guards as gd, targets as tg, advisor
    from pflab.pm import today
    t = today.build(con, asof)
    pos = t["positions"]
    eq = {i for (i,) in con.execute("SELECT isin FROM instruments WHERE asset_class = 'equity'").fetchall()}
    pos = pos[pos["value"].notna() & (pos["qty"] > 0) & pos["isin"].isin(eq)]
    values = pos.groupby("isin")["value"].sum().to_dict()
    costs = pos.groupby("isin")["cost"].sum().to_dict()
    syms = {r.isin: str(r.symbol) for r in pos.itertuples()}
    lst = gd.stock_list()
    for s in lst:
        syms.setdefault(s["isin"], s["symbol"])
    notes = []
    bands: Dict[str, tuple] = {}
    max_w = advisor.DEFAULT_MAX_WEIGHT
    try:
        tt = tg.load()
        bands = {b.bucket: (b.target, b.soft_band, b.hard_band) for b in tt.buckets.values()}
        max_w = float(_toml.load(tg.default_path()).get("stocks", {}).get("max_weight", max_w))
    except Exception as e:                                   # no targets: drift has no share to compare with
        notes.append(f"targets not readable ({type(e).__name__}): no per-name share")
    rows = (watch or {}).get("rows", [])
    if not rows:
        notes.append("guards not checked yet (the watch list has not been computed): no name counts as a candidate")
    return Book(asof, float(t["investable"]) or 0.0, values, syms, {s["isin"] for s in lst},
                {r["isin"]: (r.get("guard", "not checked"), r.get("reasons", [])) for r in rows},
                {r["isin"]: r.get("zone") or {} for r in rows}, {r["isin"]: r.get("results") or [] for r in rows},
                dict(t["buckets"]), bands, max_w, {i: (values[i], costs.get(i, 0.0)) for i in values},
                pos.groupby("isin")["qty"].sum().to_dict(), notes)


def _pct(x: Optional[float], nd: int = 1) -> Optional[float]:
    return None if x is None or not math.isfinite(x) else round(x * 100, nd)


def trend(c: pd.Series) -> dict:
    v = c.dropna()
    if len(v) < 2:
        return {"note": "no price history"}
    px = float(v.iloc[-1])
    out = {"price": round(px, 2), "price_date": str(v.index[-1].date()), "sessions": int(len(v))}
    for k, n in TREND.items():
        out[f"return_{k}_pct"] = _pct(px / float(v.iloc[-n - 1]) - 1) if len(v) > n else None
    for n in (50, 200):
        out[f"vs_sma{n}_pct"] = _pct(px / float(v.iloc[-n:].mean()) - 1) if len(v) >= n else None
    y = v.iloc[-250:]
    out["from_52w_high_pct"] = _pct(px / float(y.max()) - 1)
    out["above_52w_low_pct"] = _pct(px / float(y.min()) - 1)
    return out


def drift(bk: Book, isin: str, c: pd.Series) -> dict:
    inv = bk.investable or float("nan")
    val = bk.values.get(isin, 0.0)
    w = val / inv if inv == inv and inv > 0 else None
    cands = bk.candidates()
    eq = bk.bands.get("equity")
    share, rule = None, ""
    if isin not in bk.on_list:
        rule = "not on the stock list: no share, no top-ups (the advisor buys list names only)"
    elif eq is None:
        rule = "no target for the direct-stock bucket"
    elif isin not in cands:
        g = bk.guards.get(isin, ("not checked", []))
        rule = f"guard {g[0]}: no new buying; nothing is sold by the rule"
    else:
        share = min(eq[0] / max(len(cands), 1), bk.max_weight)
        rule = (f"equal share of the direct-stock bucket among {len(cands)} list names with an OK guard, "
                f"capped at {bk.max_weight:.0%}")
    out = {"symbol": bk.symbols.get(isin), "held": isin in bk.values, "weight_pct": _pct(w, 2),
           "share_pct": _pct(share, 2), "gap_pct": _pct(w - share, 2) if (w is not None and share is not None) else None,
           "cap_pct": _pct(bk.max_weight, 0), "over_cap": bool(w is not None and w > bk.max_weight), "share_rule": rule}
    if isin in bk.gains and bk.gains[isin][1]:
        v, cst = bk.gains[isin]
        out["gain_pct"] = _pct(v / cst - 1)
    if eq is not None and inv == inv and inv > 0:
        bw = bk.buckets.get("equity", 0.0) / inv
        d = abs(bw - eq[0])
        out["bucket"] = {"name": "equity", "weight_pct": _pct(bw), "target_pct": _pct(eq[0]),
                         "soft_band_pct": _pct(eq[1]), "hard_band_pct": _pct(eq[2]),
                         "state": "inside its soft band" if d <= eq[1] else ("outside its soft band" if d <= eq[2]
                                                                              else "outside its hard band")}
    out["trend"] = trend(c)
    out["source"] = "portfolio today (ledger + Kite), targets.toml, the advisor's rule, prices"
    return out


def _windows(c: pd.Series, h: int) -> pd.Series:
    return (c.shift(-h) / c - 1).dropna()


def odds(bk: Book, isin: str, c: pd.Series, paths: int = PATHS) -> dict:
    from pflab.plan import buyzone as bz
    v = c.dropna().iloc[-ODDS_SESSIONS:]
    out: dict = {"symbol": bk.symbols.get(isin), "sessions": int(len(v)),
                 "source": f"the stock's own closes, last {len(v)} sessions; bootstrap {paths:,} paths, mean removed"}
    if len(v) < bz.YEAR:
        out["note"] = f"too little history ({len(v)} sessions, {bz.YEAR} needed): no odds"
        return out
    moves = {}
    for h in MOVE_H:
        r = _windows(v, h) * 100
        n_ind = len(r) // h
        up, dn = float((r >= MOVE_PCT).mean()), float((r <= -MOVE_PCT).mean())
        moves[f"{h}_sessions"] = {"up_10pct": smalln.rate(int(round(up * n_ind)), n_ind)["text"],
                                  "down_10pct": smalln.rate(int(round(dn * n_ind)), n_ind)["text"],
                                  "up_share": round(up, 3), "down_share": round(dn, 3), "windows": int(len(r)),
                                  "independent": n_ind}
    out["moves_end_to_end"] = moves
    px = float(v.iloc[-1])
    lr = np.diff(np.log(v.to_numpy(float)))
    falls = {}
    for h in FALL_H:
        t = bz.touch_chance(lr, [px * (1 - f / 100) for f in FALLS], px, paths=paths, horizon=h)
        falls[f"{h}_sessions"] = {f"touch_minus_{f:g}pct": smalln.tail(p, paths)["text"] for f, p in zip(FALLS, t["p"])}
    out["falls_touch"] = falls
    z = bk.zones.get(isin)
    if not z or z.get("verdict") is None:
        g = bk.guards.get(isin, ("ok",))[0]
        z = bz.zone(c.dropna(), bk.asof, guard=g if g in ("fail", "block") else "ok", paths=paths)
        z["computed_here"] = "no valuation part (the watch list adds it)"
    keep = ("verdict", "headline", "bottom", "top", "price", "rich", "implied_growth", "growth", "horizon", "computed_here")
    out["zone"] = {k: (round(z[k], 2) if isinstance(z.get(k), float) else z.get(k)) for k in keep if k in z}
    for k in ("touch_top", "touch_bottom"):
        if isinstance(z.get(k), dict):
            out["zone"][k] = z[k].get("text")
    return out


def round_trip_pct(order: float) -> float:
    from pflab.pm import costs
    b, _ = costs.estimate("equity_delivery", "buy", order)
    s, _ = costs.estimate("equity_delivery", "sell", order)
    return (b + s) / order * 100


def edge(bk: Book, isin: str, c: pd.Series, index: pd.Series, order: Optional[float] = None) -> dict:
    order = order or DEFAULT_ORDER
    cost = round_trip_pct(order)
    j = pd.concat([c.dropna().rename("s"), index.dropna().rename("m")], axis=1, join="inner").dropna()
    j = j[j.index >= j.index[-1] - pd.Timedelta(days=int(365.25 * EDGE_YEARS))] if len(j) else j
    out: dict = {"symbol": bk.symbols.get(isin), "round_trip_cost_pct": round(cost, 3), "order_rupees": round(order),
                 "source": f"the stock's adjusted closes and the NIFTY 500 TRI, common sessions ({len(j)}), up to "
                           f"{EDGE_YEARS} years; Zerodha delivery charges (pm/costs.py)",
                 "label": "historical description, not a forecast or a tested signal (CLAUDE.md rule 12)"}
    for h in EDGE_H:
        key = f"{h}_sessions"
        if len(j) <= h + 1:
            out[key] = {"note": f"too little history ({len(j)} sessions)"}
            continue
        fs, fm = _windows(j["s"], h), _windows(j["m"], h)
        ex = (fs - fm).dropna()
        ind = ex.iloc[::-1].iloc[::h]                       # non-overlapping windows, newest first
        n = int(len(ind))
        mean = float(ex.mean())
        se = float(ind.std(ddof=1) / math.sqrt(n)) if n >= 2 else float("nan")
        t = mean / se if se and math.isfinite(se) and se > 0 else float("nan")
        after = mean * 100 - cost
        ok = n >= smalln.MIN_N and math.isfinite(t) and abs(t) >= T_MIN
        out[key] = {"stock_mean_pct": _pct(float(fs.mean()), 2), "nifty500_mean_pct": _pct(float(fm.mean()), 2),
                    "excess_mean_pct": _pct(mean, 2), "excess_after_costs_pct": round(after, 2),
                    "independent_windows": n, "t": round(t, 2) if math.isfinite(t) else None,
                    "excess_label": smalln.average(mean * 100, n, "{:+.2f}%")["text"],
                    "worth_a_study": ok,
                    "reading": (f"history shows {mean * 100:+.2f}% a window against the Nifty 500 (t {t:.1f}, n {n})"
                                if ok else "no edge shown: too few independent windows or the excess is within noise")}
    return out


def index_series(root: Path) -> pd.Series:
    from pflab.data import indices
    df = indices.load("NIFTY500_TRI", root)
    return df.assign(date=pd.to_datetime(df["date"])).set_index("date")["close"].sort_index()


def closes(con, root: Path, isin: str, asof: date) -> pd.Series:
    from pflab.app import research
    return research.closes(con, root, isin, asof, years=EDGE_YEARS)


def order_size(bk: Book, isin: str) -> float:
    """The rupees a buy would be: what is missing to its share, else the default (for the round-trip cost)."""
    d = drift(bk, isin, pd.Series(dtype=float))
    if d["share_pct"] is not None and bk.investable:
        gap = (d["share_pct"] - (d["weight_pct"] or 0.0)) / 100 * bk.investable
        if gap > 5_000:
            return gap
    return DEFAULT_ORDER


def facts(con, root: Path, bk: Book, symbol: str, parts=("drift", "odds", "edge"), index=None) -> dict:
    isin = bk.isin(symbol)
    if not isin:
        return {"error": f"{symbol!r} is neither held nor on the stock list", "names": sorted(set(bk.symbols.values()))}
    c = closes(con, root, isin, bk.asof)
    out = {"symbol": bk.symbols[isin], "isin": isin, "asof": str(bk.asof),
           "guard": bk.guards.get(isin, ("not checked", []))[0], "guard_reasons": bk.guards.get(isin, ("", []))[1][:3]}
    if isin.startswith("INE"):                                 # S64: a company with too little detail -> the Tijori ask
        from pflab.agents import needs
        try:
            if needs.check_company(con, root, isin, symbol=bk.symbols[isin]) is not None:
                out["missing_detail"] = "results history is short; the investor was asked for the Tijori sheet"
        except Exception:                                      # a read never fails because the ask could not be made
            pass
    if "drift" in parts:
        out["drift"] = drift(bk, isin, c)
    if "odds" in parts:
        out["odds"] = odds(bk, isin, c)
    if "edge" in parts:
        out["edge"] = edge(bk, isin, c, index if index is not None else index_series(root), order_size(bk, isin))
        if bk.results.get(isin):
            out["results_forecast"] = bk.results[isin][:3]
    if "capm" in parts:
        out["capm"] = capm_part(root, isin, bk.asof)
    if "process" in parts:
        out["process"] = process_part(root, isin, c, bk.asof)
    if "business" in parts:
        from pflab.hq import business
        try:
            out["business"] = business.facts(con, root, isin, bk.symbols[isin], bk.asof, closes=c)
        except Exception as e:
            out["business"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    if "valuation" in parts:
        from pflab.hq import valuation
        try:
            out["valuation"] = valuation.facts(con, root, isin, bk.symbols[isin], c, bk.asof)
        except Exception as e:
            out["valuation"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    if bk.notes:
        out["notes"] = bk.notes
    return out


_ERP: Dict[str, float] = {}


def capm_part(root: Path, isin: str, asof: date) -> dict:
    """S64 CAPM facts by code (risk/capm.py): beta, alpha with t, the CAPM expected return (an estimate)."""
    from pflab.risk import capm
    try:
        f = capm.for_isin(root, isin, asof)
        out = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in f.items()}
        out["sentence"] = capm.describe(f)
        if f.get("beta") is not None:
            key = str(root)
            if key not in _ERP:
                _ERP[key] = capm.erp(root)
            out["expected_return_pct"] = round(capm.expected_return(f["beta"], f["rf_now"], _ERP[key]) * 100, 1)
            out["expected_return_label"] = (f"estimate: cash {f['rf_now'] * 100:.1f}% ({f['rf_label']}) + beta x market "
                                            f"premium {_ERP[key] * 100:.1f}% ({capm.ERP_LABEL}); a long-run average, not a forecast")
        out["source"] = "risk/capm.py (monthly excess returns on the Nifty 500 TRI, Newey-West)"
        return out
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:120]}"}


def process_part(root: Path, isin: str, c: pd.Series, asof: date) -> dict:
    """S64: what process the stock's log price (and its spread to its sector index) behaves like (quant/process.py)."""
    from pflab.data import indices
    from pflab.quant import comove, process
    v = c.dropna().iloc[-ODDS_SESSIONS:]
    out: dict = {"price": process.describe(np.log(v)) if len(v) >= 30 else {"sentence": "too little history"},
                 "source": "quant/process.py: ADF, Lo-MacKinlay variance ratios, OU half-life; the last 3 years of closes"}
    try:
        ind, key = comove.sector_index_for(root, isin, asof)
        if key:
            df = indices.load(key, root)
            idx = df.assign(date=pd.to_datetime(df["date"])).set_index("date")["close"].sort_index()
            sp, beta = process.spread(v, idx[idx.index <= pd.Timestamp(asof)])
            if len(sp) >= 250:
                out["spread_to_sector"] = {"sector_index": key, "industry": ind, "beta": round(beta, 2),
                                           **process.describe(sp)}
        else:
            out["spread_to_sector"] = {"note": f"no sector index for {ind or 'its industry'}"}
    except Exception as e:
        out["spread_to_sector"] = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
    return out


def overview(con, root: Path, bk: Book, paths: int = PATHS) -> dict:
    """One compact row per held and listed stock (the brain's first look), plus the market's tested states."""
    from pflab.plan import buyzone as bz, guards as gd
    idx = index_series(root)
    rows = []
    for isin in sorted(set(bk.values) | bk.on_list, key=lambda i: -bk.values.get(i, 0.0)):
        c = closes(con, root, isin, bk.asof)
        d = drift(bk, isin, c)
        r = {"symbol": bk.symbols.get(isin), "held": d["held"], "weight_pct": d["weight_pct"], "share_pct": d["share_pct"],
             "gap_pct": d["gap_pct"], "gain_pct": d.get("gain_pct"), "return_3m_pct": d["trend"].get("return_3m_pct"),
             "from_52w_high_pct": d["trend"].get("from_52w_high_pct"), "guard": bk.guards.get(isin, ("not checked",))[0],
             "zone": (bk.zones.get(isin) or {}).get("verdict")}
        v = c.dropna().iloc[-ODDS_SESSIONS:]
        if len(v) >= bz.YEAR:
            px = float(v.iloc[-1])
            t = bz.touch_chance(np.diff(np.log(v.to_numpy(float))), [px * 0.9], px, paths=paths, horizon=63)
            r["touch_minus_10pct_63s"] = smalln.tail(t["p"][0], paths)["text"]
        e = edge(bk, isin, c, idx, order_size(bk, isin)).get("63_sessions", {})
        r["edge_63s_after_costs_pct"], r["edge_63s_n"], r["edge_63s_t"] = (e.get("excess_after_costs_pct"),
                                                                          e.get("independent_windows"), e.get("t"))
        r["edge_63s_worth_a_study"] = bool(e.get("worth_a_study"))      # n >= 20 and |t| >= 2; never a signal
        rows.append(r)
    market = {}
    try:
        dip = gd.market_dip(bk.asof, root)
        market["dip_rule"] = {"nifty500_from_1y_high_pct": _pct(dip["drawdown"]), "active": bool(dip["active"]),
                              "source": "the adopted dip rule (S34): market-wide 10% dip"}
    except Exception as e:
        market["dip_rule"] = f"not read: {type(e).__name__}"
    try:
        cl = gd.market_cluster(bk.asof, root)
        if cl:
            market["state"] = {k: (round(v, 3) if isinstance(v, float) else v) for k, v in cl.items()
                               if isinstance(v, (str, float, int, bool))}
    except Exception as e:
        market["state"] = f"not read: {type(e).__name__}"
    return {"asof": str(bk.asof), "stocks": rows, "market": market, "notes": bk.notes,
            "fall_paths": paths, "source": "hq/stocks.py (drift, odds, edge by code)"}
