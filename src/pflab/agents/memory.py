"""The memory agent (PLAN A7, S43): The investor's decisions, the reasons he gave, outcomes and feedback, dated and kept.

Rows live in the PM store (`memory`, migration 17), never in git. A row is never edited: a changed decision is a
new row that `supersedes` the old one, which then gets `valid_to`, so "what did I decide, and when did it
change" can always be answered. Recall is plain filtering (subject, kind, words, time); the centre cites a
memory row as a source, so a recalled sentence is quoted, never paraphrased into new numbers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional, Sequence

KINDS = ("decision", "reason", "outcome", "feedback", "answer", "note", "state")      # state: the brain's own (S60)


@dataclass(frozen=True)
class Memory:
    mem_id: int
    created_at: datetime
    kind: str
    subject: Optional[str]
    text: str
    source: str
    valid_from: date
    valid_to: Optional[date]
    supersedes: Optional[int]

    def line(self) -> str:
        end = f" (until {self.valid_to})" if self.valid_to else ""
        return f"#{self.mem_id} {self.valid_from} {self.kind}{' [' + self.subject + ']' if self.subject else ''}: {self.text}{end}"


def remember(con, kind: str, text: str, *, subject: Optional[str] = None, source: str = "investor",
             valid_from: Optional[date] = None, supersedes: Optional[int] = None, now: Optional[datetime] = None) -> int:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if not text.strip():
        raise ValueError("nothing to remember")
    now = now or datetime.now()
    valid_from = valid_from or now.date()
    if supersedes is not None:
        old = con.execute("SELECT valid_to FROM memory WHERE mem_id=?", [supersedes]).fetchone()
        if old is None:
            raise LookupError(f"no memory #{supersedes}")
        if old[0] is not None:
            raise ValueError(f"memory #{supersedes} was already superseded on {old[0]}")
        con.execute("UPDATE memory SET valid_to=? WHERE mem_id=?", [valid_from, supersedes])
    from pflab.pm.store import next_id
    mid = next_id(con, "memory", "mem_id")
    con.execute("INSERT INTO memory VALUES (?,?,?,?,?,?,?,?,?)",
                [mid, now, kind, subject, text.strip(), source, valid_from, None, supersedes])
    return mid


def correct(con, mem_id: int, text: str, reason: str, *, by: str, now: Optional[datetime] = None) -> int:
    """S60: a memory row corrected: the old row is kept and ended, the new one supersedes it (same kind and subject),
    and the reason is kept as a `reason` row about the new one. Returns the new row's id."""
    old = con.execute("SELECT kind, subject FROM memory WHERE mem_id=?", [mem_id]).fetchone()
    if old is None:
        raise LookupError(f"no memory #{mem_id}")
    if not reason.strip():
        raise ValueError("a correction needs its reason")
    new = remember(con, old[0], text, subject=old[1], source=by, now=now, supersedes=mem_id)
    remember(con, "reason", f"#{new} corrects #{mem_id}: {reason.strip()}", subject=old[1], source=by, now=now)
    return new


def recall(con, *, subject: Optional[str] = None, kinds: Optional[Sequence[str]] = None, words: str = "",
           asof: Optional[date] = None, include_past: bool = False, limit: int = 20) -> List[Memory]:
    """Rows in force on `asof` (default today), newest first; `include_past` adds superseded ones. `words`: every
    word must appear in the text or subject (case-insensitive)."""
    asof = asof or date.today()
    sql, args = "SELECT * FROM memory WHERE valid_from <= ?", [asof]
    if not include_past:
        sql += " AND (valid_to IS NULL OR valid_to > ?)"
        args.append(asof)
    if subject:
        sql += " AND lower(subject) = lower(?)"
        args.append(subject)
    if kinds:
        sql += f" AND kind IN ({','.join('?' * len(kinds))})"
        args += list(kinds)
    rows = [Memory(*r) for r in con.execute(sql + " ORDER BY valid_from DESC, mem_id DESC", args).fetchall()]
    ws = [w for w in re.findall(r"\w+", words.lower()) if len(w) > 2]
    if ws:
        rows = [m for m in rows if all(w in (m.text + " " + (m.subject or "")).lower() for w in ws)]
    return rows[:limit]


def as_sources(mems: Sequence[Memory], start: int = 1) -> dict:
    """Memory rows as quotable sources for the centre: {"S1": "#12 2026-10-17 decision [mix]: ..."}."""
    return {f"S{start + k}": m.line() for k, m in enumerate(mems)}
