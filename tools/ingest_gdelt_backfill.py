"""Load the BigQuery GDELT daily aggregate into data/gdelt/agg/ (E2-C §4).

    python tools/ingest_gdelt_backfill.py [CSV]

CSV defaults to data/gdelt/backfill/gdelt_india_daily.csv, the result of
tools/gdelt_bigquery.sql. Writes data/gdelt/agg/YYYY-MM-DD.parquet in the
schema gdelt.aggregate() writes, for every day that has no file yet. Days the
live collector already wrote are NOT overwritten; they are compared instead,
and the comparison is printed (the live job can miss a fifteen-minute file
that BigQuery has, so its counts may be slightly lower, never higher).

Idempotent: re-running writes nothing new. Provenance (the CSV's SHA-256,
rows, range, days written) goes to data/gdelt/backfill/_ingest.json.
"""
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pflab.data import data_dir  # noqa: E402

COLS = ["n_events", "n_articles", "mean_tone", "mean_goldstein", "q1", "q2", "q3", "q4"]


def load_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = {"day", *COLS} - set(df.columns)
    if missing:
        raise ValueError(f"{path.name}: missing columns {sorted(missing)} -- "
                         "was it exported from tools/gdelt_bigquery.sql?")
    df["date"] = pd.to_datetime(df["day"].astype(str), format="%Y%m%d").dt.date
    if df["date"].duplicated().any():
        raise ValueError("duplicate days in the export")
    if (df[["q1", "q2", "q3", "q4"]].sum(axis=1) > df["n_events"]).any():
        raise ValueError("QuadClass counts exceed n_events: not this query's output")
    for c in ("n_events", "n_articles", "q1", "q2", "q3", "q4"):
        df[c] = df[c].astype("int64")
    return df[["date", *COLS]].sort_values("date").reset_index(drop=True)


def ingest(csv: Path, root: Path) -> dict:
    df = load_csv(csv)
    agg = root / "gdelt" / "agg"
    agg.mkdir(parents=True, exist_ok=True)
    written, compared = 0, []
    for row in df.itertuples(index=False):
        p = agg / f"{row.date.isoformat()}.parquet"
        one = pd.DataFrame([row._asdict()])
        if p.exists():
            live = pd.read_parquet(p).iloc[0]
            compared.append({"date": str(row.date), "live_events": int(live["n_events"]),
                             "bigquery_events": int(row.n_events)})
            continue
        one.to_parquet(p, index=False)
        written += 1
    out = {"csv": str(csv), "sha256": hashlib.sha256(csv.read_bytes()).hexdigest(),
           "rows": len(df), "first": str(df["date"].min()), "last": str(df["date"].max()),
           "written": written, "already_present": compared,
           "ingested_at": datetime.now().isoformat(timespec="seconds")}
    (csv.parent / "_ingest.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    root = data_dir()
    csv = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "gdelt" / "backfill" / "gdelt_india_daily.csv"
    r = ingest(csv, root)
    print(f"{r['rows']} days in export, {r['first']} .. {r['last']}; wrote {r['written']} new day files")
    for c in r["already_present"]:
        print(f"  {c['date']}: live collector {c['live_events']:,} events, BigQuery {c['bigquery_events']:,}")
