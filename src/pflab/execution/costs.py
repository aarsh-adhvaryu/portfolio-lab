"""Zerodha equity-delivery cost model (charter E1 §7). Per-side charges."""
from __future__ import annotations

from dataclasses import dataclass, replace

from pflab import _toml


@dataclass(frozen=True)
class CostModel:
    brokerage_pct: float = 0.0
    stt_buy_pct: float = 0.001
    stt_sell_pct: float = 0.001
    exchange_txn_pct: float = 0.0000297
    sebi_per_crore: float = 10.0
    stamp_buy_pct: float = 0.00015
    gst_pct: float = 0.18
    dp_charge_per_sell: float = 15.34
    multiplier: float = 1.0

    @classmethod
    def from_toml(cls, path, multiplier: float = 1.0) -> "CostModel":
        return cls(**_toml.load(path)["costs"], multiplier=multiplier)

    def scaled(self, multiplier: float) -> "CostModel":
        return replace(self, multiplier=multiplier)

    def _common(self, notional: float) -> float:
        brokerage = notional * self.brokerage_pct
        exch = notional * self.exchange_txn_pct
        sebi = notional / 1e7 * self.sebi_per_crore
        gst = (brokerage + exch + sebi) * self.gst_pct
        return brokerage + exch + sebi + gst

    def buy_cost(self, notional: float) -> float:
        c = self._common(notional) + notional * self.stt_buy_pct + notional * self.stamp_buy_pct
        return c * self.multiplier

    def sell_cost(self, notional: float, n_scrips: int = 1) -> float:
        c = self._common(notional) + notional * self.stt_sell_pct + self.dp_charge_per_sell * n_scrips
        return c * self.multiplier

    # STT is paid in cash but is not deductible in computing capital gains
    # (Income Tax Act s.48). The lot book is given cost minus these (E1 §15,
    # 2026-09-27); stamp duty and the other charges stay in basis/proceeds.
    def buy_stt(self, notional: float) -> float:
        return notional * self.stt_buy_pct * self.multiplier

    def sell_stt(self, notional: float) -> float:
        return notional * self.stt_sell_pct * self.multiplier
