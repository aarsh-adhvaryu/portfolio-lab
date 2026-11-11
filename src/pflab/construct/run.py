"""`construct` on the live paper book (S79b item 18A): read the book, the ensemble's forecasts, the prices and the allocation target; build the optimisation problem;
solve; report the target weights, the trades they imply, the binding constraints and the gap to the current sizing rules. Read-only except for the optional log row.

Inputs, and what each one is
    expected return   mu = equity_premium (a stated prior, the same for every name that HAS a forecast) + tilt, where the tilt is the annualised log of the hedge forecast's median
                      return over `horizon` sessions (the ensemble's departure from the naive no-view forecast, clipped at +-tilt_cap). A name WITHOUT a forecast gets mu = 0
                      (zero expected excess: no view, no reason to take its risk) and a shrunk volatility estimate.
    dispersion        the hedge forecast's 10th-90th range turned into an annual volatility, blended (geometric, `vol_blend`) with the shrunk covariance's own volatility.
    risk              Ledoit-Wolf shrunk covariance of the last `window` daily returns, point in time (`risk.py`).
    rails             a company 10%, a sector 25%, one ETF 35% (`paper/rails.py`); the circuit breaker (12% below the account's own high) forbids all new buying; cash >= 0; no
                      short sale, no F&O. A holding already over a rail is never sold by force and never added to.
    costs             Zerodha charges and the estimated FIFO tax of a sale (`costs.py`), plus a small turnover damper.
    allocation        the system's own target (`paper/allocation.py`) as a soft band: a gap inside the band costs nothing, a bigger one costs lambda x (excess gap)^2.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pflab.construct import costs, optimiser as O, risk, settings

MIN_TRADE = 0.001                       # a change smaller than 0.1% of the book is not reported as a trade


# --- prices -----------------------------------------------------------------------------------------------------------------------
def load_closes(con, root, isins: List[str], asof: date, years: int = 2) -> Dict[str, pd.Series]:
    """Daily adjusted closes of each ISIN (the research panel, spliced onto the store's closes as `app/research.closes` does), one panel query for all of them."""
    from pflab import _duck
    from pflab.data import data_dir
    root = Path(root) if root else data_dir()
    isins = [i for i in dict.fromkeys(isins) if i and not i.startswith(("ZZ", "US:"))]
    out: Dict[str, pd.Series] = {}
    if not isins:
        return out
    p = root / "panel" / "prices.parquet"
    panel = pd.DataFrame()
    if p.exists():
        inl = ",".join(repr(i) for i in isins)
        panel = _duck.sql(f"SELECT date, isin, adj_close FROM '{p.as_posix()}' WHERE isin IN ({inl}) AND date >= DATE '{asof - timedelta(days=365 * years)}' "
                          f"AND date <= DATE '{asof}' ORDER BY isin, date").df()
    for isin in isins:
        a = pd.Series(dtype=float)
        if len(panel):
            g = panel[panel["isin"] == isin]
            a = pd.Series(g["adj_close"].to_numpy(float), index=pd.to_datetime(g["date"]))
        s = con.execute("SELECT date, close FROM prices WHERE isin=? AND date<=? AND close > 0 ORDER BY date", [isin, asof]).df()
        b = pd.Series(s["close"].to_numpy(float), index=pd.to_datetime(s["date"])) if len(s) else pd.Series(dtype=float)
        if a.empty:
            r = b
        elif b.empty:
            r = a
        else:
            common = a.index.intersection(b.index)
            if len(common):
                k = b.loc[common[-1]] / a.loc[common[-1]]
                r = pd.concat([(a * k)[a.index <= common[-1]], b[b.index > common[-1]]])
            else:
                r = pd.concat([a, b[b.index > a.index[-1]]])
        r = r[~r.index.duplicated(keep="last")].sort_index().dropna()
        if len(r):
            out[isin] = r
    return out


# --- forecasts --------------------------------------------------------------------------------------------------------------------
def forecast_inputs(con, market: str, day: date, st: dict, isins: Optional[List[str]] = None) -> Dict[str, dict]:
    """{isin: {'tilt', 'sigma', 'as_of', 'q10','q50','q90'}} from the latest live HEDGE forecast dated <= day (and not older than `forecast_max_age_days`), at the configured horizon.
    tilt and sigma are annual. Empty when there is none."""
    h = int(st["horizon"])
    try:
        r = con.execute("SELECT max(as_of) FROM forecasts_s79 WHERE market=? AND source='live' AND forecaster='hedge' AND horizon_sessions=? AND as_of<=?", [market, h, day]).fetchone()
        if not r or r[0] is None or (day - r[0]).days > int(st["forecast_max_age_days"]):
            return {}
        asof = r[0]
        rows = con.execute("SELECT subject, quantiles_json FROM forecasts_s79 WHERE market=? AND source='live' AND forecaster='hedge' AND horizon_sessions=? AND as_of=?", [market, h, asof]).fetchall()
    except Exception:
        return {}
    out = {}
    ann = 252.0 / h
    for subject, qj in rows:
        if isins is not None and subject not in isins:
            continue
        if len(str(subject)) != 12:                                   # the index is not a candidate; names are ISINs
            continue
        try:
            q = {float(k): float(v) for k, v in json.loads(qj).items()}
            lq10, lq50, lq90 = (math.log1p(q[0.1]), math.log1p(q[0.5]), math.log1p(q[0.9]))
        except Exception:
            continue
        tilt = float(np.clip(lq50 * ann, -st["tilt_cap"], st["tilt_cap"]))
        sigma = (lq90 - lq10) / (2 * 1.2815515655446004) * math.sqrt(ann)
        out[subject] = {"tilt": tilt, "sigma": float(sigma), "as_of": str(asof), "q10": q[0.1], "q50": q[0.5], "q90": q[0.9]}
    return out


# --- the problem ------------------------------------------------------------------------------------------------------------------
def _class_of(row: dict) -> str:
    from pflab.paper import allocation
    return allocation.class_of(row.get("asset_class"), row.get("name"), row.get("symbol"), row.get("isin"))


def build(con, now: datetime, root=None, closes: Optional[Dict[str, pd.Series]] = None, decisions: Optional[List[dict]] = None, market: str = "IN") -> Tuple[Optional[O.Problem], dict]:
    """The optimisation problem for the paper book on now.date(), and a meta dict (per-name facts, notes). (None, meta) when there is no book."""
    from pflab.paper import allocation, book, cadence, rails
    st = settings()
    day = now.date()
    meta: dict = {"as_of": str(day), "notes": []}
    if not book.started(con):
        meta["note"] = "no paper book yet"
        return None, meta
    h = book.holdings(con, day)
    total = float(h["value"] or 0.0)
    if total <= 0:
        meta["note"] = "the paper book has no value"
        return None, meta
    held = {r["isin"]: r for r in h["rows"]}
    dec = decisions or []
    dec_by = {}
    for d in dec:
        if d.get("isin") and str(d.get("action", "")).upper() in ("BUY", "ADD", "REDUCE", "SELL", "HOLD", "WAIT"):
            dec_by[d["isin"]] = str(d["action"]).upper()
    # candidates: the book, the names the ensemble forecasts, the paper watchlist (a decision list restricts it to the decisions)
    cand = list(held)
    if dec:
        cand += [i for i in dec_by if i not in cand]
    else:
        fi_all = forecast_inputs(con, market, day, st)
        cand += [i for i in fi_all if i not in cand]
        try:
            for (sym,) in con.execute("SELECT DISTINCT symbol FROM paper_watch WHERE status IN ('waiting','near','triggered')").fetchall():
                i = book.isin_of(con, sym) if sym else None
                if i and i not in cand:
                    cand.append(i)
        except Exception:
            pass
    info = {}
    for i in cand:
        if i in held:
            r = held[i]
            info[i] = {"isin": i, "symbol": r["symbol"], "name": r["name"], "sector": r["sector"], "asset_class": r["asset_class"], "price": r["price"], "value": float(r["value"] or 0.0)}
        else:
            m = book.inst(con, i)
            px = book.close_on(con, i, day)
            info[i] = {"isin": i, "symbol": m["symbol"] or i, "name": m["name"], "sector": m["sector"], "asset_class": m["asset_class"], "price": px[1] if px else None, "value": 0.0}
    names = [i for i in cand if info[i]["price"]]
    if not names:
        meta["note"] = "no candidate has a price"
        return None, meta
    n = len(names)
    w0 = np.array([info[i]["value"] / total for i in names])
    closes = closes if closes is not None else load_closes(con, root, names, day)
    px_df = pd.DataFrame({i: closes[i] for i in names if i in closes and len(closes[i])})
    rets = risk.daily_returns(px_df, day, int(st["window"])) if px_df.shape[1] else pd.DataFrame()
    fi = forecast_inputs(con, market, day, st, set(names))
    fvol = {i: v["sigma"] for i, v in fi.items()}
    cov, src, shrink = risk.cov_for(names, rets, fvol, float(st["vol_blend"]), float(st["fallback_vol"]))
    mu = np.array([(float(st["equity_premium"]) + fi[i]["tilt"]) if i in fi else 0.0 for i in names])
    meta["expected_return_source"] = {info[i]["symbol"]: ("forecast: premium %.1f%% + tilt %+.1f%%" % (st["equity_premium"] * 100, fi[i]["tilt"] * 100) if i in fi else "no forecast: zero expected excess; held where it is")
                                      for i in names}
    # bounds, groups
    buyable = np.array([(info[i]["asset_class"] or "") in book.BUYABLE for i in names])
    is_etf = np.array([(info[i]["asset_class"] or "") == "etf" for i in names])
    ub = np.array([rails.limit_of(info[i]["asset_class"], info[i].get("symbol")) for i in names])      # S82 (A56): a broad-market index ETF 60%, another ETF 35%, a stock 10%
    no_buy = ~buyable
    frozen = ~buyable                                                  # funds, SGBs and gold are neither added to nor sized here
    if st.get("freeze_no_forecast", True):                              # no forecast: zero expected excess AND no view, so no trade either way (it still counts in the risk)
        frozen = frozen | np.array([i not in fi for i in names])
        if any(i not in fi for i in names):
            meta["notes"].append("names with no forecast are held where they are (no view, no trade)")
    br = cadence.breaker(con)
    if br["on"]:
        no_buy = np.ones(n, bool)
        meta["notes"].append(f"circuit breaker on ({-br['drawdown']:.1%} below the account's high): no new buying")
    no_sell = np.zeros(n, bool)
    if dec:                                                            # sizing the team's decisions: only the names it decided on move
        act = np.array([dec_by.get(i, "") for i in names])
        frozen = frozen | np.isin(act, ["", "HOLD", "WAIT", "SELL"])
        no_buy = no_buy | np.isin(act, ["REDUCE"])
        no_sell = np.isin(act, ["BUY", "ADD"])
    sectors: Dict[str, np.ndarray] = {}
    for k, i in enumerate(names):
        sec = info[i]["sector"]
        if sec and (info[i]["asset_class"] or "") != "etf":
            sectors.setdefault(sec, np.zeros(n))[k] = 1.0
    groups = {f"sector {s}": (m, max(rails.MAX_SECTOR, float(m @ w0))) for s, m in sectors.items()}
    buy_c = np.zeros(n)
    sell_c = np.zeros(n)
    lots_by = {}
    for k, i in enumerate(names):
        ac = info[i]["asset_class"]
        buy_c[k] = costs.rate(ac, "buy")
        lots = [(a, float(q), float(c), tcl) for a, q, c, tcl in con.execute(book._lots_sql("acq_date, qty, cost_per_unit, tax_class", " AND isin=? ORDER BY acq_date, lot_id"), [i]).fetchall()] if w0[k] > 0 else []
        lots_by[i] = lots
        sell_c[k] = costs.rate(ac, "sell") + (costs.tax_rate(lots, float(info[i]["price"]), day, ac, book.inst(con, i)["tax_class"]) if lots else 0.0)
    # the system's own allocation target
    tA = tb = tt = None
    labels: List[str] = []
    lam = 0.0
    try:
        tgt = allocation.active_target(con, market)
    except Exception:
        tgt = None
    if tgt and float(st["lambda_target"]) > 0:
        cls = np.array([_class_of(info[i]) for i in names])
        A, b0, t = [], [], []
        for c in allocation.CLASSES:
            if c == "cash":
                A.append((cls == "cash").astype(float) - 1.0)
                b0.append(1.0)
            else:
                A.append((cls == c).astype(float))
                b0.append(0.0)
            t.append(float(tgt["classes"].get(c, 0.0)) / 100.0)
            labels.append(f"class {c}")
        for s, pct in sorted(tgt["sectors"].items()):
            m = sectors.get(s, np.zeros(n))
            A.append(m)
            b0.append(0.0)
            t.append(float(pct) / 100.0)
            labels.append(f"sector {s}")
        tA, tb, tt, lam = np.array(A), np.array(b0), np.array(t), float(st["lambda_target"])
        meta["target_id"] = tgt["target_id"]
    else:
        meta["notes"].append("no active allocation target: no pull toward one")
    p = O.Problem(names=names, w0=w0, mu=mu, cov=cov, ub=ub, buy_cost=buy_c, sell_cost=sell_c, risk_aversion=float(st["risk_aversion"]),
                  turnover_penalty=float(st["turnover_penalty"]), groups=groups, target_A=tA, target_b=tb, target_t=tt, target_labels=labels,
                  target_band=float(st["band_pct"]) / 100.0, target_lambda=lam, frozen=frozen, no_buy=no_buy, no_sell=no_sell, budget=1.0)
    meta.update(info=info, total=total, shrinkage=round(float(shrink), 4), risk_source=src, lots=lots_by, n_returns=int(rets.shape[0]), n_with_history=int(rets.shape[1]),
                n_with_forecast=len(fi), breaker=br, cash_now=1.0 - float(w0.sum()))
    return p, meta


# --- the result -------------------------------------------------------------------------------------------------------------------
def _fy_gains(con, day: date) -> Dict[str, float]:
    try:
        from pflab.paper import book
        return book.year_gains(con, book._fy(day))
    except Exception:
        return {}


def trades_of(con, p: O.Problem, meta: dict, w: np.ndarray, day: date) -> List[dict]:
    from pflab.paper import book
    total = meta["total"]
    yg = _fy_gains(con, day)
    out = []
    for k, i in enumerate(p.names):
        d = float(w[k] - p.w0[k])
        if abs(d) < MIN_TRADE:
            continue
        inf = meta["info"][i]
        px = float(inf["price"])
        rupees = abs(d) * total
        side = "buy" if d > 0 else "sell"
        qty = math.floor(rupees / px) if side == "buy" else min(math.floor(rupees / px), (inf["value"] / px))
        if qty <= 0:
            continue
        c = costs.trade_cost(meta["lots"].get(i, []), px, float(qty), side, day, inf["asset_class"], None, yg)
        out.append({"symbol": inf["symbol"], "isin": i, "side": side, "qty": float(qty), "price": round(px, 2), "rupees": round(qty * px, 2),
                    "weight_before_pct": round(p.w0[k] * 100, 2), "weight_after_pct": round(float(w[k]) * 100, 2),
                    "est_charges": round(c["charges"], 2), "est_tax": round(c["tax"], 2)})
    out.sort(key=lambda t: (t["side"] != "sell", -t["rupees"]))
    return out


def rule_buys(p: O.Problem, buy_idx: List[int]) -> Dict[int, float]:
    """What the CURRENT rules would buy for the same buy list: the book's cash split equally over the names, each cut to the rail room (the way `paper/manager.decide` cuts
    an amount). Fractions of the book."""
    cash = max(0.0, p.budget - float(p.w0.sum()))
    room = O.fix_bounds(p)
    out = {}
    if not buy_idx:
        return out
    share = cash / len(buy_idx)
    for k in buy_idx:
        out[k] = float(min(share, room[k]))
    return out


def advise(con, now: datetime, root=None, closes: Optional[Dict[str, pd.Series]] = None, decisions: Optional[List[dict]] = None, log: bool = False, market: str = "IN") -> dict:
    """The tool's answer (also used by the sizing hook). Never raises: a problem becomes {'ok': False, 'fallback': ...}."""
    st = settings()
    base = {"market": market, "tool": "construct", "estimates": "charges and tax are ESTIMATES (Zerodha rates, FIFO lots, cess and surcharge not added)",
            "fallback": "the current sizing rules decide", "settings": {k: st[k] for k in ("risk_aversion", "equity_premium", "horizon", "window", "lambda_target", "turnover_penalty")}}
    try:
        from pflab import construct as C
        v = C.verdict(con)
        base["adopted"] = bool(C.adopted(con))
        base["status"] = ("ADOPTED: it sizes the paper team's decisions" if base["adopted"] else
                          "NOT ADOPTED: advice only; the current sizing rules decide" + ("" if v else " (the registered comparison has not been run)"))
        base["comparison"] = {k: v.get(k) for k in ("verdict", "reason", "run_at")} if v else None
        p, meta = build(con, now, root, closes, decisions, market)
        if p is None:
            return {**base, "ok": False, "note": meta.get("note", "nothing to size"), "target_weights": []}
        res = O.solve(p)
        day = now.date()
        if not res["ok"]:
            return {**base, "ok": False, "note": "the optimiser could not give a valid answer: " + res["message"], "target_weights": []}
        w = res["weights"]
        trades = trades_of(con, p, meta, w, day)
        buys = [k for k in range(len(p.names)) if w[k] - p.w0[k] >= MIN_TRADE]
        rb = rule_buys(p, buys)
        gap = [{"symbol": meta["info"][p.names[k]]["symbol"], "construct_pct": round(float(w[k] - p.w0[k]) * 100, 2), "current_rule_pct": round(rb.get(k, 0.0) * 100, 2),
                "difference_pct": round((float(w[k] - p.w0[k]) - rb.get(k, 0.0)) * 100, 2)} for k in buys]
        tw = [{"symbol": meta["info"][i]["symbol"], "isin": i, "current_pct": round(p.w0[k] * 100, 2), "target_pct": round(float(w[k]) * 100, 2),
               "change_pct": round(float(w[k] - p.w0[k]) * 100, 2), "expected_excess_pct": round(float(p.mu[k]) * 100, 2),
               "expected_source": meta["expected_return_source"].get(meta["info"][i]["symbol"])}
              for k, i in enumerate(p.names) if w[k] > 1e-4 or p.w0[k] > 1e-4]
        tw.sort(key=lambda r: -r["target_pct"])
        fee = sum(t["est_charges"] for t in trades)
        tax = sum(t["est_tax"] for t in trades)
        out = {**base, "ok": True, "as_of": meta["as_of"], "book_value": round(meta["total"], 2), "converged": res["converged"], "n_candidates": len(p.names),
               "target_weights": tw[:25], "cash_target_pct": round((1.0 - float(w.sum())) * 100, 2), "cash_now_pct": round(meta["cash_now"] * 100, 2), "trades": trades[:20],
               "est_charges_total": round(fee, 2), "est_tax_total": round(tax, 2), "binding": res["binding"][:12], "gap_to_current_rules": gap[:12],
               "utility_gain_vs_doing_nothing": round(float(res["utility"] - res["utility_now"]), 6), "parts": {k: round(v, 6) for k, v in res["parts"].items()},
               "inputs": {"shrinkage": meta["shrinkage"], "returns_days": meta["n_returns"], "names_with_history": meta["n_with_history"], "names_with_forecast": meta["n_with_forecast"],
                          "no_forecast_rule": "a name without a forecast has zero expected excess and a shrunk volatility estimate",
                          "forecast_horizon_sessions": st["horizon"], "target_id": meta.get("target_id")},
               "notes": meta["notes"], "how": "weights are fractions of the book; the manager's rails, cash and fill rules still apply to anything executed"}
        if decisions is not None:
            out["sizes"] = _sizes_from(p, meta, w, decisions)
        if log:
            _log(con, now, "sizes" if decisions is not None else "advice", out)
        return out
    except Exception as e:
        return {**base, "ok": False, "error": f"{type(e).__name__}: {str(e)[:160]}"}


def _sizes_from(p: O.Problem, meta: dict, w: np.ndarray, decisions: List[dict]) -> Dict[str, dict]:
    sizes = {}
    ix = {i: k for k, i in enumerate(p.names)}
    for d in decisions:
        i, a = d.get("isin"), str(d.get("action", "")).upper()
        if i not in ix:
            continue
        k = ix[i]
        delta = float(w[k] - p.w0[k])
        key = str(d.get("decision_id") or d.get("id") or i)
        if a in ("BUY", "ADD"):
            sizes[key] = {"amount_rupees": round(max(0.0, delta) * meta["total"], 2)}
        elif a == "REDUCE" and p.w0[k] > 0:
            sizes[key] = {"fraction": round(float(np.clip(-delta / p.w0[k], 0.0, 1.0)), 4)}
    return sizes


def _log(con, now: datetime, kind: str, out: dict) -> None:
    try:
        from pflab.pm.store import next_id
        slim = {k: out[k] for k in ("as_of", "target_weights", "cash_target_pct", "trades", "binding", "gap_to_current_rules", "est_charges_total", "est_tax_total") if k in out}
        con.execute("INSERT INTO construct_runs_s85 VALUES (?,?,?,?,?,?,?,?,?)",
                    [next_id(con, "construct_runs_s85", "run_id"), out.get("market", "IN"), kind, now.date(), now, bool(out.get("ok")), bool(out.get("adopted")),
                     json.dumps({"n": out.get("n_candidates"), "status": out.get("status")}), json.dumps(slim, default=str)[:60000]])
    except Exception:
        pass


# --- the manager's two hooks ------------------------------------------------------------------------------------------------------
def construct_sizes(con, now: datetime, decisions: List[dict], root=None, closes=None) -> dict:
    """Sizes for the paper team's decisions ({'decision_id' or 'id', 'action', 'isin'} dicts): {key: {'amount_rupees'} or {'fraction'}}. Empty (the current rules size) unless
    `construct.adopted(con)`; also empty when the optimiser fails."""
    from pflab import construct as C
    if not C.adopted(con):
        return {}
    r = advise(con, now, root, closes, decisions, log=True)
    return r.get("sizes", {}) if r.get("ok") else {}


def size_buy(con, now: datetime, case_id: int, isin: str, action: str, root=None, closes=None) -> Optional[dict]:
    """The hook of `paper/manager.decide`: the size construct gives a BUY/ADD of `isin` in the mission `case_id`, given the mission's other proposed decisions, or None (the
    current rule sizes) when construct is not adopted, the optimiser fails, or it asks for nothing."""
    from pflab import construct as C
    if not C.adopted(con):
        return None
    dec = [{"id": did, "action": a, "isin": i} for did, a, i in con.execute(
        "SELECT decision_id, action, isin FROM paper_decisions WHERE case_id=? AND status='proposed' AND isin IS NOT NULL", [case_id]).fetchall()]
    dec = [d for d in dec if d["isin"] != isin] + [{"id": "new", "action": action, "isin": isin}]
    s = construct_sizes(con, now, dec, root, closes)
    return s.get("new")


def dossier_text(con, now: datetime) -> str:
    """One paragraph for the paper team's dossier: the advice of today (computed once a day and kept), labelled by its status. '' when off."""
    if not settings()["on"]:
        return ""
    try:
        r = con.execute("SELECT result_json FROM construct_runs_s85 WHERE kind='advice' AND as_of=? AND ok ORDER BY run_id DESC LIMIT 1", [now.date()]).fetchone()
        if r:
            out = json.loads(r[0])
            status = "NOT ADOPTED"
        else:
            out = advise(con, now, log=True)
            if not out.get("ok"):
                return ""
            status = "ADOPTED" if out.get("adopted") else "NOT ADOPTED"
        moves = [f"{t['side'].upper()} {t['symbol']} about Rs {t['rupees']:,.0f}" for t in out.get("trades", [])[:6]]
        return (f"CONSTRUCT ({status}: advice from the risk model, the ensemble forecast, the rails, charges and tax; sizing is by the current rules unless adopted; call `construct` for the numbers): "
                + ("; ".join(moves) if moves else "no trade beats doing nothing after costs and tax") + f". Binding: {', '.join(out.get('binding', [])[:4]) or 'none'}.")
    except Exception:
        return ""
