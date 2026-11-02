"""Is everything in step? The wake-up check (S53): market data, the ledger, the service, against the market's clock.

Each finding is one of
    ok      in step
    off     a job switched off on purpose (no Kite login today, the analyst not adopted): shown, never chased
    auto    behind, and a scheduled job fills it on its own (nothing for the investor to do)
    ask     only the investor can fix it (a file, a setting): it becomes a question (`agents.questions`) and a message
    warn    behind or broken, and no job fills it: shown in the fact sheet, the health page and `pflab conductor status`
Nothing here trusts a completion notice: dates come from the store's rows and the files' own date columns.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import List, Optional

from pflab.conductor.calendar import Calendar
from pflab.service import health, jobs

OFFLINE_AFTER = timedelta(hours=36)     # a longer gap since the last conductor pass means the system was off
STATEMENTS_EVERY = 35                   # days: the ledger is rebuilt from new statements about monthly
STATEMENTS_FROM_DAY = 3                 # last month's statements are asked for from this day of the month
KITE_ASK_FROM = time(8, 30)             # on a trading day, a missing Kite login is asked for from this time
GLOBAL_STALE = 7                        # days: foreign markets (not in the daily collection) count as behind after this


@dataclass(frozen=True)
class Finding:
    name: str
    status: str                         # ok | auto | ask | warn
    detail: str
    ask_key: Optional[str] = None       # `questions.subject_key` for an ask
    ask_text: Optional[str] = None


def last_pass(con, now: datetime) -> Optional[datetime]:
    """The last successful conductor pass before `now` (None on the first start)."""
    return con.execute("SELECT max(started_at) FROM job_runs WHERE job='conductor' AND status='ok' AND started_at < ?",
                       [now]).fetchone()[0]


def offline_gap(con, now: datetime) -> Optional[timedelta]:
    last = last_pass(con, now)
    return None if last is None else now - last


def _job_on(ctx: jobs.Ctx, name: str) -> bool:
    job = jobs.REGISTRY.get(name)
    if job is None:
        return False
    if job.enabled_fn is None:
        return True
    try:
        return bool(job.enabled_fn(ctx)[0])
    except Exception:
        return False


def _behind(cal: Calendar, last: date, expect: date) -> int:
    """Trading sessions after `last` up to `expect` (0 when in step)."""
    n, d = 0, last
    while d < expect:
        d += timedelta(days=1)
        n += cal.is_trading_day(d)
    return n


def _fresh(ctx, cal: Calendar, name: str, last: Optional[date], expect: date, job: Optional[str],
           slack: int = 0) -> Finding:
    if last is None:
        what = "no rows yet"
    else:
        b = _behind(cal, last, expect)
        if b <= slack:
            return Finding(f"data:{name}", "ok", f"to {last}")
        what = f"to {last}, expected {expect}: {b} session(s) behind"
    if job and _job_on(ctx, job):
        return Finding(f"data:{name}", "auto", f"{what}; the '{job}' job fills it")
    return Finding(f"data:{name}", "warn", f"{what}; no job fills it" + (f" ('{job}' is off)" if job else ""))


def _max_date_parquet(path: Path) -> Optional[date]:
    if not path.exists():
        return None
    from pflab import _duck
    try:
        v = _duck.sql(f"SELECT max(date) FROM read_parquet('{path.as_posix()}')").fetchone()[0]
    except Exception:
        return None
    return v.date() if isinstance(v, datetime) else v


def _newest_dated_file(folder: Path) -> Optional[date]:
    """The newest YYYY-MM-DD.parquet under `folder` (one level of year folders allowed)."""
    if not folder.exists():
        return None
    best = None
    for p in list(folder.glob("*.parquet")) + list(folder.glob("*/*.parquet")):
        try:
            d = date.fromisoformat(p.stem[:10])
        except ValueError:
            continue
        best = d if best is None or d > best else best
    return best


def _store_max(con, table: str) -> Optional[date]:
    try:
        return con.execute(f"SELECT max(date) FROM {table}").fetchone()[0]
    except Exception:
        return None


def data_findings(ctx: jobs.Ctx, cal: Calendar) -> List[Finding]:
    now, root, con = ctx.now, Path(ctx.data_root), ctx.con
    session = cal.last_closed_session(now)
    prev = cal.previous_trading_day(now.date())
    yesterday = now.date() - timedelta(days=1)
    out = [
        _fresh(ctx, cal, "NSE bhavcopy", _newest_dated_file(root / "bhavcopy"), session, "collect"),
        _fresh(ctx, cal, "prices (ledger)", _store_max(con, "prices"), session, "prices"),
        _fresh(ctx, cal, "India VIX", _max_date_parquet(root / "indices" / "INDIA_VIX.parquet"), session, "collect"),
        _fresh(ctx, cal, "Nifty 500 TRI", _max_date_parquet(root / "indices" / "NIFTY500_TRI.parquet"), session, "collect",
               slack=1),                                  # NSE posts index files a session late at times
        _fresh(ctx, cal, "fund NAVs", _store_max(con, "navs"), prev, "nav", slack=1),
        _fresh(ctx, cal, "gold rates", _store_max(con, "gold_rates"), prev, "nav", slack=1),
    ]
    # calendar-day sources: filings and news arrive on closed days too
    for name, folder, job in (("BSE filings", root / "bse_announcements", "filings"), ("GKG news", root / "gkg", "collect")):
        last = _newest_dated_file(folder)
        if last is not None and last >= yesterday:
            out.append(Finding(f"data:{name}", "ok", f"to {last}"))
        else:
            what = "no files yet" if last is None else f"to {last}, expected {yesterday}"
            st = "auto" if _job_on(ctx, job) else "warn"
            out.append(Finding(f"data:{name}", st, f"{what}; " + (f"the '{job}' job fills it" if st == "auto" else "no job fills it")))
    g = _max_date_parquet_glob(root / "global")
    age = None if g is None else (now.date() - g).days
    if age is not None and age <= GLOBAL_STALE:
        out.append(Finding("data:foreign markets", "ok", f"to {g}"))
    else:
        what = "no files yet" if g is None else f"to {g}, {age} days old"
        st = "auto" if _job_on(ctx, "global") else "warn"
        out.append(Finding("data:foreign markets", st, f"{what}; " + ("the 'global' job fills it" if st == "auto"
                                                                       else "no job fills it")))
    return out


def _max_date_parquet_glob(folder: Path) -> Optional[date]:
    if not folder.exists() or not any(folder.glob("*.parquet")):
        return None
    from pflab import _duck
    try:
        v = _duck.sql(f"SELECT max(date) FROM read_parquet('{(folder / '*.parquet').as_posix()}')").fetchone()[0]
    except Exception:
        return None
    return v.date() if isinstance(v, datetime) else v


def ledger_findings(ctx: jobs.Ctx) -> List[Finding]:
    """The ledger is rebuilt from the investor's statements (`tools/build_pm_ledger.py`); only he has them."""
    con, now = ctx.con, ctx.now
    from pflab.ledger import system
    if system.active(ctx.pm_dir):                            # S77: the ledger is the system's own account: nothing to ask him for
        return [Finding("ledger", "ok", "the system's own account (no statements are read)")]
    try:
        n, built = con.execute("SELECT count(*), max(ingested_at) FROM events").fetchone()
    except Exception:
        n, built = 0, None
    how = ("drop the new Zerodha Console tradebook, funds ledger and contract notes, the bank statements and the CAS "
           "in the dashboard's Inbox and files: each is checked by a dry-run rebuild and added when you press 'Add to "
           r"the ledger' (or list them in pm\sources.toml and run .venv\Scripts\python tools\build_pm_ledger.py)")
    if not n:
        return [Finding("ledger", "ask", "the ledger is empty", "conductor:ledger-empty",
                        "The ledger is empty, so nothing about your portfolio can be worked out. To build it, " + how)]
    age = (now - built).days
    month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev = month - timedelta(days=1)
    # S58b (The investor 2026-10-24): every month, once the banks have posted, last month's statements are asked for; between
    # them the portfolio is read from Kite each day
    if age > STATEMENTS_EVERY or (now.day >= STATEMENTS_FROM_DAY and built < month):
        return [Finding("ledger", "ask", f"last rebuilt {built:%d %b %Y} ({age} days ago); {prev:%B}'s statements not in",
                        f"conductor:statements:{now:%Y-%m}",
                        f"Time for {prev:%B %Y}'s statements (the ledger was last rebuilt on {built:%d %b %Y}): the Zerodha "
                        "Console funds statement and tradebook, the bank statements (first the bank Zerodha pays unused "
                        "funds to) and the CAS. Until they are in, holdings and cash are read from Kite each day and cash "
                        f"moved to the bank is an estimate. To add them, {how}")]
    return [Finding("ledger", "ok", f"rebuilt {built:%d %b %Y} ({age} days ago)")]


