"""Telegram notifications: a durable outbox and a send-only client (PLAN S9, §5).

Decision 2026-10-06 (PLAN §10): send-only use of the Bot API over `requests` (a core dependency);
`python-telegram-bot` is not added because nothing here receives commands. Every message is written
to the `outbox` table first, then sent: a message that cannot be delivered stays queued and shows
as undelivered on the health page; it is never silently dropped. Token and chat id come from the
secrets file; nothing here logs them.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from pflab import _toml

MAX_LEN = 4096
MAX_ATTEMPTS = 5
RETRY_AFTER_CAP = 60

Transport = Callable[[str, Dict], Tuple[int, dict]]     # (url, payload) -> (http status, json body)


class TelegramNotConfigured(RuntimeError):
    pass


def split_message(text: str, limit: int = MAX_LEN) -> List[str]:
    """Break on line boundaries where possible; no part exceeds `limit` characters."""
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            parts.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + (1 if cur else 0) > limit:
            parts.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        parts.append(cur)
    return parts


def requests_transport(url: str, payload: Dict) -> Tuple[int, dict]:
    from pflab import guard
    guard.require("telegram")                       # S65: the workshop never sends outward unless run with --live
    import requests
    r = requests.post(url, json=payload, timeout=15)
    try:
        body = r.json()
    except ValueError:
        body = {}
    return r.status_code, body


def make_sender(secrets, transport: Optional[Transport] = None, sleep: Callable[[float], None] = time.sleep
                ) -> Callable[[str], None]:
    """send(text): one message, split if long. Raises TelegramNotConfigured without a token and chat id,
    and RuntimeError on a failed send (with the token scrubbed from the message)."""
    if secrets is None or not (secrets.has("telegram", "token") and secrets.has("telegram", "chat_id")):
        def unconfigured(text: str) -> None:
            raise TelegramNotConfigured("telegram token and chat_id are not in the secrets file")
        return unconfigured
    if transport is None:                           # S65: the real network path: blocked in the workshop, everything stays pending
        from pflab import guard
        why = guard.blocked("telegram")
        if why:
            def workshop(text: str) -> None:
                raise TelegramNotConfigured(why)
            return workshop
    token, chat = secrets.get("telegram", "token"), secrets.get("telegram", "chat_id")
    transport = transport or requests_transport
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    def send(text: str) -> None:
        for part in split_message(text):
            payload = {"chat_id": chat, "text": part, "disable_web_page_preview": True}
            for attempt in range(2):
                status, body = transport(url, payload)
                if status == 200 and body.get("ok", True):
                    break
                if status == 429 and attempt == 0:
                    sleep(min(float((body.get("parameters") or {}).get("retry_after", 1)), RETRY_AFTER_CAP))
                    continue
                raise RuntimeError(secrets.redact(f"telegram HTTP {status}: {body.get('description', body)}"))
            else:
                raise RuntimeError("telegram rate limit: still 429 after waiting")

    return send


# --- outbox --------------------------------------------------------------------------------------------------

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "telegram.toml"


def goes_at_once(kind: str, config: Optional[Path] = None) -> bool:
    """True for an urgent or direct kind (configs/telegram.toml); any other kind waits for the summaries. Without the
    file everything goes at once (the behaviour before S64)."""
    p = config or CONFIG
    if not p.exists():
        return True
    c = _toml.load(p)
    return kind in set(c.get("urgent", [])) | set(c.get("direct", []))


def enqueue(con, text: str, kind: str = "alert", dedup_key: Optional[str] = None,
            now: Optional[datetime] = None) -> Optional[int]:
    """Queue a message. A `dedup_key` already in the outbox is not queued again (returns None). A kind that does not
    matter today is stored as 'held' for the summaries (S64)."""
    if dedup_key and con.execute("SELECT 1 FROM outbox WHERE dedup_key=?", [dedup_key]).fetchone():
        return None
    from pflab.pm.store import next_id
    mid = next_id(con, "outbox", "msg_id")
    con.execute("INSERT INTO outbox VALUES (?,?,?,?,?,?,?,?,?)",
                [mid, now or datetime.now(), kind, text, dedup_key, "pending" if goes_at_once(kind) else "held", 0, None, None])
    return mid


def pending(con) -> List[tuple]:
    return con.execute("SELECT msg_id, kind, text, attempts FROM outbox WHERE status='pending' ORDER BY msg_id").fetchall()


def flush(con, send: Callable[[str], None], now: Optional[datetime] = None, max_attempts: int = MAX_ATTEMPTS) -> dict:
    """Try every pending message once, oldest first. Success marks it sent; a failure counts an attempt and
    keeps it pending until `max_attempts`, then marks it failed (still listed as undelivered). A
    TelegramNotConfigured error leaves everything pending and stops (nothing can be sent)."""
    now = now or datetime.now()
    out = {"sent": 0, "still_pending": 0, "failed": 0}
    for mid, kind, text, attempts in pending(con):
        try:
            send(text)
        except TelegramNotConfigured as e:
            out["still_pending"] = len(pending(con))
            out["error"] = str(e)
            return out
        except Exception as e:
            attempts += 1
            status = "failed" if attempts >= max_attempts else "pending"
            con.execute("UPDATE outbox SET attempts=?, last_error=?, status=? WHERE msg_id=?", [attempts, str(e), status, mid])
            out["failed" if status == "failed" else "still_pending"] += 1
            continue
        con.execute("UPDATE outbox SET status='sent', sent_at=?, attempts=attempts+1 WHERE msg_id=?", [now, mid])
        out["sent"] += 1
    return out


def drop_before(con, before: datetime) -> int:
    """Mark held messages queued before `before` as dropped (S58b switch-on: stale ones never go out). Kept, not
    deleted, so `pflab pm alerts --all` still shows them."""
    n = con.execute("SELECT count(*) FROM outbox WHERE status IN ('pending','held') AND created_at < ?", [before]).fetchone()[0]
    con.execute("UPDATE outbox SET status='dropped' WHERE status IN ('pending','held') AND created_at < ?", [before])
    return n


def undelivered(con) -> int:
    return con.execute("SELECT count(*) FROM outbox WHERE status IN ('pending','failed')").fetchone()[0]


# --- formatting --------------------------------------------------------------------------------------------------------

def format_test() -> str:
    return "Portfolio Manager: test alert. If you can read this, Telegram delivery works. No action needed."


def format_job_failure(job: str, detail: str, when: datetime) -> str:
    return f"Portfolio Manager: job '{job}' failed at {when:%d-%b-%Y %H:%M}.\n{detail[:500]}\nSee: pflab service status"
