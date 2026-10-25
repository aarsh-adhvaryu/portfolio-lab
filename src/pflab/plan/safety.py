"""Safety checks before any direct-stock buy (S34: the 'Fsafe' filters, applied live).

The four tests are the ones the dip-rule study validated (docs/research/dip_rule_results.md):
    F1 profitable        trailing four quarters' net profit > 0
    F2 no collapse       trailing net profit at least half of the trailing net profit a year earlier
    F3 can pay interest  trailing (PBT + finance costs) / finance costs >= 2, or no finance costs
    F4 not a crash       no more than 50% below the 1-year high
A stock with too few filed quarters fails F1-F3: unknown is not safe. Results are BSE standalone filings
(`fundamentals.pit`); a quarter counts only once it is filed, so nothing here uses the future.
Exchange surveillance (ASM/GSM/ESM/T2T/IBC) is a separate guard.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

import pandas as pd


@dataclass
class Check:
    isin: str
    symbol: str
    ok: bool
    reasons: List[str] = field(default_factory=list)
    ttm_np: Optional[float] = None          # Rs mn
    ttm_np_prev: Optional[float] = None
    cover: Optional[float] = None
    drawdown: Optional[float] = None
    latest_quarter: Optional[date] = None


def ttm(q: pd.DataFrame) -> dict:
    """Trailing sums from the last 8 consecutive quarters (oldest first): this year's and last year's."""
    q = q.sort_values("quarter_end").drop_duplicates("quarter_end", keep="last").tail(8)
    q = q.assign(quarter_end=pd.to_datetime(q["quarter_end"]))
    if len(q) >= 2 and (q["quarter_end"].diff().dropna().dt.days > 100).any():
        q = q[q["quarter_end"] > q["quarter_end"][q["quarter_end"].diff().dt.days > 100].max() - pd.Timedelta(days=1)]
    num = lambda c, s: pd.to_numeric(s[c], errors="coerce")
    last4, prev4 = q.tail(4), q.iloc[-8:-4] if len(q) >= 8 else q.iloc[0:0]
    out = {"n": len(q), "latest": q["quarter_end"].max().date() if len(q) else None}
    out["np"] = float(num("net_profit", last4).sum()) if len(last4) == 4 and num("net_profit", last4).notna().all() else None
    out["np_prev"] = float(num("net_profit", prev4).sum()) if len(prev4) == 4 and num("net_profit", prev4).notna().all() else None
    pbt = num("pbt", last4).sum() if len(last4) == 4 else None
    fc = num("finance_costs", last4).abs().fillna(0).sum() if len(last4) == 4 else None   # BSE sometimes files it negative
    out["cover"] = None if pbt is None or fc is None else (float("inf") if fc <= 0 else float((pbt + fc) / fc))
    return out


FINANCIAL_SECTORS = ("financial services", "financial institution", "banks", "finance", "insurance",
                     "capital markets")                # "financial institution": NSE's pre-2014 label (PFC, REC)


def is_financial(sector: Optional[str]) -> bool:
    return bool(sector) and any(k in sector.lower() for k in FINANCIAL_SECTORS)


def evaluate(isin: str, symbol: str, q: pd.DataFrame, drawdown: Optional[float], financial: bool = False,
             basis: str = "standalone") -> Check:
    """`financial`: banks, NBFCs, insurers: interest is their business, so F3 (interest cover) does not apply
    (amendment 1 to the dip-rule protocol, 2026-10-15). `basis`: which results `q` holds (amendment 2, 2026-10-18:
    consolidated once eight consecutive quarters exist); a failing reason names it when it is consolidated."""
    t = ttm(q) if len(q) else {"n": 0, "latest": None, "np": None, "np_prev": None, "cover": None}
    c = Check(isin, symbol, True, [], t["np"], t["np_prev"], t["cover"], drawdown, t["latest"])
    b = " (consolidated)" if basis == "consolidated" else ""
    if t["np"] is None:
        c.reasons.append("F1/F2/F3 unknown: fewer than four consecutive filed quarters")
    else:
        if t["np"] <= 0:
            c.reasons.append(f"F1 loss-making{b}: trailing net profit {t['np']:,.0f} mn")
        if t["np_prev"] is None:
            c.reasons.append("F2 unknown: no full year before to compare")
        elif t["np"] < 0.5 * t["np_prev"]:
            c.reasons.append(f"F2 profit collapsed{b}: {t['np']:,.0f} mn vs {t['np_prev']:,.0f} mn a year earlier")
        if not financial and t["cover"] is not None and t["cover"] < 2:
            c.reasons.append(f"F3 interest cover{b} {t['cover']:.2f} (< 2)")
    if drawdown is None:
        c.reasons.append("F4 unknown: no 1-year price history")
    elif drawdown < -0.50:
        c.reasons.append(f"F4 crash: {drawdown:.0%} from the 1-year high")
    c.ok = not c.reasons
    return c


def drawdown(isin: str, asof: date, root=None) -> Optional[float]:
    """Close vs the 1-year high, from NSE bhavcopy (or BSE for BSE-only listings), split-safe via the panel's
    adjustment factor where the panel covers the window."""
    from pflab import _duck
    from pflab.data import bhavcopy, bse_bhavcopy, data_dir
    root = root or data_dir()
    start = asof - timedelta(days=372)
    px = _duck.sql(f"select date, adj_close as close from '{root}/panel/prices.parquet' where isin = '{isin}' "
                    f"and date >= DATE '{start}' and date <= DATE '{asof}' order by date").df()
    tail_from = px["date"].max() if len(px) else start
    raw = bhavcopy.load(pd.Timestamp(tail_from).date() + timedelta(days=1), asof, root=root, series=None)
    raw = raw[raw["isin"] == isin][["date", "close"]] if len(raw) else raw
    if (raw is None or not len(raw)) and not len(px):
        raw = bse_bhavcopy.load(start, asof, root=root)
        raw = raw[raw["isin"] == isin][["date", "close"]] if len(raw) else raw
    s = pd.concat([px, raw]) if len(px) else raw
    if s is None or not len(s):
        return None
    s = s.sort_values("date")["close"].astype(float)
    return float(s.iloc[-1] / s.max() - 1)
