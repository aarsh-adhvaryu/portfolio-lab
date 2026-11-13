"""The shared conversation (S85 E1): one store for the laptop window and Telegram. Chats, messages (with their channel, model, price, status, kind and buttons) and attachments.

    active chat   the newest chat titled "Assistant" (what the laptop thread, Telegram and the system's own messages all use); older ones are kept as "Earlier: <what he first asked>".
                  A new chat is only a new thread: the standing instructions, the graph and what he sent before are shared by all (they never lived in the chat).
    roles         "me" (him) and "ai" (the system); "user" / "assistant" / "system" are accepted and mapped.
    channel       "laptop" | "telegram" for what he sent (and where the answer goes), "system" for what the system said by itself.
    kind          "text" | "card" | "loop" | "file" | "note" | any word a poster gives (a card carries `actions`: [{"id","label"}]).
    a stored message is never rewritten away: a row is only ever inserted, or its own fields updated as the answer is worked out.

Every function takes the cursor it is given, retries a write conflict a few times (the app process is the one writer; the intake, the loop and the screens each use their own cursor on it).
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

ACTIVE = "Assistant"
EARLIER = "Earlier: "
CHANNELS = ("laptop", "telegram", "system")
_ROLE = {"me": "me", "ai": "ai", "user": "me", "assistant": "ai", "system": "ai", "him": "me"}
_CHAT_LOCK = threading.RLock()                             # two windows asking for the active chat at the same moment must get the SAME chat
NO_MIRROR = ("reply", "test", "question", "decision")                              # outbox kinds that are answers or tests, not the system speaking first


def retry(fn: Callable[[], Any], tries: int = 8, pause: float = 0.05):
    """Run `fn`, trying again when the store reports a write conflict (two cursors touched the same row); anything else is raised at once."""
    last: Optional[BaseException] = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            msg = str(e).lower()
            if "conflict" not in msg and "transactioncontext" not in type(e).__name__.lower() and "transaction" not in msg:
                raise
            last = e
            time.sleep(pause * (i + 1))
    raise last  # type: ignore[misc]


def _next(con, table: str, col: str) -> int:
    from pflab.pm.store import next_id
    return next_id(con, table, col)


def _norm_role(role: str) -> str:
    try:
        return _ROLE[role]
    except KeyError:
        raise ValueError(f"role must be one of {sorted(_ROLE)}")


# --- chats -------------------------------------------------------------------------------------------------------------------------------------------

def _make(con, now: datetime, title: str, channel: str, label: Optional[str] = None) -> int:
    def do():
        cid = _next(con, "chats", "chat_id")
        con.execute("INSERT INTO chats (chat_id, title, created_at, updated_at, channel, label) VALUES (?,?,?,?,?,?)", [cid, title[:80], now, now, channel, label])
        return cid
    return retry(do)


def _active(con) -> Optional[int]:
    r = con.execute("SELECT chat_id FROM chats WHERE title=? ORDER BY chat_id DESC LIMIT 1", [ACTIVE]).fetchone()
    return int(r[0]) if r else None


def _has_user_message(con, chat_id: int) -> bool:
    return con.execute("SELECT 1 FROM chat_messages WHERE chat_id=? AND role='me' LIMIT 1", [chat_id]).fetchone() is not None


def _label(con, cid: int) -> str:
    r = con.execute("SELECT text FROM chat_messages WHERE chat_id=? AND role='me' ORDER BY msg_id LIMIT 1", [cid]).fetchone()
    words = " ".join((r[0] if r else "a chat").split())[:48].rstrip(" .,;:")
    return EARLIER + (words or "a chat")


def latest_chat(con, now: datetime) -> int:
    """The chat every window writes to now: the active one (made when there is none)."""
    with _CHAT_LOCK:
        cid = _active(con)
        return cid if cid is not None else _make(con, now, ACTIVE, "laptop")


def start_new(con, now: datetime, title: str = "New chat", channel: str = "laptop") -> Dict[str, Any]:
    """A clean thread. The current one is kept under "Earlier: <what he first asked>"; what he pinned comes with him. A chat he has not written in is not archived (no empty chats pile up):
    -> {"chat_id", "new": bool}."""
    with _CHAT_LOCK:
        return _start_new(con, now, title, channel)


def _start_new(con, now: datetime, title: str, channel: str) -> Dict[str, Any]:
    cur = latest_chat(con, now)
    if not _has_user_message(con, cur):
        return {"chat_id": cur, "new": False}
    pins = con.execute("SELECT pins_json FROM chat_summary WHERE chat_id=?", [cur]).fetchone()

    def do():
        con.execute("UPDATE chats SET title=? WHERE chat_id=?", [_label(con, cur), cur])
    retry(do)
    cid = _make(con, now, ACTIVE, channel, None if title == "New chat" else title[:80])
    if pins and pins[0] and pins[0] != "[]":
        retry(lambda: con.execute("INSERT INTO chat_summary VALUES (?,?,?,?,?)", [cid, "", pins[0], 0, now]))
    return {"chat_id": cid, "new": True}


def new_chat(con, now: datetime, title: str = "New chat", channel: str = "laptop") -> int:
    """`/new` in Telegram and New chat on the laptop: a new thread for every window. Returns its id (the current one when it is still empty)."""
    return int(start_new(con, now, title, channel)["chat_id"])


def open_chat(con, chat_id: int, now: datetime) -> int:
    """Go back to an earlier chat: it becomes the active one for every window and the current one is archived (an empty one is dropped)."""
    r = con.execute("SELECT title FROM chats WHERE chat_id=?", [chat_id]).fetchone()
    if not r or not str(r[0]).startswith(EARLIER):
        raise ValueError("that is not an earlier chat")
    cur = _active(con)
    if cur is not None and cur != chat_id:
        if not con.execute("SELECT 1 FROM chat_messages WHERE chat_id=? LIMIT 1", [cur]).fetchone():
            retry(lambda: con.execute("DELETE FROM chats WHERE chat_id=?", [cur]))          # an empty chat is not kept (a chat with system messages in it is)
        else:
            name = _label(con, cur) if _has_user_message(con, cur) else EARLIER + "from the system"
            retry(lambda: con.execute("UPDATE chats SET title=? WHERE chat_id=?", [name, cur]))
    retry(lambda: con.execute("UPDATE chats SET title=? WHERE chat_id=?", [ACTIVE, chat_id]))
    return chat_id


def earlier(con, limit: int = 8) -> List[dict]:
    return [{"id": i, "title": t[len(EARLIER):], "updated": str(u)[:16]} for i, t, u in con.execute(
        "SELECT chat_id, title, updated_at FROM chats WHERE title LIKE ? ORDER BY updated_at DESC, chat_id DESC LIMIT ?", [EARLIER + "%", limit]).fetchall()]


def chats(con) -> List[dict]:
    """Every chat, newest first: {"id", "title", "active", "channel", "updated", "n"}."""
    rows = con.execute("SELECT c.chat_id, c.title, c.updated_at, c.channel, (SELECT count(*) FROM chat_messages m WHERE m.chat_id = c.chat_id) "
                       "FROM chats c ORDER BY c.updated_at DESC, c.chat_id DESC").fetchall()
    return [{"id": r[0], "title": r[1], "active": r[1] == ACTIVE, "channel": r[3], "updated": str(r[2])[:16], "n": int(r[4])} for r in rows]


# --- messages ----------------------------------------------------------------------------------------------------------------------------------------

def _meta_cols(meta) -> tuple:
    """(display text, json) of a `meta` given as text or as a dict (the dict may carry "text")."""
    if meta is None:
        return None, None
    if isinstance(meta, dict):
        shown = meta.get("text") or " · ".join(str(meta[k]) for k in ("model", "price", "why") if meta.get(k)) or ""
        return shown, json.dumps(meta, default=str)
    return str(meta), None


def add_message(con, chat_id: int, role: str, text: str, *, channel: str = "laptop", status: str = "done", model: Optional[str] = None, thinking: Optional[str] = None,
                cost_inr: Optional[float] = None, kind: str = "text", meta=None, attachments=None, ref: Optional[str] = None, now: Optional[datetime] = None,
                mode: Optional[str] = None, reply_to: Optional[int] = None, item_id: Optional[int] = None, actions=None, post_key: Optional[str] = None) -> int:
    """One message into a chat (both windows see it). `meta`: text or a dict; `attachments`: a list of {"name","path","mime","kind"} (each is also kept in chat_attachments_s85)."""
    now = now or datetime.now()
    role = _norm_role(role)
    shown, mjson = _meta_cols(meta)

    def do():
        mid = _next(con, "chat_messages", "msg_id")
        con.execute("INSERT INTO chat_messages (msg_id, chat_id, role, mode, text, status, meta, cost_inr, created_at, channel, model, thinking, kind, attachments_json, actions_json, ref, "
                    "reply_to, item_id, post_key, meta_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    [mid, chat_id, role, mode or kind or "text", text, status, shown, cost_inr, now, channel, model, thinking, kind, json.dumps(attachments) if attachments else None,
                     json.dumps(actions) if actions else None, ref, reply_to, item_id, post_key, mjson])
        con.execute("UPDATE chats SET updated_at=? WHERE chat_id=?", [now, chat_id])
        return mid
    mid = retry(do)
    for a in attachments or []:
        if a.get("path"):
            attach(con, mid, a["path"], a.get("name") or str(a["path"]).replace("\\", "/").rsplit("/", 1)[-1], a.get("mime") or "", a.get("kind") or "", chat_id=chat_id, _record_only=True)
    return mid


_UPDATABLE = {"text": "text", "status": "status", "model": "model", "thinking": "thinking", "cost_inr": "cost_inr", "kind": "kind", "ref": "ref", "reply_to": "reply_to", "item_id": "item_id",
              "report_doc": "report_doc", "channel": "channel"}


def update_message(con, msg_id: int, now: Optional[datetime] = None, *, meta=None, route: Optional[List[str]] = None, actions=None, finish: bool = False, **fields) -> None:
    """Change the fields of a message as its answer is worked out (progress text, the answer, its model and price). Nothing is deleted."""
    sets, args = [], []
    for k, v in fields.items():
        if k not in _UPDATABLE:
            raise ValueError(f"cannot update {k!r}")
        sets.append(f"{_UPDATABLE[k]}=?")
        args.append(v)
    if meta is not None:
        shown, mjson = _meta_cols(meta)
        sets += ["meta=?", "meta_json=?"]
        args += [shown, mjson]
    if route is not None:
        sets.append("route_json=?")
        args.append(json.dumps(route))
    if actions is not None:
        sets.append("actions_json=?")
        args.append(json.dumps(actions))
    if finish:
        sets.append("finished_at=?")
        args.append(now or datetime.now())
    if not sets:
        return
    retry(lambda: con.execute(f"UPDATE chat_messages SET {', '.join(sets)} WHERE msg_id=?", [*args, msg_id]))


def progress(con, msg_id: int, text: str, steps: Optional[List[str]] = None) -> None:
    """The "working: ..." line a pending answer shows (the screen polls the chat topic)."""
    update_message(con, msg_id, meta=text, route=(steps or [])[-8:] if steps is not None else None)


def message(con, msg_id: int) -> Optional[dict]:
    rows = _rows(con, "WHERE msg_id=?", [msg_id])
    return rows[0] if rows else None


_COLS = ("msg_id, chat_id, role, mode, text, status, route_json, meta, report_doc, cost_inr, created_at, channel, model, thinking, kind, attachments_json, actions_json, ref, reply_to, item_id, "
         "post_key, meta_json, finished_at")


def _rows(con, where: str, args: list) -> List[dict]:
    out = []
    for r in con.execute(f"SELECT {_COLS} FROM chat_messages {where} ORDER BY msg_id", args).fetchall():
        out.append({"id": r[0], "chat_id": r[1], "role": r[2], "mode": r[3], "text": r[4], "status": r[5], "route": json.loads(r[6] or "[]"), "meta": r[7] or "", "report": r[8], "cost_inr": r[9],
                    "at": str(r[10])[:16], "channel": r[11] or ("system" if str(r[3] or "").startswith("note:") else "laptop"), "model": r[12], "thinking": r[13], "kind": r[14] or "text",
                    "attachments": json.loads(r[15] or "[]"), "actions": json.loads(r[16] or "[]"), "ref": r[17], "reply_to": r[18], "item_id": r[19], "post_key": r[20],
                    "meta_obj": json.loads(r[21]) if r[21] else {}, "finished": str(r[22])[:16] if r[22] else None})
    return out


def messages(con, chat_id: int) -> List[dict]:
    """The chat's messages, oldest first. The old keys (id, role, mode, text, status, route, meta, report, cost_inr, at) are all here, with channel, model, thinking, kind, attachments, actions, ref."""
    return _rows(con, "WHERE chat_id=?", [chat_id])


