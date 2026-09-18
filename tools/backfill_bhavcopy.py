"""Resumable bhavcopy backfill.

Safe to kill (Ctrl-C) and re-run: finished sessions are skipped, cached raw
zips are re-normalised without touching the network, and a partially written
file from a hard kill is repaired before the run starts.

    python tools/backfill_bhavcopy.py                    # 2004-01-01 -> today
    python tools/backfill_bhavcopy.py --from 2012-01-01  # a slice
    python tools/backfill_bhavcopy.py --status           # coverage, no network
    python tools/backfill_bhavcopy.py --repair           # drop bad files only

Needs PFLAB_DATA_DIR set (see README).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta

import pandas as pd

from pflab.data import data_dir
from pflab.data.bhavcopy import collect

START = date(2004, 1, 1)


def _parquets(root):
    return sorted((root / "bhavcopy").glob("*/*.parquet"))


def repair(root) -> int:
    """Delete unreadable or empty parquets so the next run refetches them.

    A hard kill during to_parquet() leaves a file that exists but will not
    load; without this the collector would skip it forever.
    """
    bad = 0
    for p in _parquets(root):
        try:
            if len(pd.read_parquet(p)) == 0:
                raise ValueError("empty")
        except Exception as e:
            print(f"  repair: dropping {p.name} ({type(e).__name__})")
            p.unlink()
            bad += 1
    # A truncated zip is re-downloaded the same way.
    for z in sorted((root / "raw" / "bhavcopy").glob("*/*.zip")):
        if z.stat().st_size < 1024:
            print(f"  repair: dropping truncated {z.name}")
            z.unlink()
            bad += 1
    return bad


def _log_rows(root) -> list[dict]:
    log = root / "bhavcopy" / "_log.jsonl"
    if not log.exists():
        return []
    out = []
    for line in log.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _session_calendar(root, start: date, end: date):
    """The authoritative session list: the Nifty 50 price index, if collected.

    Falls back to weekdays. The fallback is only an approximation -- NSE trades
    on some Saturdays and Sundays (Budget days, Diwali Muhurat), and 27 such
    sessions were missed until the index calendar exposed them.
    """
    try:
        from pflab.data import indices
        days = set(indices.load("NIFTY50_PRICE")["date"])
        if days:
            return sorted(d for d in days if start <= d <= end), True
    except Exception:
        pass
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out, False


def holes(root, start: date, end: date) -> list[date]:
    """Sessions with neither a parquet nor a logged 404 holiday.

    A network drop logs an error and moves on, so the session is simply
    absent. Counting files alone hides that; this reconciles against the
    calendar so the hole is visible.
    """
    have = {p.stem for p in _parquets(root)}
    holiday = {r["date"] for r in _log_rows(root) if r.get("status") == "no-file"}
    days, _authoritative = _session_calendar(root, start, end)
    return [d for d in days
            if d.isoformat() not in have and d.isoformat() not in holiday]


def status(root) -> None:
    ps = _parquets(root)
    if not ps:
        print("no sessions collected yet")
        return
    by_year: dict[str, int] = {}
    for p in ps:
        by_year[p.parent.name] = by_year.get(p.parent.name, 0) + 1
    first, last = date.fromisoformat(ps[0].stem), date.fromisoformat(ps[-1].stem)
    print(f"{len(ps)} sessions, {first} .. {last}")

    gaps = holes(root, first, last)
    by_year_gap: dict[str, int] = {}
    for d in gaps:
        by_year_gap[str(d.year)] = by_year_gap.get(str(d.year), 0) + 1
    for y in sorted(by_year):
        n, g = by_year[y], by_year_gap.get(y, 0)
        print(f"  {y}: {n:3d}" + (f"   <-- {g} UNRESOLVED weekday(s)" if g else ""))

    rows = _log_rows(root)
    errs = [r for r in rows if "error" in r]
    throttled = [r for r in rows if 403 in (r.get("codes") or []) or r.get("status") == 403]
    print(f"log: {len(rows)} entries, {len(throttled)} throttled (403), {len(errs)} fetch errors")
    if gaps:
        print(f"\n{len(gaps)} unresolved weekday(s) -- re-run to fill:")
        for y in sorted(by_year_gap):
            ds = [d for d in gaps if str(d.year) == y]
            print(f"  {y}: {' '.join(d.isoformat()[5:] for d in ds[:15])}"
                  + (f" ... (+{len(ds) - 15})" if len(ds) > 15 else ""))
    else:
        print("\nno unresolved weekdays: every weekday is a session or a logged holiday")


class _Lock:
    """Refuse to run two backfills against one data dir.

    Two processes fetching the same archive concurrently get their
    connections reset by NSE, which surfaces as ConnectionError on days that
    are perfectly fine -- observed on 2015-12 during Phase 1. It also matters
    for task 1.7, where Task Scheduler can start a run while the last one is
    still going.
    """

    def __init__(self, root):
        self.path = root / "bhavcopy" / "_backfill.lock"

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            prev = self.path.read_text(encoding="utf-8").strip()
            if _alive(prev.split()[0] if prev else ""):
                raise SystemExit(
                    f"another backfill is running ({prev}).\n"
                    f"wait for it, or delete {self.path} if it is stale."
                )
            print(f"  clearing stale lock from {prev}")
        self.path.write_text(f"{os.getpid()} {datetime.now():%Y-%m-%d %H:%M:%S}",
                             encoding="utf-8")
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def _alive(pid: str) -> bool:
    if not pid.isdigit():
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=START.isoformat())
    ap.add_argument("--to", dest="end", default=date.today().isoformat())
    ap.add_argument("--status", action="store_true", help="report coverage and exit")
    ap.add_argument("--repair", action="store_true", help="drop bad files and exit")
    ap.add_argument("--sleep", type=float, default=0.7, help="seconds between requests")
    a = ap.parse_args(argv)

    root = data_dir()
    print(f"data dir: {root.resolve()}")
    if a.status:
        status(root)
        return 0
    if a.repair:
        print(f"repaired {repair(root)} file(s)")
        return 0

    print("checking for partially written files...")
    print(f"  repaired {repair(root)} file(s)")

    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    # One calendar year at a time, so an interrupted run loses at most a year
    # of progress and the per-year totals are visible as it goes.
    with _Lock(root):
        y = start.year
        while y <= end.year:
            lo = max(start, date(y, 1, 1))
            hi = min(end, date(y, 12, 31))
            done = len(list((root / "bhavcopy" / str(y)).glob("*.parquet"))) \
                if (root / "bhavcopy" / str(y)).exists() else 0
            print(f"{y}: {lo} -> {hi} ({done} already on disk)", flush=True)
            try:
                print(f"  {collect(lo, hi, root, sleep=a.sleep)}", flush=True)
            except KeyboardInterrupt:
                print("\ninterrupted; re-run the same command to resume")
                return 130
            y += 1

    print()
    status(root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
