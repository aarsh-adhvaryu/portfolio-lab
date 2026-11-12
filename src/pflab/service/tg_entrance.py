"""Telegram as the second window of the one conversation (S85 E6, A69-A72): plain words, files and photos go to the INTAKE; a few commands and the inline buttons
are handled here. Only the investor's chat is served (`bot.process` checks the chat id before anything below runs).

    plain text / caption   -> intake.submit(rt, "telegram", text, attachments=..., model=<his /model>, thinking=<his /think>, reply=<this module's reply>)
    document / photo       -> getFile through the Bot API (about 20 MB: a bigger file gets one line asking him to send it on the laptop and is NOT downloaded),
                              saved in a scratch inbox folder, passed to the intake as {"path", "name", "mime"}; the scratch copy is deleted when the intake has answered
    voice / audio / video note -> one line: type, or send a file (not built)
    /new                   -> store.new_chat(channel="telegram"): a new thread; standing instructions, the graph and earlier files are shared by all chats
    /model [name|auto]  /think [low|medium|high|max|auto]   -> the picker (inline buttons) or a direct setting, kept in `tg_prefs_s85`, passed to `submit`
    /status  /help         -> text; the legacy commands that remain (/questions /answer /decide /remember /feedback /memory /tradecheck /spend) go to `legacy`
    buttons: `card:<msg_id>:yes|no` -> cards.answer_card(con, msg_id, answer, "telegram");  `undo:<rule>` -> rules.undo;  `mdl:<key>` / `thk:<level>` -> the picker;
             anything else (the question buttons `q:<id>:<i>`) stays with `voice.handle_callback` in `bot._callback`

The intake's reply callback `reply(text, msg_id, final)` runs on the intake's worker threads: it only talks to the Bot API (progress is ONE message edited in place, the
final answer is a NEW message so the phone notifies, then the progress line is deleted) and never touches the store. It never raises.
The entrance modules are looked up lazily (`mods`), so a test injects a stub and the app without them falls back to the old reply path (`available()`).
"""
from __future__ import annotations

import importlib
import logging
import mimetypes
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pflab.service import telegram as tgm
from pflab.service.tg_api import FILE_LIMIT, TgApi, TgError, TgFileTooBig

log = logging.getLogger("pflab.tg")

LEVELS = ("low", "medium", "high", "max")
OWN_CALLBACKS = ("mdl:", "thk:", "card:", "undo:")
VOICE_LINE = "Voice notes are not built yet: please type it, or send a file."
BIG_LINE = "That file is over Telegram's 20 MB limit for bots. Please send it from the laptop."
FETCH_LINE = "I could not fetch that file from Telegram. Please send it again in a minute."
BUSY_LINE = "I could not take that just now. Please send it again in a minute."
UNKNOWN_LINE = "I don't know that command. Write it in plain words, or /help."
NO_CHATS_LINE = "Chats are not available yet."
LEGACY_KEPT = ("/questions", "/answer", "/decide", "/remember", "/feedback", "/memory", "/tradecheck", "/spend")
FALLBACK_MODELS = [{"key": "haiku", "model": "claude-haiku-5-5"}, {"key": "sonnet", "model": "claude-sonnet-5-5"}, {"key": "opus", "model": "claude-opus-5-5"}]
MIN_EDIT_SECONDS = 1.5                   # Telegram allows about one edit a second per chat
SCOPE = "telegram"
INBOX_KEEP = timedelta(days=1)

HELP = ("Ask me anything about your portfolio in plain words. Send a PDF, a spreadsheet or a photo (with a line about it) and I will read it.\n"
        "/new: start a new chat (your standing instructions and what I know carry over)\n"
        "/model [auto|haiku|sonnet|opus]: pick the model for your next messages\n"
        "/think [low|medium|high|max|auto]: how hard it thinks\n"
        "/status: what I am working on, your picks, this month's spend\n"
        "/questions, /answer N text: what I need from you\n"
        "/memory [words], /decide subject: text, /remember text, /feedback text: what I keep\n"
        "/tradecheck: compare Kite with the ledger;  /spend: this month's API spend;  /help: this list\n"
        "I only read and explain. I never place orders.")


