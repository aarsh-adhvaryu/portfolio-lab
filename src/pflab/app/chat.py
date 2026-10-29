"""The AI centre's chats (S54b): one conversation, four modes, the route of every answer shown beside it.

    ask        the ask centre (`agents.centre`): local routing to the system's read-only tools, a guarded answer;
               nothing leaves the PC
    web        Opus with web search (`analyst.web_search`): public questions only, priced first, cited pages
    deep       the doorbell (`analyst.ask_deep`): a cited note from public documents, kept in the graph; the local
               model answers when Opus is not rung
    calc       the calculation workshop (`agents.workshop`): Opus writes the code from the data layout, it runs here

Answers are computed on a worker thread (one at a time: the local model and the GPU are shared) and written back to
the message; the screen sees the change through the runtime's "chat" topic. Each question stands on its own (the local
model's window is small); the chat keeps the history for the investor. Chats untouched for TIDY_DAYS are summarised into the
system's memory and removed.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from typing import List, Optional

MODES = ("auto", "ask", "web", "deep", "calc")
TIDY_DAYS = 30
_WORK = threading.Lock()


def create(con, now: datetime, title: str = "New chat") -> int:
    from pflab.pm.store import next_id
    cid = next_id(con, "chats", "chat_id")
    con.execute("INSERT INTO chats VALUES (?,?,?,?)", [cid, title[:80], now, now])
    return cid


def listing(con) -> List[dict]:
    return [{"id": i, "title": t, "updated": str(u)[:16]} for i, t, u in con.execute(
        "SELECT chat_id, title, updated_at FROM chats ORDER BY updated_at DESC").fetchall()]


def messages(con, chat_id: int) -> List[dict]:
    rows = con.execute("SELECT msg_id, role, mode, text, status, route_json, meta, report_doc, cost_inr, created_at "
                       "FROM chat_messages WHERE chat_id=? ORDER BY msg_id", [chat_id]).fetchall()
    return [{"id": r[0], "role": r[1], "mode": r[2], "text": r[3], "status": r[4], "route": json.loads(r[5] or "[]"),
             "meta": r[6] or "", "report": r[7], "cost_inr": r[8], "at": str(r[9])[:16]} for r in rows]


def delete(con, chat_id: int) -> None:
    from pflab.pm.store import transaction
    with transaction(con):
        con.execute("DELETE FROM chat_messages WHERE chat_id=?", [chat_id])
        con.execute("DELETE FROM chats WHERE chat_id=?", [chat_id])


def _add(con, chat_id: int, role: str, mode: str, text: str, status: str, now: datetime) -> int:
    from pflab.pm.store import next_id
    mid = next_id(con, "chat_messages", "msg_id")
    con.execute("INSERT INTO chat_messages (msg_id, chat_id, role, mode, text, status, created_at) VALUES (?,?,?,?,?,?,?)",
                [mid, chat_id, role, mode, text, status, now])
    con.execute("UPDATE chats SET updated_at=? WHERE chat_id=?", [now, chat_id])
    return mid


def _finish(con, mid: int, text: str, route: List[str], meta: str, now: datetime, status: str = "done",
            report: Optional[str] = None, cost: Optional[float] = None) -> None:
    con.execute("UPDATE chat_messages SET text=?, status=?, route_json=?, meta=?, report_doc=?, cost_inr=?, finished_at=? "
                "WHERE msg_id=?", [text, status, json.dumps(route), meta, report, cost, now, mid])


def post(rt, chat_id: int, text: str, mode: str, approved: bool = False) -> dict:
    """Record the question and a pending answer; the answer is worked out on a background thread."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    q = text.strip()
    if not q:
        raise ValueError("empty message")
    con = rt.cursor()
    now = rt.clock()
    row = con.execute("SELECT title FROM chats WHERE chat_id=?", [chat_id]).fetchone()
    if row is None:                                      # no chat open (or it was deleted): start one
        chat_id = create(con, now, q[:60])
    elif row[0] == "New chat":                           # a new chat takes its first question as its title
        con.execute("UPDATE chats SET title=? WHERE chat_id=?", [q[:60], chat_id])
    _add(con, chat_id, "me", mode, q, "done", now)
    aid = _add(con, chat_id, "ai", mode, "Working on it…", "working", now)
    rt.bump("chat")
    threading.Thread(target=_work, args=(rt, chat_id, aid, q, mode, approved), name=f"chat-{aid}", daemon=True).start()
    return {"chat_id": chat_id, "msg_id": aid}


HISTORY_TURNS, HISTORY_CHARS = 6, 220


def history_text(con, chat_id: int, before_msg: int, turns: int = HISTORY_TURNS) -> str:
    """The last few finished turns of this chat before message `before_msg`, short, oldest first: what a follow-up refers to (S67: the
    same history reaches the ask centre and the brain, which are otherwise two roads). A pending or failed answer is not history."""
    rows = con.execute("SELECT role, text FROM chat_messages WHERE chat_id=? AND msg_id < ? AND status='done' ORDER BY msg_id DESC LIMIT ?",
                       [chat_id, before_msg, turns]).fetchall()
    return "\n".join(f"{'he asked' if r == 'me' else 'you answered'}: {' '.join((t or '').split())[:HISTORY_CHARS]}" for r, t in reversed(rows))


def _work(rt, chat_id: int, aid: int, q: str, mode: str, approved: bool) -> None:
    con = rt.cursor()
    with _WORK:
        try:
            out = answer(rt, con, q, mode, approved, history=history_text(con, chat_id, aid - 1))
        except Exception as e:                               # shown in the chat, never hidden
            out = {"text": f"This could not be answered: {type(e).__name__}: {str(e)[:300]}", "route": ["error"],
                   "meta": "", "status": "failed"}
    _finish(con, aid, out["text"], out.get("route", []), out.get("meta", ""), rt.clock(), out.get("status", "done"),
            out.get("report"), out.get("cost"))
    con.execute("UPDATE chats SET updated_at=? WHERE chat_id=?", [rt.clock(), chat_id])
    rt.bump("chat", "notifications")


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
    for cid, title in con.execute("SELECT chat_id, title FROM chats WHERE updated_at < ?", [now - timedelta(days=days)]).fetchall():
        msgs = messages(con, cid)
        qs = [m["text"][:160] for m in msgs if m["role"] == "me"][:8]
        summary = f"Chat '{title}' ({msgs[0]['at'][:10] if msgs else ''}): " + " | ".join(qs)
        mem.remember(con, "note", summary[:1500], subject="chat", source=f"chat {cid} (tidied)", now=now)
        delete(con, cid)
        n += 1
    return n
