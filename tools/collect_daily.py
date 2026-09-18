"""Daily collector job (Phase 1 task 1.7).

Idempotent: re-running for the same days re-uses whatever is already on disk
and makes no network call for it. Schedule once a day after 19:00 IST.

    python tools/collect_daily.py                 # last 3 days
    python tools/collect_daily.py --days 7
    python tools/collect_daily.py --sources bhavcopy,corporate_actions
    python tools/collect_daily.py --status        # what the last runs did

Sources are isolated: bhavcopy is on E1's critical path, while BSE and GDELT
are E2 and their endpoints are still unverified (tasks 1.5/1.6). A failure in
one never stops the others, and the exit code reflects only the critical ones,
so a Task Scheduler alert means something real.

Exit codes: 0 all critical sources fine; 1 a critical source failed;
2 another run holds the lock.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date, datetime, timedelta

from pflab._lock import FileLock, LockBusy
from pflab.data import data_dir

# name -> (callable(start, end, root), critical)
CRITICAL = {"bhavcopy", "corporate_actions"}


def _bhavcopy(start, end, root):
    from pflab.data import bhavcopy
    # Every day, not just weekdays: NSE trades some Saturdays and Sundays
    # (Budget days, Diwali Muhurat).
    return bhavcopy.collect(start, end, root)


def _corporate_actions(start, end, root):
    """Refresh the current year so new splits and bonuses reach the factors.

    Without this the panel silently misadjusts the moment a held name splits --
    the exact failure the section 15 change of 2026-09-16 was made to prevent.
    """
    from pflab.data import nse_corporate_actions as nca
    nca.collect(start.year, end.year, root, refresh=True)
    f = nca.factors(root)
    nca.write(f, root)
    return {"factors": len(f), "years": sorted({start.year, end.year})}


def _dividends(start, end, root):
    from pflab.data import dividends as dv
    d = dv.from_feed(root)
    dv.write(d, root)
    return {"rows": len(d)}


def _bse(start, end, root):
    from pflab.data import bse_announcements
    return bse_announcements.collect(start, end, root)


def _gdelt(start, end, root):
    from pflab.data import gdelt
    # GDELT publishes in arrears, so ask for yesterday and back.
    return gdelt.collect(start - timedelta(days=1), end - timedelta(days=1), root)


SOURCES = {
    "bhavcopy": _bhavcopy,
    "corporate_actions": _corporate_actions,
    "dividends": _dividends,
    "bse": _bse,
    "gdelt": _gdelt,
}


def _log(root, rec: dict) -> None:
    p = root / "_daily" / "collect_log.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def status(root, limit: int = 20) -> None:
    p = root / "_daily" / "collect_log.jsonl"
    if not p.exists():
        print("no daily runs recorded yet")
        return
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows[-limit:]:
        mark = "ok " if r.get("ok") else "FAIL"
        print(f"  {r['ts'][:19]}  {mark} {r['source']:18s} {r.get('result') or r.get('error','')}")
    bad = [r for r in rows if not r.get("ok")]
    print(f"\n{len(rows)} entries, {len(bad)} failures")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--sources", default=",".join(SOURCES))
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)

    root = data_dir()
    if a.status:
        status(root)
        return 0

    names = [s.strip() for s in a.sources.split(",") if s.strip()]
    unknown = set(names) - set(SOURCES)
    if unknown:
        print(f"unknown source(s): {sorted(unknown)}; known: {sorted(SOURCES)}")
        return 1

    end = date.today()
    start = end - timedelta(days=a.days)
    print(f"data dir: {root.resolve()}")
    print(f"window:   {start} .. {end}")

    failed_critical = []
    try:
        with FileLock(root / "_daily" / "collect.lock", "daily collector"):
            for name in names:
                t0 = datetime.now()
                try:
                    res = SOURCES[name](start, end, root)
                    ok, err = True, None
                    print(f"  {name:18s} ok   {res}", flush=True)
                except Exception as e:
                    ok, err, res = False, f"{type(e).__name__}: {e}", None
                    print(f"  {name:18s} FAIL {err}", flush=True)
                    if name in CRITICAL:
                        failed_critical.append(name)
                        traceback.print_exc()
                _log(root, {"ts": t0.isoformat(), "source": name, "ok": ok,
                            "window": [start, end], "result": res, "error": err,
                            "seconds": round((datetime.now() - t0).total_seconds(), 1)})
    except LockBusy as e:
        print(f"skipped: {e}")
        return 2

    if failed_critical:
        print(f"\nCRITICAL source(s) failed: {failed_critical}")
        return 1
    print("\nall requested sources completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
