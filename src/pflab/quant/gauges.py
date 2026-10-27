"""Three market gauges, from our own data (S64; the idea comes from public trading-skills repositories whose scores are untested
heuristics, so only the descriptions are taken, never their thresholds or "risk budgets"):

    ipo_froth     large main-board listings (day-one traded value of Rs 200 crore or more) in the last four quarters against the
                  average quarter of the five years before, and their median listing gain at the close against the same history
    breadth       the share of today's Nifty 500 members trading above their 200-day and 50-day averages (raw closes of the
                  bhavcopy; names with a split or bonus in the last 300 days are left out, their old closes are another unit),
                  and where that share sits in its own history
    corrections   for the Nifty 500 and each sector index: how deep and how long past falls of 10% or more were (peak to trough
                  and back to the old peak, in sessions), against how far into a fall the index is now

They describe; none of them is a signal. The one tested fact near them: names below their 200-day average earned less in 2010-2021
(`docs/research/s64_rules_results.md`), so a low breadth is a fact about many names being in that group, not a forecast.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

MIN_TURNOVER = 2e9
DEPTH = 0.10
INDICES = ["NIFTY500_TRI", "SECTOR_IT_TRI", "SECTOR_BANK_TRI", "SECTOR_AUTO_TRI", "SECTOR_PHARMA_TRI", "SECTOR_FMCG_TRI",
           "SECTOR_METAL_TRI", "SECTOR_ENERGY_TRI", "SECTOR_FIN_SERVICES_TRI", "SECTOR_INFRA_TRI", "SECTOR_CONSUMER_DURABLES_TRI"]


def ipo_froth(root: Path, asof: date) -> dict:
    from pflab import _duck
    root = Path(root)
    ld = pd.read_parquet(root / "panel" / "listing_dates.parquet")
    ld = ld[ld.index.astype(str).str.startswith("INE")]
    ld["first_trade"] = pd.to_datetime(ld["first_trade"])
    start = pd.Timestamp(asof) - pd.DateOffset(years=7)
    ld = ld[(ld["first_trade"] >= start) & (ld["first_trade"] <= pd.Timestamp(asof))]
    d = _duck.sql(f"select date, isin, series, close, prev_close, turnover from '{root}/panel/prices.parquet' where isin in "
                  f"({','.join(repr(i) for i in ld.index)}) and date >= DATE '{start.date()}'").df()
    d["date"] = pd.to_datetime(d["date"])
    first = d.sort_values("date").groupby("isin").head(1)
    first = first.merge(ld.reset_index().rename(columns={"index": "isin"}), on="isin")
    first = first[(first["date"] == first["first_trade"]) & (first["series"] == "EQ") & (first["turnover"] >= MIN_TURNOVER)]
    first = first.assign(gain=first["close"] / first["prev_close"] - 1)
    first = first[first["gain"].between(-0.6, 3.0)]
    q = first["date"].dt.to_period("Q")
    per_q = q.value_counts().sort_index()
    pmax = pd.Timestamp(_duck.sql(f"select max(date) from '{root}/panel/prices.parquet'").fetchone()[0])
    pq = min(pd.Timestamp(asof), pmax).to_period("Q")
    end_q = pq if min(pd.Timestamp(asof), pmax) >= pq.end_time.normalize() - pd.Timedelta(days=3) else pq - 1     # whole quarters only
    last4 = [end_q - k for k in range(4)]
    prior = [end_q - 4 - k for k in range(20)]
    n_last = int(per_q.reindex(last4, fill_value=0).sum())
    avg_prior = float(per_q.reindex(prior, fill_value=0).mean())
    g_last = first[q.isin(last4)]["gain"]
    g_prior = first[q.isin(prior)]["gain"]
    ratio = n_last / 4 / avg_prior if avg_prior > 0 else None
    return {"large_listings_last_4_quarters": n_last, "per_quarter_now": round(n_last / 4, 1), "per_quarter_prior_5_years": round(avg_prior, 1),
            "ratio": None if ratio is None else round(ratio, 2),
            "median_listing_gain_now_pct": None if g_last.empty else round(float(g_last.median()) * 100, 1),
            "median_listing_gain_prior_5_years_pct": None if g_prior.empty else round(float(g_prior.median()) * 100, 1),
            "listings_counted_to": str(first["date"].max().date()) if len(first) else None,
            "read": ("busier than its 5-year norm" if ratio and ratio > 1.5 else "quieter than its norm" if ratio and ratio < 0.7 else
                     "about its norm") if ratio is not None else "no history to compare"}


def breadth(root: Path, asof: date, members: Optional[List[str]] = None, closes: Optional[pd.DataFrame] = None) -> dict:
    """Share of today's Nifty 500 members above their 200- and 50-day average, with its own 1-year percentile."""
    from pflab import _duck
    from pflab.data import bhavcopy
    if closes is None:
        root = Path(root)
        m = pd.read_parquet(root / "index_membership" / "NIFTY500.parquet")
        m["to_date"] = pd.to_datetime(m["to_date"]).fillna(pd.Timestamp("2099-01-01"))
        live = m[(pd.to_datetime(m["from_date"]) <= pd.Timestamp(asof)) & (m["to_date"] > pd.Timestamp(asof))]["isin"].tolist()
        files = bhavcopy.bhav_files(root, asof - timedelta(days=520), asof)
        rel = f"read_parquet({files!r}, union_by_name=true)"
        d = _duck.sql(f"select date, isin, close from {rel} where series in ('EQ','BE') and isin in ({','.join(repr(i) for i in live)})").df()
        d["date"] = pd.to_datetime(d["date"])
        closes = d.drop_duplicates(["date", "isin"]).pivot(index="date", columns="isin", values="close").sort_index()
        try:                                               # a split or bonus changes the unit of an old close: leave those names out
            from pflab.data import nse_corporate_actions as nca
            ev = nca.events(root)
            bad = set(ev[(ev["kind"].isin(["split", "bonus"])) & (pd.to_datetime(ev["ex_date"]) >= pd.Timestamp(asof) - timedelta(days=330))]["isin"])
            closes = closes.drop(columns=[c for c in closes.columns if c in bad])
        except Exception:
            pass
    c = closes.astype(float).iloc[-(260 + 252):]
    ok = c.notna().sum() >= 210
    c = c.loc[:, ok]
    s200 = c.rolling(200, min_periods=200).mean()
    s50 = c.rolling(50, min_periods=50).mean()
    a200 = ((c > s200).where(s200.notna()).sum(axis=1).astype(float) / s200.notna().sum(axis=1).astype(float).replace(0.0, np.nan)).dropna()
    a50 = ((c > s50).where(s50.notna()).sum(axis=1).astype(float) / s50.notna().sum(axis=1).astype(float).replace(0.0, np.nan)).dropna()
    if a200.empty:
        return {"not_built": "too little price history"}
    now200, now50 = float(a200.iloc[-1]), float(a50.iloc[-1])
    hist = a200.iloc[-252:]
    return {"on": str(a200.index[-1].date()), "names": int(len(c.columns)), "above_200d_pct": round(now200 * 100, 1),
            "above_50d_pct": round(now50 * 100, 1), "above_200d_percentile_1y": round(float((hist <= now200).mean() * 100)),
            "above_200d_1y_range_pct": [round(float(hist.min()) * 100, 1), round(float(hist.max()) * 100, 1)],
            "read": ("most names are in a downtrend" if now200 < 0.35 else "most names are in an uptrend" if now200 > 0.65 else "mixed"),
            "note": "raw closes of the bhavcopy; names with a split or bonus in the last 11 months are left out; a description"}


