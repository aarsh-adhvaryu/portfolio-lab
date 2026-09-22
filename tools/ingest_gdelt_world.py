"""Load the GDELT world-by-country daily aggregate (tools/gdelt_world_bigquery.sql).

    python tools/ingest_gdelt_world.py

Reads every CSV in data/gdelt/world_backfill/, checks the columns and that no
(day, country) appears twice, and writes data/gdelt/world/daily_by_country.parquet
(date, country, n_events, n_articles, mean_tone, mean_goldstein, q1..q4) plus
a provenance file _ingest.json (each CSV's SHA-256). Rewrites the output whole;
re-running on the same CSVs gives the same file.
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


def ingest(src: Path, out: Path) -> dict:
    files = sorted(src.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"no CSV in {src}")
    frames = []
    for f in files:
        df = pd.read_csv(f, dtype={"country": str}, keep_default_na=False, na_values=[""])
        missing = {"day", "country", *COLS} - set(df.columns)
        if missing:
            raise ValueError(f"{f.name}: missing columns {sorted(missing)}")
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["day"].astype(str), format="%Y%m%d").dt.date
    if df.duplicated(["date", "country"]).any():
        raise ValueError("a (day, country) appears twice: overlapping CSVs in the folder?")
    df = df[["date", "country", *COLS]].sort_values(["date", "country"]).reset_index(drop=True)
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / "daily_by_country.parquet", index=False)
    info = {"files": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files},
            "rows": len(df), "days": int(df["date"].nunique()), "countries": int(df["country"].nunique()),
            "first": str(df["date"].min()), "last": str(df["date"].max()),
            "ingested_at": datetime.now().isoformat(timespec="seconds")}
    (out / "_ingest.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


if __name__ == "__main__":
    root = data_dir() / "gdelt"
    r = ingest(root / "world_backfill", root / "world")
    print(f"{r['rows']:,} rows: {r['days']} days x {r['countries']} countries, {r['first']} .. {r['last']}")
