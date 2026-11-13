"""S85 E5: questions with a default, and decisions that wait for his Yes, as CARDS in the chat (laptop and Telegram).

    post_question_card(con, now, question_id) -> msg_id      a `voice` question as a card in the active chat (once per question) and, within voice's daily cap, on Telegram with buttons
    post_decision_card(con, now, kind, payload, text, on_yes, *, expires_hours=48) -> msg_id   a Yes/No card for a change only he may approve ("change my target to X"); `on_yes` runs ONLY on Yes
    answer_card(con, msg_id, answer, channel) -> dict        answer "yes" | "no" | "opt<N>" (a third option and on) | an option's own text; channel "laptop" | "telegram"
    ensure_cards(con, now)                                    every open question has its card (at app start and on every voice sweep)
    sync(con, q_id, now)                                      a question answered or defaulted elsewhere updates its card
    sweep(con, now)                                           a decision card nobody answered expires: nothing changed

A card is a chat message of kind `card` with `actions=[{"id","label"}]`; Telegram's buttons carry `card:<msg_id>:<action id>`. The question's own answer path (`agents/questions.answer`) stores the
answer; the system runs on the question's default until then (`voice.effective`). A decision card holds a dated handler (`module:function`, a name from `register_handler`, or a module-level
callable) called as `fn(con, now, payload) -> dict | str` only after Yes. A second tap on either button is harmless. Nothing here makes a number.
"""
from __future__ import annotations

import importlib
import json
import threading
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from pflab.entrance import store

_LOCK = threading.RLock()
_CH = threading.local()                               # the window an answer is coming from, for the card line written when the question's own answer path syncs the card
HANDLERS: Dict[str, Callable] = {}                    # name -> fn(con, now, payload); register_handler()
_LOCAL: Dict[int, Callable] = {}                      # a callable that cannot be named again after a restart (closures): kept per card for this process only
EXPIRE_HOURS = 48


def register_handler(name: str, fn: Callable) -> None:
    HANDLERS[name] = fn


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now()


def _next(con, col: str = "card_id") -> int:
    from pflab.pm.store import next_id
    return next_id(con, "cards_s85", col)


def _actions(options: List[str], default_first: bool = True) -> List[dict]:
    ids = ["yes", "no"] + [f"opt{i}" for i in range(3, 7)]
    out = []
    for i, o in enumerate(options[:6]):
        out.append({"id": ids[i], "label": (o + " (default)") if (i == 0 and default_first) else o})
    return out


def _tg_rows(msg_id: int, actions: List[dict]) -> List[List[tuple]]:
    return [[((a["label"])[:60], f"card:{msg_id}:{a['id']}")] for a in actions]


def _row(con, msg_id: int) -> Optional[dict]:
    r = con.execute("SELECT card_id, msg_id, chat_id, kind, q_id, options_json, payload_json, on_yes, expires_at, state, answer, answered_by, answered_at, result_json, tg_outbox_id "
                    "FROM cards_s85 WHERE msg_id=?", [msg_id]).fetchone()
    if r is None:
        return None
    keys = ["card_id", "msg_id", "chat_id", "kind", "q_id", "options", "payload", "on_yes", "expires_at", "state", "answer", "answered_by", "answered_at", "result", "tg_outbox_id"]
    d = dict(zip(keys, r))
    d["options"] = json.loads(d["options"] or "[]")
    d["payload"] = json.loads(d["payload"]) if d["payload"] else {}
    return d


def card_of_question(con, qid: int) -> Optional[dict]:
    r = con.execute("SELECT msg_id FROM cards_s85 WHERE q_id=? ORDER BY card_id LIMIT 1", [qid]).fetchone()
    return _row(con, int(r[0])) if r else None


def _question_text(text: str, default: str, deadline: datetime) -> str:
    return f"{text}\n\nIf you do not answer, I go with: {default} (until {deadline:%a %d %b %H:%M}). Until then the system runs on that."


