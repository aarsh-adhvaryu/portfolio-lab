"""A strategist session asked for in the chat (S81 B6): "look into X" replaces the lost background investigation.

The chat tool `ask_strategist` only WRITES a request here (cheap, at once, nothing paid). The strategist job reads the open requests as a reason for a session (`lab/strategist.due`),
runs it inside the session budget, marks the request with the session and its note, and tells the chat (`app/assistant.notify`) in the same thread. A session he asked for is
counted apart from the system's own in the autonomy check. Code only.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

PREFIX = "chat: "                      # the reason a requested session carries (`core.autonomy.HUMAN_REASONS` reads it)
MAX_OPEN = 3                           # open requests at once; more are refused with the reason
DUPLICATE_HOURS = 6                    # the same question inside this many hours is the same request


def _norm(t: str) -> str:
    return " ".join((t or "").lower().split())


def request(con, now: datetime, text: str, made_by: str = "chat") -> dict:
    from pflab.pm.store import next_id
    text = " ".join((text or "").split())
    if len(text) < 12:
        return {"ok": False, "problem": "say what to look into in a sentence (at least a few words)"}
    for rid, t, st in con.execute("SELECT req_id, text, status FROM strategist_requests_s81 WHERE made_at >= ? AND status IN ('open','running','done')",
                                  [now - timedelta(hours=DUPLICATE_HOURS)]).fetchall():
        if _norm(t) == _norm(text):
            return {"ok": True, "req_id": int(rid), "duplicate": True, "status": st, "note": "the same question is already with the strategist"}
    if con.execute("SELECT count(*) FROM strategist_requests_s81 WHERE status IN ('open','running')").fetchone()[0] >= MAX_OPEN:
        return {"ok": False, "problem": f"{MAX_OPEN} requests are already waiting for the strategist: ask again when one is done"}
    rid = next_id(con, "strategist_requests_s81", "req_id")
    con.execute("INSERT INTO strategist_requests_s81 (req_id, made_at, text, made_by, status) VALUES (?,?,?,?,'open')", [rid, now, text[:600], made_by])
    return {"ok": True, "req_id": rid, "status": "open", "note": "the strategist takes it at its next turn (inside its budget); its note will appear in this conversation"}


def open_requests(con) -> List[dict]:
    rows = con.execute("SELECT req_id, made_at, text FROM strategist_requests_s81 WHERE status='open' ORDER BY req_id").fetchall()
    return [{"req_id": int(r[0]), "made_at": r[1], "text": r[2]} for r in rows]


def reasons(con) -> List[str]:
    """For `strategist.due`: one reason per open request, in the form the autonomy check recognises as his."""
    return [f"{PREFIX}{r['text'][:200]}" for r in open_requests(con)]


def take(con, now: datetime, session_id: Optional[int] = None) -> List[int]:
    """Mark every open request as running under `session_id` (the session that read them)."""
    ids = [r["req_id"] for r in open_requests(con)]
    for i in ids:
        con.execute("UPDATE strategist_requests_s81 SET status='running', session_id=? WHERE req_id=?", [session_id, i])
    return ids


def finish(con, now: datetime, ids: List[int], status: str, note: str) -> None:
    """Close the requests a session took and tell the chat what came of it (a refused or wasted session says so)."""
    for i in ids:
        con.execute("UPDATE strategist_requests_s81 SET status=?, finished_at=?, note=? WHERE req_id=?", ["done" if status in ("done", "ok") else status, now, (note or "")[:800], i])
        row = con.execute("SELECT text FROM strategist_requests_s81 WHERE req_id=?", [i]).fetchone()
        try:
            from pflab.app import assistant
            body = (f"The strategist looked into: \"{row[0][:160]}\". " if row else "") + (note or "It ended without a note.")[:900]
            assistant.notify(con, now, body, f"strategist-request:{i}")
        except Exception:
            pass
