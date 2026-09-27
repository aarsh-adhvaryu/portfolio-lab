"""Reconcile the saved E1 regression CASH_CREDIT and SELL_DELIST rows against
local data (audit Deliverable 1 e/f). Read-only; never opens sealed results.

Usage: python tools/audit/reconcile_events.py [--json out.json]

For each CASH_CREDIT: the factor row that produced it, every NSE corporate-
action subject for that ISIN within +-20 days, and the dividend feed on the
date. For each SELL_DELIST: the last quote under the held ISIN, any later
quote under it (relisting), a successor ISIN for the same symbol in the
symbol map (remap), and the NSE subjects near the last quote (merger etc.).
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import timedelta

import duckdb
import pandas as pd

from pflab.data import data_dir, experiments_dir
from pflab.data import nse_corporate_actions as nca

RUNS = {"development": "development-64343858a094c09e",
        "validation": "validation-303190300ed98ced"}
DEMERGER = re.compile(r"demerg|scheme of arrangement|arrangement", re.I)
MERGER = re.compile(r"amalgam|merger|scheme", re.I)


def _subjects(raw, isin, symbols, lo, hi):
    m = (raw["isin"] == isin) | raw.symbol.isin(symbols)
    m &= (raw.ex_date >= lo) & (raw.ex_date <= hi)
    return [f"{r.ex_date} {r.symbol}: {r.subject}" for r in raw[m].itertuples()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()
    root = data_dir()
    c = duckdb.connect()
    prices = str(root / "panel" / "prices.parquet")
    smap = pd.read_parquet(root / "panel" / "symbol_isin_map.parquet")
    fac = pd.read_parquet(root / "corporate_actions" / "factors.parquet")
    fac["ex_date"] = pd.to_datetime(fac.ex_date).dt.date
    raw = nca.load_raw(root)[["isin", "symbol", "exDate", "subject"]].copy()
    raw["ex_date"] = pd.to_datetime(raw.exDate, format="%d-%b-%Y", errors="coerce").dt.date
    div = pd.read_parquet(root / "dividends" / "dividends.parquet") \
        if (root / "dividends" / "dividends.parquet").exists() else None
    out = {"cash_credit": [], "sell_delist": []}
    for period, run in RUNS.items():
        tr = pd.read_parquet(experiments_dir() / "E1" / "regression" / run
                             / "rows" / "base" / "trades.parquet")
        for r in tr[tr.side == "CASH_CREDIT"].itertuples():
            q = c.sql(f"select distinct symbol from '{prices}' where isin='{r.isin}'").fetchall()
            syms = [s[0] for s in q]
            f = fac[(fac["isin"] == r.isin) & (fac.ex_date == r.date)]
            subj = _subjects(raw, r.isin, syms, r.date - timedelta(20), r.date + timedelta(20))
            dv = None
            if div is not None and {"isin", "ex_date"} <= set(div.columns):
                dd = div[(div["isin"] == r.isin) & (pd.to_datetime(div.ex_date).dt.date == r.date)]
                dv = dd.to_dict("records") or None
            out["cash_credit"].append({
                "period": period, "date": str(r.date), "isin": r.isin, "symbols": syms,
                "qty": int(r.qty), "per_share": float(r.fill_price),
                "amount": float(r.qty * r.fill_price),
                "factor_rows": f.drop(columns="isin").astype(str).to_dict("records"),
                "nse_subjects": subj, "dividend_feed": dv,
                "demerger_named": any(DEMERGER.search(s) for s in subj)})
        for r in tr[tr.side == "SELL_DELIST"].itertuples():
            q = c.sql(f"""select min(date), max(date), count(*),
                          max(date) filter (where date <= '{r.date}'),
                          min(date) filter (where date > '{r.date}')
                          from '{prices}' where isin='{r.isin}'""").fetchone()
            syms = [s[0] for s in c.sql(
                f"select distinct symbol from '{prices}' where isin='{r.isin}'").fetchall()]
            if r.isin.startswith("NSESYM:"):
                syms = sorted(set(syms) | {r.isin.split(":", 1)[1]})
            last = q[3]
            succ = smap[smap.symbol.isin(syms) & (smap["isin"] != r.isin)]
            succ = succ[pd.to_datetime(succ.valid_from).dt.date >= last - timedelta(10)] \
                if last else succ
            succ_rows = []
            for s in succ.itertuples():
                n = c.sql(f"""select min(date), max(date), count(*) from '{prices}'
                              where isin='{s.isin}'""").fetchone()
                succ_rows.append({"symbol": s.symbol, "isin": s.isin,
                                  "valid_from": str(s.valid_from), "first_quote": str(n[0]),
                                  "last_quote": str(n[1]), "sessions": n[2]})
            subj = _subjects(raw, r.isin, syms, last - timedelta(120), last + timedelta(120)) \
                if last else []
            if q[4]:
                verdict = "relisted"
            elif succ_rows:
                verdict = "remap"
            elif any(MERGER.search(s) for s in subj):
                verdict = "merger"
            else:
                verdict = "dead_or_unresolved"
            out["sell_delist"].append({
                "period": period, "date": str(r.date), "isin": r.isin, "symbols": syms,
                "qty": int(r.qty), "stale_price": float(r.fill_price),
                "gross": float(r.qty * r.fill_price),
                "first_quote": str(q[0]), "last_quote_before": str(last),
                "next_quote_after": str(q[4]), "successors": succ_rows,
                "nse_subjects": subj, "verdict": verdict})
    txt = json.dumps(out, indent=1, default=str)
    if a.json:
        open(a.json, "w", encoding="utf-8").write(txt)
    print(txt)


if __name__ == "__main__":
    main()
