"""S91: the automatic live check of a trading day (Monday 16 Nov is the first). Every 10 minutes between 09:20 and 16:00, with a Kite login, it checks what the morning must show and writes each check to
`live_checks_s91` (what, ok or not, the detail, the time): the running release, a complete and fresh holdings snapshot, the operator's availability, a NEW closed five-minute candle since the last
check (successive bars), no failed job in the last 30 minutes, and the day's saved study. Once a day it tells him the outcome in the chat (`livecheck:<day>`): at the first moment every check has
passed, or at 11:00 with what failed and why. Code only, 0 tokens. Historical replays and synthetic checks are never recorded here: a row is a live observation."""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import List, Optional

DDL = """CREATE TABLE IF NOT EXISTS live_checks_s91 (checked_at TIMESTAMP NOT NULL, day DATE NOT NULL, check_name VARCHAR NOT NULL, ok BOOLEAN, detail VARCHAR)"""
OPEN_AFTER = time(9, 20)
TELL_BY = time(11, 0)
FRESH_MIN = 12


def ensure(con) -> None:
    con.execute(DDL)


def checks(rt, con, now: datetime) -> List[tuple]:
    """[(name, ok, detail)] for this moment."""
    from pflab.app import investigation, s89
    from pflab.ingest import intraday5
    out: List[tuple] = []
    try:
        from pflab import release
        tag = ((release.load() or {}).get("app") or {}).get("tag")
        out.append(("running release", bool(tag), tag or "this is a workshop copy, not an installed release"))
    except Exception as e:
        out.append(("running release", False, f"{type(e).__name__}"))
    snap, m = s89._snap_at(con), s89._meta(con, "india_refresh")
    age = None if snap is None else (now - snap).total_seconds() / 60
    out.append(("complete holdings snapshot", bool(snap and age is not None and age <= FRESH_MIN and m and m[0] == "ok"),
                "no snapshot" if snap is None else f"{str(snap)[11:16]}, {age:.0f} min old, refresh {m[0] if m else 'unknown'}"))
    try:
        from pflab.llm import claude_plan as cp
        st = cp.state(con, now)                                      # probes the sign-in (cached for 10 minutes): a job, never a page load
        out.append(("operator available", bool(st["signed_in"]) and st["thinking"] != "paused", f"signed in {st['signed_in']}, thinking {st['thinking']}"))
    except Exception as e:
        out.append(("operator available", False, f"{type(e).__name__}"))
    prev = con.execute("SELECT detail FROM live_checks_s91 WHERE day=? AND check_name='new closed candle' ORDER BY checked_at DESC LIMIT 1", [now.date()]).fetchone()
    lc = intraday5.latest_closed_any(con, now)
    fresh_today = bool(lc and lc[:10] == str(now.date()))
    old = (prev[0] or "").split("|")[0] if prev else ""
    out.append(("new closed candle", fresh_today and (lc != old or not old), f"{lc}|previous {old or 'none'}"))
    bad = con.execute("SELECT count(*) FROM job_runs WHERE status='failed' AND started_at >= ?", [now - timedelta(minutes=30)]).fetchone()[0]
    out.append(("no failed job in 30 minutes", bad == 0, f"{bad} failed"))
    row = investigation.get(con, now.date())
    out.append(("saved study of the day", bool(row and row["status"] == "done"), (row or {}).get("subject") or ((row or {}).get("detail") or "not yet")))
    return out


def run(rt, con, now: datetime) -> dict:
    ensure(con)
    from pflab import markets
    from pflab.ingest import kite as km
    if not markets.get("IN").is_session(now.date()) or now.time() < OPEN_AFTER or now.time() >= time(16, 0):
        return {"skipped": "outside the session"}
    try:
        if km.TokenStore().load(now) is None:
            return {"skipped": "no Kite login yet: the live check starts with it"}
    except Exception:
        return {"skipped": "Kite token unreadable"}
    res = checks(rt, con, now)
    for name, ok, detail in res:
        con.execute("INSERT INTO live_checks_s91 VALUES (?,?,?,?,?)", [now, now.date(), name, bool(ok), str(detail)[:300]])
    passed = sum(1 for _, ok, _ in res if ok)
    out = {"passed": passed, "of": len(res), "failed": [n for n, ok, _ in res if not ok]}
    if not out["failed"] or now.time() >= TELL_BY:
        out["told"] = _tell(con, now, res, passed)
    return out


def _tell(con, now: datetime, res: List[tuple], passed: int) -> bool:
    try:
        from pflab.entrance import store
        lines = [f"{'ok ' if ok else 'NOT YET '}{name}: {detail.split('|')[0]}" for name, ok, detail in res]
        head = f"Live check, {now:%a %d %b %H:%M}: {passed} of {len(res)} passed." + ("" if passed == len(res) else " What is missing is stated below; it checks again every 10 minutes.")
        return store.post_system(con, now, head + "\n" + "\n".join(lines), kind="livecheck", key=f"livecheck:{now:%Y-%m-%d}", channels=("laptop",)) is not None
    except Exception:
        return False


def latest(con, day) -> Optional[dict]:
    """The newest full set of checks of the day (for the screens)."""
    ensure(con)
    t = con.execute("SELECT max(checked_at) FROM live_checks_s91 WHERE day=?", [day]).fetchone()[0]
    if t is None:
        return None
    rows = con.execute("SELECT check_name, ok, detail FROM live_checks_s91 WHERE checked_at=? ORDER BY check_name", [t]).fetchall()
    return {"at": str(t)[:16], "checks": [{"name": n, "ok": bool(o), "detail": d} for n, o, d in rows]}
