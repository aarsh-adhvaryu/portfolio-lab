"""The voice (S79 item 6): a question carries a default and a deadline, goes out at once on Telegram with reply buttons, and the system runs on the
default until he answers. At most `DAILY_CAP` questions a day unless urgent; the rest wait on the screen and go out as the cap allows.

    questions.ask(con, agent, key, text, now, default="keep as is", deadline=..., options=["keep as is", "change"])   # the normal way in
    voice.effective(con, subject_key)  -> (answer, source)   source: "him" | "default" | "pending-default"
    voice.sweep(con, now)              -> applies defaults whose deadline passed, sends held questions the cap now allows (job `voice`)

A question that ran on its default stays answerable (`defaulted`): his later answer replaces it. Numbers in a question are the asker's own; nothing here
makes a number.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

DAILY_CAP = 3
DEFAULT_HOURS = 24


def _options(default: str, options: Optional[List[str]]) -> List[str]:
    out = [default] + [o for o in (options or []) if o != default]
    return out[:6]


def attach(con, qid: int, text: str, default: str, deadline: Optional[datetime], urgent: bool, options: Optional[List[str]], now: datetime) -> None:
    deadline = deadline or now + timedelta(hours=DEFAULT_HOURS)
    con.execute("INSERT INTO question_terms_s79 (q_id, default_answer, deadline, urgent, options_json, market) VALUES (?,?,?,?,?,?)",
                [qid, default, deadline, bool(urgent), json.dumps(_options(default, options)), "IN"])
    dispatch(con, qid, now)


def sent_today(con, now: datetime) -> int:
    start = datetime.combine(now.date(), datetime.min.time())
    return int(con.execute("SELECT count(*) FROM question_terms_s79 WHERE sent_at >= ? AND coalesce(urgent, FALSE) = FALSE", [start]).fetchone()[0])


def message(text: str, default: str, deadline: datetime) -> str:
    return f"{text}\n\nIf you do not answer, I go with: {default} (until {deadline:%a %d %b %H:%M}). Press a button or write /answer N your words."


def dispatch(con, qid: int, now: datetime) -> bool:
    """Send the question now if it is urgent or today's cap allows; otherwise it stays on the screen until a later sweep. True when sent."""
    from pflab.service import telegram as tgm
    r = con.execute("SELECT t.default_answer, t.deadline, t.urgent, t.options_json, t.sent_at, q.text, q.status FROM question_terms_s79 t "
                    "JOIN questions q USING (q_id) WHERE t.q_id=?", [qid]).fetchone()
    if r is None or r[4] is not None or r[6] not in ("open",):
        return False
    default, deadline, urgent, opts, _, text, _st = r
    try:                                                 # S85 (E5): the card is on the screen at once, even when the daily cap holds Telegram back
        from pflab.entrance import cards
        cards.ensure_question_card(con, now, qid)
    except Exception:
        pass
    if not urgent and sent_today(con, now) >= DAILY_CAP:
        return False
    options = json.loads(opts)
    deadline = max(deadline, now + timedelta(hours=2))          # a question held back by the cap still gets time to be read once it goes out
    con.execute("UPDATE question_terms_s79 SET deadline=? WHERE q_id=?", [deadline, qid])
    try:                                                 # S85 (E5): the question is a card in the chat and its Telegram buttons are the card's (`entrance/cards.py`)
        from pflab.entrance import cards
        carded = cards.deliver(con, now, qid, message(text, default, deadline))
    except Exception:
        carded = False
    if not carded:
        rows = [[((o + " (default)") if i == 0 else o)[:60], f"q:{qid}:{i}"] for i, o in enumerate(options)]
        tgm.enqueue_with_buttons(con, message(text, default, deadline), "question", [[tuple(b) for b in row] for row in [[x] for x in rows]],
                                 dedup_key=f"question:{qid}", now=now)
    con.execute("UPDATE question_terms_s79 SET sent_at=? WHERE q_id=?", [now, qid])
    return True


def handle_callback(con, data: str, now: datetime) -> str:
    """A pressed button: `q:<id>:<option index>`."""
    from pflab.agents import questions
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "q":
        return "I did not understand that button."
    qid, i = int(parts[1]), int(parts[2])
    r = con.execute("SELECT options_json FROM question_terms_s79 WHERE q_id=?", [qid]).fetchone()
    if r is None:
        return f"Question #{qid} has no buttons."
    options = json.loads(r[0])
    if not 0 <= i < len(options):
        return "That option does not exist."
    questions.answer(con, qid, options[i], now)
    return f"Noted for #{qid}: {options[i]}."


def mark_answered(con, qid: int, now: datetime) -> None:
    con.execute("UPDATE question_terms_s79 SET resolved_by='him', resolved_at=? WHERE q_id=?", [now, qid])


def effective(con, subject_key: str) -> Tuple[Optional[str], str]:
    """What the system should act on for this question: his answer, else the default (final after the deadline, pending before it)."""
    r = con.execute("SELECT q.status, q.answer, t.default_answer FROM questions q LEFT JOIN question_terms_s79 t USING (q_id) WHERE q.subject_key=?",
                    [subject_key]).fetchone()
    if r is None:
        return None, "none"
    status, ans, default = r
    if status == "answered":
        return ans, "him"
    if default is None:
        return None, "unanswered"
    return default, "default" if status == "defaulted" else "pending-default"


def sweep(con, now: datetime) -> dict:
    """Defaults whose deadline passed become final (status 'defaulted', a memory row says so); held questions go out as the cap allows."""
    from pflab.agents import memory
    out = {"defaulted": [], "sent": []}
    due = con.execute("SELECT t.q_id, t.default_answer, q.agent, q.subject_key, q.text FROM question_terms_s79 t JOIN questions q USING (q_id) "
                      "WHERE q.status='open' AND t.sent_at IS NOT NULL AND t.deadline <= ?", [now]).fetchall()
    for qid, default, agent, key, text in due:
        con.execute("UPDATE questions SET status='defaulted', answer=?, answered_at=? WHERE q_id=?", [default, now, qid])
        con.execute("UPDATE question_terms_s79 SET resolved_by='default', resolved_at=? WHERE q_id=?", [now, qid])
        memory.remember(con, "answer", f"Q: {text} A (he did not answer; the default stands): {default}", subject=key, source=f"question #{qid} ({agent}), default", now=now)
        out["defaulted"].append(qid)
    for (qid,) in con.execute("SELECT t.q_id FROM question_terms_s79 t JOIN questions q USING (q_id) WHERE t.sent_at IS NULL AND q.status='open' "
                              "ORDER BY coalesce(t.urgent, FALSE) DESC, t.q_id").fetchall():
        if dispatch(con, qid, now):
            out["sent"].append(qid)
    try:                                                 # S85 (E5): every open question has its card in the chat; a card follows its question's state
        from pflab.entrance import cards
        cards.ensure_cards(con, now)
        cards.sweep(con, now)
    except Exception:
        pass
    return out
