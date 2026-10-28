"""E5-A §6(f) feature store, family A5: valuation.

Columns (E5-A §14 2026-10-01, the investor: the 8-column set), nothing thresholded:

  ey_ttm       TTM EPS, restated to M's share basis, / M's close
  sy_ttm       TTM revenue / market cap at M
  dy_ttm       TTM dividend per share, restated to M's basis, / M's close;
               NaN at month-ends 2009-04-30 .. 2011-03-31 (the NSE feed hole)
               and through 2007-12-31 (the feed is thin before 2007)
  *_pct36      each yield's percentile within the name's own trailing 36
               month-ends (M included); NaN with fewer than 24 values
  rev_ttm_yoy  (TTM revenue - TTM revenue a year earlier) / |the earlier|
  np_ttm_yoy   the same for net profit

Sources: BSE quarterly results (`data/bse_results/`, standalone, BSE's
template, ₹ million; the S38 probe, retired in S63), the NSE dividend
feed (`data/dividends/`), BSE shareholding share counts (`bse_shareholding`,
dated as A2's quarters are), the truncated panel's close and split/bonus
factor (adj_close / close).

Dating (§14 2026-10-01, decided before any A5 data was collected): a
quarter's results are usable from the LATER of the statutory deadline
(quarter end + 45 days; + 60 for the March quarter) and the matched results
announcement (after 15:30: next day); unmatched, quarter end + 90 days. The
match is the first announcement from the day after the quarter end to 15
days after the next quarter end, in BSE's category Result / Financial
Results, or with a headline naming results and the quarter's month
(`docs/BUILT.md` §3; the probe's query).

Build readings (declared in the meta and §14): TTM = the latest quarter
usable at M and the three before it, each usable at M and each with the
field, else NaN (an older quarter is never substituted); the year-earlier
TTM likewise from the four quarters before those. EPS and dividends are
restated by k(then) / k(M), k = adj_close / close, which moves only with the
splits and bonuses between the two dates. Market cap = the latest usable
shareholding quarter's shares outstanding x k(M) / k(then) (a count moves
opposite to a per-share figure), x M's close. (the A5 probe, retired in S63
restated shares the other way; its coverage is unaffected.) A name in U(M) with no dividend in the window has yield 0.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

from pflab.data import positioning as pos
from pflab._store_consts import CLOSE_IST, STORE_COLUMNS, TZ

COLUMNS = ["ey_ttm", "sy_ttm", "dy_ttm", "ey_pct36", "sy_pct36", "dy_pct36",
           "rev_ttm_yoy", "np_ttm_yoy"]
YIELDS = ("ey_ttm", "sy_ttm", "dy_ttm")
DEADLINE_DAYS, DEADLINE_DAYS_MARCH, UNMATCHED_DAYS = 45, 60, 90
HIST, HIST_MIN = 36, 24
DY_NAN = ((date(1900, 1, 1), date(2007, 12, 31)),      # feed thin before 2007 (§14, session 12)
          (date(2009, 4, 30), date(2011, 3, 31)))     # the 2009-10 hole (§14 2026-10-01)
MONTHS = ("january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december")
# the probe's field rules (FIELDS / pick), verbatim
FIELDS = {"revenue": ("net sales/revenue from operations", "net sales / income from operations",
                      "revenue from operations", "net sales", "income from operations",
                      "interest earned"),
          "net_profit": ("net profit",),
          "eps": ("basic eps", "basic for", "basic", "eps")}


def quarter_end(qtr: float) -> date:
    """BSE's quarter id -> quarter end (Jun-2000 = 26)."""
    k = int(round(qtr)) - 26
    y, m = 2000 + (6 + 3 * k - 1) // 12, (6 + 3 * k - 1) % 12 + 1
    return (pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)).date()


def _num(v) -> Optional[float]:
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def pick(descs: Sequence[str], values: Sequence, keys) -> Optional[float]:
    for k in keys:
        for d, v in zip(descs, values):
            if (d or "").strip().lower().startswith(k):
                x = _num(v)
                if x is not None:
                    return x
    return None


def results_quarters(raw: pd.DataFrame) -> pd.DataFrame:
    """Raw line items (scrip_code, qtr, fld_desc, Value) -> one row per
    (scrip_code, quarter_end) with revenue, net_profit, eps. A quarter whose
    fetch failed (`__ERROR__`) or that has three lines or fewer is dropped."""
    rows = []
    for (sc, q), g in raw.groupby(["scrip_code", "qtr"], sort=True):
        d, v = g["fld_desc"].astype(str).tolist(), g["Value"].tolist()
        if "__ERROR__" in d or len(d) <= 3:
            continue
        rows.append({"scrip_code": str(sc), "quarter_end": quarter_end(float(q)),
                     **{f: pick(d, v, keys) for f, keys in FIELDS.items()}})
    return pd.DataFrame(rows, columns=["scrip_code", "quarter_end", *FIELDS])


