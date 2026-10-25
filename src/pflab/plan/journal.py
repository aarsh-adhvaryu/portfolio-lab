"""Proposal log (PLAN S17 first cut; S29 adds the scoreboard). Every proposal is stored with a
SHA-256 of its evidence, and the investor's choice and reason are recorded separately. Nothing here
executes anything."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Optional


def evidence_sha(evidence: dict) -> str:
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()


def log_proposal(con, kind: str, asof: date, evidence: dict, alternatives: Optional[dict] = None,
                 now: Optional[datetime] = None) -> int:
    from pflab.pm.store import next_id
    pid = next_id(con, "proposals", "proposal_id")
    con.execute("INSERT INTO proposals VALUES (?,?,?,?,?,?,?)",
                [pid, kind, asof, evidence_sha(evidence), json.dumps(evidence, sort_keys=True, default=str),
                 json.dumps(alternatives or {}, sort_keys=True, default=str), now or datetime.now()])
    return pid


def record_decision(con, proposal_id: int, choice: str, reason: str = "", now: Optional[datetime] = None) -> None:
    if not con.execute("SELECT 1 FROM proposals WHERE proposal_id=?", [proposal_id]).fetchone():
        raise KeyError(f"no proposal {proposal_id}")
    con.execute("INSERT INTO decisions VALUES (?,?,?,?)", [proposal_id, choice, reason, now or datetime.now()])


def save_targets(con, targets) -> None:
    from pflab.pm.store import transaction
    with transaction(con):                               # all or nothing (S58 drill 2)
        con.execute("DELETE FROM targets")
        for b in targets.buckets.values():
            con.execute("INSERT INTO targets VALUES (?,?,?,?,?,?,?)",
                        [b.bucket, b.target, b.soft_band, b.hard_band, targets.effective_from, targets.set_by,
                         json.dumps(list(b.buy))])
