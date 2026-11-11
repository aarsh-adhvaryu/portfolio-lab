"""Portfolio construction (S79b item 18A), after A60 (2026-11-11).

`construct` (a shrunk-covariance optimiser that sized the paper book) was tested once against the current sizing rules (`docs/protocols/s79_construct_protocol.md`): inconclusive
(p 0.41) and never adopted, so the advice tool, the optimiser and the study driver were deleted (rule 10: what does not pass has no live feature). This package keeps

    risk.py     the Ledoit-Wolf shrunk covariance (read by `core/state.py` volatilities and `core/card.py`)
    costs.py    Zerodha charges and the estimated FIFO tax as per-side rates (read by `lab/runner.py`)
    compare.py  `clean`, the data-break filter `lab/runner.py:build_panel` uses
    here        the record of the registered study: its protocol hash and the counter row (the learner's counter N keeps it)
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[3]
PROTOCOL = REPO / "docs" / "protocols" / "s79_construct_protocol.md"
NOTE = "s79:construct"
TEMPLATE = "construct_s79"


def protocol_sha() -> str:
    if not PROTOCOL.exists():
        raise FileNotFoundError(f"the protocol file is missing: {PROTOCOL}")
    return hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()


def register(con, now: datetime) -> bool:
    """Count the comparison in the learner's counter once (origin 'study', note 's79:construct'; idempotent). The protocol file must exist and is committed before any run.
    Returns True when a row was added."""
    from pflab.learner import counter
    if con.execute("SELECT 1 FROM learn_tests WHERE note=?", [NOTE]).fetchone():
        return False
    counter.record(con, now, "study", TEMPLATE, {"protocol": "docs/protocols/s79_construct_protocol.md", "protocol_sha256": protocol_sha()}, note=NOTE)
    return True


def registered_sha(con) -> Optional[str]:
    r = con.execute("SELECT params_json FROM learn_tests WHERE note=?", [NOTE]).fetchone()
    return None if r is None else json.loads(r[0] or "{}").get("protocol_sha256")


def protocol_ok(con) -> dict:
    """{'registered', 'unchanged'}: was the study counted, and is the protocol file the one that was counted."""
    reg = registered_sha(con)
    try:
        now = protocol_sha()
    except FileNotFoundError:
        return {"registered": reg is not None, "unchanged": False, "why": "the protocol file is missing"}
    return {"registered": reg is not None, "unchanged": reg == now, "why": None if reg == now else ("not registered yet" if reg is None else "the protocol file changed after it was registered")}
