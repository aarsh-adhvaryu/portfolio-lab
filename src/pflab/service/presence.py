"""App-open time (S79 item 3, A42): the laptop being off is normal, never an error. Open time is recorded as segments; a gap between two segments is "off from X to Y".
Silence, staleness and wake checks count OPEN time only (`open_time`), so a loop is not "silent" because the lid was shut.

    start(con, now, pid)   at app start: opens a segment, records the gap since the last beat (if longer than GAP)
    wake(con, now)         the PC slept: a new segment, the gap recorded
    beat(con, now)         the heart: moves the current segment's end
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Tuple

GAP = timedelta(minutes=5)
LIVE = timedelta(seconds=120)


def _open_segment(con, now: datetime, pid: Optional[int], reason: str) -> dict:
    from pflab.pm.store import next_id
    prev = con.execute("SELECT seg_id, last_beat FROM app_presence_s79 ORDER BY seg_id DESC LIMIT 1").fetchone()
    off_from = off_to = None
    if prev is not None and now - prev[1] > GAP:
        off_from, off_to = prev[1], now
    sid = next_id(con, "app_presence_s79", "seg_id")
    con.execute("INSERT INTO app_presence_s79 VALUES (?,?,?,?,?,?,?)", [sid, now, now, pid, reason, off_from, off_to])
    return {"seg_id": sid, "off_from": off_from, "off_to": off_to}


def start(con, now: datetime, pid: Optional[int] = None) -> dict:
    return _open_segment(con, now, pid, "start")


def wake(con, now: datetime, last_beat: Optional[datetime] = None, pid: Optional[int] = None) -> dict:
    """A sleep inside one process: the previous segment ended at its last beat (or `last_beat`), a new one begins now."""
    if last_beat is not None:
        con.execute("UPDATE app_presence_s79 SET last_beat=? WHERE seg_id=(SELECT max(seg_id) FROM app_presence_s79) AND last_beat < ?", [last_beat, last_beat])
    return _open_segment(con, now, pid, "wake")


def beat(con, now: datetime) -> None:
    con.execute("UPDATE app_presence_s79 SET last_beat=? WHERE seg_id=(SELECT max(seg_id) FROM app_presence_s79) AND last_beat < ?", [now, now])


def segments(con) -> List[Tuple[datetime, datetime]]:
    return [(a, b) for a, b in con.execute("SELECT opened_at, last_beat FROM app_presence_s79 ORDER BY seg_id").fetchall()]


def open_time(con, a: datetime, b: datetime) -> timedelta:
    """The time the app was open inside [a, b]. With no segments recorded at all (an old store, a test) it is the wall-clock span."""
    segs = segments(con)
    if not segs:
        return max(b - a, timedelta(0))
    last = len(segs) - 1
    total = timedelta(0)
    for i, (s, e) in enumerate(segs):
        if i == last and b - e <= LIVE:
            e = max(e, b)
        lo, hi = max(s, a), min(e, b)
        if hi > lo:
            total += hi - lo
    return total


def gaps(con, since: Optional[datetime] = None) -> List[Tuple[datetime, datetime]]:
    q = "SELECT off_from, off_to FROM app_presence_s79 WHERE off_from IS NOT NULL" + (" AND off_to >= ?" if since else "") + " ORDER BY seg_id"
    return [(a, b) for a, b in con.execute(q, [since] if since else []).fetchall()]


def describe(a: datetime, b: datetime) -> str:
    d = b - a
    span = f"{d.days} d {d.seconds // 3600} h" if d.days else f"{d.seconds // 3600} h {d.seconds % 3600 // 60} min"
    return f"off from {a:%a %d %b %H:%M} to {b:%a %d %b %H:%M} ({span})"
