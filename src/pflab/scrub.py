"""Secrets by their shape (S68): text that is written to a store row, a job result or a log is scrubbed of anything that looks like a
credential, whether or not the secrets file is at hand. `pm/secrets.Secrets.redact` masks the values it holds; this masks the patterns,
so a token that came back inside an exception text (a Telegram URL in a ConnectionError) never reaches `job_runs`, `app.log` or a model.

    Telegram bot token   bot<digits>:<35 chars>  (also inside a URL)
    Anthropic key        sk-ant-...
    Kite                 access_token / api_secret / request_token = value
    a generic header     Authorization: Bearer ...
"""
from __future__ import annotations

import logging
import re
from typing import Tuple

MASK = "***"
PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9])bot\d{6,}:[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?<![A-Za-z0-9])\d{8,12}:AA[A-Za-z0-9_-]{30,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?i)\b(access_token|api_secret|request_token|enctoken)\b(\s*[=:]\s*)[\"']?[A-Za-z0-9._-]{8,}[\"']?"),
    re.compile(r"(?i)\b(authorization)\b(\s*[:=]\s*)(?:bearer\s+)?[A-Za-z0-9._~+/=-]{12,}"),
]


def scrub(text) -> str:
    out = str(text)
    for rx in PATTERNS:
        if rx.groups:
            out = rx.sub(lambda m: m.group(1) + m.group(2) + MASK, out)
        else:
            out = rx.sub(MASK, out)
    return out


class Filter(logging.Filter):
    """A logging filter: the message and its arguments are scrubbed before any handler writes them."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = scrub(record.getMessage())
            record.args = None
            if record.exc_info:
                import traceback
                record.msg += "\n" + scrub("".join(traceback.format_exception(*record.exc_info)))
                record.exc_info = None
                record.exc_text = None
        except Exception:
            pass
        return True


def install(handler_owner: logging.Logger = None) -> None:
    """Put the filter on every handler of the root logger (called once, where the log file is opened)."""
    root = handler_owner or logging.getLogger()
    for h in root.handlers:
        if not any(isinstance(f, Filter) for f in h.filters):
            h.addFilter(Filter())


# columns the stores keep free text in: (table, key column, text columns)
STORE_TEXT = [("job_runs", "run_id", ("detail",)), ("api_calls", "call_id", ("error", "question")),
              ("hq_tool_calls", "call_no", ("args_json", "result")), ("hq_passes", "pass_id", ("error", "note"))]


def scrub_store(con) -> Tuple[int, int]:
    """Rewrite the rows that hold a credential-shaped string. Idempotent; returns (rows changed, tables looked at). A missing table or
    column is skipped (an older store)."""
    changed = looked = 0
    for table, key, cols in STORE_TEXT:
        have = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name=?", [table]).fetchall()}
        for col in cols:
            if col not in have or key not in have:
                continue
            looked += 1
            for k, v in con.execute(f"SELECT {key}, {col} FROM {table} WHERE {col} IS NOT NULL").fetchall():
                new = scrub(v)
                if new != v:
                    con.execute(f"UPDATE {table} SET {col}=? WHERE {key}=?", [new, k])
                    changed += 1
    return changed, looked


def scrub_file(path) -> int:
    """Rewrite a text log in place when it holds a credential-shaped string (done once at start). Returns the lines changed."""
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return 0
    raw = p.read_text(encoding="utf-8", errors="replace").split("\n")
    out = [scrub(l) for l in raw]
    n = sum(a != b for a, b in zip(raw, out))
    if n:
        p.write_text("\n".join(out), encoding="utf-8")
    return n