def _make_card(con, now: datetime, *, key: str, text: str, kind: str, options: List[str], q_id: Optional[int], payload: Optional[dict], on_yes: Optional[str],
               expires_at: Optional[datetime], default_first: bool) -> int:
    """The chat message and its cards_s85 row, once per `key`."""
    with _LOCK:
        mid = store.post_system(con, now, text, kind="card", key=key, actions=_actions(options, default_first), channels=("laptop",))
        if mid is None:                                              # posted before: hand back the same message
            r = con.execute("SELECT msg_id FROM chat_messages WHERE post_key=? ORDER BY msg_id LIMIT 1", [key]).fetchone()
            return int(r[0])
        chat = con.execute("SELECT chat_id FROM chat_messages WHERE msg_id=?", [mid]).fetchone()[0]
        con.execute("INSERT INTO cards_s85 (card_id, msg_id, chat_id, kind, q_id, options_json, payload_json, on_yes, expires_at, state, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [_next(con), mid, chat, kind, q_id, json.dumps(options), json.dumps(payload, default=str) if payload is not None else None, on_yes, expires_at, "open", now])
        return mid


def _to_telegram(con, now: datetime, msg_id: int, text: str, kind: str) -> Optional[int]:
    """The card's buttons on Telegram, through the outbox (its caps, its dedupe). The outbox message is remembered on the card so the other window's answer can be told."""
    from pflab.service import telegram as tgm
    card = _row(con, msg_id)
    acts = _actions(card["options"], card["kind"] == "question")
    mid = tgm.enqueue_with_buttons(con, text, kind, _tg_rows(msg_id, acts), dedup_key=f"card:{msg_id}", now=now)
    if mid is not None:
        con.execute("UPDATE cards_s85 SET tg_outbox_id=? WHERE msg_id=?", [mid, msg_id])
    return mid


# --- questions ---------------------------------------------------------------------------------------------------------------------------------------

def _terms(con, qid: int):
    return con.execute("SELECT q.text, q.status, t.default_answer, t.deadline, t.options_json, t.sent_at FROM questions q JOIN question_terms_s79 t USING (q_id) WHERE q.q_id=?", [qid]).fetchone()


def ensure_question_card(con, now: datetime, qid: int) -> Optional[int]:
    """The chat card of an open question (chat only: Telegram goes through `voice.dispatch`, which honours the daily cap)."""
    r = _terms(con, qid)
    if r is None or r[1] not in ("open", "defaulted"):
        return None
    text, _st, default, deadline, opts, _sent = r
    options = json.loads(opts)
    return _make_card(con, now, key=f"card:q{qid}", text=_question_text(text, default, deadline), kind="question", options=options, q_id=qid, payload=None, on_yes=None,
                      expires_at=deadline, default_first=True)


def post_question_card(con, now: datetime, question_id: int) -> Optional[int]:
    """A `voice` question as a card in the chat, once; and on Telegram with Yes/No buttons when voice's cap lets it out now. Returns the card's message id."""
    now = _now(now)
    mid = ensure_question_card(con, now, int(question_id))
    if mid is not None:
        from pflab.agents import voice
        voice.dispatch(con, int(question_id), now)                   # sends through `deliver` below (cap and urgency decided there, as before)
    return mid


def deliver(con, now: datetime, qid: int, text: str) -> bool:
    """Called by `voice.dispatch` when the question may go out: make sure the card exists and put its buttons on Telegram. False when there is no card to carry (voice then uses its old buttons)."""
    mid = ensure_question_card(con, now, qid)
    if mid is None:
        return False
    _to_telegram(con, now, mid, text, "question")
    return True


def ensure_cards(con, now: datetime) -> List[int]:
    """Every open or defaulted question that has terms has a card (app start, every voice sweep). Returns the new card message ids."""
    out = []
    for (qid,) in con.execute("SELECT q.q_id FROM questions q JOIN question_terms_s79 t USING (q_id) WHERE q.status IN ('open') AND NOT EXISTS "
                              "(SELECT 1 FROM cards_s85 c WHERE c.q_id=q.q_id) ORDER BY q.q_id").fetchall():
        try:
            mid = ensure_question_card(con, now, int(qid))
        except Exception:
            mid = None
        if mid is not None:
            out.append(mid)
    return out


def _finish(con, row: dict, state: str, answer: str, by: str, now: datetime, text_line: str, keep_buttons: bool = False) -> None:
    con.execute("UPDATE cards_s85 SET state=?, answer=?, answered_by=?, answered_at=? WHERE msg_id=?", [state, answer, by, now, row["msg_id"]])
    m = store.message(con, row["msg_id"])
    body = (m["text"] if m else "").split("\n\n")[0]
    store.update_message(con, row["msg_id"], now, text=f"{body}\n\n{text_line}"[:3500], meta={"text": text_line, "state": state, "answer": answer, "by": by},
                         actions=_actions(row["options"], row["kind"] == "question") if keep_buttons else [])


def sync(con, qid: int, now: Optional[datetime] = None, by: Optional[str] = None) -> None:
    """The question's status changed (answered anywhere, or defaulted): the card shows it. Safe to call twice."""
    now = _now(now)
    row = card_of_question(con, qid)
    if row is None:
        return
    q = con.execute("SELECT status, answer FROM questions WHERE q_id=?", [qid]).fetchone()
    if q is None:
        return
    status, ans = q
    if status == "answered" and not (row["state"] == "answered" and row["answer"] == ans):
        who = by or getattr(_CH, "who", None) or "you"
        _finish(con, row, "answered", ans, who, now, f"Answered: {ans} ({'from Telegram' if who == 'telegram' else 'from the laptop' if who == 'laptop' else 'by you'}). The system goes with it.")
    elif status == "defaulted" and row["state"] == "open":
        _finish(con, row, "defaulted", ans, "default", now, f"Default applied: {ans} (no answer in time). You can still answer; your answer replaces it.", keep_buttons=True)
    elif status == "dropped" and row["state"] in ("open", "defaulted"):
        _finish(con, row, "expired", ans or "", "system", now, "No longer needed: the system settled it itself.")


# --- decisions (a change only he may approve) ---------------------------------------------------------------------------------------------------------

def _handler_name(on_yes) -> Optional[str]:
    if isinstance(on_yes, str):
        return on_yes
    mod, qn = getattr(on_yes, "__module__", None), getattr(on_yes, "__qualname__", "")
    if mod and qn and "<locals>" not in qn and "<lambda>" not in qn:
        return f"{mod}:{qn}"
    return None


def _resolve(name: Optional[str], card_id: int) -> Optional[Callable]:
    if card_id in _LOCAL:
        return _LOCAL[card_id]
    if not name:
        return None
    if name in HANDLERS:
        return HANDLERS[name]
    if ":" in name:
        mod, attr = name.split(":", 1)
        try:
            obj = importlib.import_module(mod)
            for part in attr.split("."):
                obj = getattr(obj, part)
            return obj
        except Exception:
            return None
    return None


def post_decision_card(con, now: datetime, kind: str, payload: dict, text: str, on_yes, *, expires_hours: float = EXPIRE_HOURS, telegram: bool = True) -> int:
    """A Yes/No card. NOTHING changes before Yes: `on_yes(con, now, payload)` runs once, on Yes. No, or no answer within `expires_hours`, leaves everything as it is. Once per (kind, payload)."""
    now = _now(now)
    name = _handler_name(on_yes)
    key = "card:d:" + kind + ":" + json.dumps(payload, sort_keys=True, default=str)[:200]
    body = f"{text}\n\nNothing changes unless you press Yes (the card closes on {now + timedelta(hours=expires_hours):%a %d %b %H:%M} with no change)."
    mid = _make_card(con, now, key=key, text=body, kind=f"decision:{kind}", options=["Yes", "No"], q_id=None, payload=payload, on_yes=name,
                     expires_at=now + timedelta(hours=expires_hours), default_first=False)
    row = _row(con, mid)
    if name is None and callable(on_yes):
        _LOCAL[row["card_id"]] = on_yes
    if telegram and row["tg_outbox_id"] is None:
        _to_telegram(con, now, mid, body, "decision")
    return mid


def _answer_decision(con, row: dict, answer: str, channel: str, now: datetime) -> dict:
    yes = answer in ("yes", "opt1")
    if not yes:
        _finish(con, row, "answered", "no", channel, now, "You said No: nothing was changed.")
        return {"ok": True, "state": "answered", "answer": "no", "applied": False, "text": "Noted: No. Nothing was changed."}
    fn = _resolve(row["on_yes"], row["card_id"])
    if fn is None:
        return {"ok": False, "state": "open", "applied": False, "text": "I could not find what to apply (the app restarted since this card was made). Please ask me again; nothing was changed."}
    try:
        res = fn(con, now, row["payload"])
    except Exception as e:
        return {"ok": False, "state": "open", "applied": False, "text": f"Applying it failed ({type(e).__name__}); nothing was changed. You can press Yes again."}
    said = res if isinstance(res, str) else (res or {}).get("text") or "Done."
    con.execute("UPDATE cards_s85 SET result_json=? WHERE msg_id=?", [json.dumps(res, default=str), row["msg_id"]])
    _finish(con, row, "answered", "yes", channel, now, f"You said Yes: {said}")
    return {"ok": True, "state": "answered", "answer": "yes", "applied": True, "text": f"Done. {said}", "result": res if isinstance(res, dict) else {"text": res}}


# --- the answer ---------------------------------------------------------------------------------------------------------------------------------------

def _option_for(options: List[str], answer: str) -> str:
    a = (answer or "").strip().lower()
    if a == "yes" and options:
        return options[0]
    if a == "no" and len(options) > 1:
        return options[1]
    if a.startswith("opt") and a[3:].isdigit() and 1 <= int(a[3:]) <= len(options):
        return options[int(a[3:]) - 1]
    for o in options:
        if o.lower() == a:
            return o
    raise ValueError(f"'{answer}' is not one of this card's answers")


def answer_card(con, msg_id: int, answer: str, channel: str = "laptop", now: Optional[datetime] = None) -> dict:
    """His tap on a card, from the laptop or Telegram. Stored once (a second tap says so and changes nothing); the card shows the answer in both windows. Returns
    {"ok", "state", "answer", "applied", "text"} where `text` says what the system will do. ValueError for a message that is not a card or an answer the card does not offer."""
    now = _now(now)
    with _LOCK:
        row = _row(con, int(msg_id))
        if row is None:
            raise ValueError("that message is not a card")
        ans = str(answer or "").strip().lower()
        if row["kind"].startswith("decision"):
            if row["state"] != "open":
                return {"ok": True, "already": True, "state": row["state"], "answer": row["answer"], "applied": False, "text": f"Already {row['state']}: {row['answer'] or 'no change'}."}
            if ans not in ("yes", "no", "opt1"):
                raise ValueError(f"'{answer}' is not one of this card's answers")
            out = _answer_decision(con, row, ans, channel, now)
            return out
        option = _option_for(row["options"], ans)
        if row["state"] == "answered":
            return {"ok": True, "already": True, "state": "answered", "answer": row["answer"], "applied": False, "text": f"Already answered: {row['answer']}. Nothing changed."}
        if row["state"] == "expired":
            return {"ok": True, "already": True, "state": "expired", "answer": row["answer"], "applied": False, "text": "That question is closed."}
        from pflab.agents import questions
        _CH.who = channel
        try:
            questions.answer(con, row["q_id"], option, now)          # raises ValueError when it is no longer open or defaulted; it syncs the card
        finally:
            _CH.who = None
        sync(con, row["q_id"], now, by=channel)
        con.execute("UPDATE cards_s85 SET answered_by=? WHERE msg_id=?", [channel, row["msg_id"]])
        return {"ok": True, "state": "answered", "answer": option, "applied": True, "text": f"Noted: {option}. The system will go with it."}


def sweep(con, now: datetime) -> dict:
    """Decision cards past their time close with no change; question cards follow their questions (answered, defaulted or dropped elsewhere)."""
    now = _now(now)
    out = {"expired": [], "synced": []}
    for (mid,) in con.execute("SELECT msg_id FROM cards_s85 WHERE kind LIKE 'decision%' AND state='open' AND expires_at <= ?", [now]).fetchall():
        row = _row(con, int(mid))
        _finish(con, row, "expired", "", "system", now, "No answer in time: nothing was changed.")
        out["expired"].append(int(mid))
    for (qid,) in con.execute("SELECT q_id FROM cards_s85 WHERE q_id IS NOT NULL AND state IN ('open','defaulted')").fetchall():
        sync(con, int(qid), now)
        out["synced"].append(int(qid))
    return out
