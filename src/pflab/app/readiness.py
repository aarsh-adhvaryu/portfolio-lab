"""First-run readiness and known gaps (S67). Ready means what is RECONCILED and covered, not that jobs have run.

A stage is read from the stores each time it is asked, so it resumes by itself after a missing step is done (a password saved, Gmail
connected, Docker started) and never claims more than the data shows:

    record        the ledger has events, his accounts are approved, no statement waits for his press, no dropped file is still locked
    reconciled    Kite's holdings equal the ledger's (the latest check's breaks), with the date of that check
    mail          read-only Gmail: connected and its last run succeeded (statements and money emails flow)
    history       market history from HISTORY_START to the last session: sessions held against sessions expected (holes counted)
    tools         the local model, the sandbox and the API road are usable (system connectors)

`sync_gaps` keeps the open gaps in `known_gaps` (a key per gap, closed when resolved), so a gap is explicit, counted once and shown
the same on the screen, in the chat and to the brain. `backfill_step` fills market-history holes in bounded steps (a job, hourly): it
can be stopped at any point and picks up at the next hole.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

HISTORY_START = date(2012, 1, 1)
BACKFILL_BUDGET_S = 90
BACKFILL_SLEEP_S = 0.7
GAP_TRIES = 3                      # a message or a day that fails this many times stays a visible gap and is no longer retried by itself


# --- gaps: explicit, counted once, closed when resolved -------------------------------------------------------------------------------

def open_gap(con, key: str, source: str, detail: str, now: datetime) -> int:
    """Record (or update) an open gap; returns its attempts so far (a failure that keeps repeating is counted, then left visible)."""
    from pflab.pm.store import next_id
    r = con.execute("SELECT gap_id, attempts, status FROM known_gaps WHERE gap_key=?", [key]).fetchone()
    if r:
        n = int(r[1]) + (1 if r[2] == "open" else 0)
        con.execute("UPDATE known_gaps SET detail=?, status='open', closed_at=NULL, attempts=? WHERE gap_id=?", [detail[:400], n, r[0]])
        return n
    con.execute("INSERT INTO known_gaps VALUES (?,?,?,?,?,NULL,'open',1)", [next_id(con, "known_gaps", "gap_id"), key, source, detail[:400], now])
    return 1


def close_gap(con, key: str, now: datetime) -> bool:
    r = con.execute("SELECT gap_id FROM known_gaps WHERE gap_key=? AND status='open'", [key]).fetchone()
    if r:
        con.execute("UPDATE known_gaps SET status='closed', closed_at=? WHERE gap_id=?", [now, r[0]])
    return bool(r)


def gaps(con, source: Optional[str] = None) -> List[dict]:
    rows = con.execute("SELECT gap_key, source, detail, opened_at, attempts FROM known_gaps WHERE status='open' "
                       + ("AND source=? " if source else "") + "ORDER BY gap_id", [source] if source else []).fetchall()
    return [{"key": k, "source": s, "detail": d, "since": str(o)[:16], "attempts": a} for k, s, d, o, a in rows]


def give_up(con, key: str) -> bool:
    """True when a gap has failed GAP_TRIES times: the caller stops retrying it by itself (it stays listed)."""
    r = con.execute("SELECT attempts FROM known_gaps WHERE gap_key=? AND status='open'", [key]).fetchone()
    return bool(r and r[0] >= GAP_TRIES)


# --- market history: holes against the session calendar ----------------------------------------------------------------------------

def _sessions(root: Path, start: date, end: date) -> List[date]:
    """The sessions in [start, end]: the Nifty 50 index calendar when collected, else weekdays (an approximation, said where used)."""
    try:
        from pflab.data import indices
        days = set(indices.load("NIFTY50_PRICE")["date"])
        if days:
            return sorted(d for d in days if start <= d <= end)
    except Exception:
        pass
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def bhavcopy_holes(root: Path, start: date, end: date) -> Dict[str, object]:
    """Sessions with neither a parquet nor a logged holiday (a 404 is a holiday). {have, expected, holes: [dates], first, last}."""
    files = sorted((Path(root) / "bhavcopy").glob("*/*.parquet"))
    have = {p.stem for p in files}
    holiday = set()
    log = Path(root) / "bhavcopy" / "_log.jsonl"
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("status") == "no-file":
                holiday.add(str(r.get("date")))
    days = _sessions(Path(root), start, end)
    holes = [d for d in days if d.isoformat() not in have and d.isoformat() not in holiday]
    return {"have": len(have), "expected": len(days), "holes": holes, "first": files[0].stem if files else None,
            "last": files[-1].stem if files else None}


def backfill_step(root: Path, now: datetime, *, start: date = HISTORY_START, end: Optional[date] = None, budget_s: float = BACKFILL_BUDGET_S,
                  fetch: Optional[Callable] = None, sleep: float = BACKFILL_SLEEP_S, clock: Callable[[], float] = time.monotonic,
                  session=None) -> dict:
    """Fill market-history holes, newest first (recent history matters most), for at most `budget_s` seconds. Stopping at any point loses
    nothing: finished sessions are files, holidays are logged, and the next call starts at the next hole. `fetch(day, session, root)`
    is `bhavcopy.fetch_day` (tests pass a fake)."""
    from pflab.data import bhavcopy
    end = end or (now.date() - timedelta(days=1))
    before = bhavcopy_holes(root, start, end)
    holes = list(reversed(before["holes"]))
    if not holes:
        return {"fetched": 0, "left": 0, "errors": 0, "done": True}
    fetch = fetch or bhavcopy.fetch_day
    if session is None:
        import requests
        session = requests.Session()
        try:
            session.get("https://www.nseindia.com/", headers=bhavcopy.HEADERS, timeout=30)
        except Exception:
            pass
    t0, fetched, errors, last_error = clock(), 0, 0, None
    for d in holes:
        if clock() - t0 > budget_s:
            break
        try:
            fetched += 1 if fetch(d, session, Path(root)) else 0
        except Exception as e:                                   # one day failing never stops the rest; it stays a hole and is counted
            errors += 1
            last_error = f"{type(e).__name__}: {str(e)[:120]}"
            bhavcopy._log(Path(root), {"date": d, "error": repr(e)})
            if errors >= 5 and fetched == 0:                     # the source is down: stop instead of hammering it
                break
        if sleep:
            time.sleep(sleep)
    after = bhavcopy_holes(root, start, end)
    return {"fetched": fetched, "left": len(after["holes"]), "errors": errors, "last_error": last_error, "done": not after["holes"]}


# --- the stages ----------------------------------------------------------------------------------------------------------------------

DONE, PARTIAL, TODO, BLOCKED = "done", "partial", "todo", "blocked"


def _stage(key: str, title: str, state: str, detail: str, todo: Sequence[str] = ()) -> dict:
    return {"key": key, "title": title, "state": state, "detail": detail, "todo": list(todo)}


def _record(rt, now: datetime) -> dict:
    con = rt.cursor()
    n, last = con.execute("SELECT count(*), max(trade_date) FROM events").fetchone()
    if not n:
        return _stage("record", "Your record (ledger)", TODO, "the ledger is empty", ["Drop your statements in Inbox and files: the accounts are set up and the record is built from them by itself."])
    todo = []
    if not (rt.pm_dir / "sources.toml").exists():
        todo.append("The accounts are set up from your files at the next build (a minute after a statement arrives); change them in Setup if wrong.")
    waiting = con.execute("SELECT count(*) FROM inbox_items WHERE status IN ('awaiting setup', 'ready')").fetchone()[0]
    if waiting:
        todo.append(f"{waiting} statement(s) are being built into your record (by itself, within a few minutes).")
    for g in gaps(con, "ledger")[:4]:                      # what the built record does not yet match, each with its own detail
        todo.append(f"Difference with your files: {g['detail'][:160]}")
    locked = con.execute("SELECT count(*) FROM questions WHERE status='open' AND subject_key LIKE 'inbox:locked:%'").fetchone()[0]
    if locked:
        todo.append(f"{locked} dropped file(s) are password-protected: save the password in Settings > Keys, then drop them again.")
    state = DONE if not todo else PARTIAL
    return _stage("record", "Your record (ledger)", state, f"{n:,} events, the latest dated {last}", todo)


def _reconciled(rt, now: datetime) -> dict:
    """The latest SUCCESSFUL check of Kite against the ledger says how many holdings differ (its own count, not older runs' leftovers)."""
    con = rt.cursor()
    snap = con.execute("SELECT max(taken_at) FROM kite_snapshots").fetchone()[0]
    if snap is None:
        return _stage("reconciled", "Matches Kite", TODO, "Kite has not been read yet", ["Log in to Kite (the button, each trading morning); the system reads holdings, cash and trades."])
    last = con.execute("SELECT started_at, detail FROM job_runs WHERE job='tradecheck' AND status='ok' ORDER BY started_at DESC LIMIT 1").fetchone()
    d = json.loads(last[1]) if last and last[1] else {}
    breaks, pend = int(d.get("breaks", 0) or 0), int(d.get("pending", 0) or 0)
    todo = []
    if last is None:
        todo.append("No check of Kite against the ledger has succeeded yet.")
    elif last[0] < now - timedelta(days=3):
        todo.append(f"The last successful check against Kite was {str(last[0])[:10]}: older than three days.")
    if breaks:
        todo.append(f"{breaks} holding(s) differ between Kite and the ledger (see Needs from you).")
    if pend:
        todo.append(f"{pend} Kite trade(s) are not in the ledger yet: the Console tradebook or a contract note will bring them.")
    return _stage("reconciled", "Matches Kite", DONE if not todo else PARTIAL,
                  f"last successful check {str(last[0])[:16] if last else 'never'}; {breaks} break(s), {pend} trade(s) pending", todo)




def _holes_cached(rt, now: datetime) -> dict:
    """Counting session files and the calendar is not free (thousands of files); the screen asks every few seconds, so the answer is kept
    for five minutes and refreshed in the background (the same rule as the other slow probes)."""
    from pflab.app import system
    end = now.date() - timedelta(days=1)
    return system._cached(f"history:{rt.data_root}:{end}", 300, lambda: bhavcopy_holes(rt.data_root, HISTORY_START, end),
                          {"have": 0, "expected": 0, "holes": [], "first": None, "last": None, "pending": True})


def _history(rt, now: datetime) -> dict:
    h = _holes_cached(rt, now)
    if h.get("pending"):
        return _stage("history", "Market history", PARTIAL, "counting the sessions held…", [])
    if not h["have"]:
        return _stage("history", "Market history", TODO, "no market history yet", ["It fills itself in hourly steps; `tools/backfill_bhavcopy.py` does it faster (long run: yours)."])
    left = len(h["holes"])
    if not left:
        return _stage("history", "Market history", DONE, f"{h['have']:,} sessions, {h['first']} to {h['last']}, no holes", [])
    return _stage("history", "Market history", PARTIAL, f"{h['have']:,} of {h['expected']:,} sessions since {HISTORY_START}; {left:,} to fill (newest first, about 150 a step)",
                  [f"{left:,} session(s) are missing; the hourly backfill fills them, or run tools/backfill_bhavcopy.py."])


def _tools(rt, now: datetime) -> dict:
    from pflab.app import system
    cs = system.connectors(rt, now)
    bad = [c for c in cs if c["id"] in ("local", "sandbox", "api") and c["state"] in (system.WARN, system.DOWN)]
    return _stage("tools", "Models, sandbox and API", DONE if not bad else PARTIAL,
                  "; ".join(f"{c['name']}: {c['line']}" for c in bad)[:300] or "the local model, the sandbox and the API road are usable",
                  [c["line"] for c in bad][:3])


def assess(rt, now: Optional[datetime] = None) -> dict:
    now = now or rt.clock()
    stages = [_record(rt, now), _reconciled(rt, now), _history(rt, now), _tools(rt, now)]
    ready = all(s["state"] == DONE for s in stages)
    done = sum(1 for s in stages if s["state"] == DONE) + 0.5 * sum(1 for s in stages if s["state"] == PARTIAL)
    return {"ready": ready, "percent": round(100 * done / len(stages)), "stages": stages,
            "remaining": [t for s in stages for t in s["todo"]], "gaps": gaps(rt.cursor()),
            "say": "ready: the record matches Kite and the history is whole" if ready else
                   f"{sum(1 for s in stages if s['state'] != DONE)} of {len(stages)} parts are not complete yet"}


def sync_gaps(rt, now: Optional[datetime] = None) -> dict:
    """Write the stages' open items as known gaps and close the ones that are resolved. Code only; safe to repeat."""
    now = now or rt.clock()
    con = rt.cursor()
    a = assess(rt, now)
    live = set()
    for s in a["stages"]:
        if s["state"] != DONE:
            key = f"stage:{s['key']}"
            live.add(key)
            con.execute("DELETE FROM known_gaps WHERE gap_key=? AND status='closed'", [key])
            r = con.execute("SELECT 1 FROM known_gaps WHERE gap_key=?", [key]).fetchone()
            if r:
                con.execute("UPDATE known_gaps SET detail=? WHERE gap_key=?", [f"{s['title']}: {s['detail']}"[:400], key])
            else:
                open_gap(con, key, "readiness", f"{s['title']}: {s['detail']}", now)
    for g in gaps(con, "readiness"):
        if g["key"] not in live:
            close_gap(con, g["key"], now)
    return {"open": len(live), "ready": a["ready"]}
