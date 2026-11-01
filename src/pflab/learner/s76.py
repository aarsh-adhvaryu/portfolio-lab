"""The S76 claims (docs/protocols/s76_learner_protocol.md): after a fall, hold or sell, with a confirmation window; rebalancing bands with gold.

`register_all` turns each into a pre-registered claim (origin `study`, once: an existing one is reused). The learner's nightly cycle registers and tests them like
any claim, three a night, inside the counter.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict

from pflab.learner import claims

PROTOCOL = "docs/protocols/s76_learner_protocol.md"
_F = "Nifty 500 stocks that have fallen 30% or more below their one-year high"
FALL = [
    (0, "out", f"{_F} rebound: over the next three months they earn more than the other members, so holding after the fall pays."),
    (0, "under", f"{_F} keep lagging: over the next three months they earn less than the other members, so selling at once pays."),
    (20, "out", f"{_F}, and are still that far down after a month, rebound over the next three months: holding pays."),
    (20, "under", f"{_F}, and are still that far down after a month, keep lagging over the next three months: selling after a month pays."),
    (60, "out", f"{_F}, and are still that far down after a quarter, rebound over the next three months: holding pays."),
    (60, "under", f"{_F}, and are still that far down after a quarter, keep lagging over the next three months: selling after a quarter pays."),
]
_MIX = {"60_20_20": "60% equity, 20% gold and 20% cash", "70_30_0": "70% equity and 30% gold"}
BANDS = [
    ("60_20_20", 5, "never", "month_end"), ("60_20_20", 10, "never", "month_end"), ("60_20_20", 20, "never", "month_end"),
    ("60_20_20", 10, "monthly", "month_end"), ("60_20_20", 10, "never", "daily"), ("70_30_0", 10, "never", "month_end"),
]


def band_claim(mix: str, band: int, against: str, check: str) -> str:
    other = "a portfolio left alone after it was bought" if against == "never" else "one set back to its weights at every month end"
    when = "checked on every trading day" if check == "daily" else "checked at each month end"
    return (f"A portfolio of {_MIX[mix]}, rebalanced only when a weight drifts {band} points from its target ({when}), earns more after charges and tax than "
            f"{other}, and its worst fall is at most as deep.")


def register_all(con, proto_dir: Path, now: datetime) -> Dict[str, str]:
    out = {}
    for confirm, direction, text in FALL:
        p = {"depth": 30, "confirm": confirm, "direction": direction, "months": 3}
        cid = claims.register_study(con, "fall_response", p, text, "Members whose adjusted close was at least 30% below its 252-session high on each of the last "
                                    f"{confirm + 1} session(s), against all members, three months ahead.", f"S76 pre-registered study: after a fall, confirm {confirm}, {direction}",
                                    PROTOCOL, now)
        out[f"fall:{confirm}:{direction}"] = _state(con, cid, proto_dir, now)
    for mix, band, against, check in BANDS:
        p = {"mix": mix, "band": band, "against": against, "check": check}
        cid = claims.register_study(con, "rebalance_bands", p, band_claim(mix, band, against, check),
                                    "Nifty 500 total return, the gold ETF and cash at 7%, rebalanced at a band, against the other policy, monthly net returns.",
                                    f"S76 pre-registered study: rebalancing bands {mix} {band} {against} {check}", PROTOCOL, now)
        out[f"bands:{mix}:{band}:{against}:{check}"] = _state(con, cid, proto_dir, now)
    return out


def _state(con, cid: int, proto_dir: Path, now: datetime) -> str:
    status = con.execute("SELECT status FROM learn_claims WHERE claim_id=?", [cid]).fetchone()[0]
    return f"claim #{cid}: " + (claims.register(con, cid, proto_dir, now) if status == "proposed" else status)
