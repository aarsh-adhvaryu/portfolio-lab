"""Indian tax on the US sub-book's shares and dividends, as rupee figures from the dated rows (configs/us/tax_s81.toml). Every function returns the label of the rows it used.

Capital gains on foreign shares and ETFs held directly (FY 2026-27, Income-tax Act 2025; the same lines for transfers from 2024-07-23 under the 1961 Act):
    long-term only if held MORE than 24 months (s.2(101)), taxed at 12.5% without indexation (s.197), no Rs 1.25 lakh exemption (s.198 needs STT);
    short-term: the slab rate (the 20% of s.196 also needs STT). Cost and proceeds are converted at the SBI TT buying rate of the month-end before the PURCHASE and before the SALE
    (rule 115 / rule 206; the two-date reading, an ESTIMATE). A short-term loss sets off against any gain, a long-term loss only against long-term gains. Surcharge and cess excluded.
Dividends: the US withholds 25% (treaty Art. 10(2)(b), an individual; 30% with no W-8BEN). India taxes the gross at the slab rate; the credit is the LOWER of the US tax (in rupees at
the month-end before) and the Indian tax on that income (treaty Art. 25(2)(a); Form 67 for income to FY 2025-26, Form 44 from FY 2026-27). Any excess US tax is lost; any shortfall is paid.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from pflab.us import rows

CG_ROWS = ["cg_foreign_long_term_months", "cg_foreign_ltcg_rate", "cg_foreign_stcg_rate", "fx_conversion_rule", "fx_ttbr_stand_in"]
DIV_ROWS = ["dtaa_dividend_withholding_individual", "dividend_india_taxed_at_slab", "foreign_tax_credit_rule", "fx_conversion_rule", "fx_ttbr_stand_in"]


def slab() -> float:
    """The slab rate used for short-term gains and dividends: the rupee paper book's (paper/book.py SLAB), so the two books are taxed alike."""
    from pflab.paper import book
    return float(book.SLAB)


def fy_of(d: date) -> int:
    """The financial year's starting year (April to March): 2027-02-20 is FY 2026-27 -> 2026."""
    return d.year if d.month >= 4 else d.year - 1


def _add_months(d: date, months: int) -> date:
    y, m = d.year, d.month + months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    last = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, last))


def holding_class(acquired: date, sold: date) -> str:
    """'long' if held MORE than 24 months (sold after the date 24 months on), else 'short'."""
    return "long" if sold > _add_months(acquired, int(rows.value("cg_foreign_long_term_months"))) else "short"


def fy_tax(st: float, lt: float, slab_rate: Optional[float] = None) -> float:
    """The year's tax on short-term and long-term net gains (rupees): a short-term loss reduces long-term gains; a long-term loss reduces nothing else."""
    s = slab() if slab_rate is None else slab_rate
    r = float(rows.value("cg_foreign_ltcg_rate"))
    if st < 0:
        lt, st = lt + st, 0.0
    return s * max(0.0, st) + r * max(0.0, lt)


def lot_gain(qty: float, cost_usd_per_share: float, fx_acq: float, proceeds_usd: float, fx_sale: float, acquired: date, sold: date) -> dict:
    """One lot part: the gain in rupees (cost at the purchase's month-end rate, proceeds at the sale's) and its class."""
    cost_inr = qty * cost_usd_per_share * fx_acq
    proceeds_inr = proceeds_usd * fx_sale
    return {"qty": qty, "acquired": acquired, "class": holding_class(acquired, sold), "cost_inr": cost_inr, "proceeds_inr": proceeds_inr, "gain_inr": proceeds_inr - cost_inr}


def sale(parts: List[dict], ytd_st: float = 0.0, ytd_lt: float = 0.0, slab_rate: Optional[float] = None) -> dict:
    """The tax a sale adds to its financial year: tax(year-to-date + this sale) - tax(year-to-date). `parts` come from `lot_gain`."""
    st = sum(p["gain_inr"] for p in parts if p["class"] == "short")
    lt = sum(p["gain_inr"] for p in parts if p["class"] == "long")
    before = fy_tax(ytd_st, ytd_lt, slab_rate)
    after = fy_tax(ytd_st + st, ytd_lt + lt, slab_rate)
    return {"st_inr": st, "lt_inr": lt, "gain_inr": st + lt, "tax_inr": max(0.0, after - before), "label": rows.label(CG_ROWS) + "; excludes surcharge and cess; no exemption"}


def withholding_rate(w8ben: bool = True) -> float:
    return float(rows.value("dtaa_dividend_withholding_individual")) if w8ben else float(rows.value("us_dividend_withholding_no_w8ben"))


def dividend(gross_usd: float, fx_tax: float, w8ben: bool = True, slab_rate: Optional[float] = None) -> Dict[str, float]:
    """A dividend's US withholding, the Indian tax on it and the credit, in dollars and rupees. `fx_tax` is the rupees per dollar of the month-end before."""
    rate = withholding_rate(w8ben)
    s = slab() if slab_rate is None else slab_rate
    withheld_usd = gross_usd * rate
    gross_inr = gross_usd * fx_tax
    withheld_inr = withheld_usd * fx_tax
    india_tax = gross_inr * s
    credit = min(withheld_inr, india_tax)
    ids = DIV_ROWS if w8ben else DIV_ROWS + ["us_dividend_withholding_no_w8ben"]
    return {"gross_usd": gross_usd, "withholding_rate": rate, "withheld_usd": withheld_usd, "net_usd": gross_usd - withheld_usd, "gross_inr": gross_inr, "withheld_inr": withheld_inr,
            "india_tax_inr": india_tax, "credit_inr": credit, "residual_tax_inr": india_tax - credit, "excess_us_tax_inr": withheld_inr - credit,
            "label": rows.label(ids) + "; excludes surcharge and cess"}
