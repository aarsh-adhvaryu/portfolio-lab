"""Stress scenarios on what the book actually holds (S83 L7). Code only; for the Forecasts screen later.

Five named scenarios: "AI spending bubble bursts" (two windows: the 2000-02 and the 2021-22 tech falls, each reported, the worse one is the headline), "2008" (2008-01-01..2009-03-09),
"2020" (2020-02-19..2020-03-23), and "the dollar falls 10% against the rupee" (only the US sub-book is hit: its rupee value falls 10% from the exchange rate, its shares unchanged).

A holding's fall in a window is its OWN return in it (its adjusted closes in `data/panel/prices.parquet`, or the NAV history, or for a US share `data/us/raw`) where its history covers both ends
of the window, else (basis "estimate") its market's fall in the window times its sensitivity (beta) to that market over the last 250 sessions before `day`. A market is the Nifty 500 total
return index for an Indian share, the rupee gold series for a gold fund, the rupee Nasdaq series for an India-listed international fund, SPY for a US share; in the AI scenario the market of
every share is the Nasdaq (a cross-market beta is worked on weekly returns). Too little history for a beta: 1.0, said so. A US share's rupee fall is its dollar fall and the dollar-rupee
move of the window. Cash does not fall. Figures are signed returns: -23.4 means the value fell 23.4%.

`run(con, day, market)` -> the figures for the India book (scope IN), the US sub-book (US) and the whole (ALL); `store(...)` keeps them in `stress_s83` with the holdings they were made on;
`latest(con)` reads the last stored day. The whole book comes from `pflab.us.wholebook.whole_book_inr` when that module is importable, else the rupee book and the US holdings read from the
`us_*_s81` tables are added (the label says which).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

BETA_SESSIONS = 250
MIN_BETA_OBS = 60                                     # daily; 40 weekly
EDGE_DAYS = 10                                        # a history must start within this many days of the window's start and run to within this many of its end
SCOPES = ("IN", "US", "ALL")
FX_SHOCK = -0.10
LABEL = ("estimate where the basis says so: a holding with no history in a window is its market's fall times its sensitivity to that market over the last 250 sessions; signed returns "
         "(negative = a fall); cash does not fall; paper money")
WINDOWS = {
    "AI spending bubble bursts": [("2000-03-10", "2002-10-09"), ("2021-11-19", "2022-12-28")],
    "2008": [("2008-01-01", "2009-03-09")],
    "2020": [("2020-02-19", "2020-03-23")],
}
FX_NAME = "the dollar falls 10% against the rupee"
NAMES = list(WINDOWS) + [FX_NAME]


def _root(root) -> Path:
    if root is None:
        from pflab.data import data_dir
        root = data_dir()
    return Path(root)


def _d(s) -> date:
    return s if isinstance(s, date) else date.fromisoformat(str(s))


# --- the series -----------------------------------------------------------------------------------------------------------------------------

def _glob(kind: str, key: str, root: Path) -> Optional[pd.Series]:
    from pflab.paper import benchmark
    return benchmark._load(kind, key, root)


def _first(*series: Optional[pd.Series]) -> Optional[pd.Series]:
    """The series that reaches back furthest (FRED's dollar-rupee runs from 1973, the market one from 2003)."""
    have = [s for s in series if s is not None and len(s)]
    return min(have, key=lambda s: s.index.min()) if have else None


def reference_series(root: Path) -> Dict[str, Optional[pd.Series]]:
    """The market series, each by name: 'nifty500' (TRI), 'nasdaq' (USD), 'spy' (USD), 'usdinr' (the longest series, FRED's), 'gold_inr', 'intl_inr'."""
    from pflab.core import pick_score
    from pflab.paper import benchmark
    lv = benchmark.class_levels(root)
    return {"nifty500": lv.get("equity"), "nasdaq": _glob("global", "US_NASDAQ", root), "spy": pick_score.us_series("SPY", root), "usdinr": _first(_glob("macro", "USDINR", root), _glob("global", "FX_USDINR", root)),
            "gold_inr": lv.get("gold"), "intl_inr": lv.get("international")}


def _covers(s: Optional[pd.Series], a: date, b: date) -> bool:
    if s is None or not len(s):
        return False
    return s.index.min().date() <= a + timedelta(days=EDGE_DAYS) and s.index.max().date() >= b - timedelta(days=EDGE_DAYS)


def window_return(s: Optional[pd.Series], a: date, b: date) -> Optional[float]:
    """The series' return from the first close on or after `a` to the last close on or before `b`; None unless its history covers both ends (within EDGE_DAYS)."""
    if not _covers(s, a, b):
        return None
    lo = s[s.index >= pd.Timestamp(a)]
    hi = s[s.index <= pd.Timestamp(b)]
    if lo.empty or hi.empty or (lo.index[0].date() - a).days > EDGE_DAYS or (b - hi.index[-1].date()).days > EDGE_DAYS or lo.index[0] >= hi.index[-1]:
        return None
    return float(hi.iloc[-1] / lo.iloc[0] - 1.0)


def scenarios(root=None) -> List[dict]:
    """The five scenarios with their windows and which reference series cover them (so the screens can say which windows exist in the data)."""
    root = _root(root)
    ref = reference_series(root)
    out = []
    for name in NAMES:
        if name == FX_NAME:
            out.append({"name": name, "kind": "fx", "shock_pct": FX_SHOCK * 100.0, "windows": [], "hits": "the US sub-book only (its rupee value, from the exchange rate; shares unchanged)"})
            continue
        ws = []
        for a, b in WINDOWS[name]:
            a_, b_ = _d(a), _d(b)
            cov = {k: _covers(ref.get(k), a_, b_) for k in ("nifty500", "nasdaq", "spy", "usdinr", "gold_inr", "intl_inr")}
            ws.append({"start": a, "end": b, "series_cover": cov, "market_series": "nasdaq" if name.startswith("AI") else "nifty500 (India) / spy (US)",
                       "nasdaq_fall_pct": None if window_return(ref.get("nasdaq"), a_, b_) is None else round(window_return(ref["nasdaq"], a_, b_) * 100.0, 2),
                       "exists_in_data": bool(cov["nasdaq"] if name.startswith("AI") else (cov["nifty500"] or cov["spy"]))})
        out.append({"name": name, "kind": "window", "windows": ws, "hits": "every holding"})
    return out


# --- what is held -----------------------------------------------------------------------------------------------------------------------------

def _history_in(con, isin: str, root: Path, day: date, cache: dict) -> Optional[pd.Series]:
    if isin in cache:
        return cache[isin]
    s = None
    try:
        d = pd.read_parquet(root / "panel" / "prices.parquet", columns=["date", "isin", "adj_close"], filters=[("isin", "==", isin)])
        d = d[d["adj_close"] > 0]
        if len(d):
            s = pd.Series(d["adj_close"].astype(float).to_numpy(), index=pd.to_datetime(d["date"])).sort_index()
    except Exception:
        s = None
    if s is None or s.empty:
        try:
            rows = con.execute("SELECT date, nav FROM navs WHERE isin=? AND nav > 0 ORDER BY date", [isin]).fetchall()
            if rows:
                s = pd.Series([float(r[1]) for r in rows], index=pd.to_datetime([r[0] for r in rows]))
        except Exception:
            s = None
    if s is not None:
        s = s[~s.index.duplicated(keep="last")]
        s = s[s.index <= pd.Timestamp(day)]
    cache[isin] = s if s is not None and len(s) else None
    return cache[isin]


def india_holdings(con, day: date) -> Tuple[List[dict], float]:
    """-> (holdings of the rupee book, its total value in rupees including cash and bank)."""
    from pflab.paper import allocation, book
    h = book.holdings(con, day)
    out = []
    for r in h["rows"]:
        v = float(r["value"] or 0.0)
        if v <= 0:
            continue
        out.append({"symbol": r["symbol"] or r["isin"], "key": r["isin"], "market": "IN", "value_inr": v,
                    "klass": allocation.class_of(r["asset_class"], r.get("name"), r["symbol"], r["isin"])})
    return out, float(h["value"] or 0.0)


def us_holdings(con, day: date, root: Path) -> Tuple[List[dict], float, Optional[dict]]:
    """-> (US sub-book holdings with rupee values, the sub-book's total in rupees including its dollar cash, the FX used). Read from the `us_*_s81` tables; nothing when no account is open."""
    try:
        from pflab.us import book as ub, data as ud, fx as usfx, instruments as uins
        if ub.account(con) is None:
            return [], 0.0, None
        fx = usfx.rate_for(con, day, root, max_age_days=10)
        if fx is None:
            return [], 0.0, None
        qty: Dict[str, float] = {}
        for l in ub.open_lots(con, day):
            sym = (l["symbol"] or uins.symbol_of(con, l["isin"]) or l["isin"]).upper()
            qty[sym] = qty.get(sym, 0.0) + float(l["qty"])
        out, total = [], 0.0
        for sym, q in sorted(qty.items()):
            b = ud.last_on_or_before(ud.bars(sym, root), day)
            if not b:
                continue
            v = q * b["close"] * fx["rate"]
            total += v
            out.append({"symbol": sym, "key": sym, "market": "US", "value_inr": v, "klass": "us_equity", "shares": q, "close_usd": b["close"]})
        cash = float(ub.cash(con, day)) * fx["rate"]
        return out, total + cash, fx
    except Exception:
        return [], 0.0, None


def whole_book(con, day: date, root: Path, ih: float, uh: float) -> Tuple[float, float, str]:
    """-> (rupee book, US sub-book in rupees, label of where they come from). `pflab.us.wholebook.whole_book_inr` when importable, else the figures read here."""
    try:
        from pflab.us import wholebook
        w = wholebook.whole_book_inr(con, day, root)
        return float(w["rupee_book_inr"]), float(w["us_book_inr"]), "the whole book from us.wholebook.whole_book_inr"
    except Exception:
        return ih, uh, "us.wholebook not available: the rupee book plus the US sub-book read from the us_*_s81 tables here"


# --- a holding's fall -------------------------------------------------------------------------------------------------------------------------

def _beta(h: pd.Series, ref: pd.Series, day: date, weekly: bool) -> Tuple[Optional[float], int]:
    a, b = h[h.index <= pd.Timestamp(day)], ref[ref.index <= pd.Timestamp(day)]
    if weekly:
        a, b = a.resample("W-FRI").last().dropna(), b.resample("W-FRI").last().dropna()
        n, need = BETA_SESSIONS // 5, MIN_BETA_OBS * 2 // 3
    else:
        a, b = a.tail(BETA_SESSIONS + 1), b.tail(BETA_SESSIONS + 5)
        n, need = BETA_SESSIONS, MIN_BETA_OBS
    j = pd.concat([a.pct_change().rename("h"), b.pct_change().rename("m")], axis=1, join="inner").dropna().tail(n)
    if len(j) < need or float(j["m"].var()) <= 0:
        return None, len(j)
    return float(j["h"].cov(j["m"]) / j["m"].var()), len(j)


def _holding_fall(con, h: dict, name: str, a: date, b: date, day: date, ref: Dict[str, Optional[pd.Series]], root: Path, cache: dict) -> dict:
    """-> {'fall_pct', 'basis', 'detail'} for one holding in one window."""
    ai = name.startswith("AI")
    mk, klass = h["market"], h["klass"]
    if klass == "cash":
        return {"fall_pct": 0.0, "basis": "own history", "detail": {"note": "cash does not fall"}}
    series = None
    if mk == "IN":
        series = _history_in(con, h["key"], root, day, cache)
    else:
        from pflab.core import pick_score
        series = pick_score.us_series(h["key"], root)
    fxr = 1.0
    fx_note = None
    if mk == "US":
        fxw = window_return(ref.get("usdinr"), a, b)
        fxr = 1.0 + (fxw or 0.0)
        fx_note = "the dollar-rupee move of the window is counted" if fxw is not None else "no dollar-rupee data for this window: the rupee move is not counted"
    own = window_return(series, a, b) if series is not None else None
    if own is not None:
        return {"fall_pct": ((1.0 + own) * fxr - 1.0) * 100.0, "basis": "own history", "detail": {"own_return_pct": own * 100.0, "fx": fx_note}}
    # the estimate: its market's fall times its beta to that market over the last 250 sessions
    if mk == "US":
        rk, weekly = ("nasdaq" if ai else "spy"), False
    elif klass == "gold":
        rk, weekly = "gold_inr", False
    elif klass == "international":
        rk, weekly = "intl_inr", False
    else:
        rk, weekly = ("nasdaq", True) if ai else ("nifty500", False)
    m = window_return(ref.get(rk), a, b)
    if m is None:
        return {"fall_pct": None, "basis": "no data", "detail": {"note": f"no own history and no {rk} series covering {a}..{b}", "market_series": rk}}
    beta, n = (None, 0)
    if series is not None and ref.get(rk) is not None:
        beta, n = _beta(series, ref[rk], day, weekly)
    note = f"beta {beta:.2f} to {rk} over {n} {'weekly' if weekly else 'daily'} returns" if beta is not None else f"beta 1.0 assumed: under the minimum history to measure it ({n} returns)"
    beta = 1.0 if beta is None else beta
    raw = m * beta
    usd = max(raw, -1.0)                                      # a share cannot lose more than all of it: the straight-line estimate overstates a deep fall for a high beta
    return {"fall_pct": ((1.0 + usd) * fxr - 1.0) * 100.0, "basis": "estimate", "detail": {"market_series": rk, "market_return_pct": m * 100.0, "beta": beta, "beta_note": note, "fx": fx_note,
                                                                                              "straight_line_pct": raw * 100.0, "floored_at_total_loss": raw < -1.0}}


def _scenario_result(name: str, items: List[dict], total: float, fall_of) -> dict:
    """The book's fall from the holdings' falls (cash and holdings with no figure count as no fall)."""
    rows, loss = [], 0.0
    for h in items:
        f = fall_of(h)
        rows.append({"symbol": h["symbol"], "market": h["market"], "value_inr": round(h["value_inr"], 2), "fall_pct": None if f["fall_pct"] is None else round(f["fall_pct"], 2),
                     "basis": f["basis"], "detail": f.get("detail")})
        if f["fall_pct"] is not None:
            loss += h["value_inr"] * f["fall_pct"] / 100.0
    known = [r for r in rows if r["fall_pct"] is not None]
    worst = min(known, key=lambda r: r["fall_pct"]) if known else None
    return {"scenario": name, "book_fall_pct": round(loss / total * 100.0, 3) if total > 0 else 0.0, "holdings": rows,
            "worst_holding": None if worst is None else {"symbol": worst["symbol"], "fall_pct": worst["fall_pct"], "basis": worst["basis"], "loss_inr": round(worst["value_inr"] * worst["fall_pct"] / 100.0, 2)},
            "book_value_inr": round(total, 2), "loss_inr": round(loss, 2)}


def run(con, day: date, market: str = "ALL", root=None) -> dict:
    """The five scenarios for the India book, the US sub-book and the whole (`market` 'IN' or 'US' gives only that scope). -> {'day', 'scopes': {scope: {'value_inr', 'scenarios': [...]}}, ...}."""
    root = _root(root)
    ref = reference_series(root)
    ih, itot = india_holdings(con, day)
    uh, utot, ufx = us_holdings(con, day, root)
    rupee_total, us_total, src = whole_book(con, day, root, itot, utot)
    cache: dict = {}
    memo: dict = {}

    def fall(h, name, a, b):
        k = (h["market"], h["key"], name, a, b)
        if k not in memo:
            memo[k] = _holding_fall(con, h, name, _d(a), _d(b), day, ref, root, cache)
        return memo[k]

    scopes = {"IN": (ih, rupee_total), "US": (uh, us_total), "ALL": (ih + uh, rupee_total + us_total)}
    want = SCOPES if market == "ALL" else (market,)
    out_scopes = {}
    meta = scenarios(root)
    for scope in want:
        items, total = scopes[scope]
        res = []
        for name in NAMES:
            if name == FX_NAME:
                def fx_fall(h):
                    return {"fall_pct": FX_SHOCK * 100.0, "basis": "stated shock", "detail": {"note": "the dollar falls 10% against the rupee; shares unchanged"}} if h["market"] == "US" \
                        else {"fall_pct": 0.0, "basis": "not hit", "detail": {"note": "the rupee book is not hit"}}
                r = _scenario_result(name, items, total, fx_fall)
                us_cash = max(0.0, us_total - sum(h["value_inr"] for h in uh)) if scope in ("US", "ALL") else 0.0
                if us_cash > 0:                                           # the sub-book's dollar cash is hit too
                    r["loss_inr"] = round(r["loss_inr"] + us_cash * FX_SHOCK, 2)
                    r["book_fall_pct"] = round(r["loss_inr"] / total * 100.0, 3) if total > 0 else 0.0
                    r["holdings"].append({"symbol": "US cash (USD)", "market": "US", "value_inr": round(us_cash, 2), "fall_pct": FX_SHOCK * 100.0, "basis": "stated shock", "detail": None})
                r["window"] = None
                res.append(r)
                continue
            per = []
            for a, b in WINDOWS[name]:
                r = _scenario_result(name, items, total, lambda h, a=a, b=b, name=name: fall(h, name, a, b))
                r["window"] = f"{a}..{b}"
                per.append(r)
            usable = [r for r in per if any(h["fall_pct"] is not None for h in r["holdings"])] or per
            head = dict(min(usable, key=lambda r: r["book_fall_pct"]))
            head["windows"] = [{"window": r["window"], "book_fall_pct": r["book_fall_pct"], "worst_holding": r["worst_holding"],
                                "holdings_without_a_figure": [h["symbol"] for h in r["holdings"] if h["fall_pct"] is None]} for r in per]
            head["note"] = (f"the worse of {len(per)} windows is shown" if len(per) > 1 else None)
            res.append(head)
        out_scopes[scope] = {"value_inr": round(total, 2), "holdings": len(items), "scenarios": res}
    return {"day": str(day), "market": market, "scopes": out_scopes, "scenario_windows": meta, "whole_book_source": src, "us_fx": None if ufx is None else {"rate": ufx["rate"], "source": ufx["source"]},
            "label": LABEL, "sign": "negative = a fall"}


# --- storing and reading ------------------------------------------------------------------------------------------------------------------------

def store(con, day: date, result: dict) -> int:
    """Keep one row per scope and scenario for `day` (a re-run replaces the day's rows) with the holdings the figures were made on. -> rows written."""
    from pflab.pm.store import next_id
    n = 0
    for scope, sc in result["scopes"].items():
        for r in sc["scenarios"]:
            con.execute("DELETE FROM stress_s83 WHERE day=? AND scope=? AND scenario=?", [day, scope, r["scenario"]])
            detail = {"holdings": r["holdings"], "worst_holding": r["worst_holding"], "window": r.get("window"), "windows": r.get("windows"), "book_value_inr": r["book_value_inr"],
                      "loss_inr": r["loss_inr"], "whole_book_source": result["whole_book_source"], "label": LABEL}
            con.execute("INSERT INTO stress_s83 VALUES (?,?,?,?,?,?)", [next_id(con, "stress_s83", "stress_id"), day, scope, r["scenario"], r["book_fall_pct"], json.dumps(detail, default=str)])
            n += 1
    return n


def run_and_store(con, day: date, market: str = "ALL", root=None) -> dict:
    res = run(con, day, market, root)
    res["stored"] = store(con, day, res)
    return res


def latest(con, scope: Optional[str] = None) -> dict:
    """The last stored day's figures: {'day', 'scopes': {scope: {'scenarios': [{'scenario', 'book_fall_pct', 'worst_holding', 'holdings', 'window', ...}]}}} or {'day': None} when none."""
    d = con.execute("SELECT max(day) FROM stress_s83").fetchone()[0]
    if d is None:
        return {"day": None, "scopes": {}, "note": "no stress figures stored yet (the stress_daily job stores them each day)"}
    q = "SELECT scope, scenario, fall_pct, detail_json FROM stress_s83 WHERE day=?" + (" AND scope=?" if scope else "") + " ORDER BY stress_id"
    scopes: Dict[str, dict] = {}
    for sc, name, fall, dj in con.execute(q, [d] + ([scope] if scope else [])).fetchall():
        det = json.loads(dj or "{}")
        scopes.setdefault(sc, {"value_inr": det.get("book_value_inr"), "scenarios": []})["scenarios"].append(
            {"scenario": name, "book_fall_pct": fall, "worst_holding": det.get("worst_holding"), "holdings": det.get("holdings"), "window": det.get("window"), "windows": det.get("windows"),
             "loss_inr": det.get("loss_inr")})
    return {"day": str(d), "scopes": scopes, "label": LABEL, "sign": "negative = a fall"}
