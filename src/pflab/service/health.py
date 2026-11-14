"""Health of the always-on service in one structure: `pflab service status` and
the dashboard's health page (S30) all render this (PLAN S9).

Status per item is OK, WARN or FAIL; the overall status is the worst. Nothing here trusts a
completion notice: it reads the job table, the stores and the files on disk.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

from pflab.service import backup as bk
from pflab.service import jobs, telegram

ORDER = {"OK": 0, "WARN": 1, "FAIL": 2}


@dataclass(frozen=True)
class Item:
    name: str
    status: str
    detail: str


def _last_weekday(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def _open_since(con, since: datetime, now: datetime) -> timedelta:
    """How long the app was open between `since` and `now` (A42: the laptop being off is normal, so staleness counts app-open time only). Without a presence
    record (a test, an old store) it is the plain elapsed time, as before."""
    try:
        from pflab.service import presence
        if con.execute("SELECT count(*) FROM app_presence_s79").fetchone()[0]:
            return presence.open_time(con, since, now)
    except Exception:
        pass
    return now - since


def check(ctx: jobs.Ctx, backup_target: Optional[Path] = None) -> List[Item]:
    con, now = ctx.con, ctx.now
    items: List[Item] = []

    # jobs: a due job that is not running is stale; a failed last run is a failure
    for name, job in jobs.REGISTRY.items():
        if job.enabled_fn is not None:
            ok, why = job.enabled_fn(ctx)
            if not ok:
                items.append(Item(f"job:{name}", "WARN", f"disabled: {why}"))
                continue
        last = con.execute("SELECT status, started_at, detail FROM job_runs WHERE job=? ORDER BY run_id DESC LIMIT 1",
                           [name]).fetchone()
        due, why = jobs.is_due(ctx, job)
        if last is None:
            items.append(Item(f"job:{name}", "WARN", "never run"))
        elif last[0] == "failed":
            items.append(Item(f"job:{name}", "FAIL", f"last run failed at {last[1]:%d-%b %H:%M}: {str(last[2])[:160]}"))
        elif last[0] == "offline":                                   # S79b: no network is not a failure; the job tries again by itself
            items.append(Item(f"job:{name}", "WARN", f"offline at {last[1]:%d-%b %H:%M}; it tries again by itself"))
        elif due and _open_since(con, last[1], now) > timedelta(hours=26):
            items.append(Item(f"job:{name}", "FAIL", f"overdue: {why}; last run {last[1]:%d-%b %H:%M}"))
        elif due:
            items.append(Item(f"job:{name}", "WARN", f"due: {why}"))
        else:
            items.append(Item(f"job:{name}", "OK", f"last {last[0]} at {last[1]:%d-%b %H:%M}"))

    # data freshness
    expect = _last_weekday(now.date() - timedelta(days=1) if now.hour < 20 else now.date())
    px = con.execute("SELECT max(date) FROM prices").fetchone()[0]
    items.append(_fresh("prices", px, expect, max_age_days=3))
    nv = con.execute("SELECT max(date) FROM navs").fetchone()[0]
    items.append(_fresh("navs", nv, _last_weekday(now.date() - timedelta(days=1)), max_age_days=3))
    gd = con.execute("SELECT max(date) FROM gold_rates").fetchone()[0]
    items.append(_fresh("gold rates", gd, _last_weekday(now.date() - timedelta(days=1)), max_age_days=4))

    try:                                                                  # S86 (A76): the eyes, each source the system sees with, and how long each has been silent
        from pflab.think import alarm as _alarm
        for e in _alarm.eyes(con, now):
            old = e["age_min"] is None or e["age_min"] > 180
            items.append(Item(f"eyes:{e['source']}", "WARN" if e["blind_since"] else "OK" if not old else "WARN",
                              ("silent since %s" % e["blind_since"].strftime("%H:%M")) if e["blind_since"] else ("no answer yet" if e["last_ok"] is None else f"answered {e['age_min']:.0f} min ago")))
    except Exception:
        pass
    # telegram outbox
    n = telegram.undelivered(con)
    items.append(Item("telegram outbox", "OK" if n == 0 else "WARN", "nothing undelivered" if n == 0 else f"{n} undelivered message(s)"))
    if ctx.secrets is None or not (ctx.secrets.has("telegram", "token") and ctx.secrets.has("telegram", "chat_id")):
        items.append(Item("telegram config", "WARN", "token / chat_id not in the secrets file: nothing can be sent"))

    # backups
    tgt = backup_target if backup_target is not None else bk.target_dir()
    if tgt is None and backup_target is None and bk.declined():
        items.append(Item("backup", "OK", f"off: The investor's decision of {bk.declined()} (no target until he asks)"))
    elif tgt is None:
        items.append(Item("backup", "WARN", "no backup target set: the ledger has NO backup"))
    else:
        lt = bk.latest(tgt) if Path(tgt).exists() else None
        if lt is None:
            items.append(Item("backup", "FAIL", f"no backup found in {tgt}"))
        else:
            age = now - lt[1]
            items.append(Item("backup", "OK" if age < timedelta(hours=36) else "FAIL",
                              f"latest {lt[1]:%d-%b %H:%M} ({age.days}d {age.seconds // 3600}h old)"))

    # disk
    free_gb = shutil.disk_usage(ctx.pm_dir).free / 1e9 if Path(ctx.pm_dir).exists() else None
    if free_gb is not None:
        items.append(Item("disk", "OK" if free_gb > 5 else "WARN" if free_gb > 1 else "FAIL", f"{free_gb:,.1f} GB free"))
    try:                                                       # S87: the operator's sign-in (his plan) and whether thinking is paused
        from pflab.llm import claude_plan as cp, gateway as gw
        if gw.current_engine(con) == "claude_plan":
            st = cp.state(con, now)
            items.append(Item("operator", "OK" if st["signed_in"] and st["thinking"] == "running" else "WARN",
                              "signed in on his Claude plan; thinking running" if st["signed_in"] and st["thinking"] == "running" else
                              (f"thinking paused until {st['paused_until']}" if st["paused_until"] else f"not signed in on his plan: {st['detail']}")))
    except Exception as e:
        items.append(Item("operator", "WARN", f"could not read the sign-in ({type(e).__name__})"))
    return items


def _fresh(name: str, last: Optional[date], expect: date, max_age_days: int) -> Item:
    if last is None:
        return Item(name, "WARN", "no rows yet")
    behind = (expect - last).days
    if behind <= 0:
        return Item(name, "OK", f"to {last}")
    return Item(name, "WARN" if behind <= max_age_days else "FAIL", f"to {last}, expected {expect}: {behind} day(s) behind")


def overall(items: List[Item]) -> str:
    return max((i.status for i in items), key=lambda s: ORDER[s], default="OK")


def render(items: List[Item], now: datetime) -> str:
    lines = [f"Portfolio Manager health {now:%d-%b-%Y %H:%M}: {overall(items)}"]
    lines += [f"  [{i.status:<4}] {i.name:<18} {i.detail}" for i in items]
    return "\n".join(lines)
