"""Context for the brain (S63, the investor 2026-10-25: "connect the dots"): facts by code, never signals.

    holders   who is buying or selling a stock: insider and SAST disclosures (BSE announcements), NSE bulk and block
              deals, the shareholding pattern (promoters, pledges) and institutional holding by quarter
    market    the market's backdrop: FII / FPI net equity flows (NSDL), India VIX, Brent, the rupee, the US 10-year
              yield, the Nifty 500 (every figure with its date)
    growth    where the portfolio's change came from over a period: money put in, gains (realised and unrealised),
              income, charges (`calc/growth.py`, on the statements' ledger)
The studies on these data (S48 institutions and deals, E2-B shock factors) found no trading rule, so nothing here is
a reason to buy or sell (CLAUDE.md 12); the learner may test claims on them through its templates. Point in time:
rows dated on or before `asof` only.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

NOISE = ("Closure of Trading Window", "Trading Window")


def _scrip(root: Path, isin: str) -> Optional[str]:
    import duckdb
    r = duckdb.sql(f"select scrip_code from '{Path(root) / 'bse_scrip_isin' / 'map.parquet'}' where isin = '{isin}' "
                   f"order by scrip_code limit 1").fetchone()
    return str(r[0]) if r else None


def holders(con, root: Path, isin: str, symbol: str, asof: date, days: int = 180) -> dict:
    root = Path(root)
    out: dict = {"symbol": symbol, "asof": str(asof)}
    scrip = _scrip(root, isin)
    since = pd.Timestamp(asof - timedelta(days=days))
    try:
        from pflab.data import bse_insider
        ins = bse_insider.load(root)
        ins = ins[(ins["scrip_code"].astype(str) == scrip) & (ins["dissem_dt"] >= since)
                  & (ins["dissem_dt"] <= pd.Timestamp(asof) + pd.Timedelta(days=1))
                  & ~ins["subcategory"].fillna("").str.contains("|".join(NOISE))]
        out["insider_and_sast"] = [f"{r.dissem_dt:%Y-%m-%d} {r.subcategory}: {str(r.headline)[:140]}"
                                   for r in ins.sort_values("dissem_dt", ascending=False).head(10).itertuples()]
    except Exception as e:                                   # a missing dataset is said, not hidden
        out["insider_and_sast"] = f"not available ({type(e).__name__})"
    try:
        from pflab.data import nse_deals
        dl = nse_deals.load(root)
        dl = dl[(dl["symbol"] == symbol) & (dl["date"] >= since) & (dl["date"] <= pd.Timestamp(asof))]
        out["bulk_block_deals"] = [f"{r.date:%Y-%m-%d} {r.kind} {r.side} {int(r.quantity):,} at {r.price:g} by {r.client}"
                                   for r in dl.sort_values("date", ascending=False).head(10).itertuples()]
    except Exception as e:
        out["bulk_block_deals"] = f"not available ({type(e).__name__})"
    if scrip:
        try:
            s = pd.read_parquet(root / "bse_shareholding" / "summary.parquet",
                                columns=["scrip_code", "quarter_end", "status", "promoter_pct", "pledged_pct_of_promoter"])
            s = s[(s["scrip_code"].astype(str) == scrip) & (s["status"] == "ok")
                  & (pd.to_datetime(s["quarter_end"]) <= pd.Timestamp(asof))].sort_values("quarter_end").tail(5)
            out["promoters_by_quarter"] = [f"{r.quarter_end}: promoters {r.promoter_pct:.2f}%, pledged "
                                           f"{(r.pledged_pct_of_promoter or 0):.2f}% of theirs" for r in s.itertuples()]
        except Exception as e:
            out["promoters_by_quarter"] = f"not available ({type(e).__name__})"
        try:
            from pflab.data import bse_institutions as bi
            q = bi.load(root)
            q = q[(q["scrip_code"].astype(str) == scrip) & (q["status"] == "ok")
                  & (pd.to_datetime(q["quarter_end"]) <= pd.Timestamp(asof))].sort_values("quarter_end").tail(5)
            out["institutions_by_quarter"] = [f"{r.quarter_end}: institutions {r.inst_pct:.2f}% (funds {r.mf_pct:.2f}%, "
                                              f"FPIs {r.fpi_pct:.2f}%)" for r in q.itertuples()]
        except Exception as e:
            out["institutions_by_quarter"] = f"not available ({type(e).__name__})"
    out["source"] = ("BSE announcements (insider / SAST), NSE bulk and block deals, BSE shareholding patterns; context, "
                     "never a signal (S48 found no rule)")
    return out


def _last_and_change(df: pd.DataFrame, col: str, asof: date, days: int = 30) -> Optional[dict]:
    df = df[pd.to_datetime(df["date"]) <= pd.Timestamp(asof)].sort_values("date")
    if df.empty:
        return None
    last = df.iloc[-1]
    before = df[pd.to_datetime(df["date"]) <= pd.Timestamp(last["date"]) - pd.Timedelta(days=days)]
    ch = (float(last[col]) / float(before.iloc[-1][col]) - 1) * 100 if len(before) and before.iloc[-1][col] else None
    return {"value": round(float(last[col]), 4), "on": str(pd.Timestamp(last["date"]).date()),
            f"change_{days}d_pct": round(ch, 2) if ch is not None else None}


def market(root: Path, asof: date) -> dict:
    root = Path(root)
    out: dict = {"asof": str(asof)}
    try:
        from pflab.data import fpi_flows
        f = fpi_flows.load(root)
        f = f[(f["asset"] == "Equity") & (f["route"] == "Sub-total") & (pd.to_datetime(f["report_date"]) <= pd.Timestamp(asof))]
        f = f.sort_values("report_date")
        out["fpi_equity_net_cr"] = {"last_day": round(float(f["net_cr"].iloc[-1]), 1), "on": str(f["report_date"].iloc[-1]),
                                    "last_5_days": round(float(f["net_cr"].tail(5).sum()), 1),
                                    "last_20_days": round(float(f["net_cr"].tail(20).sum()), 1)}
    except Exception as e:
        out["fpi_equity_net_cr"] = f"not available ({type(e).__name__})"
    from pflab.data import macro
    for key, label in (("BRENT", "brent_usd"), ("USDINR", "usd_inr"), ("US10Y", "us_10y_pct")):
        try:
            out[label] = _last_and_change(macro.load(key, root), "value", asof)
        except Exception as e:
            out[label] = f"not available ({type(e).__name__})"
    for name, file, col in (("india_vix", "INDIA_VIX.parquet", "close"), ("nifty500_tri", "NIFTY500_TRI.parquet", "close")):
        try:
            d = pd.read_parquet(root / "indices" / file)
            out[name] = _last_and_change(d.rename(columns={"value": "close"}), col, asof)
        except Exception as e:
            out[name] = f"not available ({type(e).__name__})"
    try:                                                   # S64: F&O facts (information, never a signal)
        from pflab.quant import options
        fo = options.summary(root, asof)
        from pflab.quant import implied
        im = implied.line(root, asof)
        if im:
            out["options_implied"] = im
        if fo:
            out["fo"] = {"line": options.line(root, asof), "atm_iv_pct": None if fo.get("atm_iv") is None else round(fo["atm_iv"] * 100, 1),
                         "iv_percentile_1y": fo.get("iv_percentile_1y"), "pcr": fo.get("pcr"), "max_pain": fo.get("max_pain"),
                         "max_pain_expiry": fo.get("max_pain_expiry"), "on": fo.get("date")}
    except Exception as e:
        out["fo"] = f"not available ({type(e).__name__})"
    out["source"] = "NSDL (FPI), FRED (Brent, USDINR, US 10-year), NSE (India VIX, Nifty 500 TRI, F&O bhavcopy); context, never a signal"
    return out


def growth(con, asof: date, months: int = 12) -> dict:
    from pflab.calc import growth as gr, valuation as val
    from pflab.ledger import events as ev
    log = ev.load(con)
    days = sorted({e.date for e in log})
    start = asof - timedelta(days=int(months * 30.44))
    if days:
        start = max(start, days[0])
        asof = min(asof, days[-1])                         # the statements' ledger ends where the documents end
    g = gr.growth(log, val.store_price_fn(con), start, asof)
    return {"from": str(g.start), "to": str(g.end), "start_value": round(g.start_value), "end_value": round(g.end_value),
            "money_put_in": round(g.contributions), "realised_gains": round(g.realised),
            "unrealised_change": round(g.unrealised_change), "income": round(g.income), "charges": round(g.charges),
            "other": round(g.other), "total_change": round(g.total_change),
            "source": "calc/growth.py on the statements' ledger (Kite trades after the last statement are not in it)"}