def episodes(close: pd.Series, depth: float = DEPTH) -> List[dict]:
    """Falls of at least `depth` from a peak: sessions peak to trough, sessions from the trough back above the old peak (None if
    not yet), and the depth."""
    s = close.dropna()
    if s.empty:
        return []
    out, peak_i, peak = [], 0, float(s.iloc[0])
    v = s.to_numpy(float)
    trough_i, trough = 0, peak
    in_fall = False
    for i in range(1, len(v)):
        if v[i] >= peak:
            if in_fall and (trough / peak - 1) <= -depth:
                out.append({"peak": str(s.index[peak_i].date()), "depth": trough / peak - 1, "to_trough": trough_i - peak_i,
                            "to_recover": i - trough_i, "total": i - peak_i, "open": False})
            peak_i, peak, trough_i, trough, in_fall = i, v[i], i, v[i], False
        else:
            in_fall = True
            if v[i] < trough:
                trough_i, trough = i, v[i]
    if in_fall and (trough / peak - 1) <= -depth:
        out.append({"peak": str(s.index[peak_i].date()), "depth": trough / peak - 1, "to_trough": trough_i - peak_i,
                    "to_recover": None, "total": len(v) - 1 - peak_i, "open": True})
    return out


def corrections(root: Path, asof: date, keys: Optional[List[str]] = None, loader=None) -> dict:
    from pflab.data import indices
    root = Path(root)
    load = loader or (lambda k: indices.load(k, root))
    out = {}
    for k in keys or INDICES:
        try:
            df = load(k)
            s = pd.Series(df["close"].to_numpy(float), index=pd.to_datetime(df["date"])).sort_index()
            s = s[s.index <= pd.Timestamp(asof)]
        except Exception:
            continue
        ep = episodes(s)
        done = [e for e in ep if not e["open"]]
        peak = float(s.cummax().iloc[-1])
        sessions_since_peak = int(len(s) - 1 - int(np.argmax(s.to_numpy() == peak)))
        row = {"now_below_peak_pct": round((float(s.iloc[-1]) / peak - 1) * 100, 1), "sessions_since_peak": sessions_since_peak,
               "past_falls_of_10pct_or_more": len(done)}
        if done:
            row["median_sessions_peak_to_trough"] = int(np.median([e["to_trough"] for e in done]))
            row["median_sessions_trough_to_new_high"] = int(np.median([e["to_recover"] for e in done]))
            row["longest_peak_to_new_high"] = int(max(e["total"] for e in done))
            row["median_depth_pct"] = round(float(np.median([e["depth"] for e in done])) * 100, 1)
        out[k.replace("_TRI", "").replace("SECTOR_", "").title()] = row
    return {"indices": out, "from": "total-return indices (NSE); 252 sessions is about a year",
            "note": "history of past falls: how long they lasted so far; not a forecast of how long this one will"}
