"""Foreign (US) investing rules as sourced inputs to estimates (S64 Phase 6 item 1; configs/tax/foreign.toml).

Every number comes from a row with its source and the date it was looked up. A row marked `unverified` is refused: it is never
used in a figure. The results are ESTIMATES (the investor's tax depends on his whole income and his adviser's reading); each
function says which rows it used.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from pflab import _toml

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "tax" / "foreign.toml"
USABLE = ("primary", "secondary")


class Unconfirmed(ValueError):
    pass


def rows(path: Optional[Path] = None) -> Dict[str, dict]:
    return {r["id"]: r for r in _toml.load(path or CONFIG)["fact"]}


def fact(fid: str, path: Optional[Path] = None) -> dict:
    r = rows(path).get(fid)
    if r is None:
        raise KeyError(f"no foreign-tax row {fid!r}")
    if r.get("verification") not in USABLE:
        raise Unconfirmed(f"{fid} is {r.get('verification')!r}: not used in a figure")
    return r


def label(fids: List[str], path: Optional[Path] = None) -> str:
    """The sources behind a figure, for its label."""
    return "estimate; rows " + ", ".join(f"{i} ({fact(i, path)['verification']}, looked up {fact(i, path)['verified_on']})" for i in fids)


def tcs(remitted_before: float, amount: float, path: Optional[Path] = None) -> dict:
    """TCS on `amount` rupees remitted when `remitted_before` rupees went abroad earlier in the same financial year."""
    th, rate = float(fact("tcs_lrs_threshold_inr", path)["value"]), float(fact("tcs_lrs_rate_investment", path)["value"])
    taxable = max(0.0, remitted_before + amount - max(th, remitted_before))
    return {"tcs_rs": round(taxable * rate, 2), "taxable_rs": round(taxable, 2), "threshold_rs": th, "rate": rate,
            "note": "a credit against his tax when he files, a cash cost until then", "label": label(["tcs_lrs_threshold_inr", "tcs_lrs_rate_investment"], path)}


def lrs_room(sent_this_year_usd: float, path: Optional[Path] = None) -> float:
    return float(fact("lrs_limit_usd", path)["value"]) - sent_this_year_usd


def holding_class(bought: date, sold: date, path: Optional[Path] = None) -> str:
    """'long' if held MORE than 24 months, else 'short' (shares of a foreign company)."""
    months = int(fact("cg_foreign_long_term_months", path)["value"])
    y, m = bought.year, bought.month + months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    day = min(bought.day, [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return "long" if sold > date(y, m, day) else "short"


def gain_tax(gain_inr: float, bought: date, sold: date, slab: float, path: Optional[Path] = None) -> dict:
    """Tax on a gain in rupees: 12.5% if long-term (sale on or after 2024-07-23), else the slab rate `slab`. Losses give 0 here
    (set-off is the tax engine's job)."""
    if sold < date(2024, 7, 23):
        raise Unconfirmed("transfers before 2024-07-23 are outside the rows looked up")
    kind = holding_class(bought, sold, path)
    rate = float(fact("cg_foreign_ltcg_rate", path)["value"]) if kind == "long" else slab
    return {"class": kind, "rate": rate, "tax_rs": round(max(gain_inr, 0.0) * rate, 2), "excludes": "surcharge and cess",
            "label": label(["cg_foreign_long_term_months", "cg_foreign_ltcg_rate", "cg_foreign_stcg_rate"], path)}


def dividend_withholding(gross_usd: float, w8ben: bool = True, path: Optional[Path] = None) -> dict:
    rate = float(fact("dtaa_dividend_withholding", path)["value"]) if w8ben else 0.30
    return {"withheld_usd": round(gross_usd * rate, 4), "rate": rate,
            "label": label(["dtaa_dividend_withholding"], path) + ("" if w8ben else "; 30% is the standard rate without a W-8BEN (Zerodha)")}


def fx_date(event: date) -> date:
    """The last day of the month BEFORE `event`'s month: the date whose SBI TT buying rate converts a sale or a dividend."""
    first = event.replace(day=1)
    return date.fromordinal(first.toordinal() - 1)


def estate_exposure(us_assets_usd: float, path: Optional[Path] = None) -> Optional[str]:
    th = float(fact("us_estate_tax_nra_threshold_usd", path)["value"])
    if us_assets_usd <= th:
        return None
    return (f"US-listed holdings of about USD {us_assets_usd:,.0f} are above USD {th:,.0f}: if he died holding them, his heirs would "
            "file a US estate return and may owe US estate tax (rates 18% to 40% per Zerodha); India and the US have no estate-tax "
            "treaty. " + label(["us_estate_tax_nra_threshold_usd"], path))
