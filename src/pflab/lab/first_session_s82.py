"""The first REAL strategist session in the app (S82 C9) and the first picks (S83 L8): once-only, kept in the store (`strategist_first_s82`, keys `first_session_s82` and `first_picks_s83`).

On the first app open after the S82 release the strategist's tick adds one reason, "the first strategist session in the app (S82)", so ONE session runs by itself (Opus through the doorbell,
inside A55 and the session cap `[strategist] session_rupees`; the kill switch, `[strategist] on` and his Rs 2,500 monthly cap still stop it). The trigger is IDEMPOTENT:

    done      a session ran (done, wasted or out of its budget): the trigger never fires again (a session that ran cost money; running it twice would double that)
    waiting   no session could start (no API key or no cloud client, the cap or the window's cap used up, a refused or failed first call): it is recorded with the reason and tried again at
              most once a day on the next opens, never failing the app. A session that failed AFTER spending money counts as a paid attempt; after `MAX_PAID_FAILURES` of them it stops.
It never changes his targets, limits or the stock list: the strategist only proposes, as always.

S83 L8 adds a second once-only reason, `REASON_PICKS` (key `first_picks_s83`, the same table): the first picks in both markets. Every session's brief has the picks step, so when both reasons are
still to run it is ONE session that serves both (the two keys move together); when the S82 session already ran, one session for the picks alone. If the session fails or the paid cap has no
room the book holds what it holds (his stocks, the core, SPY) and Today says "no picks yet: <reason>" (`picks_line`); never an error.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

KEY = "first_session_s82"
REASON = "the first strategist session in the app (S82): the weekly review of the allocation, with its note kept for the next one"
MAX_PAID_FAILURES = 2

KEY_PICKS = "first_picks_s83"
REASON_PICKS = ("the first picks (S83): make the first stock picks for the picks sleeve, in India (up to its share, beside his Kite stocks) and in the US (beside SPY): "
                "screen, read company cards, name stocks with a thesis, record the ones skipped")
# S84 F1: one picks session for India at the first open after the release made room for the system's own picks (his decision 2026-11-12); once-only like the others, and only after the
# share's new start was written (`pick_share.set_start_by_decision`), since before it there is no room to name a pick for.
KEY_PICKS_IN = "first_picks_in_s84"
REASON_PICKS_IN = ("the first Indian picks with room (S84): the India picks sleeve now has room for the system's own picks beside his Kite stocks (ordinary picks up to 10 points; 10 points are the "
                   "opportunity reserve, not for picks): screen India, read company cards, name stocks with a thesis, record the ones skipped")
KEYS = {REASON: KEY, REASON_PICKS: KEY_PICKS, REASON_PICKS_IN: KEY_PICKS_IN}


def state(con, key: str = KEY) -> Optional[dict]:
    try:
        r = con.execute("SELECT status, attempts, paid_attempts, first_tried_at, last_tried_at, session_id, cost_inr, detail FROM strategist_first_s82 WHERE key=?", [key]).fetchone()
    except Exception:
        return None
    return dict(zip(("status", "attempts", "paid_attempts", "first_tried_at", "last_tried_at", "session_id", "cost_inr", "detail"), r)) if r else None


def _pending(con, now: datetime, key: str) -> bool:
    st = state(con, key)
    if st is None:
        return True
    if st["status"] == "done" or int(st["paid_attempts"] or 0) >= MAX_PAID_FAILURES:
        return False
    if st["last_tried_at"] is not None and st["last_tried_at"].date() >= now.date():           # one try a day: "waiting" is retried at a later open, not at every tick
        return False
    return True


def reasons(con, now: datetime) -> list:
    """The once-only reasons still to run: REASON (the S82 first session) and REASON_PICKS (the S83 first picks), each while never done, tried less than once today and not given up.
    Both pending = both in the list, and the one session that follows serves both. S84 F1 adds REASON_PICKS_IN (key `first_picks_in_s84`), listed only once the India share's new start exists."""
    out = []
    for r, k in KEYS.items():
        if k == KEY_PICKS_IN:
            try:
                from pflab.core import pick_share
                if not pick_share.decision_done(con, "IN"):
                    continue                                                              # no room yet: the share's new start was not written (waiting for his Kite stocks to be held)
            except Exception:
                continue
        if _pending(con, now, k):
            out.append(r)
    return out


