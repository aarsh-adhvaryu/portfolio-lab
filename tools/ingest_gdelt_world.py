"""Load the GDELT world aggregates exported from BigQuery.

    python tools/ingest_gdelt_world.py [world|types|bilateral]      (default world)

    kind       query                                 reads                              writes (data/gdelt/...)
    world      tools/gdelt_world_bigquery.sql        world_backfill/*.csv               world/daily_by_country.parquet
    types      tools/gdelt_world_types_bigquery.sql  world_types_backfill/*.csv         world/daily_event_types.parquet
    bilateral  tools/gdelt_bilateral_bigquery.sql    bilateral_backfill/*.csv           world/daily_bilateral.parquet

Checks the columns and that no key (day + country, or day + pair) appears
twice, and writes a provenance file beside the output (each CSV's SHA-256).
Rewrites the output whole; re-running on the same CSVs gives the same file.
Country codes are read as text, so Namibia's 'NA' is not a missing value.
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
KINDS = {
    "world": ("world_backfill", "daily_by_country", ["country"], COLS),
    "types": ("world_types_backfill", "daily_event_types", ["country"],
              [f"r{i:02d}" for i in range(1, 21)]),
    "bilateral": ("bilateral_backfill", "daily_bilateral", ["a1", "a2"],
                  COLS + ["sanctions_coerce", "violence"]),
}


def ingest(src: Path, out: Path, kind: str = "world") -> dict:
    _, name, keys, cols = KINDS[kind]
    files = sorted(src.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"no CSV in {src}")
    frames = []
    for f in files:
        df = pd.read_csv(f, dtype={k: str for k in keys}, keep_default_na=False, na_values=[""])
        missing = {"day", *keys, *cols} - set(df.columns)
        if missing:
            raise ValueError(f"{f.name}: missing columns {sorted(missing)}")
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["day"].astype(str), format="%Y%m%d").dt.date
    if df.duplicated(["date", *keys]).any():
        raise ValueError(f"a (day, {', '.join(keys)}) appears twice: overlapping CSVs in the folder?")
    df = df[["date", *keys, *cols]].sort_values(["date", *keys]).reset_index(drop=True)
    out.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out / f"{name}.parquet", index=False)
    info = {"kind": kind, "files": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files},
            "rows": len(df), "days": int(df["date"].nunique()),
            "keys": int(df[keys].drop_duplicates().shape[0]),
            "first": str(df["date"].min()), "last": str(df["date"].max()),
            "ingested_at": datetime.now().isoformat(timespec="seconds")}
    (out / f"_ingest_{name}.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


if __name__ == "__main__":
    kind = sys.argv[1] if len(sys.argv) > 1 else "world"
    root = data_dir() / "gdelt"
    r = ingest(root / KINDS[kind][0], root / "world", kind)
    what = "pairs" if kind == "bilateral" else "countries"
    print(f"{kind}: {r['rows']:,} rows: {r['days']} days x {r['keys']} {what}, {r['first']} .. {r['last']}")
