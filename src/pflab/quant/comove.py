"""How stocks and sectors move together (S64 Phase 2d). Layer: tool (code only); the `comovement` brain tool, the stock
page's "moves with" block and the weekly `comove` job read its table.

For every pair in the universe:
    correlation   monthly total returns over the last 5 years
    Engle-Granger statsmodels `coint` on 3 years of daily log prices (total-return indexes); p value
    stability     the share of rolling 12-month windows (a monthly step over the last 3 years) with EG p < 0.05; computed
                  for pairs with EG p < 0.10 only (the rest cannot be stable) so the weekly run stays minutes
    half-life     of the spread ln a - beta ln b over the 3 years (process.ou_half_life), in sessions
Sector groups of 6 names or fewer (his names in one industry): Johansen trace test (statsmodels `coint_johansen`).
Multiple testing: Benjamini-Hochberg at 10% within each run over the EG p values; each run reports "n pairs tested, k
significant, about m expected by chance" (m = 5% of n at p < 0.05 alone).

Universe: his holdings and his stock list, each with its same-industry Nifty 500 peers at the as-of date (point in
time); the 23 sector TRI indexes against each other. (Phase 6 adds the US sector ETFs.)
A DESCRIPTION: relations break (S39: 9% stayed cointegrated), so pairs trading stays excluded: it needs shorting, and
the system never trades. Output: data/derived/comove.parquet.
"""
from __future__ import annotations

import glob
import itertools
import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from pflab.data import data_dir
from pflab.quant import process

EG_SESSIONS, CORR_MONTHS, STABLE_WINDOW, STABLE_STEPS = 750, 60, 252, 36
P_PAIR, P_SCREEN, BH_Q = 0.05, 0.10, 0.10
MAX_JOHANSEN = 6
LABEL = "description: relations break (S39: 9% stayed cointegrated)"
OUT_NAME = "comove.parquet"

COLUMNS = ["asof", "group", "kind", "a", "b", "a_sym", "b_sym", "industry", "corr_5y", "months", "eg_p", "eg_q", "significant",
           "stability", "windows", "half_life", "beta", "johansen_rank", "n_sessions"]


# Sector map industries (taxonomy C, the current one) that have a sector TRI index of their own.
SECTOR_INDEX = {"Automobile and Auto Components": "SECTOR_AUTO_TRI", "Chemicals": "SECTOR_CHEMICALS_TRI",
                "Consumer Durables": "SECTOR_CONSUMER_DURABLES_TRI", "Fast Moving Consumer Goods": "SECTOR_FMCG_TRI",
                "Financial Services": "SECTOR_FIN_SERVICES_TRI", "Healthcare": "SECTOR_HEALTHCARE_TRI",
                "Information Technology": "SECTOR_IT_TRI", "Media Entertainment & Publication": "SECTOR_MEDIA_TRI",
                "Metals & Mining": "SECTOR_METAL_TRI", "Oil Gas & Consumable Fuels": "SECTOR_OIL_GAS_TRI",
                "Realty": "SECTOR_REALTY_TRI", "Services": "SECTOR_SERVICES_TRI"}


def sector_index_for(root: Path, isin: str, asof: date) -> tuple:
    """(industry, sector index key or None) of a stock as of `asof` (the latest sector-map capture on or before it)."""
    from pflab.data import sector_map
    t = sector_map.sector_at(sector_map.load(root), [isin], asof, allow_later=False)
    ind = t["industry"].iloc[0] if len(t) else None
    return ind, SECTOR_INDEX.get(ind)


def out_path(root: Optional[Path] = None) -> Path:
    return (root or data_dir()) / "derived" / OUT_NAME


def eg_test(la: pd.Series, lb: pd.Series) -> dict:
    """Engle-Granger on two log-price series (common sessions): p, hedge ratio, half-life of the spread, n."""
    from statsmodels.tsa.stattools import coint
    j = pd.concat([la.rename("a"), lb.rename("b")], axis=1, join="inner").dropna()
    n = len(j)
    if n < 250 or float(j["a"].std()) == 0.0 or float(j["b"].std()) == 0.0:
        return {"p": None, "beta": None, "half_life": None, "n": n}
    p = float(coint(j["a"].to_numpy(), j["b"].to_numpy(), trend="c", autolag="aic")[1])
    sp, beta = process.spread(np.exp(j["a"]), np.exp(j["b"]))
    return {"p": p, "beta": beta, "half_life": process.ou_half_life(sp), "n": n}