def announcement_window(q_end: date) -> tuple:
    nxt = (pd.Timestamp(q_end) + pd.offsets.QuarterEnd(1)).date()
    return q_end + timedelta(days=1), nxt + timedelta(days=15)


def matched_announcements(ann: pd.DataFrame, rq: pd.DataFrame) -> pd.DataFrame:
    """(scrip_code, quarter_end) -> the first matching results announcement.
    `ann`: scrip_code, t, category, subcategory, headline."""
    a = ann.assign(scrip_code=ann["scrip_code"].astype(str).str.strip(),
                   t=pd.to_datetime(ann["t"]))
    a = a.dropna(subset=["t"])
    cat = (a["category"].fillna("") == "Result") & (a["subcategory"].fillna("") == "Financial Results")
    hl = a["headline"].fillna("").str.lower()
    res = hl.str.contains("result", regex=False)
    keys = rq[["scrip_code", "quarter_end"]].drop_duplicates()
    m = keys.merge(a[["scrip_code", "t"]].assign(_cat=cat.values, _res=res.values, _hl=hl.values),
                   on="scrip_code", how="inner")
    lo_hi = [announcement_window(q) for q in m["quarter_end"]]
    lo = pd.to_datetime([x[0] for x in lo_hi])
    hi = pd.to_datetime([x[1] for x in lo_hi]) + pd.Timedelta(hours=23, minutes=59, seconds=59)
    month = [MONTHS[q.month - 1] for q in m["quarter_end"]]
    named = np.array([r and (mo in h) for r, mo, h in zip(m["_res"], month, m["_hl"])])
    ok = (m["t"].values >= lo.values) & (m["t"].values <= hi.values) & (m["_cat"].values | named)
    m = m[ok]
    return (m.sort_values("t", kind="mergesort")
             .groupby(["scrip_code", "quarter_end"], sort=True)["t"].first()
             .rename("announced").reset_index())


def usable_from(q_end: date, announced) -> tuple:
    """(usable date, source) under the 2026-10-01 A5 rule."""
    floor = q_end + timedelta(days=DEADLINE_DAYS_MARCH if q_end.month == 3 else DEADLINE_DAYS)
    if announced is not None and not pd.isna(announced):
        return max(pos.filed_usable_from(pd.Timestamp(announced)), floor), "announcement"
    return q_end + timedelta(days=UNMATCHED_DAYS), "unmatched_90"


def dated_quarters(rq: pd.DataFrame, matched: pd.DataFrame) -> pd.DataFrame:
    df = rq.merge(matched, on=["scrip_code", "quarter_end"], how="left")
    u = [usable_from(q, a) for q, a in zip(df["quarter_end"], df["announced"])]
    df["usable_from"] = [x[0] for x in u]
    df["date_source"] = [x[1] for x in u]
    return df.drop(columns=["announced"])


def _qshift(q: date, j: int) -> date:
    return (pd.Timestamp(q) - pd.offsets.QuarterEnd(j)).date() if j else q


def ttm_at(dq: pd.DataFrame, m: date) -> pd.DataFrame:
    """Per scrip: the latest quarter usable at M, and for each field its TTM
    (that quarter + three before) and the year-earlier TTM (the four before
    those), each quarter usable at M and carrying the field, else NaN.
    Also the four quarter ends (for EPS restatement)."""
    c = dq[dq["usable_from"] <= m]
    if not len(c):
        return pd.DataFrame(columns=["scrip_code", "quarter_end"])
    last = c.groupby("scrip_code")["quarter_end"].max().reset_index()
    idx = c.set_index(["scrip_code", "quarter_end"])[["revenue", "net_profit", "eps"]]
    idx = idx[~idx.index.duplicated(keep="last")]
    out = last.copy()
    for j in range(8):
        keys = pd.MultiIndex.from_arrays([last["scrip_code"], [_qshift(q, j) for q in last["quarter_end"]]])
        got = idx.reindex(keys)
        for f in ("revenue", "net_profit", "eps"):
            out[f"{f}_{j}"] = got[f].to_numpy()
        out[f"q_{j}"] = [_qshift(q, j) for q in last["quarter_end"]]
    for f in ("revenue", "net_profit"):
        a = out[[f"{f}_{j}" for j in range(4)]].to_numpy(dtype=float)
        b = out[[f"{f}_{j}" for j in range(4, 8)]].to_numpy(dtype=float)
        out[f"{f}_ttm"] = np.where(np.isnan(a).any(axis=1), np.nan, a.sum(axis=1))
        out[f"{f}_ttm_prev"] = np.where(np.isnan(b).any(axis=1), np.nan, b.sum(axis=1))
    return out


