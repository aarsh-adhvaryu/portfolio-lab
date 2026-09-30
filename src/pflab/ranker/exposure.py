"""E5-A §6(d) feature store, family A3: world exposure (E2-B's factors).

For each factor in {Brent, USDINR, US 10-year, India VIX, net FII flows}:
the name's trailing beta (`signals.shock_betas.rolling_betas`, 36 month-ends,
>= 24 pairs), and beta x the factor's change over the last 1 and 3 months;
plus the name's Nifty 500 beta. No new data: the series are the ones E2-B
reads.

Build readings, for the lock to confirm (none is in the charter's text):

  * transforms are shock_betas' (E2-B readiness §3(d)): Brent and USDINR
    `pct`, US 10-year and India VIX `diff`, FII `sum` of the month's daily
    net equity flow; the Nifty 500 TRI `pct`;
  * the 3-month change is the same transform over three month-ends: level
    ratio minus 1 (`pct`), level difference (`diff`), three months' sum (`sum`);
  * **timing.** A value enters at M only if it was public by M's close
    (15:30 IST). Brent, USDINR (FRED DEXINUS, noon New York) and US 10-year
    (New York close) print after 15:30 IST on their own date, so each
    observation is usable from the NEXT calendar day. NSDL's FPI report for
    `report_date` d is treated the same way (usable d + 1). India VIX and
    the Nifty 500 TRI close at 15:30 IST and are usable on their date;
  * a stock's monthly return is month-end to month-end on adjusted close,
    with no forward fill across a missing month-end (shock_betas).

Everything at M uses rows usable on or before M.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Mapping, Sequence

import numpy as np
import pandas as pd

from pflab.ranker.features import CLOSE_IST, STORE_COLUMNS, TZ
from pflab.signals import shock_betas as sb

# name -> (transform, usable lag in calendar days)
FACTORS = {"brent": ("pct", 1), "usdinr": ("pct", 1), "us10y": ("diff", 1),
           "india_vix": ("diff", 0), "fii": ("sum", 1)}
INDEX = "nifty500"
WINDOW, MIN_OBS = 36, 24


def feature_names() -> List[str]:
    out = []
    for f in FACTORS:
        out += [f"beta_{f}", f"beta_{f}_x_chg1", f"beta_{f}_x_chg3"]
    return out + [f"beta_{INDEX}"]


def load_series(root=None) -> Dict[str, pd.Series]:
    """The five factor series and the Nifty 500 TRI, indexed by date, as on
    disk. `usable` shifts them; nothing here truncates."""
    from pflab.data import data_dir, macro
    root = root or data_dir()

    def s(df, col, dcol="date"):
        d = df[[dcol, col]].dropna()
        return pd.Series(d[col].astype(float).to_numpy(),
                         index=[pd.Timestamp(x).date() for x in d[dcol]])

    fpi = pd.read_parquet(root / "macro" / "FPI_DAILY.parquet")
    fpi = fpi[(fpi["asset"] == "Equity") & (fpi["route"] == "Sub-total")]
    return {"brent": s(macro.load("BRENT", root), "value"),
            "usdinr": s(macro.load("USDINR", root), "value"),
            "us10y": s(macro.load("US10Y", root), "value"),
            "india_vix": s(pd.read_parquet(root / "indices" / "INDIA_VIX.parquet"), "close"),
            "fii": s(fpi.groupby("report_date", as_index=False)["net_cr"].sum(),
                     "net_cr", "report_date"),
            INDEX: s(pd.read_parquet(root / "indices" / "NIFTY500_TRI.parquet"), "close")}


def usable(series: pd.Series, lag_days: int, end: date) -> pd.Series:
    """The series re-dated to when each value became usable, cut at `end`."""
    s = series.sort_index()
    if lag_days:
        s = pd.Series(s.to_numpy(), index=[d + timedelta(days=lag_days) for d in s.index])
    return s[[d <= end for d in s.index]]


def changes(series: pd.Series, month_ends: Sequence[date], transform: str,
            k: int) -> pd.Series:
    """The factor's change over the last k month-ends at each month-end."""
    if k == 1:
        return sb.month_end_values(series, month_ends, transform)
    if transform == "sum":
        one = sb.month_end_values(series, month_ends, "sum")
        return one.rolling(k, min_periods=k).sum()
    s = series.dropna().sort_index()
    idx = pd.Index(s.index)
    pos = idx.searchsorted(list(month_ends), side="right") - 1
    lv = pd.Series([s.iloc[p] if p >= 0 else np.nan for p in pos],
                   index=list(month_ends), dtype=float)
    return lv / lv.shift(k) - 1.0 if transform == "pct" else lv - lv.shift(k)


def a3_features(close_wide: pd.DataFrame, series: Mapping[str, pd.Series],
                universe: Mapping[date, Sequence[str]], month_ends: Sequence[date],
                end: date) -> pd.DataFrame:
    """The §6(d) store, long format, sorted (M, isin, feature).

    `close_wide` is adjusted close (sessions x ISIN) from the truncated panel;
    `month_ends` every engine month-end; `series` as `load_series` returns."""
    mes = sorted(month_ends)
    rets = sb.monthly_returns(close_wide, mes)
    wide: Dict[str, pd.DataFrame] = {}
    for f, (tr, lag) in FACTORS.items():
        s = usable(series[f], lag, end)
        c1 = sb.month_end_values(s, mes, tr)
        c3 = changes(s, mes, tr, 3)
        b = sb.rolling_betas(rets, c1.reindex(rets.index), WINDOW, MIN_OBS)
        wide[f"beta_{f}"] = b
        wide[f"beta_{f}_x_chg1"] = b.mul(c1.reindex(b.index), axis=0)
        wide[f"beta_{f}_x_chg3"] = b.mul(c3.reindex(b.index), axis=0)
    idx = sb.month_end_values(usable(series[INDEX], 0, end), mes, "pct")
    wide[f"beta_{INDEX}"] = sb.rolling_betas(rets, idx.reindex(rets.index), WINDOW, MIN_OBS)

    names = feature_names()
    src = {n: "macro" for n in names}
    for f in FACTORS:
        for n in (f"beta_{f}", f"beta_{f}_x_chg1", f"beta_{f}_x_chg3"):
            src[n] = f"panel+{f}"
    src[f"beta_{INDEX}"] = f"panel+{INDEX}"
    out = []
    for m in sorted(universe):
        elig = list(universe[m])
        pub = pd.Timestamp(datetime.combine(m, CLOSE_IST), tz=TZ)
        for n in names:
            w = wide[n]
            v = (w.loc[m].reindex(elig).to_numpy(dtype=float) if m in w.index
                 else np.full(len(elig), np.nan))
            v = np.where(np.isfinite(v), v, np.nan)
            ok = ~np.isnan(v)
            out.append(pd.DataFrame({
                "isin": elig, "month_end": m, "feature": n, "value": v,
                "available": ok, "source": src[n],
                "source_record_id": [f"{i}@{m}" if o else None for i, o in zip(elig, ok)],
                "published_at": pub, "usable_from": m}))
    if not out:
        return pd.DataFrame(columns=STORE_COLUMNS)
    store = pd.concat(out, ignore_index=True)
    order = {f: k for k, f in enumerate(names)}
    store = (store.assign(_o=store["feature"].map(order))
                  .sort_values(["month_end", "isin", "_o"], kind="mergesort")
                  .drop(columns="_o").reset_index(drop=True))
    return store[STORE_COLUMNS]
