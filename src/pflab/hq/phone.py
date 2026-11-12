"""Telegram as the phone front end (S59, S85): with the intake present (`service/tg_entrance.py`) plain words, files and photos go to the intake and the
answer comes back through its reply callback; /new /model /think /status /help and the inline buttons are the entrance's. Without the intake the old path
serves: plain messages go to the receptionist's rules and the answer comes back when the agent finishes (the board delivers it); the bot's own commands
(/questions, /answer, /decide, /remember, ...) work as before (`service.bot.handle`). Only the investor's chat id is served (`service.bot.process`).

The bot runs inside the app process (A42, 2026-11-05): a thread long-polls Telegram while Telegram is switched on in Settings; the tick's `hq` job
(only when the app is not running) polls once. Both hold the bot's lock, so a `pflab bot run` cannot steal the updates.
"""
from __future__ import annotations

from typing import Optional



def reply_for(rt, text: str) -> str:
    """The OLD reply path (used only while the intake is not there, and for the legacy commands the entrance passes on): /help, /spend and the bot's own
    commands; plain words go to the receptionist's board. S85 (E6): the HQ agent commands (/calc /sim /web /research /analyse /quant /graph /order /agents
    /board ...) are retired with the v1 layers: say it in plain words."""
    from pflab.hq import board, governor as gv, roster
    from pflab.hq.reception import route
    from pflab.service import bot
    con, now = rt.cursor(), rt.clock()
    t = text.strip()
    cmd = t.split(" ", 1)[0].lower().split("@")[0] if t.startswith("/") else ""
    if cmd in ("/start", "/help"):
        return bot.HELP
    if cmd == "/spend":
        s = gv.spend(con, now)
        return (f"API this month: ~Rs {s['month']:,.0f} of Rs {s['cap']:,.0f}.\n" +
                "\n".join(f"{a['agent']}: ~Rs {a['month']:,.1f} ({a['calls']} calls)" for a in s["agents"][:10]))
    if t.startswith("/"):
        return bot.handle(con, t, now.date(), ask=bot.centre_ask(con, now.date()),
                          tradecheck=bot.kite_tradecheck(con, rt.secrets, now.date()), now=now)
    agent, body = route(t)
    if agent not in roster.ROSTER:
        return "I could not tell who should take that. Write it in plain words, or /help."
    tid = board.post(con, agent, body, now, channel="telegram")
    wake = getattr(rt, "wake_hq", None)
    if wake:
        wake()
    return f"{roster.ROSTER[agent].title}: on it (task #{tid}). The answer comes here."


def configured(rt) -> bool:
    s = rt.secrets
    return s is not None and s.has("telegram", "token") and s.has("telegram", "chat_id")


def poll_once(rt, timeout: int = 0, transport=None, entrance=None) -> int:
    """One getUpdates; every message from the investor's chat gets its reply. S85: with the entrance (the intake is there) plain words, files and photos go to the
    intake and its answer comes back through the entrance's reply callback; commands and buttons are the entrance's. Without it the old reply path serves."""
    from pflab.service import bot
    from pflab.service import telegram as tgm
    if not (rt.settings.get("telegram_send") and configured(rt)):
        return 0
    from pflab import guard
    if transport is None and guard.blocked("telegram"):          # S65: the workshop does not poll
        return 0
    token, chat_id = rt.secrets.get("telegram", "token"), rt.secrets.get("telegram", "chat_id")
    ups = bot.get_updates(token, bot.next_offset(rt.cursor()), transport or bot.poll_transport, timeout)
    if not ups:
        return 0
    if entrance is None:
        from pflab.service import tg_entrance
        entrance = tg_entrance.for_runtime(rt, transport)
    return bot.process(rt.cursor(), ups, chat_id, tgm.make_sender(rt.secrets, transport), lambda text: reply_for(rt, text), rt.clock(),
                       ack=bot.make_ack(token, transport or bot.poll_transport), entrance=entrance)


def loop(rt, stop, lock_path=None, wait=None) -> Optional[str]:
    """The dashboard's phone thread: long-polls while Telegram is on; holds the bot's lock while it runs."""
    from pflab._lock import FileLock, LockBusy
    lock = FileLock(lock_path or (rt.pm_dir / "locks" / "bot.lock"), "bot")
    try:
        lock.__enter__()
    except LockBusy as e:
        return f"another bot holds the lock: {e}"
    pause = 5.0
    try:
        while not stop.is_set():
            if not (rt.settings.get("telegram_send") and configured(rt)):
                stop.wait(60)
                continue
            try:
                poll_once(rt, timeout=50)
                pause = 5.0
            except Exception:                                    # network down: back off, never die
                stop.wait(pause)
                pause = min(pause * 2, 300.0)
    finally:
        lock.__exit__(None, None, None)
    return None