def _pct_own(values: pd.DataFrame) -> pd.DataFrame:
    """values: month-end x isin. Percentile of each value within its column's
    trailing HIST rows (itself included); NaN with fewer than HIST_MIN."""
    arr = values.to_numpy(dtype=float)
    out = np.full_like(arr, np.nan)
    for i in range(arr.shape[0]):
        w = arr[max(0, i - HIST + 1): i + 1]
        cur = arr[i]
        n = np.sum(~np.isnan(w), axis=0)
        le = np.sum(w <= cur, axis=0)                 # NaN compares False
        ok = (n >= HIST_MIN) & ~np.isnan(cur)
        out[i] = np.where(ok, le / np.maximum(n, 1), np.nan)
    return pd.DataFrame(out, index=values.index, columns=values.columns)


class _K:
    """k = adj_close / close of an ISIN at its last session <= a date."""

    def __init__(self, kw: pd.DataFrame):
        self.idx, self.a = kw.index, kw.to_numpy()
        self.col = {c: i for i, c in enumerate(kw.columns)}

    def at(self, isins: Sequence[str], when: Sequence[date]) -> np.ndarray:
        rows = self.idx.searchsorted(pd.to_datetime(list(when)), side="right") - 1
        return np.array([self.a[r, self.col[i]] if (r >= 0 and i in self.col) else np.nan
                         for r, i in zip(rows, isins)], dtype=float)


