"""Backfill the daily F&O files (futures and options rows, participant-wise open interest) and their derived tables.

    .venv\Scripts\python tools\backfill_fo.py --start 2024-01-01 [--end 2026-10-27]

Takes more than 5 minutes (one request a second or so per session, two files each); safe to stop and start again: sessions
already on disk are skipped. Holidays are reported as missing. Output: data\fo_daily, data\fo_participant, and
data\derived\fo_index.parquet / fo_buildup.parquet (the implied-volatility history needs 60 sessions before a percentile shows).
"""
import argparse
from datetime import date, timedelta

from pflab.data import data_dir, fo_daily
from pflab.quant import options


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", default=str(date.today()))
    a = ap.parse_args()
    root = data_dir()
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    d = start
    while d <= end:                                         # month by month so progress shows and a stop loses little
        stop = min(end, (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1))
        got = fo_daily.collect(d, stop, root)
        n = options.derive_missing(root)
        print(f"{d:%Y-%m}: new {got['ok']}, had {got['have']}, participants {got['participants']}, "
              f"missing {len(got['missing'])}, errors {len(got['error'])}, derived {n}", flush=True)
        d = stop + timedelta(days=1)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
