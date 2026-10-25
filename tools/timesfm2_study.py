"""S52 (docs/research/timesfm2_protocol.md): prepare the inputs, record the development choice that fine-tuning needs,
evaluate against the registered rules. Main venv. TimesFM itself runs in .venv-train (timesfm2_forecast.py,
timesfm2_finetune.py).

    .venv\\Scripts\\python tools\\timesfm2_study.py prepare [--only q1,q3,q5,q6]
    .venv\\Scripts\\python tools\\timesfm2_study.py dev-choice      # after the zero-shot Q1 forecasts, before fine-tuning
    .venv\\Scripts\\python tools\\timesfm2_study.py evaluate        # writes results.json; prints the decisions
    .venv\\Scripts\\python tools\\timesfm2_study.py describe        # after evaluate: describe.json (Nifty, 2020-21; no rule)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pflab.data import data_dir  # noqa: E402
from pflab.quant import tfm2 as tf  # noqa: E402
from pflab.quant import tfm2_eval as ev  # noqa: E402
from pflab.quant import tfm2_prep as pp  # noqa: E402


def folder() -> Path:
    return data_dir() / "research" / "timesfm2"


def save(name: str, arrays: dict) -> None:
    import numpy as np
    p = folder() / "inputs" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    np.savez(p, **arrays)


def prepare_markets(only) -> None:
    root = data_dir()
    vix = tf.market_frame(root / "global" / "US_VIX.parquet")
    for m in tf.MARKETS:
        df = tf.market_frame(root / "global" / f"{m}.parquet")
        if "q1" in only:
            a = pp.q1_arrays(df, vix, m in tf.VIX_SAME_DAY, tf.fold_of(m))
            save(f"q1_{m}.npz", a)
            print(f"q1 {m}: {len(a['dates'])} sessions, {len(a['idx'])} forecast dates", flush=True)
        if "q3" in only:
            a = pp.q3_arrays(df)
            save(f"q3_{m}.npz", a)
            print(f"q3 {m}: {len(a['idx'])} forecast dates", flush=True)
    if "q1" in only:                                   # the Nifty: described only; its own VIX, same close
        nf = tf.market_frame(root / "indices" / "NIFTY50_PRICE.parquet")
        iv = tf.market_frame(root / "indices" / "INDIA_VIX.parquet")
        save("q1_NIFTY50.npz", pp.q1_arrays(nf, iv, True, "-"))
        print("q1 NIFTY50 (described)", flush=True)


def prepare_q5() -> None:
    root = data_dir()
    mem = duckdb.sql(f"SELECT DISTINCT isin FROM read_parquet('{(root / 'index_membership' / 'NIFTY500.parquet').as_posix()}') "
                     "WHERE from_date <= DATE '2015-01-01' AND (to_date IS NULL OR to_date >= DATE '2015-01-01')").df()
    members = mem["isin"].tolist()
    isins = ",".join(f"'{i}'" for i in members)
    t0 = time.time()
    # NSE's bhavcopy carries ISINs only from mid-2011: earlier rows take theirs from the panel's date-ranged
    # symbol -> ISIN map (data.symbol_isin; never a join on symbol without a date, CLAUDE.md rule 4)
    bhav = (root / "bhavcopy").as_posix()
    mp = (root / "panel" / "symbol_isin_map.parquet").as_posix()
    tv = duckdb.sql(f"""
        WITH b AS (SELECT date, symbol, max(NULLIF(isin, '')) AS isin, sum(turnover) AS t
                   FROM read_parquet('{bhav}/*/*.parquet') WHERE series IN ('EQ', 'BE', 'BZ') GROUP BY 1, 2),
             j AS (SELECT b.date, b.symbol, coalesce(b.isin, min(m.isin)) AS isin, any_value(b.t) AS t
                   FROM b LEFT JOIN read_parquet('{mp}') m
                     ON b.isin IS NULL AND b.symbol = m.symbol AND b.date BETWEEN m.valid_from AND m.valid_to
                   GROUP BY b.date, b.symbol, b.isin)
        SELECT date, isin, sum(t) AS turnover FROM j WHERE isin IN ({isins}) GROUP BY 1, 2""").df()
    sessions = duckdb.sql(f"SELECT DISTINCT date FROM read_parquet('{(root / 'bhavcopy').as_posix()}/*/*.parquet')").df()
    wide = tv.pivot(index="date", columns="isin", values="turnover").reindex(sorted(sessions["date"]))
    wide.index = pd.to_datetime(wide.index).date
    picked = pp.q5_pick(wide, members)
    for isin in picked:
        save(f"q5_{isin}.npz", pp.q5_arrays(wide[isin]))
    print(f"q5: {len(picked)} stocks of {len(members)} members ({time.time() - t0:.0f} s)", flush=True)


def prepare_q6() -> None:
    from pflab.fundamentals import pit
    root = data_dir()
    quarters = {}
    for p in sorted((root / "bse_results").glob("*.parquet")):
        q = pit.load_history(p.stem, root)
        if len(q) >= pp.Q6_MIN_RUN + 1:
            quarters[p.stem] = q
    t = pp.q6_table(quarters)
    save("q6.npz", t)
    print(f"q6: {len(quarters)} companies, {int(t['forecastable'].sum())} forecastable quarters", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=["prepare", "dev-choice", "evaluate", "describe"])
    ap.add_argument("--only", default="q1,q3,q5,q6")
    a = ap.parse_args(argv)
    if a.step == "prepare":
        only = set(a.only.split(","))
        if only & {"q1", "q3"}:
            prepare_markets(only)
        if "q5" in only:
            prepare_q5()
        if "q6" in only:
            prepare_q6()
        print("PREPARE DONE", flush=True)
        return 0
    if a.step == "dev-choice":
        c = ev.q1_dev_choice(folder())
        (folder() / "choices.json").write_text(json.dumps(c, indent=1), encoding="utf-8")
        print("dev choice:", c, flush=True)
        return 0
    if a.step == "describe":
        res = json.loads((folder() / "results.json").read_text(encoding="utf-8"))
        d = ev.describe(folder(), res)
        (folder() / "describe.json").write_text(ev.to_json(d), encoding="utf-8")
        print(ev.to_json(d))
        return 0
    res = ev.evaluate_all(folder())
    (folder() / "results.json").write_text(ev.to_json(res), encoding="utf-8")
    print("Q1 adopt:", res["q1"].get("adopt"), "| Q2 adopt:", res["q2"].get("adopt"))
    for h, r in res.get("q3", {}).items():
        print(f"Q3 h={h}:", {c: r[c]["passes"] for c in ("T25", "T30") if c in r})
    if "q3b" in res:
        print("Q3b vol-aware Monte Carlo:", res["q3b"]["passes"])
    if res.get("q4"):
        print("Q4:", res["q4"].get(res["q4"].get("chosen_on_dev"), {}).get("passes"))
    if "q5" in res:
        print("Q5 adopt:", res["q5"].get("adopt"))
    if "q6" in res:
        print("Q6 adopt:", {k: v.get("adopt") for k, v in res["q6"].items()})
    print("EVALUATE DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
