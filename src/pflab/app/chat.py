"""The AI centre's chats (S54b; the entrance since S85): what is left here is the old surface the rest of the app calls. The conversation itself, one for the laptop and Telegram, lives in
`entrance/store.py`, and a question is taken by the intake (`entrance/intake.py`), never by a thread started here.

    create / listing / messages / delete / _add / _finish   the old helpers, now on the shared store (messages carry their channel, model and price)
    post          a question into a chat -> `intake.submit` (a mode is only validated: the old ask / web / deep / calc roads are the tools the model picks)
    answer        the board agent's synchronous road (hq/roster: ask, web, deep, calc), unchanged; it does not run on the chat's intake
    tidy          chats untouched for TIDY_DAYS are summarised into the system's memory and removed
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional

MODES = ("auto", "ask", "web", "deep", "calc")       # kept so old callers still pass a mode; since S85 the model chooses its tools itself (the mode buttons are gone)
TIDY_DAYS = 30


def create(con, now: datetime, title: str = "New chat") -> int:
    from pflab.entrance import store
    return store._make(con, now, title, "laptop")


def listing(con) -> List[dict]:
    from pflab.entrance import store
    return store.chats(con)


def messages(con, chat_id: int) -> List[dict]:
    from pflab.entrance import store
    return store.messages(con, chat_id)


def delete(con, chat_id: int) -> None:
    from pflab.pm.store import transaction
    with transaction(con):
        con.execute("DELETE FROM chat_messages WHERE chat_id=?", [chat_id])
        con.execute("DELETE FROM chat_attachments_s85 WHERE chat_id=?", [chat_id])
        con.execute("DELETE FROM chats WHERE chat_id=?", [chat_id])


def _add(con, chat_id: int, role: str, mode: str, text: str, status: str, now: datetime) -> int:
    from pflab.entrance import store
    return store.add_message(con, chat_id, role, text, status=status, now=now, mode=mode)


def _finish(con, mid: int, text: str, route: List[str], meta: str, now: datetime, status: str = "done",
            report: Optional[str] = None, cost: Optional[float] = None) -> None:
    from pflab.entrance import store
    store.update_message(con, mid, now, text=text, status=status, route=route, meta=meta, report_doc=report, cost_inr=cost, finish=True)


def post(rt, chat_id: int, text: str, mode: str, approved: bool = False) -> dict:
    """The old entry (S54b): a question into a chat. Since S85 it is the intake's: the message and a pending answer are in the chat at once and a worker answers on the model the router picks
    (`mode` is only checked; the old ask / web / deep / calc roads are the tools Auto picks). -> {"chat_id", "msg_id" (the pending answer)}."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    q = text.strip()
    if not q:
        raise ValueError("empty message")
    from pflab.entrance import intake
    out = intake.submit(rt, "laptop", q, chat_id=chat_id or None)
    return {"chat_id": out["chat_id"], "msg_id": out["msg_id"]}


HISTORY_TURNS, HISTORY_CHARS = 6, 220


def history_text(con, chat_id: int, before_msg: int, turns: int = HISTORY_TURNS) -> str:
    """The last few finished turns of this chat before message `before_msg`, short, oldest first: what a follow-up refers to (S67: the
    same history reaches the ask centre and the brain, which are otherwise two roads). A pending or failed answer is not history."""
    rows = con.execute("SELECT role, text FROM chat_messages WHERE chat_id=? AND msg_id < ? AND status='done' ORDER BY msg_id DESC LIMIT ?",
                       [chat_id, before_msg, turns]).fetchall()
    return "\n".join(f"{'he asked' if r == 'me' else 'you answered'}: {' '.join((t or '').split())[:HISTORY_CHARS]}" for r, t in reversed(rows))


def answer(rt, con, q: str, mode: str, approved: bool = False, history: str = "") -> dict:
    """One answer. The runtime is bound for the system tools of the ask centre; `history` is the earlier turns of the chat (both the
    ask centre and the brain read it). Works the same for the dashboard's Runtime and the background Desk (Telegram, the tick)."""
    from pflab.agents import tools as at
    tok = at.bind(rt)
    try:
        return _answer(rt, con, q, mode, approved, history)
    finally:
        at.unbind(tok)


def _hist(history: str) -> dict:
    return {"history": history} if history else {}


