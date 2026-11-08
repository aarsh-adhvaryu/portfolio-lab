"""Portfolio construction (S79b item 18A): the SIZING step of the paper team's flow.

    the paper team proposes a direction with reasons (`paper_decide`)  ->  `construct` sizes it  ->  the independent reviewer checks  ->  code executes.

`construct` turns the ensemble forecast (an expected return and a dispersion per name, `fcast`) and a shrunk-covariance risk model (`risk.py`) into target weights through
a constrained optimiser (`optimiser.py`): the hard rails are constraints, Zerodha charges and the estimated tax of realising gains (`costs.py`) are in the objective, and the
book is pulled toward the system's own allocation target (`paper/allocation.py`). It never chooses a direction and never trades: the output is weights and the trades they
imply, and the manager's own execution path (rails, cash, fills, tax) is unchanged. The current sizing rules stay the fallback and decide whenever `construct` is off, not
adopted, or fails.

Two switches in `configs/s79b.toml [construct]`: `on` (the tool exists and shows its advice, labelled "not adopted") and `adopt` (the manager sizes live decisions with it;
needs `on`, AND the stored verdict "adopt" of the registered comparison `docs/protocols/s79_construct_protocol.md`, run by `compare.py`).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[3]
PROTOCOL = REPO / "docs" / "protocols" / "s79_construct_protocol.md"
CONFIG = REPO / "configs" / "s79b.toml"
NOTE = "s79:construct"
TEMPLATE = "construct_s79"

DEFAULTS = {"on": True, "adopt": False, "risk_aversion": 2.5, "equity_premium": 0.05, "tilt_cap": 0.30, "horizon": 20, "window": 250, "vol_blend": 0.5, "fallback_vol": 0.30,
            "cash_rate": 0.07, "lambda_target": 5.0, "band_pct": 2.0, "turnover_penalty": 0.0005, "forecast_max_age_days": 10, "freeze_no_forecast": True}


def settings() -> dict:
    """`[construct]` of configs/s79b.toml over the defaults above. A missing file or table gives the defaults (on, not adopted)."""
    out = dict(DEFAULTS)
    try:
        from pflab import _toml
        out.update({k: v for k, v in (_toml.load(CONFIG).get("construct") or {}).items() if k in DEFAULTS})
    except Exception:
        pass
    return out


def is_on() -> bool:
    return bool(settings()["on"])


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


def verdict(con) -> Optional[dict]:
    """The stored verdict of the registered backtest comparison (the latest 'compare' run), or None when it has not been run."""
    try:
        r = con.execute("SELECT summary_json, as_of, created_at FROM construct_runs_s85 WHERE kind='compare' ORDER BY run_id DESC LIMIT 1").fetchone()
    except Exception:
        return None
    if not r:
        return None
    d = json.loads(r[0] or "{}")
    d["run_at"] = str(r[2])[:16]
    return d


def adopted(con) -> bool:
    """True only when `on`, `adopt` are both set AND the stored comparison verdict is 'adopt' AND the protocol file is the registered one."""
    s = settings()
    if not (s["on"] and s["adopt"]):
        return False
    v = verdict(con)
    return bool(v and v.get("verdict") == "adopt" and protocol_ok(con)["unchanged"])