def button(label: str, data: str) -> dict:
    return {"text": label, "callback_data": data[:64]}


def actions_to_buttons(actions: Optional[List[dict]]) -> List[List[tuple]]:
    """A chat message's `actions=[{"id", "label"}]` as the (label, callback_data) rows `telegram.enqueue_with_buttons` takes. The ids are the callback data:
    `card:<msg_id>:yes`, `card:<msg_id>:no`, `undo:<rule_id>` (this module answers them)."""
    return [[(str(a.get("label") or a["id"]), str(a["id"])[:64])] for a in (actions or [])] if actions else []


def keyboard(actions: Optional[List[dict]]) -> Optional[dict]:
    if not actions:
        return None
    return {"inline_keyboard": [[button(str(a.get("label") or a["id"]), str(a["id"]))] for a in actions]}


class _Mods:
    """Lazy lookup of the entrance modules; a test injects stubs by name."""
    PATHS = {"intake": "pflab.entrance.intake", "store": "pflab.entrance.store", "cards": "pflab.entrance.cards",
             "rules": "pflab.hq.rules", "gateway": "pflab.llm.gateway"}

    def __init__(self, **over: Any):
        self.over = over

    def get(self, name: str) -> Any:
        if name in self.over:
            return self.over[name]
        return importlib.import_module(self.PATHS[name])


def _safe_name(name: str, fallback: str) -> str:
    base = Path(str(name or "")).name
    base = re.sub(r"[^\w.\-() ]", "_", base).strip(" .")[:120]
    return base or fallback


def _files_of(msg: dict, uid: int) -> Optional[dict]:
    """The one file of a message (a document, or the largest size of a photo) as {"kind","file_id","name","mime","size"}."""
    d = msg.get("document")
    if isinstance(d, dict) and d.get("file_id"):
        name = _safe_name(d.get("file_name") or "", f"file_{uid}")
        mime = d.get("mime_type") or mimetypes.guess_type(name)[0] or "application/octet-stream"
        return {"kind": "document", "file_id": d["file_id"], "name": name, "mime": mime, "size": d.get("file_size")}
    p = msg.get("photo")
    if isinstance(p, list) and p:
        best = max((x for x in p if isinstance(x, dict) and x.get("file_id")),
                   key=lambda x: (x.get("file_size") or 0, (x.get("width") or 0) * (x.get("height") or 0)), default=None)
        if best:
            return {"kind": "photo", "file_id": best["file_id"], "name": f"photo_{uid}.jpg", "mime": "image/jpeg", "size": best.get("file_size")}
    return None


def has_payload(msg: dict) -> bool:
    """A message of a kind the entrance handles besides plain text."""
    return any(k in msg for k in ("document", "photo", "voice", "audio", "video_note"))