def stability(la: pd.Series, lb: pd.Series, window: int = STABLE_WINDOW, steps: int = STABLE_STEPS) -> dict:
    """Share of rolling windows (window sessions, one month apart, `steps` of them ending at the latest session) with
    EG p < 0.05."""
    from statsmodels.tsa.stattools import coint
    j = pd.concat([la.rename("a"), lb.rename("b")], axis=1, join="inner").dropna()
    hit = tot = 0
    for k in range(steps):
        end = len(j) - 21 * k
        if end - window < 0:
            break
        w = j.iloc[end - window:end]
        if float(w["a"].std()) == 0.0 or float(w["b"].std()) == 0.0:
            continue
        tot += 1
        hit += int(float(coint(w["a"].to_numpy(), w["b"].to_numpy(), trend="c", autolag="aic")[1]) < P_PAIR)
    return {"share": (hit / tot) if tot else None, "windows": tot}


def monthly_corr(ra: pd.Series, rb: pd.Series, months: int = CORR_MONTHS) -> tuple:
    j = pd.concat([ra.rename("a"), rb.rename("b")], axis=1, join="inner").dropna().iloc[-months:]
    if len(j) < 24 or j["a"].std() == 0 or j["b"].std() == 0:
        return None, len(j)
    return float(j["a"].corr(j["b"])), len(j)


def bh(p: pd.Series, q: float = BH_Q) -> pd.DataFrame:
    """Benjamini-Hochberg over a series of p values (NaN skipped): columns q (adjusted) and significant."""
    out = pd.DataFrame({"eg_q": np.nan, "significant": False}, index=p.index)
    ok = p.dropna()
    if len(ok):
        from statsmodels.stats.multitest import multipletests
        rej, qv, _, _ = multipletests(ok.to_numpy(float), alpha=q, method="fdr_bh")
        out.loc[ok.index, "eg_q"] = qv
        out.loc[ok.index, "significant"] = rej
    return out


def johansen(logs: pd.DataFrame) -> Optional[int]:
    """Cointegration rank by the trace test at 95% (statsmodels coint_johansen, constant, one lag difference)."""
    from statsmodels.tsa.vector_ar.vecm import coint_johansen
    x = logs.dropna()
    if len(x) < 250 or x.shape[1] < 2:
        return None
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")                       # statsmodels casts a zero imaginary part
        r = coint_johansen(x.to_numpy(), det_order=0, k_ar_diff=1)
    rank = 0
    for i in range(x.shape[1]):
        if r.lr1[i] > r.cvt[i, 1]:
            rank += 1
        else:
            break
    return rank


def summary(df: pd.DataFrame) -> dict:
    pairs = df[(df["kind"] == "pair") & df["eg_p"].notna()]
    n, k = len(pairs), int(pairs["significant"].sum())
    return {"pairs_tested": n, "significant": k, "expected_by_chance": round(P_PAIR * n, 1),
            "text": f"{n} pairs tested, {k} significant after Benjamini-Hochberg at {BH_Q:.0%}, about {P_PAIR * n:.0f} would "
                    f"pass p < {P_PAIR} by chance alone", "label": LABEL}


# --- the universe and the run --------------------------------------------------------------------------------------------------

def focus(con, root: Path, asof: date) -> Dict[str, str]:
    """isin -> symbol: his direct holdings and his stock list."""
    from pflab.plan import guards as gd
    from pflab.pm import today
    out = {s["isin"]: s["symbol"] for s in gd.stock_list() if s.get("isin")}
    try:
        pos = today.build(con, asof)["positions"]
        eq = {i for (i,) in con.execute("SELECT isin FROM instruments WHERE asset_class = 'equity'").fetchall()}
        for r in pos[pos["value"].notna() & (pos["qty"] > 0) & pos["isin"].isin(eq)].itertuples():
            out.setdefault(r.isin, str(r.symbol))
    except Exception:
        pass
    return out


def peers(root: Path, isins: List[str], asof: date) -> Dict[str, List[str]]:
    """For each isin, same-industry Nifty 500 members at asof (point in time), the isin itself left out."""
    from pflab.data import index_membership as im, sector_map
    mem = im.members_at(pd.read_parquet(root / "index_membership" / "NIFTY500.parquet").assign(
        from_date=lambda d: pd.to_datetime(d["from_date"]).dt.date,
        to_date=lambda d: pd.to_datetime(d["to_date"]).dt.date), "NIFTY500", asof)
    table = sector_map.load(root)
    lab = sector_map.sector_at(table, sorted(mem | set(isins)), asof, allow_later=False).set_index("isin")["industry"]
    out = {}
    for i in isins:
        ind = lab.get(i)
        out[i] = sorted(x for x in mem if x != i and ind is not None and lab.get(x) == ind) if ind else []
    return out


