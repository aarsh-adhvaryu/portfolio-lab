"""S79 predict, score, correct: the constants fixed by `docs/protocols/s79_forecast_protocol.md` and its registration in the learner's counter.

Nothing here is tuned after a run. The registration writes one row per market into `learn_tests` (origin "study", note `forecast_s79:<M>`) with the
SHA-256 of the protocol file in its parameters; `verdict` refuses to run if the file changed since (an amendment is dated and re-registered)."""
from __future__ import annotations

import hashlib
from datetime import date, datetime
from pathlib import Path
from typing import Tuple

LEVELS: Tuple[float, ...] = (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95)
HORIZONS: Tuple[int, ...] = (1, 5, 20)
MARKETS: Tuple[str, ...] = ("IN", "US")
FORECASTERS = ("naive", "volatility", "momentum", "reversion", "overnight")
BENCHMARK = "naive"
COMBINED = "hedge"
MIN_LIVE = 60                       # live sessions per market and horizon before any verdict
COVER_LO, COVER_HI = 0.75, 0.85     # the 80% range must cover this share of outcomes
FLOOR = 0.03                        # no forecaster's weight falls below this
EWMA_LAMBDA = 0.94
SIGMA_WINDOW, SIGMA_MIN = 250, 120
MOM_WINDOW, REV_WINDOW = 126, 50
TILT = 0.1                          # momentum and reversion move the centre by at most this many sigma
BETA_WINDOW, BETA_MIN = 500, 250
FALL_X, FALL_H = 0.05, 20          # a fall: a close >= 5% under the forecast date's close, within 20 sessions
FALL_MIN_N = 20                     # below this many resolved outcomes: show n, no conclusion
REPLAY_START, REPLAY_END = date(2012, 1, 1), date(2021, 12, 31)
SPENT_START, SPENT_END = date(2022, 1, 1), date(2025, 12, 31)
PROTOCOL = Path(__file__).resolve().parents[3] / "docs" / "protocols" / "s79_forecast_protocol.md"


def eta(h: int) -> float:
    """Hedge learning rate: slow, and slower for the longer (overlapping) horizons."""
    return 1.0 / max(int(h), 1)


def protocol_sha() -> str:
    if not PROTOCOL.exists():
        raise FileNotFoundError(f"the protocol file is missing: {PROTOCOL}")
    return hashlib.sha256(PROTOCOL.read_bytes()).hexdigest()


def note_key(market: str) -> str:
    return f"forecast_s79:{market}"


def register(con, now: datetime) -> int:
    """Count the claim of each market in the learner's counter (once each; the protocol file must exist). Returns how many were added."""
    from pflab.learner import counter
    sha = protocol_sha()
    have = {r[0] for r in con.execute("SELECT note FROM learn_tests").fetchall()}
    n = 0
    for m in MARKETS:
        if note_key(m) not in have:
            counter.record(con, now, "study", "forecast_s79", {"market": m, "protocol_sha256": sha, "horizons": list(HORIZONS),
                                                               "levels": list(LEVELS), "min_live": MIN_LIVE}, note=note_key(m))
            n += 1
    return n


def registered_sha(con, market: str):
    import json
    r = con.execute("SELECT params_json FROM learn_tests WHERE note=?", [note_key(market)]).fetchone()
    return None if r is None else json.loads(r[0] or "{}").get("protocol_sha256")


def refuse_spent(d) -> None:
    """2022-2025 is spent (CLAUDE.md 2): no replay date may fall in it, and none may be after the replay's end."""
    d = d.date() if isinstance(d, datetime) else d
    if SPENT_START <= d <= SPENT_END:
        raise ValueError(f"{d}: 2022-2025 is spent and never used (S79 protocol, history replay)")
    if d > REPLAY_END:
        raise ValueError(f"{d}: the history replay ends {REPLAY_END}")
    if d < REPLAY_START:
        raise ValueError(f"{d}: the history replay starts {REPLAY_START}")
