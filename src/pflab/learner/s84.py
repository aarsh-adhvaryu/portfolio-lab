"""S84: this session's pre-registered study in the learner's counter (rule 10), modelled on `learner/s83.py`.

    register_thinking_live(con, now)   the thinking loop's LIVE test: `docs/protocols/s84_thinking_live_protocol.md` (committed before the first live case), counted ONCE (idempotent by note
                                       key; the protocol's SHA-256 with line ends normalised is stored). Called when the app starts (`app/runtime.py`).
    protocol_ok(con)                   {registered, unchanged}: was it counted, and is the file the one that was counted
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parents[3]
PROTOCOL = REPO / "docs" / "protocols" / "s84_thinking_live_protocol.md"
PROTOCOL_REL = "docs/protocols/s84_thinking_live_protocol.md"
TEMPLATE = "thinking_live_s84"
NOTE = "s84:thinking_live"
WHAT = "the thinking loop's rule beats doing nothing after tax and charges, measured live (scored at 5, 20 and 60 sessions)"


def protocol_sha() -> str:
    """SHA-256 of the protocol with its line ends normalised (a checkout that turns LF into CRLF must not look like an edit)."""
    if not PROTOCOL.exists():
        raise FileNotFoundError(f"the protocol file is missing: {PROTOCOL}")
    return hashlib.sha256(PROTOCOL.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def register_thinking_live(con, now: datetime) -> List[str]:
    """Count the live test (origin 'study'); idempotent by note key. Nothing is counted if the protocol file is missing."""
    from pflab.learner import counter
    if not PROTOCOL.exists():
        return []
    if con.execute("SELECT 1 FROM learn_tests WHERE note=?", [NOTE]).fetchone():
        return []
    counter.record(con, now, "study", TEMPLATE, {"protocol": PROTOCOL_REL, "protocol_sha256": protocol_sha()}, note=NOTE)
    return [NOTE]


def protocol_ok(con) -> dict:
    r = con.execute("SELECT params_json FROM learn_tests WHERE note=?", [NOTE]).fetchone()
    registered = r is not None
    stored = json.loads(r[0] or "{}").get("protocol_sha256") if registered else None
    try:
        now = protocol_sha()
    except FileNotFoundError:
        return {"registered": registered, "unchanged": False, "why": "the protocol file is missing"}
    same = registered and stored == now
    return {"registered": registered, "unchanged": bool(same), "why": None if same else ("not registered yet" if not registered else "the protocol file changed after it was registered")}
