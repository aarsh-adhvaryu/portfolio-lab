"""Questions the agents need the investor to answer (PLAN A7, S43): asked once per subject, kept until answered.

An agent never guesses a missing fact (an unrecorded trade, a transfer, a corporate action): it asks. Each
question has a `subject_key` so the same gap is asked once, however many times the check runs. An answer is
stored with the question and also as a memory row, so later agents see it.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from pflab.agents import memory


def ask(con, agent: str, subject_key: str, text: str, now: Optional[datetime] = None, *, default: Optional[str] = None,
        deadline: Optional[datetime] = None, urgent: bool = False, options: Optional[List[str]] = None) -> Optional[int]:
    """Queue a question; None if this subject was already asked (open or answered). S79: with a `default` the question carries it and a deadline
    (`agents/voice.py`): the system runs on the default until he answers, the question goes out on Telegram with reply buttons."""
    if con.execute("SELECT 1 FROM questions WHERE subject_key=?", [subject_key]).fetchone():
        return None
    from pflab.pm.store import next_id
    qid = next_id(con, "questions", "q_id")
    con.execute("INSERT INTO questions VALUES (?,?,?,?,?,?,?,?)",
                [qid, now or datetime.now(), agent, subject_key, text, "open", None, None])
    if default is not None:
        from pflab.agents import voice
        voice.attach(con, qid, text, default, deadline, urgent, options, now or datetime.now())
    return qid


def open_questions(con) -> List[Tuple[int, str, str]]:
    return con.execute("SELECT q_id, agent, text FROM questions WHERE status='open' ORDER BY q_id").fetchall()


def answer(con, q_id: int, text: str, now: Optional[datetime] = None) -> int:
    """Record the investor's answer; returns the memory row it became."""
    row = con.execute("SELECT status, agent, subject_key, text FROM questions WHERE q_id=?", [q_id]).fetchone()
    if row is None:
        raise LookupError(f"no question #{q_id}")
    if row[0] not in ("open", "defaulted"):             # S79: a question that ran on its default can still be answered by him
        raise ValueError(f"question #{q_id} is already {row[0]}")
    now = now or datetime.now()
    con.execute("UPDATE questions SET status='answered', answer=?, answered_at=? WHERE q_id=?", [text, now, q_id])
    try:
        from pflab.agents import voice
        voice.mark_answered(con, q_id, now)
    except Exception:                                    # the voice's own table must never block his answer
        pass
    try:                                                 # S85 (E5): the question's card in the chat shows the answer
        from pflab.entrance import cards
        cards.sync(con, q_id, now)
    except Exception:
        pass
    return memory.remember(con, "answer", f"Q: {row[3]} A: {text}", subject=row[2], source=f"question #{q_id} ({row[1]})",
                           now=now)


def close_with_evidence(con, subject_like: str, evidence: str, now: Optional[datetime] = None) -> int:
    """Close open questions whose subject matches `subject_like` because the system itself proved what they asked about (S70, A34): the evidence is
    kept as the question's answer. An answer by him is never what closes a warning of this kind. Returns how many were closed."""
    rows = con.execute("SELECT q_id FROM questions WHERE subject_key LIKE ? AND status='open'", [subject_like]).fetchall()
    for (q_id,) in rows:
        con.execute("UPDATE questions SET status='dropped', answer=?, answered_at=? WHERE q_id=?", [f"closed by evidence: {evidence}"[:900], now or datetime.now(), q_id])
    return len(rows)


def drop(con, subject_key: str, now: Optional[datetime] = None) -> bool:
    """Close an open question the agent no longer needs (the gap resolved itself, e.g. the tradebook arrived)."""
    r = con.execute("SELECT q_id FROM questions WHERE subject_key=? AND status='open'", [subject_key]).fetchone()
    if r:
        con.execute("UPDATE questions SET status='dropped', answered_at=? WHERE q_id=?", [now or datetime.now(), r[0]])
    return bool(r)
