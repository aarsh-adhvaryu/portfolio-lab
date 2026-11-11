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
    "strategist": {"on": True, "session_rupees": 300.0, "min_session_rupees": 40.0, "weekly_days": 7, "max_turns": 18, "model": "claude-opus-5-5", "weeks_to_win": 8,
                   "throttle_after": "2026-12-09"},
    # S81 (A48): the baseline for the close loop. "v2" holds the core ETFs and buys them from the first close; "v1" is the old one (the safe fallback).
    "baseline_v2": {"version": "v2", "core_pct": 60.0, "longterm_pct": 40.0, "longterm_buy_pct": 35.0, "gold_pct": 10.0, "international_pct": 10.0,
                    "index_etfs": ["MONIFTY500", "NIFTYBEES", "JUNIORBEES"], "gold_etfs": ["GOLDBEES"], "international_etfs": ["MON100"],
                    "index_fallback": True},
    # S81 (A50): the satellite slices of lab variants on probation.
    "probation": {"start_share": 0.05, "steps": [0.05, 0.10, 0.20], "sessions_to_grow": [20, 40], "max_total_share": 0.20, "tolerance": 0.002, "min_sessions_to_judge": 10},
    "checker": {"on": True, "big_trade_share": 0.05, "model": "claude-sonnet-5-5"},
    "tactical": {"on": True, "start_share": 0.10, "high_share": 0.20, "low_share": 0.05, "views_to_judge": 20},
    "rails": {"turnover_day": 0.10, "turnover_month": 0.40, "min_trade_rupees": 2000.0, "max_cost_share": 0.02},
    "baseline": {"band_pts": 1.5, "vol_window": 250, "gauge_drawdown": 0.10, "gauge_below_ma": 200, "gauge_cut": 0.25},
    # S83 L1/L5 (A61-A63): the picks sleeve; read through `core.picks.settings()` (it merges the nested market tables, which `settings()` here would replace whole)
    "picks": {"on": True, "judge_every_sessions": 60, "window_sessions": 120, "behind_points": 2.0, "min_liquidity_inr": 50000000, "us_floor_price": 5, "us_floor_value_usd": 2000000,
              "us_max_stocks": 12, "us_stock_cap": 0.10, "us_spy_floor": 0.30,
              "in": {"on": True, "start_share": 0.40, "min_share": 0.20, "max_share": 0.60, "step": 0.05},
              "us": {"on": False, "start_share": 0.50, "min_share": 0.30, "max_share": 0.70, "step": 0.05}},
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


def baseline_version() -> str:
    """Which baseline decides the close loop when no lab champion does: 'v2' (core ETFs and the longterm names, A48) or 'v1' (the S80 baseline, the safe fallback)."""
    v = str(settings()["baseline_v2"].get("version", "v2")).lower()
    return "v1" if v == "v1" else "v2"


def throttle_active(day) -> bool:
    """A55: the strategist's budget-halving rules are applied only from `[strategist] throttle_after` (release date plus 28 days: 2026-12-09). Before it they are recorded, not applied."""
    from datetime import date, datetime
    raw = settings()["strategist"].get("throttle_after")
    try:
        after = raw if isinstance(raw, date) and not isinstance(raw, datetime) else (raw.date() if isinstance(raw, datetime) else date.fromisoformat(str(raw)[:10]))
    except Exception:
        return True                                                        # an unreadable date applies the rules: the safe side for the money
    d = day.date() if isinstance(day, datetime) else day
    return d >= after
