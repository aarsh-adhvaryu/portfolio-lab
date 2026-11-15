"""S88 L1: the light road for plain chat questions. ONE short SDK session with its own system prompt (not the Claude Code preset), no built-in tool, no MCP server but its own, no skills, no subagents, no
CLAUDE.md, five small in-process tools (each at most about 1,500 characters), at most 4 turns, and a short history (the last 6 messages and a 10-line code-made summary of the older ones, never a resumed
session). If it needs something it does not have (a study, a backtest, a file, a web check, a code change) it says `needs_full` and the dispatcher hands the question to the full operator ONCE."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Callable, List, Optional, Tuple

from pflab.llm import claude_plan as cp
from pflab.llm import gateway as gw

MAX_TURNS = 4
TOOL_CHARS = 1500
SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}, "needs_full": {"type": "boolean"}, "why": {"type": "string"}}, "required": ["answer", "needs_full", "why"]}
SYSTEM = """You are the portfolio operator for one private investor in India. He is not a trader.
Plain words. Say what a number MEANS for him. 15 lines or fewer. Answer first, then stop.

Numbers: every number you state comes from a tool result in this conversation, with its source and date as the tool gives them. Never from memory. If no tool gives it, say "I don't have that".
Never say "it will". For a decision give worst, likely and best cases in rupees when the tools give them, and say how sure the evidence is. Say so, kindly, when he is wrong.
Two books: HIS real holdings (read-only, from the broker feed) and the SYSTEM'S paper book (traded by a coded policy at each close). Say which one you mean.
You never place an order and cannot; a "ticket" is text for him to enter himself. His targets, limits and stock list change only on his Yes.