def service_findings(ctx: jobs.Ctx, cal: Calendar) -> List[Finding]:
    """Health items that are not data freshness (the calendar-aware checks above replace those)."""
    out: List[Finding] = []
    for it in health.check(ctx):
        if it.name in ("prices", "navs", "gold rates", "job:conductor", "job:backup"):
            continue                          # replaced by the calendar-aware checks; the backup is the ask below
        if it.name == "job:tradecheck" and it.detail.startswith("disabled:") and cal.is_trading_day(ctx.now.date()) \
                and ctx.now.time() >= KITE_ASK_FROM and not __import__("pflab.ledger.system", fromlist=["x"]).active():      # S58b; S78: in the system's own account Kite is only a data feed (the bar's button covers it)
            out.append(Finding("kite login", "ask", "no Kite login today", f"conductor:kite-login:{ctx.now.date()}",
                               "Log in to Kite for today (the button at the top of the dashboard, or "
                               r".venv\Scripts\python tools\kite_login.py): holdings, cash and today's trades are read "
                               "from Kite; without the login the portfolio is the one from your last statements."))
            continue
        if it.name.startswith("job:") and it.detail.startswith("disabled:"):
            out.append(Finding(it.name, "off", it.detail.removeprefix("disabled: ")))
            continue
        if it.name == "backup" and it.detail.startswith("off:"):   # his decision: shown, never chased
            out.append(Finding("backup", "off", it.detail.removeprefix("off: ")))
            continue
        if it.name == "backup" and it.status != "OK":
            out.append(Finding("backup", "ask", it.detail, "conductor:backup-target",
                               "The ledger has no backup. Pick a target (an external drive or a synced folder) and set "
                               r"PFLAB_BACKUP_DIR to it, or [backup] target in configs\service.toml; the nightly backup "
                               "then turns on by itself."))
            continue
        if it.name == "disk" and it.status != "OK":     # S58 drill 4: low space is asked about, not only listed
            out.append(Finding("disk", "ask", it.detail, f"conductor:disk-low:{ctx.now:%Y-%m}",
                               f"The drive with the ledger and the data is nearly full ({it.detail}). Downloads stop "
                               "below 3 GB free so the ledger is never written to a full disk. Free some space: the "
                               r"largest the system keeps are data\panel and data\kg\text (rebuildable) and "
                               r"pm\app\edge-profile (the dashboard window's cache)."))
            continue
        st = {"OK": "ok", "WARN": "warn", "FAIL": "warn"}[it.status]
        if it.name.startswith("job:") and it.status == "WARN" and it.detail.startswith(("due:", "never run")):
            st = "auto"                       # due now: the tick runs it
        out.append(Finding(it.name, st, it.detail))
    y = ctx.now.year
    if not cal.has_year(y):
        out.append(Finding("market holidays", "warn", f"no NSE holiday list for {y} in configs/market_holidays.toml: "
                                                      "weekdays are treated as trading days"))
    elif ctx.now.month == 12 and not cal.has_year(y + 1):
        out.append(Finding("market holidays", "warn", f"NSE's {y + 1} holiday list is not in configs/market_holidays.toml yet"))
    else:
        out.append(Finding("market holidays", "ok", f"list for {y}"))
    return out


def check(ctx: jobs.Ctx, cal: Calendar) -> List[Finding]:
    return data_findings(ctx, cal) + ledger_findings(ctx) + service_findings(ctx, cal)


def asks(findings: List[Finding]) -> List[Finding]:
    return [f for f in findings if f.status == "ask"]


def render(findings: List[Finding]) -> str:
    mark = {"ok": "ok  ", "off": "off ", "auto": "auto", "ask": "ASK ", "warn": "WARN"}
    return "\n".join(f"  [{mark[f.status]}] {f.name:<24} {f.detail}" for f in findings)
