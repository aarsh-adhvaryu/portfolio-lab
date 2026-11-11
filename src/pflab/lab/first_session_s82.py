"""The first REAL strategist session in the app (S82 C9): once-only, kept in the store (`strategist_first_s82`, key `first_session_s82`).

On the first app open after the S82 release the strategist's tick adds one reason, "the first strategist session in the app (S82)", so ONE session runs by itself (Opus through the doorbell,
inside A55 and the session cap `[strategist] session_rupees`; the kill switch, `[strategist] on` and his Rs 2,500 monthly cap still stop it). The trigger is IDEMPOTENT:

    done      a session ran (done, wasted or out of its budget): the trigger never fires again (a session that ran cost money; running it twice would double that)
    waiting   no session could start (no API key or no cloud client, the cap or the window's cap used up, a refused or failed first call): it is recorded with the reason and tried again at
              most once a day on the next opens, never failing the app. A session that failed AFTER spending money counts as a paid attempt; after `MAX_PAID_FAILURES` of them it stops.
It never changes his targets, limits or the stock list: the strategist only proposes, as always.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

KEY = "first_session_s82"
REASON = "the first strategist session in the app (S82): the weekly review of the allocation, with its note kept for the next one"
MAX_PAID_FAILURES = 2


def state(con) -> Optional[dict]:
    try:
        r = con.execute("SELECT status, attempts, paid_attempts, first_tried_at, last_tried_at, session_id, cost_inr, detail FROM strategist_first_s82 WHERE key=?", [KEY]).fetchone()
    except Exception:
        return None
    return dict(zip(("status", "attempts", "paid_attempts", "first_tried_at", "last_tried_at", "session_id", "cost_inr", "detail"), r)) if r else None


def reasons(con, now: datetime) -> list:
    """[REASON] while the first session is still to run (never done, tried less than once today, not given up), else []."""
    st = state(con)
    if st is None:
        return [REASON]
    if st["status"] == "done" or int(st["paid_attempts"] or 0) >= MAX_PAID_FAILURES:
        return []
    if st["last_tried_at"] is not None and st["last_tried_at"].date() >= now.date():           # one try a day: "waiting" is retried at a later open, not at every tick
        return []
    return [REASON]


def _write(con, now: datetime, status: str, detail: str, *, paid: bool = False, session_id: Optional[int] = None, cost: Optional[float] = None) -> None:
    st = state(con)
    if st is None:
        con.execute("INSERT INTO strategist_first_s82 (key, status, attempts, paid_attempts, first_tried_at, last_tried_at, session_id, cost_inr, detail) VALUES (?,?,?,?,?,?,?,?,?)",
                    [KEY, status, 1, 1 if paid else 0, now, now, session_id, cost, detail[:500]])
    else:
        con.execute("UPDATE strategist_first_s82 SET status=?, attempts=?, paid_attempts=?, last_tried_at=?, session_id=?, cost_inr=?, detail=? WHERE key=?",
                    [status, int(st["attempts"]) + 1, int(st["paid_attempts"]) + (1 if paid else 0), now, session_id if session_id is not None else st["session_id"],
                     cost if cost is not None else st["cost_inr"], detail[:500], KEY])


def room(con, now: datetime) -> dict:
    """{'ok', 'why'}: is there room in the paid cap for a session (the window's cap in an acceptance window, else the month's, less what is spent; the minimum session budget)."""
    try:
        from pflab import core
        from pflab.agents import analyst as an
        need = float(core.settings()["strategist"]["min_session_rupees"])
        cfg = an.config()
        acc = an.acceptance(cfg, now)
        if acc:
            cap, spent = float(acc["cap"]), an.window_spend(con, acc["since"])
        else:
            cap, spent = float(cfg["cap"]), an.month_spend_inr(con, now)
        if cap <= 0:
            return {"ok": False, "why": "no paid cap is set for this installation (api_budget.toml), so nothing is sent"}
        if cap - spent < need:
            return {"ok": False, "why": f"the paid cap is used up (about Rs {spent:,.0f} of Rs {cap:,.0f}; a session needs at least Rs {need:,.0f})"}
        return {"ok": True, "why": ""}
    except Exception as e:                                                                    # an unreadable budget file is not a reason to fail the app; the call itself is still governed
        return {"ok": True, "why": f"(cap not pre-checked: {type(e).__name__})"}


def waiting(con, now: datetime, why: str) -> None:
    """No session could start: recorded, tried again at a later open."""
    _write(con, now, "waiting", f"waiting: {why}")


def after_session(con, now: datetime, session: dict) -> str:
    """Record what `run_session` returned. -> the status written."""
    if not session or session.get("session_id") is None:
        _write(con, now, "waiting", "waiting: " + str((session or {}).get("skipped") or "the session did not start"))
        return "waiting"
    cost = float(session.get("cost_inr") or 0.0)
    if session.get("status") == "failed":
        paid = cost > 0
        _write(con, now, "waiting", "waiting: the session failed and will be tried again at a later open", paid=paid, session_id=session["session_id"], cost=cost)
        return "waiting"
    _write(con, now, "done", f"the first session ran: {session.get('status')}, {session.get('lab_runs', 0)} lab run(s), Rs {cost:,.2f}", session_id=session["session_id"], cost=cost)
    return "done"


def status_line(con) -> Optional[str]:
    st = state(con)
    if st is None:
        return None
    return f"first strategist session: {st['status']}" + (f" ({st['detail']})" if st["detail"] else "")
