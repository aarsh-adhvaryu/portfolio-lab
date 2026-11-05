"""S79 (rule 10): the studies this session pre-registered count in the learner's counter the moment they are registered (the bar rises with N).
Idempotent by note key. The forecast study registers itself in `fcast/protocol.py`; the local-model comparison in `llm/` (its own protocol)."""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import List

from pflab.learner import counter

REPO = Path(__file__).resolve().parents[3]
STUDIES = (
    ("s79:debate_bear_warnings", "bear_warnings_s79", "docs/protocols/s79_debate_protocol.md", "bull/bear debate: the bear's warnings beat the base rate (scored by code)"),
    ("s79:implied_calibration", "implied_calibration:scale_k", "docs/protocols/implied_calibration_protocol.md", "option-implied fall probability, calibrated against realised outcomes"),
)


def register_all(con, now: datetime) -> List[str]:
    done = []
    for key, template, doc, what in STUDIES:
        p = REPO / doc
        if not p.exists() or con.execute("SELECT 1 FROM learn_tests WHERE note=?", [key]).fetchone():
            continue
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        counter.record(con, now, "study", template, {"protocol": doc, "protocol_sha256": sha}, note=key)
        done.append(key)
    return done
