"""Theme exposure of a book (S79b item 15b, tool `theme_exposure`).

Each holding (and each stock of the universe) is mapped to the sentiment themes three ways, none of them a model's opinion:
  * a SECTOR PRIOR: the point-in-time sector-map label contains one of the theme's `industries` keywords (word prefix, case-insensitive) as of the date;
  * the REVENUE MIX, where data exists: `derived/revenue_mix_s79b.parquet` (isin, theme, share, as_of). None exists on this PC today; the result says so;
  * MEASURED BETAS to the theme's price proxies: the stock's daily return regressed on the proxy's daily return over the trailing `beta_window` sessions ending on the
    date (rows dated <= the date only). A proxy that settles after the Indian close (a US close, Brent futures: `lag = 1` in the config) is paired with the stock's
    NEXT Indian session, so the proxy move was known before the stock traded. The beta is "percent move of the stock per 1% move of the proxy" (for the US 10-year
    yield: per 1% move of the yield level). The theme's PRIMARY proxy (the first listed, fixed in the config) decides `carries`.
A holding CARRIES a theme when its sector prior hits or the primary-proxy beta has |t| >= t_carry. Its contribution to the book is weight x beta (beta of a carrier
by sector prior with an insignificant beta counts as 0: the prior says the theme is relevant, the data has not shown how much).
The book's exposure to a theme = sum of contributions = "percent move of the whole book for a 1% move of the primary proxy", plus the weight that carries it.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab import _duck
from pflab import sentiment as S
from pflab.sentiment import themes as T

REVENUE_FILE = "revenue_mix_s79b.parquet"


# --- the book -------------------------------------------------------------------------------------------------------------------------

def book_weights(con, day: date, which: str = "auto") -> dict:
    """{"source": paper|main|none, "rows": [{isin, symbol, weight, value}], "total"}: the paper book via `paper.book.holdings`, else the main book; neither is tolerated."""
    if which in ("auto", "paper"):
        try:
            from pflab.paper import book as pb
            h = pb.holdings(con, day)
            rows = [{"isin": r["isin"], "symbol": r["symbol"], "weight": float(r["weight"] or 0.0), "value": float(r["value"] or 0.0)} for r in h["rows"] if (r["value"] or 0) > 0]
            if rows:
                return {"source": "paper", "rows": rows, "total": float(h["value"])}
        except Exception:
            pass
    if which in ("auto", "main"):
        try:
            from pflab.risk import themes as rt
            ex = rt.portfolio_exposures(con, day)
            st = ex["stock"]
            names = dict(con.execute("SELECT isin, symbol FROM instruments").fetchall())
            rows = [{"isin": r.isin, "symbol": names.get(r.isin, r.isin), "weight": float(r.weight), "value": float(r.value)} for r in st.itertuples() if r.value > 0]
            if rows:
                return {"source": "main", "rows": rows, "total": float(ex.get("total") or 0.0)}
        except Exception:
            pass
    return {"source": "none", "rows": [], "total": 0.0}


def universe_isins(root, day: date) -> List[str]:
    try:
        from pflab.learner import templates as tp
        m = tp.members(Path(root))
        ts = pd.Timestamp(day)
        return sorted(set(m[(m["from_date"] <= ts) & (m["to_date"] > ts)]["isin"]))
    except Exception:
        return []


# --- returns and betas ----------------------------------------------------------------------------------------------------------------

def stock_returns(root, isins: List[str], day: date, sessions: int = 420) -> pd.DataFrame:
    """Daily simple returns (sessions x isin) of the adjusted close up to `day` (nothing dated after it is read)."""
    if not isins:
        return pd.DataFrame()
    start = day - timedelta(days=int(sessions * 1.6))
    lst = ",".join(repr(i) for i in isins)
    px = _duck.sql(f"select date, isin, adj_close from '{Path(root).as_posix()}/panel/prices.parquet' where isin in ({lst}) "
                   f"and date between DATE '{start}' and DATE '{day}' and adj_close > 0").df()
    if px.empty:
        return pd.DataFrame()
    px["date"] = pd.to_datetime(px["date"])
    px = px.sort_values(["isin", "date"]).drop_duplicates(["isin", "date"])
    w = px.pivot(index="date", columns="isin", values="adj_close").sort_index()
    return w.pct_change(fill_method=None).iloc[1:]


def proxy_returns(level: pd.Series, target_index: pd.DatetimeIndex, lag: int) -> pd.Series:
    """The proxy's daily return paired with each date of `target_index`: lag 0 = the return of the proxy session on that same date; lag 1 = the return of the latest
    proxy session strictly BEFORE that date (so it was known before the stock traded). Dates with no proxy print within 6 days are NaN."""
    r = level.astype(float).pct_change(fill_method=None).dropna()
    left = pd.DataFrame({"d": pd.DatetimeIndex(target_index).astype("datetime64[ns]")}).sort_values("d")
    right = pd.DataFrame({"pd": pd.DatetimeIndex(r.index).astype("datetime64[ns]"), "r": r.to_numpy(float)}).sort_values("pd")
    m = pd.merge_asof(left, right, left_on="d", right_on="pd", allow_exact_matches=(int(lag) == 0))
    ok = (m["d"] - m["pd"]) <= pd.Timedelta(days=6)
    return pd.Series(np.where(ok, m["r"], np.nan), index=pd.DatetimeIndex(m["d"])).reindex(pd.DatetimeIndex(target_index))


def betas(R: pd.DataFrame, x: pd.Series, window: int, min_n: int) -> pd.DataFrame:
    """OLS beta, t-statistic, r and n of each column of R on `x` over the last `window` rows (index-aligned), vectorised. Columns: beta, t, r, n."""
    R = R.iloc[-window:]
    x = x.reindex(R.index)
    Y = R.to_numpy(float)
    X = x.to_numpy(float)
    m = np.isfinite(Y) & np.isfinite(X)[:, None]
    n = m.sum(axis=0).astype(float)
    Xm = np.where(m, X[:, None], 0.0)
    Ym = np.where(m, Y, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        nx = np.where(n > 0, n, np.nan)
        mx, my = Xm.sum(0) / nx, Ym.sum(0) / nx
        dx, dy = np.where(m, X[:, None] - mx, 0.0), np.where(m, Y - my, 0.0)
        sxx, syy, sxy = (dx * dx).sum(0), (dy * dy).sum(0), (dx * dy).sum(0)
        beta = sxy / np.where(sxx > 0, sxx, np.nan)
        r = sxy / np.sqrt(np.where(sxx * syy > 0, sxx * syy, np.nan))
        t = r * np.sqrt((n - 2) / np.maximum(1 - r ** 2, 1e-12))
    out = pd.DataFrame({"beta": beta, "t": t, "r": r, "n": n}, index=R.columns)
    out.loc[out["n"] < min_n, ["beta", "t", "r"]] = np.nan
    return out


def rolling_beta(y: pd.Series, x: pd.Series, window: int, min_periods: int) -> pd.Series:
    """Rolling beta of y on x ending on each date (rows <= the date only): cov / var over the trailing window."""
    both = pd.concat([y, x], axis=1, keys=["y", "x"]).dropna(how="any")
    cov = both["y"].rolling(window, min_periods=min_periods).cov(both["x"])
    var = both["x"].rolling(window, min_periods=min_periods).var()
    return (cov / var.where(var > 1e-18)).reindex(y.index)


# --- sector prior and revenue mix -----------------------------------------------------------------------------------------------------

def sector_labels(root, isins: List[str], day: date) -> Dict[str, Optional[str]]:
    try:
        from pflab.data import sector_map
        t = sector_map.sector_at(sector_map.load(Path(root)), isins, day, allow_later=False)
        return dict(zip(t["isin"], t["industry"]))
    except Exception:
        return {}


def sector_hit(label: Optional[str], theme: T.Theme) -> bool:
    if not label:
        return False
    lab = str(label).lower()
    return any(re.search(r"\b" + re.escape(k), lab) for k in theme.industries)


def revenue_mix(root, day: date) -> Optional[pd.DataFrame]:
    p = Path(root) / "derived" / REVENUE_FILE
    if not p.exists():
        return None
    try:
        df = pd.read_parquet(p)
        df = df[pd.to_datetime(df["as_of"]) <= pd.Timestamp(day)].sort_values("as_of").drop_duplicates(["isin", "theme"], keep="last")
        return df
    except Exception:
        return None


# --- the result -----------------------------------------------------------------------------------------------------------------------

def compute(con, root, day: date, market: str = "IN", which: str = "auto", themes: Optional[Dict[str, T.Theme]] = None, universe: bool = True,
            top: int = 5) -> dict:
    """The book's exposure per theme and which holdings carry it; the same map for the universe (Nifty 500 members) as counts and the strongest carriers."""
    st = S.settings()
    root = Path(root)
    themes = themes if themes is not None else T.load_themes(market)
    out: dict = {"market": market, "asof": str(day), "units": "beta = % move of the stock per 1% move of the primary proxy; book_beta = % move of the whole book per 1% move of it; "
                                                              "weights are shares of the whole book value", "themes": {}}
    if market != "IN":
        return out | {"note": f"no stock price panel for market {market} on this PC: theme exposure is built for the NSE book (IN)", "source": "none"}
    bk = book_weights(con, day, which)
    out["source"] = bk["source"]
    held = [r["isin"] for r in bk["rows"]]
    uni = universe_isins(root, day) if universe else []
    all_isins = sorted(set(held) | set(uni))
    if not all_isins:
        return out | {"note": "no book to read (no paper portfolio, no main book) and no universe list on this PC", "themes": {}}
    R = stock_returns(root, all_isins, day)
    if R.empty:
        return out | {"note": "no stock price panel on this PC (panel/prices.parquet)"}
    lab = sector_labels(root, all_isins, day)
    sym = {}
    for r in bk["rows"]:
        sym[r["isin"]] = r["symbol"]
    missing_syms = [i for i in all_isins if i not in sym]
    if missing_syms:
        try:
            s2 = _duck.sql(f"select isin, last(symbol order by date) as symbol from '{root.as_posix()}/panel/prices.parquet' where isin in ({','.join(repr(i) for i in missing_syms)}) "
                           f"and date <= DATE '{day}' group by isin").df()
            sym.update(dict(zip(s2["isin"], s2["symbol"])))
        except Exception:
            pass
    rev = revenue_mix(root, day)
    out["revenue_mix"] = (f"{len(rev)} rows from derived/{REVENUE_FILE}" if rev is not None and len(rev) else "no revenue-mix data on this PC: the sector prior and the measured betas are used")
    out["universe_size"] = len(uni)
    out["book_value_rupees"] = round(bk["total"]) if bk["total"] else None
    w = {r["isin"]: r["weight"] for r in bk["rows"]}
    missing_proxies = []
    for k, th in themes.items():
        entry: dict = {"label": th.label, "primary_proxy": th.primary, "proxies": {}}
        prim_b = None
        for pk in th.proxies:
            lv = T.load_proxy(root, pk)
            if lv is None:
                missing_proxies.append(pk)
                entry["proxies"][pk] = {"available": False}
                continue
            lv = lv[lv.index <= pd.Timestamp(day)]
            x = proxy_returns(lv, R.index, T.proxy_lag(pk))
            b = betas(R, x, int(st["beta_window"]), int(st["beta_min"]))
            entry["proxies"][pk] = {"available": True, "label": T.proxy_label(pk), "lag_sessions": T.proxy_lag(pk), "last_print": str(lv.index.max().date()) if len(lv) else None}
            if pk == th.primary:
                prim_b = b
        carriers, contrib_sum, w_carry, w_sector = [], 0.0, 0.0, 0.0
        for isin in held:
            hit = sector_hit(lab.get(isin), th)
            bb = prim_b.loc[isin] if prim_b is not None and isin in prim_b.index else None
            beta = float(bb["beta"]) if bb is not None and np.isfinite(bb["beta"]) else None
            tt = float(bb["t"]) if bb is not None and np.isfinite(bb["t"]) else None
            meas = beta is not None and tt is not None and abs(tt) >= float(st["t_carry"])
            carries = bool(hit or meas)
            if hit:
                w_sector += w[isin]
            if not carries:
                continue
            c = w[isin] * beta if meas else 0.0
            contrib_sum += c
            w_carry += w[isin]
            carriers.append({"symbol": sym.get(isin, isin), "isin": isin, "weight": round(w[isin], 5), "sector_prior": bool(hit), "beta": None if beta is None else round(beta, 3),
                             "t": None if tt is None else round(tt, 2), "n": int(bb["n"]) if bb is not None else 0, "contribution": round(c, 5), "sector": lab.get(isin)})
        carriers.sort(key=lambda r: -abs(r["contribution"]) if r["contribution"] else -r["weight"] * 1e-3)
        entry.update({"book_beta": round(contrib_sum, 5) if prim_b is not None else None, "weight_carrying": round(w_carry, 5), "weight_sector_prior": round(w_sector, 5),
                      "n_carriers": len(carriers), "holdings": carriers[:max(top, 10)]})
        if prim_b is None:
            entry["note"] = f"the primary proxy {th.primary!r} is not on this PC: only the sector prior is available for this theme"
        if universe and uni:
            n_sec = sum(1 for i in uni if sector_hit(lab.get(i), th))
            ub = prim_b.loc[[i for i in uni if prim_b is not None and i in prim_b.index]] if prim_b is not None else pd.DataFrame()
            sig = ub[ub["t"].abs() >= float(st["t_carry"])] if len(ub) else ub
            top_pos = sig.sort_values("beta", ascending=False).head(top) if len(sig) else sig
            top_neg = sig.sort_values("beta").head(top) if len(sig) else sig
            entry["universe"] = {"n": len(uni), "n_sector_prior": n_sec, "n_beta_carriers": int(len(sig)),
                                 "strongest_positive": [{"symbol": sym.get(i, i), "beta": round(float(r.beta), 2), "t": round(float(r.t), 1)} for i, r in top_pos.iterrows()],
                                 "strongest_negative": [{"symbol": sym.get(i, i), "beta": round(float(r.beta), 2), "t": round(float(r.t), 1)} for i, r in top_neg.iterrows()]}
        out["themes"][k] = entry
    out["missing_proxies"] = sorted(set(missing_proxies))
    out["window_sessions"] = int(st["beta_window"])
    return out


def persist(con, res: dict, day: date, scope: str = "book") -> int:
    """Keep the book's per-holding map in theme_exposure_s79 (replaces the day's rows)."""
    from datetime import datetime
    n = 0
    now = datetime.now()
    con.execute("DELETE FROM theme_exposure_s79 WHERE market=? AND day=? AND scope=?", [res.get("market", "IN"), day, scope])
    for k, e in (res.get("themes") or {}).items():
        for h in e.get("holdings", []):
            con.execute("INSERT INTO theme_exposure_s79 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        [res["market"], day, scope, k, h["isin"], h["symbol"], h["weight"], h["sector_prior"], h["beta"], h["t"], h["n"], True, h["contribution"], now])
            n += 1
    return n