def a5_features(dq: pd.DataFrame, dividends: pd.DataFrame, shares: pd.DataFrame,
                panel: pd.DataFrame, universe: Mapping[date, Sequence[str]],
                resolver: "pos.ScripResolver") -> pd.DataFrame:
    """The §6(f) store, long format (STORE_COLUMNS), sorted (M, isin, feature).

    dq: `dated_quarters`; dividends: isin, ex_date, dividend_per_share;
    shares: scrip_code, quarter_end, usable_from, shares_outstanding (A2's
    dating); panel: date, isin, close, adj_close (truncated); universe: U(M).
    Yields are computed on every month-end for every name that is ever in
    U(M), so the own-history percentile sees the name's whole past."""
    mes = sorted(universe)
    names = sorted(set().union(*map(set, universe.values())))
    p = panel.loc[panel["isin"].isin(names), ["date", "isin", "close", "adj_close"]].copy()
    p["date"] = pd.to_datetime(p["date"])
    p["k"] = p["adj_close"] / p["close"]
    close = p.pivot_table(index="date", columns="isin", values="close", aggfunc="last").sort_index()
    kw = p.pivot_table(index="date", columns="isin", values="k", aggfunc="last")
    # pivot_table drops all-NaN rows and columns, and which ones depends on
    # the names present: align k to close, or row r of one is not row r of
    # the other (found by the dev-vs-validation point-in-time check)
    # the other (found by the dev-vs-validation point-in-time check); k moves
    # only on a split or bonus, so each name's last known k carries forward
    kw = kw.reindex(index=close.index, columns=close.columns).ffill()
    del p
    K = _K(kw)
    div = dividends[dividends["isin"].isin(names)].copy()
    div["ex_date"] = pd.to_datetime(div["ex_date"]).dt.date
    div["k"] = K.at(div["isin"].tolist(), div["ex_date"].tolist())
    div["dps_adj"] = div["dividend_per_share"] * div["k"]   # on the latest basis
    sh = shares[shares["shares_outstanding"] > 0]

    grids = {c: {} for c in ("ey_ttm", "sy_ttm", "dy_ttm", "rev_ttm_yoy", "np_ttm_yoy")}
    rid: Dict[tuple, str] = {}
    mts = pd.to_datetime(mes)
    for m, mt in zip(mes, mts):
        r = close.index.searchsorted(mt, side="right") - 1
        if r < 0 or close.index[r] != mt:
            continue
        c_m = close.iloc[r]
        k_m = kw.iloc[r]
        have = [i for i in names if np.isfinite(c_m.get(i, np.nan))]
        # -- results: scrip -> isin at M (lower scrip code wins a shared ISIN)
        t = ttm_at(dq, m)
        by_isin: Dict[str, int] = {}
        if len(t):
            t = t.sort_values("scrip_code", kind="mergesort").reset_index(drop=True)
            for j, sc in enumerate(t["scrip_code"]):
                i = resolver.isin_at(sc, m)
                if i and i not in by_isin:
                    by_isin[i] = j
        # -- shares outstanding at M (latest usable shareholding quarter)
        s = sh[sh["usable_from"] <= m]
        s = s.sort_values(["scrip_code", "quarter_end"], kind="mergesort").groupby("scrip_code").tail(1)
        so: Dict[str, tuple] = {}
        for x in s.sort_values("scrip_code", kind="mergesort").itertuples(index=False):
            i = resolver.isin_at(x.scrip_code, m)
            if i and i not in so:
                so[i] = (float(x.shares_outstanding), x.quarter_end)
        # -- dividends with ex-date in (M - 12 months, M]
        lo = (pd.Timestamp(m) - pd.DateOffset(months=12)).date()
        d = div[(div["ex_date"] > lo) & (div["ex_date"] <= m)]
        dsum = d.groupby("isin")["dps_adj"].sum()
        dy_off = any(lo_ <= m <= hi_ for lo_, hi_ in DY_NAN)
        for i in have:
            px, km = float(c_m[i]), float(k_m[i])
            grids["dy_ttm"][(m, i)] = np.nan if dy_off else float(dsum.get(i, 0.0)) / km / px
            if i in so:
                n, qe = so[i]
                kq = K.at([i], [qe])[0]
                mcap = n * km / kq * px        # a share count moves opposite to a per-share figure
            else:
                mcap = np.nan
            if i not in by_isin:
                continue
            row = t.iloc[by_isin[i]]
            rid[(m, i)] = f"bse_res:{row['scrip_code']}@{row['quarter_end']}"
            eps = np.array([row[f"eps_{j}"] for j in range(4)], dtype=float)
            kq4 = K.at([i] * 4, [row[f"q_{j}"] for j in range(4)])
            eps_m = np.nan if np.isnan(eps).any() else float(np.sum(eps * kq4 / km))
            grids["ey_ttm"][(m, i)] = eps_m / px
            rev = row["revenue_ttm"]
            grids["sy_ttm"][(m, i)] = rev * 1e6 / mcap if mcap and np.isfinite(mcap) and mcap > 0 else np.nan
            for f, col in (("revenue", "rev_ttm_yoy"), ("net_profit", "np_ttm_yoy")):
                a, b = row[f"{f}_ttm"], row[f"{f}_ttm_prev"]
                grids[col][(m, i)] = (a - b) / abs(b) if (np.isfinite(a) and np.isfinite(b) and b != 0) else np.nan

    def wide(g):
        s = pd.Series(g, dtype=float)
        if not len(s):
            return pd.DataFrame(index=mes, columns=names, dtype=float)
        s.index = pd.MultiIndex.from_tuples(s.index)
        # 12 decimals: k(then)/k(M) is a ratio of two panel factors whose
        # common scale depends on later splits, so the same value can differ
        # in the 16th digit between period truncations and flip a tie
        return s.unstack().reindex(index=mes, columns=names).round(12)
    w = {c: wide(g) for c, g in grids.items()}
    for y in YIELDS:
        w[y.replace("_ttm", "_pct36")] = _pct_own(w[y])

    out = []
    for m in mes:
        elig = list(universe[m])
        pub = pd.Timestamp(datetime.combine(m, CLOSE_IST), tz=TZ)
        for n in COLUMNS:
            v = w[n].loc[m].reindex(elig).to_numpy(dtype=float)
            v = np.where(np.isfinite(v), v, np.nan)
            ok = ~np.isnan(v)
            src = "nse_dividends" if n.startswith("dy") else "bse_results"
            out.append(pd.DataFrame({
                "isin": elig, "month_end": m, "feature": n, "value": v, "available": ok,
                "source": src,
                "source_record_id": [(rid.get((m, i)) if src == "bse_results" else f"nse_div:{i}@{m}")
                                     if o else None for i, o in zip(elig, ok)],
                "published_at": pub, "usable_from": m}))
    if not out:
        return pd.DataFrame(columns=STORE_COLUMNS)
    store = pd.concat(out, ignore_index=True)
    order = {f: k for k, f in enumerate(COLUMNS)}
    store = (store.assign(_o=store["feature"].map(order))
                  .sort_values(["month_end", "isin", "_o"], kind="mergesort")
                  .drop(columns="_o").reset_index(drop=True))
    return store[STORE_COLUMNS]
