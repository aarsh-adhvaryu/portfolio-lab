"""Run the pre-registered split / limit study (docs/research/split_study_protocol.md) on the real panel.

    python tools/split_study.py            # writes data/research/split_study.json and prints the decision

The decision file is what the trader planner reads (`plan/trader.py`).
"""
from __future__ import annotations

import json
import sys
import time

import duckdb
import pandas as pd

from pflab.data import data_dir
from pflab.quant import execution_study as es

PERIODS = {"development": ("2010-01-01", "2017-12-31"), "validation": ("2018-01-01", "2021-12-31"),
           "spent": ("2022-01-01", "2025-12-31")}


def main() -> int:
    root = data_dir()
    t0 = time.time()
    mem = duckdb.sql(f"select isin, from_date, coalesce(to_date, DATE '2099-01-01') to_date "
                     f"from '{root}/index_membership/NIFTY500.parquet'").df()
    mem["from_date"], mem["to_date"] = pd.to_datetime(mem["from_date"]), pd.to_datetime(mem["to_date"])
    isins = sorted(set(mem["isin"]))
    out = {}
    for name, (a, b) in PERIODS.items():
        panel = duckdb.sql(f"select date, isin, open, low, close, adj_factor from '{root}/panel/prices.parquet' "
                           f"where date between DATE '{a}' - INTERVAL 10 DAY and DATE '{b}' + INTERVAL 15 DAY "
                           f"and isin in ({','.join(repr(i) for i in isins)})").df()
        panel["date"] = pd.to_datetime(panel["date"])
        months = pd.date_range(a, b, freq="MS")
        sv = es.savings(panel, mem, months)
        out[name] = es.summarise(sv)
        print(f"{name}: {len(sv):,} stock-months; " + "; ".join(f"{k} {v['mean_bps']:+.1f} bps (t {v['t']:.1f})"
                                                                for k, v in out[name].items()), flush=True)
    d = es.decide(out["development"], out["validation"])
    res = {"protocol": "docs/research/split_study_protocol.md", "periods": PERIODS, "results": out, "decision": d,
           "minutes": round((time.time() - t0) / 60, 1)}
    p = root / "research" / "split_study.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"decision: chosen on development {d['chosen_on_dev']}; adopted: {d['adopted'] or 'none (buy at once)'}; -> {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
