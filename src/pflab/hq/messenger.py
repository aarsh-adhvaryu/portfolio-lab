"""The messenger (S59): what the investor must be told, delivered; his reminders kept and sent when due.

Delivery is the outbox's (`service.telegram`): a message is queued there first, so nothing is lost; when Telegram is
switched on in Settings it is also sent at once (the same way the bot sends its replies). Reminders are dated by fixed
rules on his words ("in 2 hours", "tomorrow at 9", "on 3 Nov at 4pm", "on monday"); words without a time are asked about.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

DEFAULT_HOUR = 9
_IN = re.compile(r"\bin\s+(\d+|an?|one|two|three)\s+(min(ute)?s?|hours?|hrs?|days?|weeks?)\b", re.I)
_AT = re.compile(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b|\bat\s+(\d{1,2})(?::(\d{2}))?\b", re.I)
_DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3}


def _clock(text: str) -> Optional[Tuple[int, int]]:
    m = _AT.search(text)
    if not m:
        return None
    if m.group(1):
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
        h = h % 12 + (12 if ap == "pm" else 0)
    else:
        h, mi = int(m.group(4)), int(m.group(5) or 0)
    return (h, mi) if 0 <= h < 24 and 0 <= mi < 60 else None


def when(text: str, now: datetime) -> Optional[datetime]:
    """The time a reminder is for, or None when the words do not say."""
    m = _IN.search(text)
    if m:
        n = _WORDS.get(m.group(1).lower()) or int(m.group(1))
        unit = m.group(2).lower()
        step = (timedelta(minutes=n) if unit.startswith("min") else timedelta(hours=n) if unit.startswith("h") else
                timedelta(weeks=n) if unit.startswith("w") else timedelta(days=n))
        return now + step
    hm = _clock(text)
    low = text.lower()
    day = None
    if "tomorrow" in low:
        day = now.date() + timedelta(days=1)
    elif "today" in low or "tonight" in low:
        day = now.date()
    else:
        for i, d in enumerate(_DAYS):
            if re.search(rf"\b(on\s+)?{d}\b", low):
                ahead = (i - now.weekday()) % 7 or 7
                day = now.date() + timedelta(days=ahead)
                break
    if day is None:
        m2 = re.search(r"\bon\s+(\d{1,2}\s+[a-z]{3,9}(?:\s+\d{4})?|[a-z]{3,9}\s+\d{1,2}(?:\s+\d{4})?|\d{4}-\d{2}-\d{2})\b", low)
        if m2:
            from dateutil import parser
            try:
                d = parser.parse(m2.group(1), default=datetime(now.year, now.month, now.day)).date()
            except (ValueError, OverflowError):
                d = None
            if d is not None:
                day = d if d >= now.date() else d.replace(year=d.year + 1)
    if day is None and hm is None:
        return None
    day = day or now.date()
    h, mi = hm or (DEFAULT_HOUR, 0)
    at = datetime(day.year, day.month, day.day, h, mi)
    if at <= now and hm is not None and "today" not in low and day == now.date():
        at += timedelta(days=1)                            # "at 9" said after 9: tomorrow's
    return at


def what(text: str) -> str:
    t = re.sub(r"^\s*/?\w*\s*", "", text) if text.strip().startswith("/") else text
    t = re.sub(r"\b(please\s+)?(remind me|reminder|don'?t let me forget|ping me|nudge me)\s*(to|about|that)?\s*", "", t,
               flags=re.I)
    return t.strip(" .") or text.strip()


def add(con, text: str, at: datetime, now: datetime, source: str = "investor") -> int:
    from pflab.pm.store import next_id
    rid = next_id(con, "hq_reminders", "rem_id")
    con.execute("INSERT INTO hq_reminders (rem_id, text, due_at, created_at, source) VALUES (?,?,?,?,?)",
                [rid, text[:500], at, now, source])
    return rid


def upcoming(con, limit: int = 20) -> List[tuple]:
    return con.execute("SELECT rem_id, text, due_at FROM hq_reminders WHERE sent_at IS NULL AND NOT cancelled "
                       "ORDER BY due_at LIMIT ?", [limit]).fetchall()


def send_now(rt, text: str, kind: str, dedup_key: Optional[str] = None) -> Optional[int]:
    """Queue in the outbox; with Telegram switched on, send it straight away too (the outbox job retries a failure)."""
    from pflab.service import telegram as tgm
    con = rt.cursor()
    now = rt.clock()
    mid = tgm.enqueue(con, text, kind, dedup_key=dedup_key, now=now)
    if mid is None or not tgm.goes_at_once(kind) or not rt.settings.get("telegram_send") or rt.secrets is None:
        return mid                                           # a held kind waits for the summary (S64)
    try:
        tgm.make_sender(rt.secrets)(text)
        con.execute("UPDATE outbox SET status='sent', sent_at=?, attempts=1 WHERE msg_id=?", [now, mid])
    except Exception as e:                                   # left queued: the outbox job delivers it later
        con.execute("UPDATE outbox SET attempts=1, last_error=? WHERE msg_id=?", [str(e)[:300], mid])
    return mid


def due(rt) -> int:
    """Send the reminders that are due (once each)."""
    con = rt.cursor()
    now = rt.clock()
    n = 0
    for rid, text, at in con.execute("SELECT rem_id, text, due_at FROM hq_reminders WHERE sent_at IS NULL AND NOT cancelled "
                                     "AND due_at <= ? ORDER BY due_at", [now]).fetchall():
        send_now(rt, f"Reminder: {text}", "reminder", dedup_key=f"reminder:{rid}")
        con.execute("UPDATE hq_reminders SET sent_at=? WHERE rem_id=?", [now, rid])
        n += 1
    if n:
        rt.bump("hq", "notifications")
    return n