Tools (small, fast): book_card (his holdings and the paper book), today_card (the session, alarms, what is running), name_card (one stock: facts, move, what the system knows, open cases),
decisions_card (the paper book's recent trades with their reasons, the thinking loop's decisions and open cases), graph_name (one name's recent events and headlines with their times). Use at most three tools, then answer.

If the question needs something you do not have (a study, a backtest, a correlation or comparison, a stress test, a file or link, a web check, a change to the system), do not guess:
set needs_full to true, put one short line in why, and leave answer empty. The full operator will take it.

Reply as JSON: {"answer": "...", "needs_full": false, "why": ""}."""


# --- compact tool results ---------------------------------------------------------------------------------------------------------------------

def _slim(x, depth: int = 0):
    if isinstance(x, float):
        return round(x, 2)
    if isinstance(x, str):
        return x if len(x) <= 140 else x[:137] + "..."
    if isinstance(x, dict):
        return {k: _slim(v, depth + 1) for k, v in list(x.items())[:18] if k not in ("source_note", "tools", "note_for_model")}
    if isinstance(x, list):
        return [_slim(v, depth + 1) for v in x[:6]]
    return x


def compact(text: str, n: int = TOOL_CHARS) -> str:
    try:
        s = json.dumps(_slim(json.loads(text)), ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        s = " ".join(str(text).split())
    return s if len(s) <= n else s[:n].rsplit(",", 1)[0] + " ...(cut)"


def _run(ctx, name: str, args: Optional[dict] = None, n: int = 600) -> str:
    from pflab.entrance import tools as ct
    text, err = ct.run(ctx, name, args or {}, 1)
    return ("error: " if err else "") + compact(text, n)


def tools_for(ctx) -> List[tuple]:
    """The five tools bound to this chat's context: [(name, description, schema, fn(args) -> str)]."""
    sym = {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}
    none = {"type": "object", "properties": {}}

    def book_card(a):
        return _run(ctx, "portfolio", n=800) + " || PAPER: " + _run(ctx, "paper_book", n=650)

    def today_card(a):
        parts = [_run(ctx, "market_context", n=500)]
        try:
            from pflab.think import alarm
            parts.append("ALARMS: " + compact(json.dumps(alarm.status(ctx.con, ctx.now.date()), default=str), 500))
        except Exception:
            pass
        parts.append("RUNNING: " + _run(ctx, "working_on", n=300))
        return " || ".join(parts)[:TOOL_CHARS + 300]

    def name_card(a):
        s = str(a.get("symbol") or "").upper()
        return " || ".join([_run(ctx, "stock_facts", {"symbol": s}, 500), "MOVE: " + _run(ctx, "price_history", {"symbol": s, "days": 30}, 350), "KNOWN: " + _run(ctx, "what_do_you_know", {"name": s}, 450)])

    def decisions_card(a):
        n = max(1, min(8, int(a.get("n") or 5)))
        from pflab.oper import tools as ot
        paper = ""
        try:                                                           # the paper book's own trades with the reason code gave (a sale's cause is here)
            rows = ctx.con.execute("SELECT cast(made_at as date), action, symbol, substr(reason, 1, 260), status FROM paper_decisions ORDER BY made_at DESC LIMIT ?", [n]).fetchall()
            paper = " || PAPER TRADES: " + compact(json.dumps([[str(x) for x in r] for r in rows]), 900)
        except Exception:
            pass
        return "DECISIONS: " + compact(ot.decision_log(ctx, {"n": n}), 600) + paper + " || CASES: " + _run(ctx, "thinking_cases", n=500)

    def graph_name(a):
        return _run(ctx, "graph_timeline", {"symbol": str(a.get("symbol") or "").upper(), "days": 30}, TOOL_CHARS)

    return [("book_card", "His real holdings and the paper book, short.", none, book_card),
            ("today_card", "Today: market state, alarms, what the system is working on.", none, today_card),
            ("name_card", "One stock: facts, 30-day move, what the system knows about it.", sym, name_card),
            ("decisions_card", "The thinking loop's recent decisions and open cases.", {"type": "object", "properties": {"n": {"type": "integer"}}}, decisions_card),
            ("graph_name", "One name's recent events and headlines with their times.", sym, graph_name)]


# --- history: the last 6 messages and a 10-line summary of the older ones, per thread ------------------------------------------------------------

DDL = "CREATE TABLE IF NOT EXISTS oper_thread_summary_s88 (chat_id INTEGER PRIMARY KEY, n_older INTEGER, summary VARCHAR, updated_at TIMESTAMP)"


def _thread(con, cid: Optional[int], aid: Optional[int], q: str) -> List[dict]:
    if not cid:
        return []
    from pflab.entrance import store
    rows = []
    for m in store.messages(con, cid) or []:
        if aid and m.get("msg_id") is not None and int(m["msg_id"]) >= int(aid):
            continue
        if m.get("role") not in ("user", "assistant") or not str(m.get("text") or "").strip() or m.get("status") not in (None, "done"):
            continue
        rows.append({"role": m["role"], "text": " ".join(str(m["text"]).split())})
    if rows and rows[-1]["role"] == "user" and rows[-1]["text"] == " ".join(q.split()):
        rows.pop()
    return rows


def summary_line(m: dict) -> str:
    return ("He: " if m["role"] == "user" else "You: ") + m["text"][:110]


def history(con, cid: Optional[int], aid: Optional[int], q: str, keep: int = 6, every: int = 10) -> Tuple[str, str]:
    """(summary of older messages, the last `keep` messages as text). The summary is made by code (a line per older exchange, at most 10 lines), kept per thread and rewritten every `every` messages."""
    rows = _thread(con, cid, aid, q)
    recent, older = rows[-keep:], rows[:-keep]
    summary = ""
    if older and cid:
        con.execute(DDL)
        have = con.execute("SELECT n_older, summary FROM oper_thread_summary_s88 WHERE chat_id=?", [cid]).fetchone()
        if have and len(older) // every == int(have[0]) // every:
            summary = str(have[1])
        else:
            summary = "\n".join(summary_line(m) for m in older[-10:])
            con.execute("DELETE FROM oper_thread_summary_s88 WHERE chat_id=?", [cid])
            con.execute("INSERT INTO oper_thread_summary_s88 VALUES (?,?,?,?)", [cid, len(older), summary, datetime.now()])
    return summary, "\n".join(("He: " if m["role"] == "user" else "You: ") + m["text"][:600] for m in recent)


def thread_summary_for_full(con, cid: Optional[int], aid: Optional[int], q: str) -> str:
    s, r = history(con, cid, aid, q)
    return "\n".join(x for x in (("EARLIER IN THIS CHAT (summary):\n" + s) if s else "", ("RECENT MESSAGES:\n" + r) if r else "") if x)


# --- the call ---------------------------------------------------------------------------------------------------------------------------------

def answer(rt, con, now: datetime, *, ctx, q: str, route: dict, model_id: Optional[str], cid: Optional[int], aid: Optional[int]) -> dict:
    """-> {"text", "needs_full", "why", "model", "thinking", "input_tokens", "output_tokens", "turns", "seconds", "steps", "session"} or raises the plan's refusals (PlanPaused ...)."""
    summ, recent = history(con, cid, aid, q)
    prompt = (f"EARLIER IN THIS CHAT (summary):\n{summ}\n\n" if summ else "") + (f"RECENT MESSAGES:\n{recent}\n\n" if recent else "") + f"TODAY: {now:%Y-%m-%d %H:%M}\nHIS MESSAGE:\n{q}"
    auto = bool(route.get("auto"))
    spec = gw.resolve("read", engine="claude_plan", model=model_id, thinking="low" if auto else route.get("thinking"))
    server = cp.tool_server("light", tools_for(ctx))

    async def deny_builtin(name, inp, c):                              # nothing but the light tools: a built-in or other tool is refused (and none is offered)
        return cp.deny_result("not available on the light road")
    res = cp.run(con, prompt=prompt, system=SYSTEM, model=spec["model"], effort=spec["thinking"], klass="chat_light", purpose="light_chat", agent="chat", now=now, tools=[], mcp={"light": server},
                 allowed=["mcp__light__*"], can_use_tool=deny_builtin, schema=SCHEMA, max_turns=MAX_TURNS, setting_sources=[], chat_id=cid, timeout=240, explicit_model=bool(model_id))
    o = res.structured if isinstance(res.structured, dict) else {}
    if not o:
        from pflab.hq import llm
        try:
            o = llm.json_of(res.text) or {}
        except Exception:
            o = {}
    text = str(o.get("answer") or "").strip() if o else res.text.strip()
    needs = bool(o.get("needs_full")) or (not text and not res.tool_calls)
    return {"text": text, "needs_full": needs, "why": str(o.get("why") or "")[:200] if o else "no usable answer", "model": res.model or spec["model"], "thinking": spec["thinking"],
            "input_tokens": res.input_tokens, "output_tokens": res.output_tokens, "turns": res.turns, "seconds": res.seconds, "steps": [s.replace("mcp__light__", "") for s in res.steps],
            "session": res.session_id}