def post_system(con, now: datetime, text: str, *, kind: str, key: Optional[str] = None, chat_id: Optional[int] = None, actions=None, channels=("laptop", "telegram")) -> Optional[int]:
    """The system speaks first (the morning plan, the 15:45 report, a fill, a trim, a pick, a question, what a case did). Posted into `chat_id` (default: the active chat) once per `key`: a second
    call with the same key does nothing and returns None. `channels` is where it is shown; the laptop thread is the shared chat, and Telegram's copy is the outbox's own (service/telegram.py), so
    this function never sends anything outward. Nothing is posted when "laptop" is not among the channels."""
    if "laptop" not in channels:
        return None
    if key and con.execute("SELECT 1 FROM chat_messages WHERE post_key=? OR mode=? LIMIT 1", [key, f"note:{key}"]).fetchone():
        return None
    cid = chat_id if chat_id is not None else latest_chat(con, now)
    return add_message(con, cid, "ai", text[:3500], channel="system", kind=kind, meta={"text": "from the system", "channels": list(channels)}, now=now, mode=f"note:{key}" if key else kind,
                       actions=actions, post_key=key)


def mirror_outbox(con, mid: int, text: str, kind: str, dedup_key: Optional[str], now: Optional[datetime]) -> Optional[int]:
    """The one hook in `service/telegram.enqueue`: whatever the system queues for Telegram (within the outbox's own caps and dedupe) appears in the chat as well. An answer ("reply") is not mirrored."""
    if kind in NO_MIRROR:
        return None
    return post_system(con, now or datetime.now(), text, kind=f"outbox:{kind}", key=f"outbox:{mid}", channels=("laptop",))


