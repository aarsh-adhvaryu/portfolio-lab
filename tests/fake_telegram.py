"""An in-process fake of the Telegram Bot API for the S85 tests: a `transport(url, payload)` and a `downloader(url, dest, max_bytes)` for `service/tg_api.TgApi`.

    fake = FakeTelegram(token="TOK-SECRET", chat_id=42)
    fake.add_text(1, "hello")  fake.add_document(2, "a.pdf", b"%PDF", size=None)  fake.add_photo(3, ...)  fake.add_callback(4, "card:7:yes")
    fake.fail("sendMessage", 2)        # the next two sendMessage calls raise a ConnectionError
    fake.shown                         # the messages as the investor sees them: [{"id","text","markup","deleted","edits"}]
    fake.calls                         # every (method, payload)
No network is touched.
"""
from __future__ import annotations

from pathlib import Path


class FakeTelegram:
    def __init__(self, token: str = "TOK-SECRET", chat_id: int = 42):
        self.token, self.chat_id = token, chat_id
        self.calls = []
        self.queue = []
        self.shown = []
        self.files = {}              # file_id -> {"bytes": b, "path": str, "size": int|None, "too_big": bool}
        self.failures = {}           # method -> remaining failures
        self.downloaded = []
        self.answered = []
        self._next = 100

    # --- what the investor's phone sends ---------------------------------------------------------------------------
    def _msg(self, chat=None, **kw) -> dict:
        return {"chat": {"id": self.chat_id if chat is None else chat}, **kw}

    def add_text(self, uid: int, text: str, chat=None) -> None:
        self.queue.append({"update_id": uid, "message": self._msg(chat, text=text)})

    def add_document(self, uid: int, name: str, data: bytes, *, size="auto", mime: str = "application/pdf", caption: str = "", chat=None) -> None:
        fid = f"file-{uid}"
        reported = len(data) if size == "auto" else size
        self.files[fid] = {"bytes": data, "path": f"documents/{name}", "size": reported, "too_big": reported is not None and reported > 20 * 1024 * 1024}
        doc = {"file_id": fid, "file_name": name, "mime_type": mime}
        if reported is not None:
            doc["file_size"] = reported
        m = self._msg(chat, document=doc)
        if caption:
            m["caption"] = caption
        self.queue.append({"update_id": uid, "message": m})

    def add_photo(self, uid: int, data: bytes, caption: str = "", chat=None) -> None:
        small, big = f"ph-s-{uid}", f"ph-b-{uid}"
        self.files[small] = {"bytes": b"x", "path": f"photos/{small}.jpg", "size": 1, "too_big": False}
        self.files[big] = {"bytes": data, "path": f"photos/{big}.jpg", "size": len(data), "too_big": False}
        m = self._msg(chat, photo=[{"file_id": small, "file_size": 1, "width": 90, "height": 90},
                                   {"file_id": big, "file_size": len(data), "width": 1280, "height": 960}])
        if caption:
            m["caption"] = caption
        self.queue.append({"update_id": uid, "message": m})

    def add_voice(self, uid: int, chat=None) -> None:
        self.queue.append({"update_id": uid, "message": self._msg(chat, voice={"file_id": f"v-{uid}", "duration": 4})})

    def add_callback(self, uid: int, data: str, *, message_id: int = 5, chat=None) -> None:
        self.queue.append({"update_id": uid, "callback_query": {"id": f"cb{uid}", "data": data,
                                                                "message": {"message_id": message_id, "chat": {"id": self.chat_id if chat is None else chat}}}})

    def fail(self, method: str, times: int = 1) -> None:
        self.failures[method] = times

    # --- the API ---------------------------------------------------------------------------------------------------
    def transport(self, url: str, payload: dict):
        method = url.rsplit("/", 1)[1]
        self.calls.append((method, dict(payload)))
        if self.failures.get(method, 0) > 0:
            self.failures[method] -= 1
            raise ConnectionError(f"network down while calling {url}")             # the url holds the token: the client must scrub it
        if method == "getUpdates":
            ups, self.queue = self.queue, []
            return 200, {"ok": True, "result": ups}
        if method == "sendMessage":
            self._next += 1
            self.shown.append({"id": self._next, "text": payload["text"], "markup": payload.get("reply_markup"), "deleted": False, "edits": 0})
            return 200, {"ok": True, "result": {"message_id": self._next}}
        if method == "editMessageText":
            m = self._find(payload["message_id"])
            if m is None or m["deleted"]:
                return 400, {"ok": False, "description": "Bad Request: message to edit not found"}
            if m["text"] == payload["text"] and payload.get("reply_markup") is None:
                return 400, {"ok": False, "description": "Bad Request: message is not modified"}
            m["text"], m["edits"] = payload["text"], m["edits"] + 1
            if "reply_markup" in payload:
                m["markup"] = payload["reply_markup"]
            return 200, {"ok": True, "result": True}
        if method == "editMessageReplyMarkup":
            m = self._find(payload["message_id"])
            if m is not None:
                m["markup"] = payload["reply_markup"] or None
            return 200, {"ok": True, "result": True}
        if method == "deleteMessage":
            m = self._find(payload["message_id"])
            if m is None:
                return 400, {"ok": False, "description": "Bad Request: message to delete not found"}
            m["deleted"] = True
            return 200, {"ok": True, "result": True}
        if method == "answerCallbackQuery":
            self.answered.append((payload["callback_query_id"], payload.get("text", "")))
            return 200, {"ok": True, "result": True}
        if method == "sendChatAction":
            return 200, {"ok": True, "result": True}
        if method == "getFile":
            f = self.files.get(payload["file_id"])
            if f is None:
                return 400, {"ok": False, "description": "Bad Request: wrong file_id"}
            if f["too_big"]:
                return 400, {"ok": False, "description": "Bad Request: file is too big"}
            return 200, {"ok": True, "result": {"file_id": payload["file_id"], "file_path": f["path"], "file_size": f["size"]}}
        return 404, {"ok": False, "description": f"unknown method {method}"}

    def downloader(self, url: str, dest: Path, max_bytes: int) -> int:
        self.downloaded.append(url)
        path = url.split("/file/bot", 1)[1].split("/", 1)[1]
        for f in self.files.values():
            if f["path"] == path:
                dest = Path(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(f["bytes"])
                return len(f["bytes"])
        raise RuntimeError("no such file")

    def _find(self, mid: int):
        return next((m for m in self.shown if m["id"] == mid), None)

    # --- what the investor sees -----------------------------------------------------------------------------------
    def texts(self) -> list:
        return [m["text"] for m in self.shown if not m["deleted"]]

    def methods(self) -> list:
        return [c[0] for c in self.calls]
