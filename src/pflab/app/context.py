"""The assistant's context against drift (S77; his word 2026-11-02: "the assistant will have a context window, so we will have to make sure of that for a drift").

A chat grows for ever; what the model reads each turn must not. Each turn it gets, in this order:
    PINNED     what he decided or asked to be kept, in his own words (at most PIN_MAX, newest kept), never paraphrased
    EARLIER    a digest of the older part of the chat: one line per message, his words and the first sentence of each answer, newest lines kept up to SUMMARY_MAX
    RECENT     the last RECENT_N messages in full (RECENT_CHARS each)
    FILES      the last files he attached in this chat, with what was read from them
Folding is code, not a model: every figure in the digest is a verbatim piece of a real message, so nothing can be invented, and the standing facts the system keeps (house rules, the
account) come from the record on every turn, not from the chat. Identifiers are redacted before anything is sent.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import List, Optional, Tuple

RECENT_N, RECENT_CHARS = 8, 1200
FOLD_AT = 12                 # fold when this many finished messages are older than the recent window
SUMMARY_MAX, PIN_MAX, PIN_CHARS, DIGEST_HIS, DIGEST_AI = 3500, 12, 400, 220, 180
DECISION = re.compile(r"\b(yes|no|approve[d]?|decline[d]?|remember|from now on|always|never|stop|don'?t|do not|must|only|keep|top[- ]?up|limit|rule|instead|change)\b", re.I)


def _rows(con, chat_id: int, after: int, before: int):
    return con.execute("SELECT msg_id, role, text, mode FROM chat_messages WHERE chat_id=? AND msg_id > ? AND msg_id < ? AND status='done' ORDER BY msg_id", [chat_id, after, before]).fetchall()


def _first_sentence(t: str, n: int) -> str:
    t = " ".join((t or "").split())
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    return (m.group(1) if m and len(m.group(1)) <= n else t[:n]).strip()


def state(con, chat_id: int) -> dict:
    r = con.execute("SELECT summary, pins_json, upto_msg_id FROM chat_summary WHERE chat_id=?", [chat_id]).fetchone()
    return {"summary": r[0], "pins": json.loads(r[1]), "upto": int(r[2])} if r else {"summary": "", "pins": [], "upto": 0}


def fold(con, chat_id: int, before: int, now: datetime) -> bool:
    """Fold the finished messages older than the recent window into the digest and the pins. Returns whether anything was folded."""
    st = state(con, chat_id)
    rows = [r for r in _rows(con, chat_id, st["upto"], before) if not str(r[3] or "").startswith("note:")]
    older = rows[:-RECENT_N] if len(rows) > RECENT_N else []
    if len(older) < FOLD_AT:
        return False
    lines, pins = st["summary"].splitlines() if st["summary"] else [], list(st["pins"])
    for mid, role, text, _mode in older:
        t = " ".join((text or "").split())
        if role == "me":
            lines.append(f"he: {t[:DIGEST_HIS]}")
            if DECISION.search(t):
                pin = t[:PIN_CHARS]
                if pin not in pins:
                    pins.append(pin)
        else:
            lines.append(f"you: {_first_sentence(t, DIGEST_AI)}")
    while sum(len(x) + 1 for x in lines) > SUMMARY_MAX and len(lines) > 1:
        lines.pop(0)                                         # the oldest digest lines go first; pins stay
    pins = pins[-PIN_MAX:]
    con.execute("DELETE FROM chat_summary WHERE chat_id=?", [chat_id])
    con.execute("INSERT INTO chat_summary VALUES (?,?,?,?,?)", [chat_id, "\n".join(lines), json.dumps(pins), int(older[-1][0]), now])
    return True


def _files(con, chat_id: int, gate=None) -> str:
    rows = con.execute("SELECT name, kind, status, text FROM inbox_items WHERE chat_id=? ORDER BY item_id DESC LIMIT 3", [chat_id]).fetchall()
    out = []
    for name, kind, status, text in reversed(rows):
        t = " ".join((text or "").split())[:900]
        out.append(f"- {name} ({kind or 'file'}, {status}): {t}" if t else f"- {name} ({kind or 'file'}, {status}): nothing readable was extracted")
    return "\n".join(out)


def build(con, chat_id: int, before: int, now: Optional[datetime] = None, gate=None) -> str:
    """The context block of a turn (without the house rules and the screen, which the caller adds)."""
    from pflab.hq import redact

    def clean(t: str) -> str:
        return redact.redact(t, gate)[0] if gate is not None else t
    now = now or datetime.now()
    fold(con, chat_id, before, now)
    st = state(con, chat_id)
    rows = [r for r in _rows(con, chat_id, 0, before)][-RECENT_N:]
    parts: List[str] = []
    if st["pins"]:
        parts.append("PINNED (what he decided or asked to keep, in his words; these still hold unless he changed them later):\n" + "\n".join(f"- {clean(p)}" for p in st["pins"]))
    if st["summary"]:
        parts.append("EARLIER IN THIS CONVERSATION (a digest):\n" + clean(st["summary"]))
    if rows:
        parts.append("THE CONVERSATION SO FAR:\n" + "\n".join(f"{'he' if r[1] == 'me' else 'you'}: {clean(' '.join((r[2] or '').split())[:RECENT_CHARS])}" for r in rows))
    f = _files(con, chat_id)
    if f:
        parts.append("FILES HE ATTACHED IN THIS CHAT (what was read from them):\n" + clean(f))
    return "\n\n".join(parts)
