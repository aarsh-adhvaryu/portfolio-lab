"""S86b (W1) the Problems list: every failed job, unhandled exception, failed self-check, engine fallback, blind spot, late alarm and refused data, with its FIRST and LAST time and its context,
deduplicated by (kind, key), in plain words, with a text that copies whole (`copy_text`). Code only, free.

    collect(con, now, days=7)      read the places problems are written and upsert them into `problems_s86` (idempotent: a second call adds nothing)
    listing(con, since=None)       the rows, newest last-seen first
    copy_text(con, since=None)     one plain text block to paste to Claude Code ("what went wrong this week")
    weekly_line(con, now)          the ONE line a week for Telegram (None when the week was clean)
`pflab problems [--days N]` prints the list; the settings page's button is the S87 redesign's (the API `GET /api/problems` already returns the same text).
Sources: `job_runs` (status failed, not "abandoned"), `session_log_s81` (kind degrade), `eyes_s86` (blind spots), `alarm_s86` (slow_cause), the gateway's engine problems, `think_steps_s84` (failed steps).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional


def _upsert(con, kind: str, key: str, text: str, context: str, first: datetime, last: datetime, times: int) -> None:
    r = con.execute("SELECT problem_id, first_seen, times FROM problems_s86 WHERE kind=? AND key=?", [kind, key]).fetchone()
    if r:
        con.execute("UPDATE problems_s86 SET first_seen=?, last_seen=?, times=?, text=?, context=? WHERE problem_id=?", [min(first, r[1]), last, max(times, 1), text[:300], context[:400], r[0]])
        return
    from pflab.pm.store import next_id
    pid = next_id(con, "problems_s86", "problem_id")
    con.execute("INSERT INTO problems_s86 VALUES (?,?,?,?,?,?,?,?,NULL)", [pid, kind, key, text[:300], context[:400], first, last, max(times, 1)])


def collect(con, now: datetime, days: int = 7) -> int:
    """Upsert what the last `days` days wrote. Returns the number of distinct problems seen. Never raises for one source's sake."""
    since = now - timedelta(days=days)
    n = 0

    def guard(fn):
        nonlocal n
        try:
            n += fn() or 0
        except Exception:
            pass

    def jobs():
        c = 0
        for job, first, last, times, detail in con.execute("SELECT job, min(started_at), max(started_at), count(*), max(detail) FROM job_runs WHERE status='failed' AND started_at >= ? "
                                                           "AND coalesce(detail,'') NOT LIKE 'abandoned:%' GROUP BY job", [since]).fetchall():
            _upsert(con, "job_failed", job, f"the job {job} failed {times} time(s)", str(detail or ""), first, last, times)
            c += 1
        return c

    def degrade():
        c = 0
        for what, first, last, times in con.execute("SELECT substr(what,1,120), min(ts), max(ts), count(*) FROM session_log_s81 WHERE kind='degrade' AND ts >= ? GROUP BY 1", [since]).fetchall():
            _upsert(con, "degraded", what, what, "session / thinking loop log", first, last, times)
            c += 1
        return c

    def blind():
        c = 0
        for source, label, since_, told in con.execute("SELECT source, label, blind_since, blind_told_at FROM eyes_s86 WHERE blind_since IS NOT NULL").fetchall():
            _upsert(con, "blind_spot", source, f"no answer from {label} since {since_:%a %d %b %H:%M}", "alarm lane eyes", since_, now, 1)
            c += 1
        return c

    def slow():
        c = 0
        for aid, sym, head, cause, at in con.execute("SELECT alarm_id, symbol, headline, slow_cause, first_seen_at FROM alarm_s86 WHERE first_seen_at >= ? AND slow_cause IS NOT NULL AND slow_cause <> ''", [since]).fetchall():
            _upsert(con, "late_alarm", str(aid), f"a serious headline on {sym} took more than 30 minutes: {cause}", str(head or "")[:200], at, at, 1)
            c += 1
        return c

    def engines():
        from pflab.llm import gateway
        c = 0
        for p in gateway.open_problems(con, days):
            _upsert(con, "engine", f"{p['engine']}:{p['role']}:{str(p['text'])[:60]}", str(p["text"]), f"engine {p['engine']}, role {p['role']}", p["ts"], p["ts"], 1)
            c += 1
        return c

    def steps():
        c = 0
        for what, first, last, times in con.execute("SELECT substr(payload_json,1,160), min(step_at), max(step_at), count(*) FROM think_steps_s84 WHERE step='failed' AND step_at >= ? GROUP BY 1", [since]).fetchall():
            _upsert(con, "thinking_failed", what, "a thinking step failed: " + what, "think/session.py", first, last, times)
            c += 1
        return c

    for fn in (jobs, degrade, blind, slow, engines, steps):
        guard(fn)
    return n


def listing(con, since: Optional[datetime] = None) -> List[dict]:
    cols = ("problem_id", "kind", "key", "text", "context", "first_seen", "last_seen", "times", "reported_at")
    q = "SELECT " + ", ".join(cols) + " FROM problems_s86" + (" WHERE last_seen >= ?" if since else "") + " ORDER BY last_seen DESC"
    return [dict(zip(cols, r)) for r in con.execute(q, [since] if since else []).fetchall()]


def copy_text(con, since: Optional[datetime] = None) -> str:
    rows = listing(con, since)
    if not rows:
        return "Problems: none."
    out = [f"Problems ({len(rows)}), newest first. Each: what, first and last time, how many times, where."]
    for r in rows:
        out.append(f"- [{r['kind']}] {r['text']} (first {r['first_seen']:%a %d %b %H:%M}, last {r['last_seen']:%a %d %b %H:%M}, {r['times']}x; {r['context'] or 'no context'})")
    return "\n".join(out)


def weekly_line(con, now: datetime) -> Optional[str]:
    """One line for Telegram: how many problems this week and the commonest kinds; None when clean or when this week's line was already sent."""
    collect(con, now, 7)
    rows = listing(con, now - timedelta(days=7))
    if not rows:
        return None
    kinds: dict = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    top = ", ".join(f"{k.replace('_', ' ')} {n}" for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])[:3])
    return f"Problems this week: {len(rows)} ({top}). Open the Problems list to copy them for Claude Code."