class Entrance:
    def __init__(self, api: TgApi, chat_id, *, rt=None, mods: Optional[_Mods] = None, legacy: Optional[Callable[[str], str]] = None,
                 inbox_dir: Optional[Path] = None, monotonic: Callable[[], float] = time.monotonic):
        self.api, self.chat_id, self.rt = api, chat_id, rt
        self.mods = mods or _Mods()
        self.legacy = legacy
        self._inbox = inbox_dir
        self._mono = monotonic
        self._lock = threading.Lock()
        self._progress: Dict[Any, dict] = {}          # intake msg_id -> {"tg": telegram message id, "last": time, "text": str}

    # --- availability -----------------------------------------------------------------------------------------------------------
    def available(self) -> bool:
        try:
            return callable(getattr(self.mods.get("intake"), "submit", None))
        except Exception:
            return False

    def owns_callback(self, data: str) -> bool:
        return str(data or "").startswith(OWN_CALLBACKS)

    # --- prefs ------------------------------------------------------------------------------------------------------------------
    def prefs(self, con) -> Tuple[Optional[str], Optional[str]]:
        r = con.execute("SELECT model, thinking FROM tg_prefs_s85 WHERE scope=?", [SCOPE]).fetchone()
        return (r[0], r[1]) if r else (None, None)

    def set_prefs(self, con, now: datetime, *, model: Optional[str] = "<keep>", thinking: Optional[str] = "<keep>") -> Tuple[Optional[str], Optional[str]]:
        cur_m, cur_t = self.prefs(con)
        m = cur_m if model == "<keep>" else model
        t = cur_t if thinking == "<keep>" else thinking
        con.execute("DELETE FROM tg_prefs_s85 WHERE scope=?", [SCOPE])
        con.execute("INSERT INTO tg_prefs_s85 VALUES (?,?,?,?)", [SCOPE, m, t, now])
        return m, t

    def models(self) -> List[dict]:
        """The models of the engine in use for the picker (the gateway's `models_of`); the three Claude models when the gateway lacks it."""
        try:
            gw = self.mods.get("gateway")
            eng = gw.current_engine()
            eng = eng.get("name") if isinstance(eng, dict) else eng
            out = [m for m in (gw.models_of(eng) or []) if m.get("key")]
            if out:
                return out
        except Exception:
            pass
        return list(FALLBACK_MODELS)

    def _resolve_model(self, arg: str) -> Optional[str]:
        a = arg.strip().lower()
        for m in self.models():
            if a == str(m["key"]).lower() or a == str(m.get("model", "")).lower():
                return m["key"]
        for m in self.models():
            if a and (a in str(m["key"]).lower() or a in str(m.get("model", "")).lower()):
                return m["key"]
        return None

    def picker(self, con) -> Tuple[str, dict]:
        m, t = self.prefs(con)
        mark = lambda on: "* " if on else ""
        row1 = [button(f"{mark(m is None)}Auto", "mdl:auto")] + [button(f"{mark(m == x['key'])}{str(x['key']).capitalize()}", f"mdl:{x['key']}") for x in self.models()]
        row2 = [button(f"{mark(t == lv)}{lv}", f"thk:{lv}") for lv in LEVELS] + [button(f"{mark(t is None)}auto", "thk:auto")]
        text = (f"Model: {m or 'auto (I choose by the question)'}. Thinking: {t or 'auto'}.\n"
                "Pick below; it holds for your next messages until you change it.")
        return text, {"inline_keyboard": [row1, row2]}

    # --- replies from the phone thread (commands) -------------------------------------------------------------------------------
    def _say(self, con, text: str, now: datetime, markup: Optional[dict] = None) -> int:
        """A short answer on Telegram, kept in the outbox as the old bot did (kind `reply`)."""
        mid = tgm.enqueue(con, text, "reply", now=now)
        try:
            self.api.send_message(text, markup)
            con.execute("UPDATE outbox SET status='sent', sent_at=?, attempts=1 WHERE msg_id=?", [now, mid])
        except Exception as e:
            con.execute("UPDATE outbox SET attempts=1, last_error=? WHERE msg_id=?", [str(e)[:300], mid])
        return 1

    # --- one message ------------------------------------------------------------------------------------------------------------
    def message(self, con, msg: dict, uid: int, now: datetime) -> int:
        """Handle one message of his chat; returns how many replies were sent at once (an intake answer comes later through `reply`)."""
        raw = (msg.get("text") or "").strip()
        if raw.startswith("/"):
            return self._command(con, raw, now)
        if any(k in msg for k in ("voice", "audio", "video_note")):
            return self._say(con, VOICE_LINE, now)
        text = (msg.get("text") or msg.get("caption") or "").strip()
        f = _files_of(msg, uid)
        if f is None and not text:
            return 0
        return self._submit(con, uid, text, f, now)

    def _command(self, con, raw: str, now: datetime) -> int:
        head, _, rest = raw.partition(" ")
        cmd, rest = head.lower().split("@")[0], rest.strip()
        if cmd in ("/start", "/help"):
            return self._say(con, HELP, now)
        if cmd == "/new":
            try:
                self.mods.get("store").new_chat(con, now, channel="telegram")
            except Exception as e:
                log.warning("telegram /new failed: %s", type(e).__name__)
                return self._say(con, NO_CHATS_LINE, now)
            return self._say(con, "New chat started. Your standing instructions and everything you sent before still count.", now)
        if cmd == "/model":
            return self._model(con, rest, now)
        if cmd == "/think":
            return self._think(con, rest, now)
        if cmd == "/status":
            return self._say(con, self.status_text(con, now), now)
        if cmd in LEGACY_KEPT and self.legacy is not None:
            try:
                reply = self.legacy(raw)
            except Exception as e:
                reply = f"Sorry, that failed: {type(e).__name__}: {e}"[:500]
            return self._say(con, reply, now)
        return self._say(con, UNKNOWN_LINE, now)

    def _model(self, con, arg: str, now: datetime) -> int:
        if not arg:
            text, kb = self.picker(con)
            return self._say(con, text, now, kb)
        if arg.lower() == "auto":
            self.set_prefs(con, now, model=None)
            return self._say(con, "Model: auto. I choose by the question.", now)
        key = self._resolve_model(arg)
        if key is None:
            return self._say(con, f"No model called {arg[:30]}. Choose auto, " + ", ".join(str(m["key"]) for m in self.models()) + ".", now)
        self.set_prefs(con, now, model=key)
        return self._say(con, f"Model: {key}, for your next messages. /model auto goes back to my choice.", now)

    def _think(self, con, arg: str, now: datetime) -> int:
        a = arg.lower()
        if not a:
            text, kb = self.picker(con)
            return self._say(con, text, now, kb)
        if a == "auto":
            self.set_prefs(con, now, thinking=None)
            return self._say(con, "Thinking: auto.", now)
        if a not in LEVELS:
            return self._say(con, "Thinking can be low, medium, high, max or auto.", now)
        self.set_prefs(con, now, thinking=a)
        return self._say(con, f"Thinking: {a}, for your next messages. /think auto goes back to my choice.", now)

    def status_text(self, con, now: datetime) -> str:
        m, t = self.prefs(con)
        lines = [f"Picked: model {m or 'auto'}, thinking {t or 'auto'}."]
        try:
            q = self.mods.get("intake").queue_status(con) or []
            busy = [x for x in q if str(x.get("state", "")).lower() not in ("done", "failed", "error", "refused")]
            lines.append(f"Working on {len(busy)} thing(s) you sent." if busy else "Nothing of yours is waiting.")
            for x in busy[:3]:
                lines.append(f"- {str(x.get('progress') or x.get('state') or '')[:80]}")
        except Exception:
            pass
        try:
            gw = self.mods.get("gateway")
            eng = gw.current_engine()
            eng = eng.get("name") if isinstance(eng, dict) else eng
            if eng:
                lines.append(f"Engine in use: {eng}.")
        except Exception:
            pass
        try:
            from pflab.hq import governor as gv
            s = gv.spend(con, now)
            lines.append(f"API this month: about Rs {s['month']:,.0f} of Rs {s['cap']:,.0f}.")
        except Exception:
            pass
        return "\n".join(lines)

    # --- text and files to the intake -------------------------------------------------------------------------------------------
    def inbox_dir(self) -> Path:
        if self._inbox is not None:
            return Path(self._inbox)
        base = getattr(self.rt, "pm_dir", None)
        if base is None:
            from pflab.pm import store
            base = store.pm_dir()
        return Path(base) / "telegram_inbox"

    def sweep_inbox(self, now: datetime) -> None:
        """Scratch copies the intake never answered for (a crash) are removed after a day."""
        d = self.inbox_dir()
        if not d.exists():
            return
        cutoff = now.timestamp() - INBOX_KEEP.total_seconds()
        for p in d.iterdir():
            try:
                if p.stat().st_mtime < cutoff:
                    _rm_tree(p)
            except OSError:
                pass

    def _note_file(self, con, uid: int, now: datetime, f: dict, outcome: str, detail: str = "", size: Optional[int] = None) -> None:
        try:
            con.execute("DELETE FROM tg_files_s85 WHERE update_id=?", [uid])
            con.execute("INSERT INTO tg_files_s85 VALUES (?,?,?,?,?,?,?,?)", [uid, now, f["kind"], f["name"], f["mime"], size if size is not None else f.get("size"), outcome, detail[:300]])
        except Exception:
            pass

    def _fetch(self, con, uid: int, f: dict, now: datetime) -> Tuple[Optional[dict], Optional[str]]:
        """Download one file; returns (attachment dict, None) or (None, the line to tell him)."""
        if f.get("size") and int(f["size"]) > FILE_LIMIT:
            self._note_file(con, uid, now, f, "too_big")
            return None, BIG_LINE
        self.api.chat_action("typing")
        try:
            info = self.api.get_file(f["file_id"])
            if info.get("file_size") and int(info["file_size"]) > FILE_LIMIT:
                self._note_file(con, uid, now, f, "too_big", size=int(info["file_size"]))
                return None, BIG_LINE
            dest = self.inbox_dir() / str(uid) / f["name"]
            n = self.api.download(info["file_path"], dest, FILE_LIMIT)
        except TgFileTooBig:
            self._note_file(con, uid, now, f, "too_big")
            return None, BIG_LINE
        except TgError as e:
            log.warning("telegram file fetch failed: %s", str(e)[:120])
            self._note_file(con, uid, now, f, "fetch_failed", str(e))
            return None, FETCH_LINE
        self._note_file(con, uid, now, f, "downloaded", size=n)
        return {"path": str(dest), "name": f["name"], "mime": f["mime"]}, None

    def _submit(self, con, uid: int, text: str, f: Optional[dict], now: datetime) -> int:
        attachments = None
        paths: List[Path] = []
        if f is not None:
            att, line = self._fetch(con, uid, f, now)
            if att is None:
                return self._say(con, line, now)
            attachments = [att]
            paths = [Path(att["path"])]
        model, thinking = self.prefs(con)
        intake = self.mods.get("intake")
        self.sweep_inbox(now)
        try:
            intake.submit(self.rt if self.rt is not None else con, "telegram", text, attachments=attachments, model=model, thinking=thinking,
                          reply=self.make_reply(paths))
        except Exception as e:
            log.warning("telegram: the intake did not take a message: %s", type(e).__name__)
            _cleanup(paths)
            return self._say(con, BUSY_LINE, now)
        return 0

    # --- the intake's reply callback (worker threads) ---------------------------------------------------------------------------
    def make_reply(self, paths: Optional[List[Path]] = None) -> Callable:
        paths = list(paths or [])

        def reply(text: str, msg_id=None, final: bool = True, actions: Optional[List[dict]] = None) -> None:
            try:
                self._deliver(str(text), msg_id, bool(final), actions)
            except Exception as e:                      # never into the worker; the chat store holds the answer
                log.warning("telegram reply failed: %s", str(e)[:120])
            finally:
                if final:
                    _cleanup(paths)
        return reply

    def _deliver(self, text: str, msg_id, final: bool, actions: Optional[List[dict]]) -> None:
        with self._lock:
            st = self._progress.get(msg_id) if msg_id is not None else None
        if not final:
            if st is None:
                ids = self.api.send_message(text)
                if msg_id is not None and ids:
                    with self._lock:
                        self._progress[msg_id] = {"tg": ids[-1], "last": self._mono(), "text": text}
                return
            if text == st["text"] or self._mono() - st["last"] < MIN_EDIT_SECONDS:
                return
            if self.api.edit_message(st["tg"], text):
                st["last"], st["text"] = self._mono(), text
            return
        # final: a NEW message (the phone notifies on a new message, not on an edit), then the progress line goes
        ids: List[int] = []
        try:
            ids = self.api.send_message(text, keyboard(actions))
        except TgError:
            self.sleep_once()
            ids = self.api.send_message(text, keyboard(actions))
        if st is not None:
            with self._lock:
                self._progress.pop(msg_id, None)
            if not self.api.delete_message(st["tg"]):
                self.api.edit_message(st["tg"], "Done.")

    def sleep_once(self) -> None:
        self.api.sleep(1.0)

    # --- buttons ----------------------------------------------------------------------------------------------------------------
    def callback(self, con, cb: dict, now: datetime) -> int:
        """A button of the new kinds (his chat already checked); returns 1 when a line went to Telegram."""
        data = str(cb.get("data") or "")
        cid = str(cb.get("id") or "")
        msg = cb.get("message") or {}
        tg_mid = msg.get("message_id")
        try:
            if data.startswith(("mdl:", "thk:")):
                key = data.split(":", 1)[1]
                if data.startswith("mdl:"):
                    self.set_prefs(con, now, model=None if key == "auto" else key)
                else:
                    self.set_prefs(con, now, thinking=None if key == "auto" else key)
                text, kb = self.picker(con)
                self.api.answer_callback(cid, "Saved")
                if tg_mid is not None:
                    self.api.edit_message(tg_mid, text, kb)
                return 0
            if data.startswith("card:"):
                parts = data.split(":")
                if len(parts) != 3 or parts[2] not in ("yes", "no") or not parts[1].isdigit():
                    self.api.answer_callback(cid, "I did not understand that button.")
                    return 0
                res = self.mods.get("cards").answer_card(con, int(parts[1]), parts[2], "telegram")
                line = f"Noted: {parts[2].capitalize()}."
                if isinstance(res, dict) and res.get("text"):
                    line = str(res["text"])[:300]
                self.api.answer_callback(cid, line)
                if tg_mid is not None:
                    self.api.edit_markup(tg_mid, None)
                return self._say(con, line, now)
            if data.startswith("undo:"):
                ref = data.split(":", 1)[1]
                res = self.mods.get("rules").undo(con, now, ref)
                line = (f"Undone: {res.get('name', 'the rule')}." if res.get("undone") else f"Nothing to undo: {res.get('why', 'it is already gone')}.")
                self.api.answer_callback(cid, line)
                if tg_mid is not None:
                    self.api.edit_markup(tg_mid, None)
                return self._say(con, line, now)
        except Exception as e:
            log.warning("telegram button failed: %s", type(e).__name__)
            self.api.answer_callback(cid, "That did not work.")
            return self._say(con, f"Sorry, that button failed: {type(e).__name__}.", now)
        return 0


