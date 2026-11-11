"""The paper US sub-book (S81 B8 phase B, amendment A53). OFF by default (`[us] on = false` in configs/core.toml): nothing else depends on it.

A separate paper account in DOLLARS that is part of ONE book with the rupee paper book (S82, A57): it is funded by a TRANSFER out of the rupee book's cash (never new money; `us/transfer.py`),
sized to the international share of the WHOLE book (`us/wholebook.py`), holds SPY as its core (a broad US index ETF may be the whole sub-book), is decided once per US session by code on the
last US close, and fills at the NEXT session's open plus slippage. Costs are the
GIFT City route's (us/costs.py), the Indian tax on foreign shares and the US dividend withholding with its credit are dated rows (configs/us/tax_s81.toml, each labelled primary,
secondary or estimate; the research is docs/US_LEG_S81.md). Every rupee figure is an ESTIMATE until the SBI TT buying rate series is wired. It trades nothing real.

    clock        the US session in IST (daylight saving from the zone), the session a given IST moment has closed
    fx           USD/INR with its source stated: FBIL (if entered) > the market close > FRED; the tax rate of the previous month-end
    costs        the GIFT City route's charges in USD, from the cited rows
    tax          capital gains on foreign shares (24 months, 12.5% / slab), US dividend withholding and its credit, as rupees
    instruments  the key of a US instrument: its real ISIN, else "ZZ" + the 10-digit CIK from a date (CLAUDE.md rule 3), else the symbol key the panel already uses
    data         daily bars from data/us/raw (open, close, dividend)
    book         the account, lots, orders, fills, dividends and the daily mark
    policy       the core-ETF policy (SPY), rails reused from core/rails.py with the sub-book's own caps
    transfer     the transfer out of the rupee book's cash (funding, top-up, conversion of an old seed)
    wholebook    the whole book (rupee book + sub-book in rupees) and the international share of it
    report       plain JSON for the screens: holdings, cash, orders, funding, gap risk
    adapter      the entry points for the close loop: `close_us(con, now)` and `state_us(con, day)`
"""
from __future__ import annotations

from pathlib import Path

MARKET = "US"
CONFIG = Path(__file__).resolve().parents[3] / "configs" / "core.toml"
DEFAULTS = {
    "on": False, "fund_day_share": 0.05, "topup_below_share": 0.08,
    "universe": ["SPY", "QQQ", "XLC", "XLY", "XLP", "XLE", "XLF", "XLV", "XLI", "XLB", "XLRE", "XLK", "XLU"],      # the list the collector tracks; NOT a holding list since S82
    "broad_index_etfs": ["SPY"], "broad_index_cap": 1.0, "etf_cap": 0.35, "stock_cap": 0.10,
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
