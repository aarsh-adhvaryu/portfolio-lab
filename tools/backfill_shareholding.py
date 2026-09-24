"""Backfill BSE quarterly shareholding patterns, 2010 onward.

    python tools/backfill_shareholding.py                       # one worker
    python tools/backfill_shareholding.py --shard 0 --of 3      # one of three
    python tools/backfill_shareholding.py --merge               # combine shards
    python tools/backfill_shareholding.py --check               # coverage report
    python tools/backfill_shareholding.py --limit 50            # a sample first

PARALLELISM
-----------
Workers are safe **only** as disjoint shards. `--shard i --of n` gives a
worker the scrips where `scrip_code % n == i`, so no two workers ever touch
the same scrip-quarter, and each writes its own `summary.shardN.parquet`,
`categories.shardN.parquet` and `_verified.shardN.txt`. Sharing one output
file would interleave read-modify-write and lose rows without any error.
Run `--merge` when they finish (safe to run while they run -- it only reads).

Three is the evidence-backed maximum: the BSE announcements backfill found
that **four parallel workers draw throttled answers and three do not**
(2026-09-22). Going past three is not a speed decision, it is a decision to
re-open a failure this repo has already paid for once.

Because a throttled shareholding answer can arrive as an EMPTY table --
indistinguishable from "this company filed nothing" -- an `unavailable`
whose reason throttling could fake is re-asked once before it is believed
(`bse_shareholding.needs_confirmation`). The stats report `rescued` (the
first answer was a throttle, the filing is real) and `unstable` (the two
answers disagreed; nothing written, retried next pass).

The universe is the scrips the price panel actually has, resolved through
data/bse_scrip_isin/map.parquet. Collecting all ~10,900 BSE scrips would add
a year of requests for securities no strategy can trade.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime

import pandas as pd

from pflab.data import bse_scrip_isin, bse_shareholding as sh, data_dir

MAX_SAFE_WORKERS = 3          # four throttle; see the module docstring


class ShardBusy(RuntimeError):
    """Another live process already owns this shard."""


def _lock(shard, of):
    """Refuse to start a second copy of a shard.

    On 2026-09-24 the three commands were run six times each: eighteen
    workers, six per shard. Duplicates on one shard share a parquet and a
    ledger, and `_flush` is read-modify-write, so one writer's rows were
    overwritten by another's while BOTH had already appended to the ledger.
    972 scrip-quarters ended up marked settled with nothing behind them,
    which the ledger would have made permanent. The ledger itself also went
    backwards under concurrent appends.

    Nothing in the output said so -- each worker printed healthy progress.
    So a shard now takes a lock naming its pid, and a second copy refuses.
    A stale lock from a killed worker is reclaimed automatically.
    """
    import os
    d = data_dir() / "bse_shareholding"
    d.mkdir(parents=True, exist_ok=True)
    p = d / (f"_lock.shard{shard}" if shard is not None else "_lock.single")
    if p.exists():
        try:
            old = int(p.read_text(encoding="utf-8").split()[0])
        except (ValueError, IndexError):
            old = None
        if old is not None and _pid_alive(old) and old != os.getpid():
            raise ShardBusy(
                f"shard {shard} is already being collected by pid {old}. "
                f"Running two workers on one shard loses rows silently "
                f"(2026-09-24). If that process is gone, delete {p}.")
    p.write_text(f"{os.getpid()} {datetime.now().isoformat()}\n", encoding="utf-8")
    return p


def _pid_alive(pid: int) -> bool:
    try:
        import subprocess
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True, timeout=20).stdout
        return str(pid) in out
    except Exception:
        return True          # cannot tell -> assume alive, and refuse to start


def universe(shard=None, of=None) -> list:
    m = bse_scrip_isin.panel_universe()
    codes = sorted(m["scrip_code"].unique().tolist())
    if shard is None:
        return codes
    return [c for c in codes if sh.shard_of(c, of) == shard]


def _progress(tag):
    def p(stats, scrip, qtrid):
        done = stats["ok"] + stats["unavailable"]
        print(f"[{datetime.now():%H:%M:%S}]{tag} at {scrip} q{qtrid} | "
              f"ok {stats['ok']:,} unavail {stats['unavailable']:,} "
              f"(adds-up {stats['adds_up_failed']:,}) "
              f"rescued {stats['rescued']} unstable {stats['unstable']} "
              f"err {stats['error']} skip {stats['skipped']:,} | settled {done:,}",
              flush=True)
    return p


def check() -> int:
    root = data_dir()
    d = root / "bse_shareholding"
    # read the shard files too, so a check made while workers run reports
    # live progress instead of whatever was last merged
    parts = [pd.read_parquet(f) for f in
             sorted(d.glob("summary.shard*.parquet")) + [d / "summary.parquet"]
             if f.exists()]
    if not parts:
        print("nothing collected yet")
        return 1
    df = (pd.concat(parts, ignore_index=True)
            .drop_duplicates(["scrip_code", "qtrid"], keep="last"))
    live = sorted(d.glob("_lock.shard*"))
    if live:
        print(f"{len(live)} worker(s) currently running "
              f"({', '.join(f.name.replace('_lock.', '') for f in live)}); "
              f"numbers below are a snapshot\n")
    df["year"] = pd.to_datetime(df["quarter_end"]).dt.year
    total = len(universe()) * (sh.QTRID_MAX - sh.QTRID_2010Q1 + 1)
    print(f"scrip-quarters recorded: {len(df):,} of {total:,} "
          f"({100 * len(df) / total:.1f}%)")
    print(f"  ok          {(df['status'] == 'ok').sum():,}")
    print(f"  unavailable {(df['status'] == 'unavailable').sum():,}")
    print(f"  scrips      {df['scrip_code'].nunique():,} of {len(universe()):,}")
    print()
    g = df.groupby("year").agg(
        rows=("status", "size"),
        ok=("status", lambda s: (s == "ok").sum()),
        scrips=("scrip_code", "nunique"),
        dated=("filing_date", lambda s: s.notna().sum()),
    )
    g["pct_ok"] = (100 * g["ok"] / g["rows"]).round(1)
    g["pct_dated"] = (100 * g["dated"] / g["rows"]).round(1)
    print(g.to_string())
    print()
    bad = df[(df["status"] == "unavailable") & df["reason"].notna()]
    addsup = bad[bad["reason"].apply(sh._is_adds_up)]
    if len(addsup):
        print("adds-up failures by year (a jump here is a finding):")
        print(addsup.groupby("year").size().to_string())
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="coverage report, no network")
    ap.add_argument("--merge", action="store_true", help="combine shard files")
    ap.add_argument("--shard", type=int, default=None, help="this worker's index")
    ap.add_argument("--of", type=int, default=None, help="total workers")
    ap.add_argument("--limit", type=int, default=None, help="first N scrips only")
    ap.add_argument("--from-qtr", type=int, default=sh.QTRID_2010Q1)
    ap.add_argument("--to-qtr", type=int, default=sh.QTRID_MAX)
    ap.add_argument("--sleep", type=float, default=0.35)
    a = ap.parse_args(argv)

    if a.check:
        return check()
    if a.merge:
        print(json.dumps(sh.merge_shards(), indent=2))
        return 0

    if (a.shard is None) != (a.of is None):
        ap.error("--shard and --of go together")
    if a.of is not None:
        if not (0 <= a.shard < a.of):
            ap.error(f"--shard must be in [0, {a.of})")
        if a.of > MAX_SAFE_WORKERS:
            print(f"WARNING: {a.of} workers. Four were shown to draw throttled "
                  f"answers on 2026-09-22; {MAX_SAFE_WORKERS} is the tested "
                  f"maximum. Confirmation-on-unavailable will catch a throttled "
                  f"empty, but an adds-up failure under load is not re-asked.",
                  flush=True)

    scrips = universe(a.shard, a.of)
    if a.limit:
        scrips = scrips[:a.limit]
    n_q = a.to_qtr - a.from_qtr + 1
    tag = "" if a.shard is None else f" [shard {a.shard}/{a.of}]"
    print(f"{tag or '[single]'} universe: {len(scrips):,} scrips x {n_q} quarters "
          f"= {len(scrips) * n_q:,} scrip-quarters")
    print(f"already settled (this shard + legacy): {len(sh.done_pairs(shard=a.shard)):,}",
          flush=True)
    try:
        lock = _lock(a.shard, a.of)
    except ShardBusy as e:
        print(f"REFUSED: {e}", flush=True)
        return 2
    t0 = time.time()
    try:
        stats = sh.collect(scrips, a.from_qtr, a.to_qtr, sleep=a.sleep,
                           progress=_progress(tag), shard=a.shard)
    finally:
        lock.unlink(missing_ok=True)
    stats["elapsed_s"] = round(time.time() - t0, 1)
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
