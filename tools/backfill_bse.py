"""BSE announcements backfill, month by month. Idempotent, resumable, verified.

Charter E2-A needs BSE announcements from 2010 (dissemination timestamp as
the key). This drives `pflab.data.bse_announcements.collect`, which writes a
day only when its rows match the API's own count (Table1.ROWCNT) and skips
any day whose file already exists. Re-running the SAME command resumes.

    python tools/backfill_bse.py START END LOGFILE [--no-verify]
    python tools/backfill_bse.py --check START END         (good/missing/blank)

Every pass re-checks days already on disk that are not yet in the verified
ledger (data/bse_announcements/_verified.txt) and re-fetches any that fail.
Days written by the count-checked collector go straight into the ledger, so
a resumed run only re-checks what is genuinely unconfirmed. The job ends when
nothing is missing and nothing is unverified. --no-verify skips the checks
(fetch missing days only); it should rarely be needed.

Run as TWO workers on disjoint ranges:

    2010-01-01 2019-12-31        2020-01-01 <yesterday>

Four workers (the first attempt, 2026-09-22) drew throttled answers within
the hour -- blank one-row days the first collector wrote as if they were
data. The collector now refuses those (IncompleteDay), and each pass after
the first waits 10, 20, 30... minutes so throttling is waited out.

Logs: data/_bse/progress_r{1,2}.jsonl, one JSONL line per month per pass.
"""
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pflab.data import bse_announcements as B  # noqa: E402
from pflab.data import data_dir  # noqa: E402


def _days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _path(d: date) -> Path:
    return data_dir() / "bse_announcements" / str(d.year) / f"{d.isoformat()}.parquet"


def check(start: date, end: date) -> None:
    """Good, missing, and present-but-BLANK days (an all-null row: a throttled
    answer written by the collector before 2026-09-22)."""
    import pandas as pd
    missing, blank = [], []
    done = B.verified_days()
    unver = 0
    for d in _days(start, end):
        f = _path(d)
        if not f.exists():
            missing.append(d.isoformat())
            continue
        df = pd.read_parquet(f, columns=["scrip_code"])
        if len(df) and df["scrip_code"].isna().any():
            blank.append(d.isoformat())
        elif d.isoformat() not in done:
            unver += 1
    total = (end - start).days + 1
    good = total - len(missing) - len(blank) - unver
    print(f"{good} of {total} days verified; {unver} present but not yet verified; "
          f"{len(missing)} missing; {len(blank)} blank"
          + (f"; first missing {missing[:3]}" if missing else "")
          + (f"; first blank {blank[:3]}" if blank else ""))


def _log(log: str, **kw) -> None:
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps({**kw, "ts": datetime.now().isoformat(timespec="seconds")}) + "\n")


def main(start: date, end: date, log: str, passes: int = 6, verify: bool = True) -> None:
    for n in range(1, passes + 1):
        m = date(start.year, start.month, 1)
        while m <= end:
            nxt = date(m.year + (m.month == 12), m.month % 12 + 1, 1)
            lo, hi = max(m, start), min(nxt - timedelta(days=1), end)
            t = time.time()
            try:
                stats = B.collect(lo, hi, sleep=0.8, verify=verify)
            except Exception as e:              # never die: log and move on
                stats = {"fatal": repr(e)}
            _log(log, **{"pass": n, "from": str(lo), "to": str(hi), **stats,
                         "seconds": round(time.time() - t)})
            m = nxt
        left, unver = _state(start, end)
        _log(log, **{"pass": n, "end_of_pass": True, "missing": left,
                     "unverified": unver if verify else None})
        if not left and (not verify or not unver):
            break
        time.sleep(600 * n)                     # 10, 20, 30 ... minutes
    left, unver = _state(start, end)
    _log(log, done=True, missing=left, unverified=unver)


def _state(start: date, end: date):
    """(missing days, present-but-unverified days). A day is verified once it
    is in the ledger -- written by the count-checked collector, or re-checked
    against the API's count. Every pass re-checks the unverified ones, so a
    throttled answer to a CHECK only delays it."""
    done = B.verified_days()
    missing = unver = 0
    for d in _days(start, end):
        if not _path(d).exists():
            missing += 1
        elif d.isoformat() not in done:
            unver += 1
    return missing, unver


if __name__ == "__main__":
    if sys.argv[1] == "--check":
        check(date.fromisoformat(sys.argv[2]), date.fromisoformat(sys.argv[3]))
    else:
        main(date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2]), sys.argv[3],
             verify="--no-verify" not in sys.argv[4:])
