"""The Bot API client of the upgraded Telegram (S85 E6): the calls the entrance needs that the send-only `telegram.make_sender` does not give.

    TgApi(token, chat_id, transport, downloader)
      send_message(text, reply_markup=None) -> [message ids]        long text split at Telegram's 4096 limit, buttons on the last part
      edit_message(message_id, text, reply_markup=None) -> bool     "message is not modified" counts as done
      delete_message(message_id) / edit_markup(message_id, None)    best effort
      answer_callback(callback_id, text) / chat_action("typing")    best effort
      get_file(file_id) -> {"file_path", "file_size"}               TgFileTooBig when the Bot API refuses (about 20 MB)
      download(file_path, dest, max_bytes) -> bytes written         the file bytes through `downloader` (a test passes a fake)

The token never appears in an error, a log line or a file: every message is scrubbed (`redact`). The workshop never reaches the network
(`guard.require("telegram")` in the real transports). A network error raises `TgError`; the caller (the poll loop) backs off and retries, the bot never dies.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from pflab.service.telegram import MAX_LEN, split_message

FILE_LIMIT = 20 * 1024 * 1024            # the Bot API's getFile limit
Transport = Callable[[str, Dict], Tuple[int, dict]]
Downloader = Callable[[str, Path, int], int]      # (url, dest, max_bytes) -> bytes written


class TgError(RuntimeError):
    pass


class TgFileTooBig(TgError):
    pass


def requests_downloader(url: str, dest: Path, max_bytes: int) -> int:
    """Stream a Telegram file to `dest`; stops (and removes the part) past `max_bytes`."""
    from pflab import guard
    guard.require("telegram")
    import requests
    n = 0
    with requests.get(url, stream=True, timeout=60) as r:
        if r.status_code != 200:
            raise TgError(f"file download HTTP {r.status_code}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as fh:
            for chunk in r.iter_content(65536):
                n += len(chunk)
                if n > max_bytes:
                    fh.close()
                    dest.unlink(missing_ok=True)
                    raise TgFileTooBig("file is larger than the limit")
                fh.write(chunk)
    return n


class TgApi:
    def __init__(self, token: str, chat_id, transport: Transport, downloader: Optional[Downloader] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self._token, self.chat_id = token, chat_id
        self.transport = transport
        self.downloader = downloader or requests_downloader
        self.sleep = sleep

    # --- plumbing ---------------------------------------------------------------------------------------------------
    def _clean(self, s) -> str:
        return str(s).replace(self._token, "***") if self._token else str(s)

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self._token}/{method}"

    def call(self, method: str, payload: Dict) -> dict:
        """One Bot API method; one wait-and-retry on HTTP 429; the token scrubbed from every error."""
        for attempt in range(2):
            try:
                status, body = self.transport(self._url(method), payload)
            except Exception as e:                                       # network error, timeout, the workshop guard
                raise TgError(self._clean(f"{method}: {type(e).__name__}: {e}")) from None
            if status == 200 and (body or {}).get("ok", True):
                return body or {}
            if status == 429 and attempt == 0:
                self.sleep(min(float(((body or {}).get("parameters") or {}).get("retry_after", 1)), 30.0))
                continue
            desc = (body or {}).get("description", "")
            if "too big" in str(desc).lower():
                raise TgFileTooBig(self._clean(desc))
            raise TgError(self._clean(f"{method}: HTTP {status}: {desc}"))
        raise TgError(f"{method}: still rate limited")

    # --- messages ---------------------------------------------------------------------------------------------------
    def send_message(self, text: str, reply_markup: Optional[dict] = None) -> List[int]:
        ids: List[int] = []
        parts = split_message(text or "")
        for i, part in enumerate(parts):
            payload = {"chat_id": self.chat_id, "text": part, "disable_web_page_preview": True}
            if reply_markup and i == len(parts) - 1:
                payload["reply_markup"] = reply_markup
            body = self.call("sendMessage", payload)
            mid = ((body.get("result") or {}).get("message_id"))
            if mid is not None:
                ids.append(int(mid))
        return ids

    def edit_message(self, message_id: int, text: str, reply_markup: Optional[dict] = None) -> bool:
        payload = {"chat_id": self.chat_id, "message_id": int(message_id), "text": text[:MAX_LEN], "disable_web_page_preview": True}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            self.call("editMessageText", payload)
        except TgError as e:
            if "not modified" in str(e).lower():
                return True
            return False
        return True

    def edit_markup(self, message_id: int, reply_markup: Optional[dict]) -> bool:
        """Replace (or with None remove) the buttons under a message."""
        try:
            self.call("editMessageReplyMarkup", {"chat_id": self.chat_id, "message_id": int(message_id),
                                                 "reply_markup": reply_markup or {"inline_keyboard": []}})
            return True
        except TgError:
            return False

    def delete_message(self, message_id: int) -> bool:
        try:
            self.call("deleteMessage", {"chat_id": self.chat_id, "message_id": int(message_id)})
            return True
        except TgError:
            return False

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            self.call("answerCallbackQuery", {"callback_query_id": callback_id, "text": text[:190]})
        except TgError:
            pass

    def chat_action(self, action: str = "typing") -> None:
        try:
            self.call("sendChatAction", {"chat_id": self.chat_id, "action": action})
        except TgError:
            pass

    # --- files ------------------------------------------------------------------------------------------------------
    def get_file(self, file_id: str) -> dict:
        body = self.call("getFile", {"file_id": file_id})
        r = body.get("result") or {}
        if not r.get("file_path"):
            raise TgError("getFile: no file_path in the answer")
        return {"file_path": r["file_path"], "file_size": r.get("file_size")}

    def download(self, file_path: str, dest: Path, max_bytes: int = FILE_LIMIT) -> int:
        url = f"https://api.telegram.org/file/bot{self._token}/{file_path}"
        try:
            return int(self.downloader(url, Path(dest), max_bytes))
        except TgError as e:
            raise TgError(self._clean(e)) from None
        except Exception as e:
            raise TgError(self._clean(f"download: {type(e).__name__}: {e}")) from None


def for_secrets(secrets, transport: Optional[Transport] = None, downloader: Optional[Downloader] = None) -> Optional[TgApi]:
    """The client for the investor's bot, or None when the token or chat id is missing. Without a transport: the real network, blocked in the workshop."""
    if secrets is None or not (secrets.has("telegram", "token") and secrets.has("telegram", "chat_id")):
        return None
    from pflab.service import telegram as tgm
    return TgApi(secrets.get("telegram", "token"), secrets.get("telegram", "chat_id"), transport or tgm.requests_transport, downloader)
