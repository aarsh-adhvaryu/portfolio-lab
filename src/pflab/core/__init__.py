"""The v2 core (S80, redesign of 2026-11-08): the close loop, the policy that decides the paper book's target weights, and the rails that clip them.

    state.py   what the loop sees at a close: the book, the shrunk-covariance risk model, the allocation target, the fall gauge, the circuit breaker (code)
    policy.py  `decide(state) -> target weights`: the champion policy (phase 1: the baseline, which needs no proven edge)
    rails.py   code outside the policy: the position rails, the circuit breaker, the turnover caps and the cost-and-tax filter; turns weights into orders
    loop.py    perceive -> state -> decide -> check -> act -> score, once per closed session (no model, no paid call)

The numbers live in `configs/core.toml`. One switch (`[core] on`) stops the loop; the book, the scoring and the data collection go on.
"""
from __future__ import annotations

from pathlib import Path

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "core.toml"

DEFAULTS = {
    "core": {"on": True, "retire_missions": True, "advisors_off": True, "kill": False},
    "strategist": {"on": True, "session_rupees": 300.0, "min_session_rupees": 40.0, "weekly_days": 7, "max_turns": 18, "model": "claude-opus-5-5", "weeks_to_win": 8},
    "checker": {"on": True, "big_trade_share": 0.05, "model": "claude-sonnet-5-5"},
    "tactical": {"on": True, "start_share": 0.10, "high_share": 0.20, "low_share": 0.05, "views_to_judge": 20},
    "rails": {"turnover_day": 0.10, "turnover_month": 0.40, "min_trade_rupees": 2000.0, "max_cost_share": 0.02},
    "baseline": {"band_pts": 1.5, "vol_window": 250, "gauge_drawdown": 0.10, "gauge_below_ma": 200, "gauge_cut": 0.25},
}


def settings() -> dict:
    """The three tables with their defaults, overridden by `configs/core.toml` (an unreadable file leaves the defaults)."""
    out = {k: dict(v) for k, v in DEFAULTS.items()}
    try:
        from pflab import _toml
        for k, v in _toml.load(CONFIG).items():
            if k in out and isinstance(v, dict):
                out[k].update(v)
    except Exception:
        pass
    return out


def on() -> bool:
    """The close loop is on. `[core] kill = true` is the one kill switch: it stops all trading and all AI sessions; the book, scoring and data collection go on."""
    c = settings()["core"]
    return bool(c["on"]) and not bool(c.get("kill"))


def killed() -> bool:
    return bool(settings()["core"].get("kill"))


def strategist_on() -> bool:
    return on() and bool(settings()["strategist"]["on"])


def missions_retired() -> bool:
    s = settings()["core"]
    return bool(s["on"]) and bool(s["retire_missions"])


def advisors_off() -> bool:
    """The v1 advisor layers (readers, brain passes, mission scans, file investigations, the daily review's and the companion's proposals) are switched off while the loop is on.
    Switched off, not deleted: deletion waits for two clean weeks (phase 4)."""
    s = settings()["core"]
    return bool(s["on"]) and bool(s.get("advisors_off", True))
