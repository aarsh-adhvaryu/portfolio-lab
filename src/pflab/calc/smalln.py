"""The small-numbers rule (PLAN A9, the investor 2026-10-22: the law of large numbers holds at scale, not at small n).

Every statistic shown carries its n. A rate or average from fewer than MIN_N observations is shown as a count and
never drives an action; an annualised figure needs MIN_SESSIONS sessions; a simulated tail chance is shown only when its
standard error is at most MAX_SE_PP percentage points; an event study needs MIN_EVENTS events.
"""
from __future__ import annotations

import math
from typing import Optional

MIN_N, MIN_SESSIONS, MAX_SE_PP, MIN_EVENTS = 20, 250, 0.5, 5


def rate(k: int, n: int) -> dict:
    """k of n: a percentage only from MIN_N observations, else the count."""
    ok = n >= MIN_N
    return {"text": (f"{k / n:.0%}" if ok else f"{k} of {n}") if n else "none yet", "n": n, "actionable": ok}


def average(value: Optional[float], n: int, fmt: str = "{:.2f}") -> dict:
    ok = n >= MIN_N and value is not None and math.isfinite(value)
    return {"text": fmt.format(value) if ok else f"too few ({n})", "n": n, "actionable": ok}


def annualised(value: Optional[float], sessions: int) -> dict:
    ok = sessions >= MIN_SESSIONS and value is not None and math.isfinite(value)
    return {"text": f"{value:.1%}" if ok else f"needs {MIN_SESSIONS} sessions ({sessions})", "n": sessions, "actionable": ok}


def tail(p: Optional[float], paths: int) -> dict:
    """A simulated chance with its standard error, shown only when the error is small enough."""
    if p is None or not paths:
        return {"text": "not run yet", "n": 0, "se_pp": None, "actionable": False}
    if p == 0:                                     # no path at all: say so, with the rule-of-three bound (95%)
        return {"text": f"no path in {paths:,} (under {300 / paths:.2g}%)", "n": paths, "se_pp": None, "actionable": True}
    se = math.sqrt(max(p * (1 - p), 0.0) / paths) * 100
    ok = se <= MAX_SE_PP
    return {"text": f"{p:.1%} ± {se:.2f} pp" if ok else "needs more paths", "n": paths, "se_pp": se, "actionable": ok}


def events(k: int) -> dict:
    ok = k >= MIN_EVENTS
    return {"text": f"{k} events" if ok else f"only {k} events: not enough", "n": k, "actionable": ok}
