"""S83: this session's pre-registered studies in the learner's counter (rule 10), modelled on `lab/swing_study.register`.

    register_picks_live(con, now)   the picks sleeve's LIVE test, one per market (India, US): `docs/protocols/s83_picks_live_protocol.md` (committed before the first pick), counted once
                                    (idempotent by note key; the protocol's SHA-256 with line ends normalised is stored). Called when the app starts (`app/runtime.py`).
    protocol_ok(con)                {registered, unchanged}: was it counted, and is the file the one that was counted
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parents[3]
PROTOCOL = REPO / "docs" / "protocols" / "s83_picks_live_protocol.md"
PROTOCOL_REL = "docs/protocols/s83_picks_live_protocol.md"
TEMPLATE = "picks_live_s83"
STUDIES = (("s83:picks_live:IN", f"{TEMPLATE}:IN", "India: the longterm sleeve (his Kite stocks and the system's picks) beats the Nifty 500 after estimated tax, measured live"),
           ("s83:picks_live:US", f"{TEMPLATE}:US", "US: the system's US picks beat SPY in rupees after estimated tax, measured live"))


def protocol_sha() -> str:
    """SHA-256 of the protocol with its line ends normalised (a checkout that turns LF into CRLF must not look like an edit)."""
    if not PROTOCOL.exists():
        raise FileNotFoundError(f"the protocol file is missing: {PROTOCOL}")
    return hashlib.sha256(PROTOCOL.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def register_picks_live(con, now: datetime) -> List[str]:
    """Count the two live tests (origin 'study'); idempotent by note key. Nothing is counted if the protocol file is missing."""
    from pflab.learner import counter
    if not PROTOCOL.exists():
        return []
    sha, done = protocol_sha(), []
    for note, template, _what in STUDIES:
        if con.execute("SELECT 1 FROM learn_tests WHERE note=?", [note]).fetchone():
            continue
        counter.record(con, now, "study", template, {"protocol": PROTOCOL_REL, "protocol_sha256": sha}, note=note)
        done.append(note)
    return done


def protocol_ok(con) -> dict:
    rows = con.execute("SELECT note, params_json FROM learn_tests WHERE note IN (%s)" % ",".join("?" for _ in STUDIES), [n for n, _, _ in STUDIES]).fetchall()
    shas = {n: json.loads(p or "{}").get("protocol_sha256") for n, p in rows}
    try:
        now = protocol_sha()
    except FileNotFoundError:
        return {"registered": len(shas) == len(STUDIES), "unchanged": False, "why": "the protocol file is missing"}
    ok = len(shas) == len(STUDIES)
    same = ok and all(v == now for v in shas.values())
    return {"registered": ok, "unchanged": same, "why": None if same else ("not registered yet" if not ok else "the protocol file changed after it was registered")}