def _rm_tree(p: Path) -> None:
    if p.is_dir():
        for c in p.iterdir():
            _rm_tree(c)
        p.rmdir()
    else:
        p.unlink(missing_ok=True)


def _cleanup(paths: List[Path]) -> None:
    """The scratch copy of a file is deleted once the intake has answered (it keeps what it keeps; a refused statement is never kept here either)."""
    for p in paths:
        try:
            p.unlink(missing_ok=True)
            parent = p.parent
            if parent.exists() and not any(parent.iterdir()):
                parent.rmdir()
        except OSError:
            pass


def for_runtime(rt, transport=None, downloader=None, mods: Optional[_Mods] = None) -> Optional[Entrance]:
    """The entrance of the running app (one per runtime, so the progress messages survive from one poll to the next); None when Telegram is not
    configured or the intake is not there (the old reply path then serves)."""
    cached = getattr(rt, "_tg_entrance", None)
    if cached is not None and (transport is None and downloader is None and mods is None):
        return cached if cached.available() else None
    from pflab.service import tg_api
    api = tg_api.for_secrets(rt.secrets, transport, downloader)
    if api is None:
        return None
    from pflab.hq import phone
    ent = Entrance(api, rt.secrets.get("telegram", "chat_id"), rt=rt, mods=mods, legacy=lambda t: phone.reply_for(rt, t))
    if not ent.available():
        return None
    if transport is None and downloader is None and mods is None:
        try:
            rt._tg_entrance = ent
        except Exception:
            pass
    return ent
