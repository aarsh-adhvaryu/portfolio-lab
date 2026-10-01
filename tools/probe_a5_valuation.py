"""A5 valuation probe (E5-A §14 2026-10-01): coverage by year, 2007-2021, of
the two columns buildable from data already held. Diagnostic; writes nothing.

    python tools/probe_a5_valuation.py

* TTM dividend yield at M: dividends with ex-date in (M - 12 months, M]
  (NSE feed, the amount paid per share at the time), restated to M's share
  basis with the panel's split/bonus factor (adj_close / close), over M's
  close. Point in time by ex-date. A name in the feed's universe with no
  dividend is 0, not missing.
* Market cap at M: shares outstanding of the latest BSE shareholding quarter
  usable at M (reported from Dec 2015, derived before; E2-D1's usable-date
  rule), restated for split/bonus between quarter end and M, x M's close.

Universe: E1's U(M) from the A0 stores (e5a_development, validation).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from pflab.data import bse_scrip_isin, data_dir, positioning as pos  # noqa: E402
from pflab.ranker import store  # noqa: E402


def universe() -> pd.DataFrame:
    out = []
    for per in ("e5a_development", "validation"):
        f = pd.read_parquet(store.store_dir(per) / "features_a0.parquet",
                            columns=["isin", "month_end", "feature"])
        f = f[f["feature"] == "mom_1m"][["isin", "month_end"]]
        out.append(f)
    u = pd.concat(out).drop_duplicates()
    u["month_end"] = pd.to_datetime(u["month_end"])
    u["isin"] = u["isin"].astype(object)
    return u[(u["month_end"].dt.year >= 2007) & (u["month_end"].dt.year <= 2021)]


def main() -> int:
    u = universe()
    isins = set(u["isin"])
    panel = pd.read_parquet(data_dir() / "panel" / "prices.parquet",
                            columns=["date", "isin", "close", "adj_close"],
                            filters=[("isin", "in", sorted(isins))])
    panel["date"] = pd.to_datetime(panel["date"])
    panel = panel[panel["date"].dt.year.between(2005, 2021)]
    panel["k"] = panel["adj_close"] / panel["close"]
    panel["isin"] = panel["isin"].astype(object)
    px = u.merge(panel.rename(columns={"date": "month_end"}), on=["month_end", "isin"], how="left")

    # -- TTM dividend yield ---------------------------------------------------
    div = pd.read_parquet(data_dir() / "dividends" / "dividends.parquet")
    div["ex_date"] = pd.to_datetime(div["ex_date"])
    div = div[div["isin"].isin(isins)]
    div["isin"] = div["isin"].astype(object)
    kx = panel[["date", "isin", "k"]].sort_values("date")
    div = pd.merge_asof(div.sort_values("ex_date"), kx, left_on="ex_date", right_on="date",
                        by="isin", direction="backward")
    rows = []
    for m, g in px.groupby("month_end"):
        lo = m - pd.DateOffset(months=12)
        d = div[(div["ex_date"] > lo) & (div["ex_date"] <= m)]
        s = (d["dividend_per_share"] * d["k"]).groupby(d["isin"]).sum()
        y = g.set_index("isin")
        ttm = s.reindex(y.index).fillna(0.0) / y["k"]
        rows.append(pd.DataFrame({"month_end": m, "isin": y.index,
                                  "dy": (ttm / y["close"]).to_numpy(),
                                  "close": y["close"].to_numpy()}))
    dy = pd.concat(rows)

    # -- market cap -----------------------------------------------------------
    pq = pos.promoter_quarters(pd.read_parquet(data_dir() / "bse_shareholding" / "summary.parquet"))
    pq["_uf"] = pd.to_datetime(pd.Series(pq["usable_from"], dtype="object"))
    res = pos.ScripResolver(bse_scrip_isin.load())
    rq = res.all_isins()
    mc = []
    for m, g in px.groupby("month_end"):
        c = pq[pq["_uf"] <= m].sort_values("quarter_end").groupby("scrip_code").tail(1)
        c = c.assign(isin=[res.isin_at(sc, m.date()) for sc in c["scrip_code"]])
        c = c[c["isin"].notna() & (c["shares_outstanding"] > 0)]
        c = c.sort_values("scrip_code").drop_duplicates("isin")
        c = c.assign(q=pd.to_datetime(c["quarter_end"].astype(str)).astype(kx["date"].dtype))
        c["isin"] = c["isin"].astype(object)
        # split/bonus between quarter end and M: the panel factor moves with them
        c = pd.merge_asof(c.sort_values("q"), kx, left_on="q", right_on="date",
                          by="isin", direction="backward").rename(columns={"k": "kq"})
        y = g.merge(c[["isin", "shares_outstanding", "kq", "so_source"]], on="isin", how="left")
        mc.append(pd.DataFrame({"month_end": m, "isin": y["isin"],
                                "mcap": y["shares_outstanding"] * y["kq"] / y["k"] * y["close"],
                                "so_src": y["so_source"]}))
    mc = pd.concat(mc)
    t = dy.merge(mc, on=["month_end", "isin"])
    t["year"] = t["month_end"].dt.year
    out = t.groupby("year").agg(
        names=("isin", lambda x: round(len(x) / 12)),
        dy_available=("dy", lambda x: x.notna().mean()),
        dy_nonzero=("dy", lambda x: (x > 0).mean()),
        dy_median=("dy", "median"),
        mcap_available=("mcap", lambda x: x.notna().mean()),
        mcap_reported=("so_src", lambda x: (x == "reported").mean()),
        mcap_median_cr=("mcap", lambda x: x.median() / 1e7))
    print(out.round(3).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
