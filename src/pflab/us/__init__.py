"""The paper US sub-book (S81 B8 phase B, amendment A53). OFF by default (`[us] on = false` in configs/core.toml): nothing else depends on it.

A separate paper account in DOLLARS beside the rupee paper book: it starts as `start_share` (5%) of the system's book at the start FX rate, holds US ETFs the repo already
collects (data/us), is decided once per US session by code (an equal-weight baseline inside the same rails), and fills at the NEXT session's open plus slippage. Costs are the
GIFT City route's (us/costs.py), the Indian tax on foreign shares and the US dividend withholding with its credit are dated rows (configs/us/tax_s81.toml, each labelled primary,
secondary or estimate; the research is docs/US_LEG_S81.md). Every rupee figure is an ESTIMATE until the SBI TT buying rate series is wired. It trades nothing real.

    clock        the US session in IST (daylight saving from the zone), the session a given IST moment has closed
    fx           USD/INR with its source stated: FBIL (if entered) > the market close > FRED; the tax rate of the previous month-end
    costs        the GIFT City route's charges in USD, from the cited rows
    tax          capital gains on foreign shares (24 months, 12.5% / slab), US dividend withholding and its credit, as rupees
    instruments  the key of a US instrument: its real ISIN, else "ZZ" + the 10-digit CIK from a date (CLAUDE.md rule 3), else the symbol key the panel already uses
    data         daily bars from data/us/raw (open, close, dividend)
    book         the account, lots, orders, fills, dividends and the daily mark
    policy       the baseline (equal weights), rails reused from core/rails.py
    adapter      the entry points for the close loop: `close_us(con, now)` and `state_us(con, day)`
"""
from __future__ import annotations

from pathlib import Path

MARKET = "US"
CONFIG = Path(__file__).resolve().parents[3] / "configs" / "core.toml"
DEFAULTS = {
    "on": False, "start_share": 0.05, "start_inr_fallback": 100000.0,
    "universe": ["SPY", "QQQ", "XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU"],
    "invested_share": 0.95, "deploy_turnover_day": 1.0, "settle_minutes": 30, "slippage_bps": 5.0, "min_trade_usd": 25.0, "band_pts": 1.5, "w8ben": True,
}


def settings(cfg: dict | None = None) -> dict:
    """The [us] table with its defaults. `cfg` may be the table itself, or a dict with a 'us' key (tests pass one; the loop passes nothing)."""
    out = dict(DEFAULTS)
    if cfg is None:
        try:
            from pflab import _toml
            cfg = _toml.load(CONFIG).get("us", {})
        except Exception:
            cfg = {}
    elif isinstance(cfg.get("us"), dict):
        cfg = cfg["us"]
    out.update({k: v for k, v in (cfg or {}).items() if k in DEFAULTS})
    return out


def on(cfg: dict | None = None) -> bool:
    return bool(settings(cfg)["on"])
