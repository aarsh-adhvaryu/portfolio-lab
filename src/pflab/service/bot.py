"""Two-way Telegram (PLAN A7, S43): The investor asks, the agents answer. Long polling of the Bot API's getUpdates over
`requests` (no new library, PLAN section 10 A2). Read-only: there is no command that trades, and none that edits
the ledger; the investor's answers and notes go to the memory table.

    only the investor's chat id is served; any other chat is recorded as rejected (no text kept) and gets no reply
    replies are sent one by one; the bot never flushes the outbox, so alerts held there stay held until the investor
        switches the system on (the outbox job delivers them then)
    the PM store is opened per batch of messages and closed while waiting, so the CLI and the jobs can use it
    one bot at a time (a lock): two pollers would steal each other's updates

Commands: /help, /networth /guards /fds /plan /risk /tax (that agent's facts, written up if a model is chosen),
/questions, /answer N text, /decide subject: text, /remember text, /feedback text, /memory [words],
/tradecheck, /research SYMBOL; any other text is a question for the centre.
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime
from typing import Callable, Dict, List, Optional, Tuple

from pflab.service import telegram as tgm

POLL_TIMEOUT = 50
TOOL_COMMANDS = ("networth", "guards", "fds", "plan", "risk", "tax", "taxplan")
HELP = ("Ask me anything about your portfolio in plain words. Commands:\n"
        "/networth /guards /fds /plan /risk /tax /taxplan: what that agent knows today\n"
        "/questions: what I need from you;  /answer N text: answer question N\n"
        "/decide subject: text  /remember text  /feedback text: kept in memory\n"
        "/memory [words]: what you decided or told me\n"
        "/tradecheck: compare Kite with the ledger (needs today's Kite login)\n"
        "/research SYMBOL: what changed lately and the latest brief\n"
        "/deep question: deep research by the API analyst (public information only; costs money)\n"
        "/event news: is it confirmed, peers, what happened after similar filings, a plan\n"
        "/quant idea: run a tested study template; /theses: your theses with evidence and exposure\n"
        "I only read and explain. I never place orders.")

Transport = Callable[[str, Dict], Tuple[int, dict]]


def poll_transport(url: str, payload: Dict) -> Tuple[int, dict]:
    from pflab import guard
    guard.require("telegram")                       # S65: the workshop never polls the investor's bot (it would answer twice)
    import requests
    r = requests.post(url, json=payload, timeout=POLL_TIMEOUT + 15)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {}


def get_updates(token: str, offset: Optional[int], transport: Transport, timeout: int = POLL_TIMEOUT) -> List[dict]:
    payload = {"timeout": timeout, "allowed_updates": ["message", "callback_query"]}
    if offset is not None:
        payload["offset"] = offset
    status, body = transport(f"https://api.telegram.org/bot{token}/getUpdates", payload)
    if status != 200 or not body.get("ok"):
        raise RuntimeError(f"getUpdates HTTP {status}: {body.get('description', '')}")
    return body.get("result", [])


def next_offset(con) -> Optional[int]:
    r = con.execute("SELECT max(update_id) FROM bot_updates").fetchone()[0]
    return None if r is None else int(r) + 1


# --- commands ------------------------------------------------------------------------------------------------

def handle(con, text: str, asof: date, *, ask: Callable, tradecheck: Callable[[], str],
           now: Optional[datetime] = None) -> str:
    """One message -> the reply text. `ask(question, tools)` runs the centre (tools None = it routes)."""
    from pflab.agents import memory as mem
    from pflab.agents import questions as qs
    now = now or datetime.now()
    t = text.strip()
    head, _, rest = t.partition(" ")
    cmd = head.lower().split("@")[0] if head.startswith("/") else ""
    rest = rest.strip()
    if cmd in ("/start", "/help"):
        return HELP
    if cmd[1:] in TOOL_COMMANDS:
        return ask(rest or f"Summarise my {cmd[1:]}.", [cmd[1:]])
    if cmd == "/questions":
        open_ = qs.open_questions(con)
        return "\n\n".join(f"#{q} ({agent}): {txt}" for q, agent, txt in open_) if open_ else "No open questions."
    if cmd == "/answer":
        m = re.match(r"#?(\d+)\s+(.+)", rest, re.S)
        if not m:
            return "Write /answer N your answer (N from /questions)."
        try:
            mid = qs.answer(con, int(m.group(1)), m.group(2).strip(), now)
        except (LookupError, ValueError) as e:
            return str(e)
        return f"Thanks. Kept as memory #{mid}."
    if cmd in ("/decide", "/remember", "/feedback"):
        if not rest:
            return f"Write {cmd} followed by what to keep."
        subject, body = (rest.split(":", 1) if cmd == "/decide" and ":" in rest else (None, rest))
        kind = {"/decide": "decision", "/remember": "note", "/feedback": "feedback"}[cmd]
        mid = mem.remember(con, kind, body.strip(), subject=subject.strip() if subject else None,
                           source="telegram", now=now)
        return f"Kept as {kind} #{mid}."
    if cmd == "/memory":
        rows = mem.recall(con, words=rest, asof=asof)
        return "\n".join(m.line() for m in rows) if rows else "Nothing kept on that yet."
    if cmd == "/tradecheck":
        return tradecheck()
    if cmd in ("/deep", "/deep!"):
        if not rest:
            return "Write /deep followed by the research question (public information only)."
        from pflab.agents import analyst
        return analyst.ask_deep(con, rest, asof, approved=cmd == "/deep!", now=now)
    if cmd == "/event":
        from pflab.agents import event
        return event.research(con, rest, asof) if rest else "Paste the news after /event."
    if cmd == "/quant":
        from pflab.agents import quant
        return quant.run(rest) if rest else "Write the idea after /quant, e.g. /quant how do stocks move after downgrades"
    if cmd == "/theses":
        from pflab.agents import thesis
        return thesis.render(thesis.update(con, asof, with_cost=False))
    if cmd == "/research":
        from pflab.agents import researcher as rs
        return rs.show(con, rest.split()[0], asof) if rest else "Write /research SYMBOL."
    if cmd:
        return "I don't know that command.\n\n" + HELP
    return ask(t, None)


def centre_ask(con, asof: date) -> Callable:
    def ask(q: str, tools: Optional[List[str]]) -> str:
        from pflab.agents import centre
        a = centre.ask(con, q, asof, tools_override=tools)
        return a.text
    return ask


def kite_tradecheck(con, secrets, asof: date) -> Callable[[], str]:
    def run() -> str:
        from pflab.agents import tradecheck as tc
        from pflab.ingest import kite as km
        k = km.client(secrets)
        if k is None:
            return "Kite is not logged in today: run tools/kite_login.py, then /tradecheck again."
        return tc.check(con, k, asof).render()
    return run


# --- the loop ------------------------------------------------------------------------------------------------

def make_ack(token: str, transport: Transport) -> Callable[[str, str], None]:
    """S79: answerCallbackQuery for a pressed reply button (best effort: the button's spinner stops)."""
    def ack(callback_id: str, text: str) -> None:
        try:
            transport(f"https://api.telegram.org/bot{token}/answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190]})
        except Exception:
            pass
    return ack


def _callback(con, u: dict, chat_id: str, send: Callable[[str], None], ack: Optional[Callable[[str, str], None]], now: datetime) -> int:
    """S79 (item 6): a reply button on a question. Only his chat; `q:<id>:<option>` answers question <id> with that option."""
    cb = u.get("callback_query") or {}
    uid = int(u["update_id"])
    ok = str((((cb.get("message") or {}).get("chat")) or {}).get("id")) == str(chat_id)
    con.execute("INSERT INTO bot_updates VALUES (?,?,?,?,?)", [uid, now, ok, "callback" if ok else None, None])
    if not ok:
        return 0
    from pflab.agents import voice
    try:
        reply = voice.handle_callback(con, str(cb.get("data") or ""), now)
    except Exception as e:
        reply = f"Sorry, that failed: {type(e).__name__}: {e}"[:300]
    if ack is not None:
        ack(str(cb.get("id") or ""), reply[:190])
    mid = tgm.enqueue(con, reply, "reply", now=now)
    try:
        send(reply)
        con.execute("UPDATE outbox SET status='sent', sent_at=?, attempts=1 WHERE msg_id=?", [now, mid])
    except Exception as e:
        con.execute("UPDATE outbox SET attempts=1, last_error=? WHERE msg_id=?", [str(e)[:300], mid])
    return 1


def process(con, updates: List[dict], chat_id: str, send: Callable[[str], None], reply_for: Callable[[str], str],
            now: datetime, ack: Optional[Callable[[str, str], None]] = None) -> int:
    """Handle new updates in order; returns how many got a reply. Each update is recorded once."""
    n = 0
    for u in sorted(updates, key=lambda x: x["update_id"]):
        uid = int(u["update_id"])
        if con.execute("SELECT 1 FROM bot_updates WHERE update_id=?", [uid]).fetchone():
            continue
        if u.get("callback_query"):
            n += _callback(con, u, chat_id, send, ack, now)
            continue
        msg = u.get("message") or {}
        ok = str((msg.get("chat") or {}).get("id")) == str(chat_id) and isinstance(msg.get("text"), str)
        head = msg["text"].strip().split(" ", 1)[0][:32] if ok and msg["text"].strip().startswith("/") else None
        con.execute("INSERT INTO bot_updates VALUES (?,?,?,?,?)", [uid, now, ok, head, None])
        if not ok:
            continue
        try:
            reply = reply_for(msg["text"])
        except Exception as e:                                      # a failing agent answers with its error
            reply = f"Sorry, that failed: {type(e).__name__}: {e}"[:500]
        mid = tgm.enqueue(con, reply, "reply", now=now)
        try:
            send(reply)
            con.execute("UPDATE outbox SET status='sent', sent_at=?, attempts=1 WHERE msg_id=?", [now, mid])
        except Exception as e:
            con.execute("UPDATE outbox SET attempts=1, last_error=? WHERE msg_id=?", [str(e)[:300], mid])
        con.execute("UPDATE bot_updates SET reply_msg_id=? WHERE update_id=?", [mid, uid])
        n += 1
    return n


def run(secrets, *, connect: Callable, once: bool = False, transport: Transport = poll_transport,
        send: Optional[Callable[[str], None]] = None, reply_for: Optional[Callable] = None,
        clock: Callable[[], datetime] = datetime.now, sleep: Callable[[float], None] = time.sleep,
        lock_path=None) -> int:
    """Poll and answer until stopped (Ctrl+C), or one poll with `once`. Returns the replies sent."""
    from pflab._lock import FileLock
    from pflab.pm import store
    token, chat_id = secrets.get("telegram", "token"), secrets.get("telegram", "chat_id")
    send = send or tgm.make_sender(secrets)
    lock = FileLock(lock_path or (store.pm_dir() / "locks" / "bot.lock"), "bot")
    total, wait = 0, 5.0
    with lock:
        while True:
            try:
                con = connect()
                try:
                    off = next_offset(con)
                finally:
                    con.close()
                ups = get_updates(token, off, transport, timeout=0 if once else POLL_TIMEOUT)
                if ups:
                    con = connect()
                    try:
                        now = clock()
                        rf = reply_for or (lambda text: handle(con, text, now.date(), ask=centre_ask(con, now.date()),
                                                               tradecheck=kite_tradecheck(con, secrets, now.date()),
                                                               now=now))
                        total += process(con, ups, chat_id, send, rf, now, ack=make_ack(token, transport))
                    finally:
                        con.close()
                wait = 5.0
            except KeyboardInterrupt:
                break
            except Exception as e:                                  # network or store busy: wait and retry
                if once:
                    raise RuntimeError(secrets.redact(f"{type(e).__name__}: {e}")) from None
                sleep(wait)
                wait = min(wait * 2, 300.0)
            if once:
                break
    return total