def _answer(rt, con, q: str, mode: str, approved: bool, history: str) -> dict:
    now = rt.clock()
    asof = now.date()
    if mode == "auto":                                   # S56: the escalation chain decides the road
        from pflab.agents import escalate
        from pflab.hq import service
        r = escalate.run(con, q, asof, pm_dir=rt.pm_dir, root=rt.data_root, secrets=rt.secrets, approved=approved, now=now,
                         fns={"brain": lambda text: service.brain_now(rt, text, rival=False, history=history),
                              "local": lambda c, text, a: __import__("pflab.agents.centre", fromlist=["ask"]).ask(c, text, a, **_hist(history))})
        return {"text": r.text, "route": escalate.route(r), "status": r.status, "report": r.report, "cost": r.cost or None,
                "meta": f"{r.kind} question · " + " → ".join(s.why for s in r.steps)}
    if mode == "ask":
        from pflab.agents import centre
        a = centre.ask(con, q, asof, **_hist(history))
        route = [f"routing ({a.router}, local)"] + [f"tool: {t}" for t in a.tools] + \
                (["local model, checked by the guard"] if a.verified else ["facts only (no checked draft)"])
        return {"text": a.text, "route": route, "meta": "local · nothing left the PC"}

    from pflab.agents import analyst as an
    if mode == "web":
        try:
            o = an.web_search(con, q, an.make_client(rt.secrets), now=now, approved=approved)
        except an.NotAdopted as e:
            return {"text": f"Web search is off: {e}.", "route": ["egress check"], "status": "failed"}
        except an.NeedsApproval as e:
            return {"text": f"{e}. Press 'Approve and send' to go ahead.", "route": ["priced first"], "status": "needs_approval"}
        except an.BudgetRefused as e:
            return {"text": f"Not sent: {e}.", "route": ["priced first"], "status": "failed"}
        if o.status != "done":
            return {"text": o.text, "route": ["egress check: " + o.status], "status": "failed"}
        note = con.execute("SELECT note_doc FROM api_calls WHERE call_id=?", [o.call_id]).fetchone()
        return {"text": o.text + "".join(f"\n\nNote: {w}" for w in o.warnings), "cost": o.cost_inr,
                "route": ["egress check: public question", f"Opus web search · ₹{o.cost_inr:,.2f}", "cited pages only"],
                "meta": "Opus with web search · the note is kept in the knowledge graph", "report": note[0] if note else None}

    if mode == "deep":
        start = con.execute("SELECT coalesce(max(call_id), 0) FROM api_calls").fetchone()[0]
        text = an.ask_deep(con, q, asof, approved=approved, secrets=rt.secrets, now=now)
        row = con.execute("SELECT call_id, status, cost_inr, note_doc FROM api_calls WHERE call_id > ? ORDER BY call_id DESC "
                          "LIMIT 1", [start]).fetchone()
        if row and row[3]:
            return {"text": text, "cost": row[2], "report": row[3], "meta": "Opus · public documents only · kept in the graph",
                    "route": ["plan (local): public documents", f"Opus research · ₹{row[2] or 0:,.2f}", "numbers checked against sources",
                              "report saved"]}
        reused = text.startswith("(note of")
        return {"text": text, "meta": "a recent note was reused" if reused else "Opus not rung: the local model answered when it could",
                "route": ["note reused (not bought twice)"] if reused else ["Opus not rung", "local model (guarded)"],
                "status": "needs_approval" if "to go ahead" in text else "done"}

    from pflab.agents import sandbox as sb
    from pflab.agents import workshop as wk
    try:
        out = wk.ask(con, q, rt.pm_dir, rt.data_root, asof, writer="auto", secrets=rt.secrets, approved=approved, now=now)
    except sb.SandboxUnavailable as e:                   # S67: nothing ran; no host-process fallback
        from pflab.agents import questions as qs
        qs.ask(con, "workshop", f"workshop:sandbox:{now:%Y-%m-%d}",
               f"Calculations are paused: the sandbox is not available ({e}). Start Docker Desktop (and build the image once if asked); "
               "I run them again when it works.", now)
        return {"text": f"This calculation did not run: the sandbox is not available ({e}). Generated code only runs contained, "
                        "so it waits for Docker.", "route": ["sandbox unavailable: nothing was run"], "status": "failed",
                "meta": "nothing ran on this PC"}
    if out.measure:
        route = ["local model picks a reviewed measure", "reviewed code (calc/measures.py) on this PC"]
        meta = "a reviewed measure; your rows never left the PC"
    else:
        route = [f"{out.writer or 'no writer'} writes code from the data layout", "static check", "sandbox on this PC",
                 "worked example" + (" + second method" if out.run and out.run.cross_checked else ""),
                 f"independent second writing: {(out.confirm or {}).get('status', 'not run')}"]
        meta = "your rows never left the PC; kept as 'not reviewed'"
    return {"text": wk.render(out), "route": route, "meta": meta,
            "status": "done" if out.status == "checked" else "failed"}


def tidy(con, now: datetime, days: int = TIDY_DAYS) -> int:
    """Chats untouched for `days`: a short summary goes to the system's memory, then the chat is removed."""
    from pflab.agents import memory as mem
    n = 0
    for cid, title in con.execute("SELECT chat_id, title FROM chats WHERE updated_at < ? AND title <> 'Assistant'", [now - timedelta(days=days)]).fetchall():
        msgs = messages(con, cid)
        qs = [m["text"][:160] for m in msgs if m["role"] == "me"][:8]
        summary = f"Chat '{title}' ({msgs[0]['at'][:10] if msgs else ''}): " + " | ".join(qs)
        mem.remember(con, "note", summary[:1500], subject="chat", source=f"chat {cid} (tidied)", now=now)
        delete(con, cid)
        n += 1
    return n
