"""Estimated Zerodha charges for a proposed trade, by segment (PLAN S4).

Estimates, not facts: contract notes are the truth for what was charged. Each answer says whether the
rate row was verified against Zerodha's charges page (`known`). Equity delivery and direct mutual
funds are verified; ETF and SGB sales reuse the equity rates and are flagged unverified.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, Tuple

from pflab import _toml

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "costs_zerodha_pm.toml"


def load(path: Path = CONFIG) -> dict:
    return _toml.load(path)


def segment_of(asset_class: str, tax_class: str = "") -> str:
    """Charge segment for an instrument: equity_delivery (direct stocks, REIT/InvIT), mf_direct, etf, sgb."""
    if asset_class == "mutual_fund":
        return "mf_direct"
    if asset_class == "etf":
        return "etf"
    if asset_class == "sgb":
        return "sgb"
    return "equity_delivery"


def _equity(c: dict, side: str, notional: float, n_scrips: int) -> float:
    brokerage = notional * c["brokerage_pct"]
    txn = notional * c["exchange_txn_pct"]
    sebi = notional / 1e7 * c["sebi_per_crore"]
    gst = (brokerage + txn + sebi) * c["gst_pct"]
    stt = notional * (c["stt_buy_pct"] if side == "buy" else c["stt_sell_pct"])
    stamp = notional * c["stamp_buy_pct"] if side == "buy" else 0.0
    dp = c["dp_charge_per_sell_scrip"] * n_scrips if side == "sell" else 0.0
    return brokerage + txn + sebi + gst + stt + stamp + dp


def _futures(c: dict, side: str, notional: float) -> float:
    brokerage = min(notional * c["brokerage_pct"], c["brokerage_cap"])
    txn = notional * c["exchange_txn_pct"]
    sebi = notional / 1e7 * c["sebi_per_crore"]
    gst = (brokerage + txn + sebi) * c["gst_pct"]
    stt = notional * c["stt_sell_pct"] if side == "sell" else 0.0
    stamp = notional * c["stamp_buy_pct"] if side == "buy" else 0.0
    return brokerage + txn + sebi + gst + stt + stamp


def estimate(segment: str, side: str, notional: float, n_scrips: int = 1, cfg: dict = None) -> Tuple[float, bool]:
    """(estimated total charges in Rs, known). `known` is False when the segment's row is unverified."""
    if side not in ("buy", "sell"):
        raise ValueError("side is buy or sell")
    cfg = cfg or load()
    if segment == "mf_direct":
        return 0.0, True
    if segment == "equity_delivery":
        return _equity(cfg["equity_delivery"], side, notional, n_scrips), True
    if segment == "equity_futures":                  # research only (S39 short leg); no order path
        return _futures(cfg["equity_futures"], side, notional), True
    if segment in ("etf", "sgb"):
        return _equity(cfg["equity_delivery"], side, notional, n_scrips), False
    raise ValueError(f"unknown segment {segment!r}")


def fee_fn(instruments, cfg: dict = None):
    """A `plan.rebalance.FeeFn`: (isin, bucket, side, amount) -> (charges, known), segment from the instrument master."""
    cfg = cfg or load()
    seg = {r.isin: segment_of(r.asset_class, r.tax_class) for r in instruments.itertuples()}

    def fn(isin: str, bucket: str, side: str, amount: float) -> Tuple[float, bool]:
        return estimate(seg.get(isin, "equity_delivery"), side, amount, 1, cfg)

    return fn
