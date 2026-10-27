"""Business at a glance for one company, from our own data (S64 Phase 5 item 10; the Tijori idea).

Twelve quarters of revenue, profit and margins; the shareholding trend, deals and insider filings; the CAPM and process facts;
a peer table of same-industry Nifty 500 names we hold results for, each with its rank; the concall, presentation and
transcript filings linked from the knowledge graph. What we cannot build is said, not guessed: segment revenue (the results
parser ignores segment rows), three-year growth (the filings of 2022-2024 are not on record), and operating KPIs (stores,
volumes, order book), which come from his Tijori sheet; the ask for one opens by itself when the sheet is missing
(agents/needs.py). Every number is a filed number or a ratio of one; none is a forecast.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd

QUARTERS = 12
DOC_WORDS = re.compile(r"concall|conference call|earnings call|transcript|presentation|audio recording|analyst.{0,12}investor meet", re.I)
MIN_PEER_QUARTERS = 8
CR = 10.0                          # the store keeps Rs million; 10 million = 1 crore


def quarters_table(con, root, scrip: str, asof: date, n: int = QUARTERS) -> List[dict]:
    from pflab.fundamentals import pit
    from pflab.hq import valuation
    q = pit.load(con, scrip)
    if q.empty:
        q = pit.load(con, scrip, "consolidated")
    q = valuation.with_older_quarters(q, scrip, root)
    q = q[q["usable_from"] <= asof].sort_values("quarter_end").drop_duplicates("quarter_end", keep="last")
    by = q.set_index("quarter_end")
    out = []
    for qe, r in by.tail(n).iterrows():
        rev, npf = r.get("revenue"), r.get("net_profit")
        try:
            pr = by.loc[qe.replace(year=qe.year - 1), "revenue"] if qe.replace(year=qe.year - 1) in by.index else None
        except ValueError:                                   # 29 February
            pr = None
        yoy = (rev / pr - 1.0) if pr is not None and pd.notna(rev) and pd.notna(pr) and pr else None
        out.append({"quarter": str(qe), "revenue_cr": None if pd.isna(rev) else round(float(rev) / CR, 1),
                    "net_profit_cr": None if pd.isna(npf) else round(float(npf) / CR, 1),
                    "net_margin_pct": None if not rev or pd.isna(npf) or pd.isna(rev) else round(float(npf) / float(rev) * 100, 1),
                    "revenue_yoy_pct": None if yoy is None else round(yoy * 100, 1),
                    "eps": None if pd.isna(r.get("eps_basic")) else float(r["eps_basic"])})
    return out


def peers(con, root, isin: str, asof: date, max_n: int = 12) -> dict:
    """Same-industry Nifty 500 names that have 8+ filed quarters in the store: P/E, margin and one-year revenue growth, ranked
    together with the company (1 = lowest P/E, highest margin, highest growth)."""
    from pflab.app import research
    from pflab.data import sector_map
    from pflab.fundamentals import pit
    from pflab.learner import templates as tp
    from pflab.quant import forecast as fc
    root = Path(root)
    lab = sector_map.sector_at(sector_map.load(root), [isin], asof, allow_later=False)
    industry = lab["industry"].iloc[0] if len(lab) else None
    if not industry:
        return {"industry": None, "rows": [], "note": "no industry label for it in the sector map"}
    m = tp.members(root)
    t = pd.Timestamp(asof)
    cand = m[(m["from_date"] <= t) & (m["to_date"] > t)]["isin"].tolist()
    labs = sector_map.sector_at(sector_map.load(root), cand, asof, allow_later=False)
    same = [i for i in labs.loc[labs["industry"] == industry, "isin"] if i != isin]
    names = dict(con.execute("SELECT isin, symbol FROM instruments WHERE symbol IS NOT NULL").fetchall())
    rows, with_data = [], 0
    for i in [isin] + same:
        scrip = fc.scrip_of(root, i, asof)
        if not scrip:
            continue
        q = pit.load(con, scrip)
        if len(q) < MIN_PEER_QUARTERS:
            continue
        r = pit.ratios(pit.last_quarters(q, scrip, asof))
        px = research.closes(con, root, i, asof, years=1).dropna()
        if px.empty:
            continue
        with_data += 1
        pe = pit.valuation_ratios(float(px.iloc[-1]), r.get("eps_ttm"))["pe_ttm"]
        g = r.get("revenue_ttm_yoy")
        rows.append({"symbol": names.get(i, i), "isin": i, "pe": None if pe is None else round(pe, 1),
                     "net_margin_pct": None if r.get("net_margin_ttm") is None else round(r["net_margin_ttm"] * 100, 1),
                     "revenue_growth_1y_pct": None if g is None else round(g * 100, 1), "self": i == isin})
    df = pd.DataFrame(rows)
    if df.empty:
        return {"industry": industry, "rows": [], "note": f"{len(same)} same-industry names; none has 8 filed quarters on record"}
    df["pe_rank"] = df["pe"].rank(method="min", ascending=True)
    df["margin_rank"] = df["net_margin_pct"].rank(method="min", ascending=False)
    df["growth_rank"] = df["revenue_growth_1y_pct"].rank(method="min", ascending=False)
    df = df.sort_values(["self", "pe"], ascending=[False, True]).head(max_n)
    rows = [{k: (None if pd.isna(v) else v) for k, v in r.items()} for r in df.to_dict("records")]
    return {"industry": industry, "rows": rows, "names_in_industry": len(same) + 1, "with_results_on_record": with_data,
            "note": "ranks among the names with results on record; one-year revenue growth (three-year needs 2022-2024 filings "
                    "that are not on record); a ratio of a price and a filed number, not a forecast"}


def documents(con, isin: str, asof: date, days: int = 400) -> List[dict]:
    """Concall, presentation and transcript filings in the graph, newest first, with their URLs."""
    from pflab.kg import graph as g
    df = g.timeline(con, f"company:{isin}", asof - timedelta(days=days), kinds=("filing",), limit=300)
    out = []
    for r in df.itertuples():
        title = r.title or ""
        if DOC_WORDS.search(title):
            out.append({"date": str(r.published_at)[:10], "title": title[:160], "url": getattr(r, "url", None)})
    return out[:10]


def kpi_sheet(pm_dir: Path, symbol: str) -> Optional[str]:
    """A Tijori file he dropped that names the company (in the file name), else None."""
    inbox = Path(pm_dir) / "inbox"
    if not inbox.exists():
        return None
    for p in inbox.rglob("*"):
        if p.is_file() and "tijori" in p.name.lower() and symbol.lower() in p.name.lower():
            return p.name
    return None


def facts(con, root, isin: str, symbol: str, asof: date, pm_dir: Optional[Path] = None, closes: Optional[pd.Series] = None) -> dict:
    from pflab.hq import context, stocks
    from pflab.quant import forecast as fc
    root = Path(root)
    out: dict = {"symbol": symbol, "asof": str(asof)}
    scrip = fc.scrip_of(root, isin, asof)
    out["results_12_quarters"] = quarters_table(con, root, scrip, asof) if scrip else []
    if not out["results_12_quarters"]:
        out["results_note"] = "no filed quarters on record for it"
    try:
        out["holders"] = {k: v for k, v in context.holders(con, root, isin, symbol, asof, 365).items() if k != "source"}
    except Exception as e:
        out["holders"] = f"not available ({type(e).__name__})"
    try:
        out["peers"] = peers(con, root, isin, asof)
    except Exception as e:
        out["peers"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    c = closes if closes is not None else stocks.closes(con, root, isin, asof)
    out["capm"] = stocks.capm_part(root, isin, asof)
    out["process"] = stocks.process_part(root, isin, c, asof)
    out["concall_and_presentations"] = documents(con, isin, asof)
    sheet = kpi_sheet(pm_dir, symbol) if pm_dir else None
    out["operating_kpis"] = (f"from your Tijori sheet {sheet} (read by the researcher beside the filings)" if sheet else
                             "not on record: stores, volumes, order book come from your Tijori sheet; drop one in Inbox and files and the researcher reads it")
    out["segment_revenue"] = "not on record: the results parser keeps totals only; segment tables are in the filing itself"
    out["source"] = ("BSE results (filed, point in time), BSE shareholding, NSE deals, BSE insider filings, the sector map, "
                     "the knowledge graph; descriptions, never signals")
    return out