def keys_in(rs) -> list:
    """The state keys of the once-only reasons found in a session's reason list."""
    return [KEYS[r] for r in (rs or []) if r in KEYS]


def is_first(rs) -> bool:
    return bool(keys_in(rs))


def _write(con, now: datetime, status: str, detail: str, *, paid: bool = False, session_id: Optional[int] = None, cost: Optional[float] = None, keys=(KEY,)) -> None:
    for k in keys:
        _write_one(con, now, k, status, detail, paid=paid, session_id=session_id, cost=cost)


def _write_one(con, now: datetime, key: str, status: str, detail: str, *, paid: bool = False, session_id: Optional[int] = None, cost: Optional[float] = None) -> None:
    st = state(con, key)
    if st is None:
        con.execute("INSERT INTO strategist_first_s82 (key, status, attempts, paid_attempts, first_tried_at, last_tried_at, session_id, cost_inr, detail) VALUES (?,?,?,?,?,?,?,?,?)",
                    [key, status, 1, 1 if paid else 0, now, now, session_id, cost, detail[:500]])
    else:
        con.execute("UPDATE strategist_first_s82 SET status=?, attempts=?, paid_attempts=?, last_tried_at=?, session_id=?, cost_inr=?, detail=? WHERE key=?",
                    [status, int(st["attempts"]) + 1, int(st["paid_attempts"]) + (1 if paid else 0), now, session_id if session_id is not None else st["session_id"],
                     cost if cost is not None else st["cost_inr"], detail[:500], key])


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


def waiting(con, now: datetime, why: str, keys=(KEY,)) -> None:
    """No session could start: recorded, tried again at a later open."""
    _write(con, now, "waiting", f"waiting: {why}", keys=keys)


def after_session(con, now: datetime, session: dict, keys=(KEY,)) -> str:
    """Record what `run_session` returned. -> the status written (for every key asked for: the S82 first session and the S83 first picks move together)."""
    if not session or session.get("session_id") is None:
        _write(con, now, "waiting", "waiting: " + str((session or {}).get("skipped") or "the session did not start"), keys=keys)
        return "waiting"
    cost = float(session.get("cost_inr") or 0.0)
    if session.get("status") == "failed":
        paid = cost > 0
        _write(con, now, "waiting", "waiting: the session failed and will be tried again at a later open", paid=paid, session_id=session["session_id"], cost=cost, keys=keys)
        return "waiting"
    _write(con, now, "done", f"the first session ran: {session.get('status')}, {session.get('lab_runs', 0)} lab run(s), {session.get('picks', 0)} pick action(s), Rs {cost:,.2f}",
           session_id=session["session_id"], cost=cost, keys=keys)
    return "done"


def status_line(con) -> Optional[str]:
    st = state(con)
    if st is None:
        return None
    return f"first strategist session: {st['status']}" + (f" ({st['detail']})" if st["detail"] else "")


# --- S83 L8: what Today says while the book has no picks of its own ---------------------------------------------------------------------------------------------------

def system_picks(con) -> int:
    """How many picks the system itself has named so far (both markets, any state)."""
    try:
        return int(con.execute("SELECT count(*) FROM picks_s83 WHERE source='system'").fetchone()[0] or 0)
    except Exception:
        return 0


def picks_line(con) -> Optional[str]:
    """None once the system has named a pick; else one plain line, "no picks yet: <reason>" (the book holds what it holds: his stocks, the core and SPY)."""
    if system_picks(con) > 0:
        return None
    st = state(con, KEY_PICKS)
    held = "the book holds what it holds (his Kite stocks, the core and SPY)"
    if st is None:
        return f"no picks yet: the first picks session has not run (it runs at the first app open outside market hours); {held}"
    if st["status"] == "done":
        return f"no picks yet: the first picks session ran ({st['detail']}) and no pick was accepted by code; {held}"
    if int(st["paid_attempts"] or 0) >= MAX_PAID_FAILURES:
        return f"no picks yet: the first picks session failed {st['paid_attempts']} times and is not tried again by itself; {held}"
    return f"no picks yet: {st['detail'] or 'the first picks session is waiting'}; {held}"