def _symbols(root: Path, isins: List[str]) -> Dict[str, str]:
    """isin -> its latest symbol in the price panel (peers are not in the instrument master)."""
    from pflab import _duck
    if not isins:
        return {}
    q = (f"select isin, arg_max(symbol, date) s from '{root}/panel/prices.parquet' "
         f"where isin in ({','.join(repr(i) for i in isins)}) group by isin")
    return dict(_duck.sql(q).fetchall())


def _levels(root: Path, isins: List[str], asof: date) -> pd.DataFrame:
    from pflab.learner import templates as tp
    start = str(pd.Timestamp(asof) - pd.Timedelta(days=int(365.25 * 6)))[:10]
    w = tp.wide_panel(root, isins, start, str(asof))
    return w["tr"].ffill(limit=5)


def _sector_levels(root: Path, asof: date) -> Dict[str, pd.Series]:
    from pflab.data import indices
    out = {}
    for f in sorted(glob.glob(str(root / "indices" / "SECTOR_*_TRI.parquet"))):
        key = Path(f).stem
        s = indices.load(key, root)
        s = s.assign(date=pd.to_datetime(s["date"])).set_index("date")["close"].sort_index()
        out[key] = s[s.index <= pd.Timestamp(asof)]
    return out


def _row(asof, group, kind, a, b, a_sym, b_sym, industry, la, lb, ra, rb) -> dict:
    ls = la.iloc[-EG_SESSIONS:], lb.iloc[-EG_SESSIONS:]
    eg = eg_test(*ls)
    c, months = monthly_corr(ra, rb)
    return {"asof": str(asof), "group": group, "kind": kind, "a": a, "b": b, "a_sym": a_sym, "b_sym": b_sym,
            "industry": industry, "corr_5y": c, "months": months, "eg_p": eg["p"], "beta": eg["beta"],
            "half_life": eg["half_life"], "n_sessions": eg["n"], "_la": la, "_lb": lb}


def run(con, root: Optional[Path] = None, asof: Optional[date] = None, write: bool = True, only: Optional[Dict[str, str]] = None) -> dict:
    """The weekly run: returns {"table": DataFrame, "summary": dict}. `only` (isin -> symbol) replaces the focus names."""
    from pflab.data import sector_map
    root = root or data_dir()
    asof = asof or date.today()
    foc = only if only is not None else focus(con, root, asof)
    pe = peers(root, sorted(foc), asof) if foc else {}
    names = sorted(set(foc) | {p for v in pe.values() for p in v})
    lv = _levels(root, names, asof) if names else pd.DataFrame()
    lv = lv.loc[:, lv.notna().sum() >= EG_SESSIONS] if len(lv) else lv
    logs = np.log(lv.where(lv > 0)) if len(lv) else lv
    mret = {c: process_monthly(lv[c]) for c in lv.columns}
    ind = {}
    if len(lv):
        t = sector_map.sector_at(sector_map.load(root), list(lv.columns), asof, allow_later=False).set_index("isin")["industry"]
        ind = t.to_dict()
    sym = {**_symbols(root, names), **foc}
    rows, seen = [], set()
    for f in sorted(foc):
        if f not in logs.columns:
            continue
        for p in pe.get(f, []):
            key = tuple(sorted((f, p)))
            if p not in logs.columns or key in seen:
                continue
            seen.add(key)
            a, b = key
            rows.append(_row(asof, "stock", "pair", a, b, sym.get(a, a), sym.get(b, b), ind.get(f), logs[a].dropna(),
                             logs[b].dropna(), mret[a], mret[b]))
    sec = _sector_levels(root, asof)
    slog = {k: np.log(v[v > 0]) for k, v in sec.items() if len(v) >= EG_SESSIONS}
    smon = {k: process_monthly(v) for k, v in sec.items() if k in slog}
    for a, b in itertools.combinations(sorted(slog), 2):
        rows.append(_row(asof, "sector", "pair", a, b, a, b, None, slog[a], slog[b], smon[a], smon[b]))
    df = pd.DataFrame(rows)
    if df.empty:
        return {"table": pd.DataFrame(columns=COLUMNS), "summary": summary(pd.DataFrame(columns=COLUMNS))}
    for grp in ("stock", "sector"):                          # BH within each group of the run
        m = df["group"] == grp
        r = bh(df.loc[m, "eg_p"])
        df.loc[m, "eg_q"], df.loc[m, "significant"] = r["eg_q"], r["significant"]
    stab, wins = [], []
    for r in df.itertuples():
        if r.eg_p is not None and r.eg_p == r.eg_p and r.eg_p < P_SCREEN:
            s = stability(df.at[r.Index, "_la"], df.at[r.Index, "_lb"])
            stab.append(s["share"]), wins.append(s["windows"])
        else:
            stab.append(None), wins.append(None)
    df["stability"], df["windows"] = stab, wins
    df["johansen_rank"] = None
    byind: Dict[str, List[str]] = {}
    for i in sorted(foc):
        if i in logs.columns and ind.get(i):
            byind.setdefault(ind[i], []).append(i)
    jrows = []
    for name, members in byind.items():
        if 2 <= len(members) <= MAX_JOHANSEN:
            jrows.append({"asof": str(asof), "group": "stock", "kind": "johansen", "a": ",".join(members),
                          "b": "", "a_sym": ",".join(sym.get(m, m) for m in members), "b_sym": "", "industry": name,
                          "johansen_rank": johansen(logs[members]), "n_sessions": int(logs[members].dropna().shape[0])})
    out = pd.concat([df.drop(columns=["_la", "_lb"]), pd.DataFrame(jrows)], ignore_index=True)
    for c in COLUMNS:
        if c not in out.columns:
            out[c] = None
    out = out[COLUMNS]
    out["johansen_rank"] = pd.to_numeric(out["johansen_rank"], errors="coerce")
    out["significant"] = out["significant"].fillna(False).astype(bool)
    if write:
        p = out_path(root)
        p.parent.mkdir(parents=True, exist_ok=True)
        out.to_parquet(p, index=False)
    s = summary(out)
    s["johansen_groups"] = int((out["kind"] == "johansen").sum())
    return {"table": out, "summary": s}


