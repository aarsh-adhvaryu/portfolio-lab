"""The thinking loop (S84, A64-A68): NOTICE (code) -> UNDERSTAND (model) -> OPTIONS (a closed list) -> OUTCOMES (worst, likely, best in rupees, by code) -> DECIDE AND ACT (a registered rule in
code, inside the rails) -> COME BACK AND LEARN. One loop for any situation. Rule 8: the model reads, connects and names (a class, an option, a likelihood WORD from a closed list); every rupee,
size, price and probability comes from code. Rule 10: the loop is a registered LIVE test (`docs/protocols/s84_thinking_live_protocol.md`) with a safe fallback (advisory mode).

    cases.py    the store (signals, cases, steps, options, decisions, scores, freezes) and its plain API: every other module reads and writes cases only through it
    watch.py    T1 NOTICE (code, no model, no cost)             odds.py   T4 OUTCOMES in rupees, base rates        rule.py   T5 DECIDE (the registered rule)
    session.py  T3 UNDERSTAND and choose, T6 act and tell      score.py  T8 score, calibrate               desk.py   T10 the daily desk
    recall.py   T2x what we already know (read by T3, T10, `company_card`, `propose_picks`)

Numbers live in `configs/core.toml [think]` (his to change), with the defaults below.
"""
from __future__ import annotations

from pathlib import Path

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "core.toml"

OPTIONS = ("sell", "trim", "hold", "freeze", "wait", "buy_in_parts", "nothing")          # the closed menu (T3)
CLASSES = ("market_fear", "temporary", "damage", "unclear")                              # the closed list of classes (T3)
WORDS = ("very unlikely", "unlikely", "even", "likely", "very likely")                   # the closed likelihood words (T3, T8)
WORD_P = {"very unlikely": 0.05, "unlikely": 0.25, "even": 0.50, "likely": 0.75, "very likely": 0.95}   # the starting table; T8 corrects it in `think_calibration_s84`
STATES = ("noticed", "open", "waiting", "acted", "closed", "advisory")

DEFAULTS = {
    "on": True,
    "mode": "live",                     # live: the rule acts; advisory: cases open and report, only thesis-break sales act (T8 sets it; his to force)
    "max_cases_per_day": 3,             # A67: at most this many NEW cases are thought through a day, the rest are stored as noticed, not examined
    "move_sigmas": 2.5,                 # a move beyond this many of the name's usual daily moves (1 day and 5 days, also against its market)
    "fall_pct_10d": 0.20, "rel_pts_5d": 15.0, "market_down_20d": 0.10,
    "news_burst_x": 3.0,                # linked news today against the name's 60-day norm
    "storyline_jump_pts": 15.0,
    "missed_run_pts": 20.0,             # a skipped or screened name now this many points ahead of its index since that day
    "stretched_sigmas": 2.5,            # no first part on a day a name is more than this many usual daily moves above its 20-session average
    "bet_worst_pct_book": 0.01,         # A66: one opportunity bet loses at most this share of the WHOLE book in its worst case
    "reserve_india_pts": 10.0, "reserve_us_pts": 10.0,       # A64: points of the India part / of the US sub-book kept as an opportunity reserve
    "reserve_third_per_name": 1.0 / 3.0,
    "sale_beats_holding_pts": 1.0,      # a sale needs to beat holding by at least this many points of the position
    "damage_wait_sessions": 10, "new_low_sessions": 5, "new_low_clear_days": 3,
    "parts": 3, "parts_gap_sessions": 5, "market_fall_reserve_share": 0.5,
    "look_max_sessions": 5, "quiet_close_sessions": 60,
    "big_trade_share": 0.02,            # a sale over this share of the book, and every reserve buy, passes the independent big-trade check
    "opus_exposure_share": 0.02,        # Opus decides when the book's exposure to the case is over this share of the book or the case would spend the reserve
    "advisory_after_scored": 20,
    "base_rate_min_n": 20,
}


def settings() -> dict:
    """`configs/core.toml [think]` over the defaults (an unreadable file leaves the defaults)."""
    out = dict(DEFAULTS)
    try:
        from pflab import _toml
        out.update({k: v for k, v in (_toml.load(CONFIG).get("think") or {}).items()})
    except Exception:
        pass
    return out


def on() -> bool:
    from pflab import core
    return bool(settings()["on"]) and core.on()