# --- attachments ------------------------------------------------------------------------------------------------------------------------------------

def attach(con, msg_id: int, path, name: str, mime: str, kind: str, *, chat_id: Optional[int] = None, _record_only: bool = False) -> int:
    """A file that came with a message: a row in chat_attachments_s85 and the message's `attachments_json`. (`readers` later fills `kind`, `document_id` and `status`.)"""
    import hashlib
    from pathlib import Path
    p = Path(str(path))
    size, sha = None, None
    try:
        if p.is_file():
            size = p.stat().st_size
            h = hashlib.sha256()
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            sha = h.hexdigest()
    except OSError:
        pass
    if chat_id is None:
        r = con.execute("SELECT chat_id FROM chat_messages WHERE msg_id=?", [msg_id]).fetchone()
        chat_id = int(r[0]) if r else None

    def do():
        aid = _next(con, "chat_attachments_s85", "attachment_id")
        con.execute("INSERT INTO chat_attachments_s85 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [aid, msg_id, chat_id, name, str(path), mime, kind, size, sha, None, "received", None, datetime.now()])
        return aid
    aid = retry(do)
    if not _record_only:
        cur = con.execute("SELECT attachments_json FROM chat_messages WHERE msg_id=?", [msg_id]).fetchone()
        lst = json.loads(cur[0]) if cur and cur[0] else []
        lst.append({"name": name, "path": str(path), "mime": mime, "kind": kind})
        retry(lambda: con.execute("UPDATE chat_messages SET attachments_json=? WHERE msg_id=?", [json.dumps(lst), msg_id]))
    return aid


def attachments(con, msg_id: int) -> List[dict]:
    return [{"id": r[0], "name": r[1], "path": r[2], "mime": r[3], "kind": r[4], "sha": r[5], "document_id": r[6], "status": r[7]} for r in con.execute(
        "SELECT attachment_id, name, path, mime, kind, sha, document_id, status FROM chat_attachments_s85 WHERE msg_id=? ORDER BY attachment_id", [msg_id]).fetchall()]


def set_attachment(con, attachment_id: int, *, kind: Optional[str] = None, document_id: Optional[str] = None, status: Optional[str] = None, note: Optional[str] = None) -> None:
    sets, args = [], []
    for col, v in (("kind", kind), ("document_id", document_id), ("status", status), ("note", note)):
        if v is not None:
            sets.append(f"{col}=?")
            args.append(v)
    if sets:
        retry(lambda: con.execute(f"UPDATE chat_attachments_s85 SET {', '.join(sets)} WHERE attachment_id=?", [*args, attachment_id]))


# --- what he picked for a chat ----------------------------------------------------------------------------------------------------------------------

def get_prefs(con, chat_id: int) -> Dict[str, Optional[str]]:
    r = con.execute("SELECT model_key, thinking FROM chat_prefs_s85 WHERE chat_id=?", [chat_id]).fetchone()
    return {"model_key": r[0], "thinking": r[1]} if r else {"model_key": None, "thinking": None}


def set_prefs(con, chat_id: int, model_key: Optional[str] = None, thinking: Optional[str] = None, now: Optional[datetime] = None, *, clear: bool = False) -> Dict[str, Optional[str]]:
    """The picker (laptop) and /model, /think (Telegram): the model ("auto", "haiku", "sonnet", "opus" or a model key of the engine) and the thinking level (low/medium/high/max) for the next messages of this chat."""
    cur = get_prefs(con, chat_id)
    new = {"model_key": None if clear else (model_key if model_key is not None else cur["model_key"]), "thinking": None if clear else (thinking if thinking is not None else cur["thinking"])}
    if new["model_key"] == "auto":
        new["model_key"] = None
    if new["thinking"] not in (None, "low", "medium", "high", "max"):
        raise ValueError("thinking must be low, medium, high or max")

    def do():
        con.execute("DELETE FROM chat_prefs_s85 WHERE chat_id=?", [chat_id])
        con.execute("INSERT INTO chat_prefs_s85 VALUES (?,?,?,?)", [chat_id, new["model_key"], new["thinking"], now or datetime.now()])
    retry(do)
    return new
