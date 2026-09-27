"""Scan every INF (ETF) ISIN in the panel for unadjusted splits and ISIN changes.

Written 2026-09-27 after NIFTYBEES/GOLDBEES (`pflab.data.etf_events`). Reads
the panel read-only, applies the declared ETF events, then reports:

* every one-day adjusted move beyond +/-20%, split into the ETFs a charter
  uses (USED) and the rest;
* every symbol whose ISIN changed (the next ISIN starting within 7 days);
* NIFTYBEES's repaired daily returns against the Nifty 50 price index.

Exit status 1 if a USED ETF still has an unexplained move. Findings are in
`docs/data/etf_splits.md`.

    python tools/scan_etf_events.py
"""
from __future__ import annotations

import sys

import duckdb
import pandas as pd

from pflab.data import data_dir
from pflab.data import etf_events

USED = {"NIFTYBEES": "E3-R, E3", "GOLDBEES": "E3", "LIQUIDBEES": "E3"}
JUMP = 0.20


def main() -> int:
    panel = (data_dir() / "panel" / "prices.parquet").as_posix()
    raw = duckdb.sql(
        f"select date, isin, symbol, instrument_type, open, close, prev_close, "
        f"adj_factor, adj_close, adj_open, volume from read_parquet('{panel}') "
        f"where isin like 'INF%'").df()
    raw["date"] = pd.to_datetime(raw["date"]).dt.date
    fixed, _, report = etf_events.apply(raw, None)
    print(f"INF rows {len(raw):,}, ISINs {raw['isin'].nunique()}, "
          f"types {sorted(raw['instrument_type'].unique())}")
    for r in report:
        print(f"  declared: {r}")

    p = fixed.sort_values(["isin", "date"]).copy()
    p["r"] = p.groupby("isin")["adj_close"].pct_change()
    jumps = p[p["r"].abs() > JUMP]
    used = jumps[jumps["symbol"].isin(USED)]
    print(f"\none-day moves beyond {JUMP:.0%} after the fix: {len(jumps)} "
          f"({jumps['isin'].nunique()} ISINs); in USED ETFs: {len(used)}")
    split_like = jumps[(jumps["r"] < -0.75) & (jumps["volume"] > 1000)]
    print(f"  of which split-like (fell >75% on volume >1,000): {len(split_like)}")
    for _, j in split_like.sort_values("date").iterrows():
        print(f"    {j['date']} {j['symbol']:<11} {j['isin']} {j['prev_close']:>9.2f} -> "
              f"{j['close']:>8.2f}  ratio {j['close'] / j['prev_close']:.4f}")
    for sym in USED:
        s = p[p["symbol"] == sym]
        print(f"  {sym:<10} ({USED[sym]}): {s['isin'].nunique()} ISIN(s) after fix, "
              f"max |1-day move| {s['r'].abs().max():.2%} on "
              f"{s.loc[s['r'].abs().idxmax(), 'date']}")

    g = raw.groupby(["symbol", "isin"])["date"].agg(["min", "max"]).reset_index()
    g = g.sort_values(["symbol", "min"])
    g["prev_max"] = g.groupby("symbol")["max"].shift()
    gap = (pd.to_datetime(g["min"]) - pd.to_datetime(g["prev_max"])).dt.days
    succ = g[gap.between(1, 7)]
    print(f"\nISIN successions (same symbol, next ISIN within 7 days): {len(succ)}")

    idx = pd.read_parquet(data_dir() / "indices" / "NIFTY50_PRICE.parquet")
    idx["date"] = pd.to_datetime(idx["date"]).dt.date
    nb = p[p["symbol"] == "NIFTYBEES"][["date", "adj_close"]].copy()
    m = nb.merge(idx[["date", "close"]], on="date").sort_values("date")
    diff = (m["adj_close"].pct_change() - m["close"].pct_change()).abs()
    print(f"\nNIFTYBEES vs NIFTY50_PRICE, {len(m):,} common sessions: "
          f"|daily return gap| median {diff.median():.3%}, "
          f"99th pct {diff.quantile(0.99):.3%}, max {diff.max():.2%} on "
          f"{m.loc[diff.idxmax(), 'date']}")
    around = m[(m["date"] >= pd.Timestamp("2019-12-16").date())
               & (m["date"] <= pd.Timestamp("2019-12-24").date())]
    print("  across the 2019-12-19 split:")
    print(around.assign(etf_r=around["adj_close"].pct_change(),
                        idx_r=around["close"].pct_change()).to_string(index=False))
    return 1 if len(used) else 0


if __name__ == "__main__":
    sys.exit(main())