def process_monthly(level: pd.Series) -> pd.Series:
    from pflab.risk import capm
    return capm.monthly_returns(level)


# --- reading it back ----------------------------------------------------------------------------------------------------------

def load(root: Optional[Path] = None) -> pd.DataFrame:
    p = out_path(root)
    return pd.read_parquet(p) if p.exists() else pd.DataFrame(columns=COLUMNS)


def moves_with(symbol: str, root: Optional[Path] = None, top: int = 8) -> dict:
    """The peers a stock moves with, from the last weekly run: correlation, EG p (BH-adjusted q), stability, half-life."""
    df = load(root)
    if df.empty:
        return {"symbol": symbol, "peers": [], "note": "the weekly comove run has not produced a table yet",
                "source": "quant/comove.py", "label": LABEL}
    s = symbol.upper()
    m = df[(df["kind"] == "pair") & ((df["a_sym"].str.upper() == s) | (df["b_sym"].str.upper() == s))].copy()
    m["peer"] = np.where(m["a_sym"].str.upper() == s, m["b_sym"], m["a_sym"])
    m = m.reindex(m["corr_5y"].abs().sort_values(ascending=False, na_position="last").index).head(top)
    peers_ = [{"peer": r.peer, "corr_5y": None if pd.isna(r.corr_5y) else round(float(r.corr_5y), 2),
               "eg_p": None if pd.isna(r.eg_p) else round(float(r.eg_p), 3),
               "cointegrated_after_bh": bool(r.significant),
               "stable_share": None if pd.isna(r.stability) else round(float(r.stability), 2),
               "half_life_sessions": None if pd.isna(r.half_life) else round(float(r.half_life)), "months": int(r.months or 0)}
              for r in m.itertuples()]
    return {"symbol": symbol, "asof": str(df["asof"].iloc[0]), "peers": peers_, "run": summary(df),
            "source": "quant/comove.py (weekly): monthly correlation 5y; Engle-Granger on 3y of daily log prices",
            "label": LABEL}


def job(ctx) -> dict:
    """The weekly tick job (Saturday): rebuilds the table for his holdings and list."""
    from pflab.hq import desk
    rt = desk.from_ctx(ctx)
    p = out_path(rt.data_root)
    if p.exists() and (datetime.now().timestamp() - p.stat().st_mtime) < 6 * 86400:
        return {"skipped": True, "why": "the table is under 6 days old"}
    res = run(rt.cursor(), rt.data_root, rt.clock().date())
    return {"summary": res["summary"]["text"], "rows": int(len(res["table"]))}
