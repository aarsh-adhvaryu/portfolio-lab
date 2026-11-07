"""S79b item K: backfill the minute-bar history from Kite into PFLAB_DATA_DIR\\bars_1m\\<market>\\*.parquet (read only; resumable; idempotent).

    .venv\\Scripts\\python tools\\backfill_bars_1m.py --until 05:30 --log D:\\s79_scratch\\kite\\backfill.log
    .venv\\Scripts\\python tools\\backfill_bars_1m.py --status                 # counts only
    .venv\\Scripts\\python tools\\backfill_bars_1m.py --tiers index --max-names 3 --since 2026-01-01     # a sample

Tiers, in priority order: held (what the book holds, fetched from Kite at run time and never written down), index (Nifty 50, Bank, 500, the sectors ...),
nifty500 (the current constituents). Stop cleanly with `--until HH:MM` (today, or tomorrow when that time has passed), with a file named STOP next to the log, or when the
token is refused (the run then says 'kite logged out'). The log carries counts, never a holding's name, never a token.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from pflab.ingest import kite_backfill as kb


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--until", help="HH:MM: stop cleanly at this time")
    ap.add_argument("--log", default=r"D:\s79_scratch\kite\backfill.log")
    ap.add_argument("--root", help="default PFLAB_DATA_DIR\\bars_1m")
    ap.add_argument("--market", default="IN")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--tiers", default="held,index,nifty500")
    ap.add_argument("--since", help="YYYY-MM-DD: do not go back past this day (default: as far as the API returns)")
    ap.add_argument("--n500-since", help="YYYY-MM-DD: for the nifty500 tier only")
    ap.add_argument("--second-pass", action="store_true", help="after the first run, run the nifty500 tier again back to the API's limit (use with --n500-since for a shallow first pass)")
    ap.add_argument("--max-names", type=int, help="at most this many names per tier (a sample)")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else kb.default_root()
    if a.status:
        print(kb.coverage(root, a.market))
        return 0
    log_path = Path(a.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(log_path, "a", encoding="utf-8", buffering=1)

    def log(s: str) -> None:
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {s}" if not s[:2].isdigit() else s
        fh.write(line + "\n")
        print(line, flush=True)

    from pflab.ingest import kite as km
    from pflab.pm import secrets
    kc = km.client(secrets.load())
    if kc is None:
        log("kite logged out: no valid token (open the Portfolio Lab app and press Log in to Kite, or run tools\\kite_login.py)")
        return 2
    deadline = None
    if a.until:
        h, m = (int(x) for x in a.until.split(":"))
        deadline = datetime.combine(date.today(), time(h, m))
        if deadline <= datetime.now():
            deadline += timedelta(days=1)
    cfg = kb.RunConfig(root=root, market=a.market, workers=a.workers, tiers=tuple(a.tiers.split(",")))
    if a.max_names:
        cfg.max_names_by_tier = {t: a.max_names for t in cfg.tiers}
    if a.since:
        cfg.since_by_tier = {t: date.fromisoformat(a.since) for t in cfg.tiers}
    if a.n500_since:
        cfg.since_by_tier["nifty500"] = date.fromisoformat(a.n500_since)
    log(f"backfill start; root {root}; deadline {deadline}; tiers {a.tiers}")
    res = kb.run(kc, cfg, deadline=deadline, stop_file=log_path.parent / "STOP", log=log)
    log(f"backfill end: {res}")
    if a.second_pass and not res.get("stopped"):
        cfg2 = kb.RunConfig(root=root, market=a.market, workers=a.workers, tiers=("nifty500",))
        log("second pass: nifty500 back to the API's limit")
        res = kb.run(kc, cfg2, deadline=deadline, stop_file=log_path.parent / "STOP", log=log)
        log(f"second pass end: {res}")
    log(f"coverage: {kb.coverage(root, a.market)}")
    return 0 if not res.get("stopped") or res["stopped"] in ("StopRun",) else 1


if __name__ == "__main__":
    sys.exit(main())
