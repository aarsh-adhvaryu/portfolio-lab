"""US costs of the GIFT City route, in USD, from the cited rows (configs/us/tax_s81.toml). Every number is a row with its source and how it was checked; the breakdown names each part.

    brokerage    0.10% of the trade value each way, min USD 0.01, max USD 10, plus IGST 18% on it                              (secondary: Zerodha's schedule of 2026-10-27)
    IFSCA fee    0.005% of the trade value, both sides                                                                       (secondary)
    SEC fee      USD 20.60 per million of sales, sells only, from 2026-04-04 (0.00 before)                                    (PRIMARY: SEC advisory 2026-2)
    FINRA TAF    USD 0.000195 a share, at most USD 9.79 a trade, sells only; 0.00 for trades from 2026-10-01 to 2026-12-31   (primary schedule; the pause is secondary)
    FX markup    0.4% once, when the account is funded (the range is 0.4% to 1.4%)                                          (ESTIMATE)
    slippage     5 bps against the order at the open                                                                          (ESTIMATE)
Not charged in the paper book (a real-money matter, Phase C): TCS 20% above Rs 10 lakh a year (a credit later), the bank's wire fees, the repatriation conversion.
"""
from __future__ import annotations

from datetime import date
from typing import Dict

from pflab.us import rows

IGST = 0.18                         # on the brokerage (the schedule's own line; secondary)
BROKERAGE_MIN, BROKERAGE_MAX = 0.01, 10.0
TAF_MAX = 9.79
SEC_FEE_FROM = date(2026, 4, 4)
TAF_PAUSE = (date(2026, 10, 1), date(2026, 12, 31))
ROWS = ["cost_brokerage_pct", "cost_ifsca_turnover_pct", "cost_sec_fee_per_million", "cost_finra_taf_per_share", "cost_fx_markup_funding_pct", "cost_slippage_bps"]


def label() -> str:
    return rows.label(ROWS)


def charges(side: str, qty: float, price: float, on: date) -> Dict[str, float]:
    """The USD charges of one fill and their parts. `on` is the trading date (it picks the SEC fee and the FINRA pause)."""
    if side not in ("buy", "sell"):
        raise ValueError("side is buy or sell")
    value = float(qty) * float(price)
    brokerage = min(max(value * float(rows.value("cost_brokerage_pct")), BROKERAGE_MIN), BROKERAGE_MAX)
    igst = brokerage * IGST
    ifsca = value * float(rows.value("cost_ifsca_turnover_pct"))
    sec = taf = 0.0
    if side == "sell":
        if on >= SEC_FEE_FROM:
            sec = value * float(rows.value("cost_sec_fee_per_million")) / 1e6
        if not TAF_PAUSE[0] <= on <= TAF_PAUSE[1]:
            taf = min(float(qty) * float(rows.value("cost_finra_taf_per_share")), TAF_MAX)
    parts = {"brokerage": brokerage, "igst": igst, "ifsca_fee": ifsca, "sec_fee": sec, "finra_taf": taf}
    parts["total"] = sum(parts.values())
    return {k: round(v, 6) for k, v in parts.items()}


def slippage_bps() -> float:
    return float(rows.value("cost_slippage_bps"))


def fx_markup_funding() -> float:
    return float(rows.value("cost_fx_markup_funding_pct"))
