"""Income tax for a resident individual under both regimes, and the tax of a proposed sale
(PLAN S13). Every rate and threshold comes from the dated tables in `configs/tax/` (primary
sources; see PLAN §6), none from this file.

What is computed
    slab income      dividends + interest + short-term gains taxed at slab + other income
                     (less old-regime deductions, if supplied)
    special gains    ST_111A (20%), LT_112 and LT_112A (12.5%) from `pflab.tax.gains`
    unused basic exemption absorbs special gains (ss.196(2), 197(2), 198(3)): spread over
                     ST_111A, then LT_112, then LT_112A, the tax-minimising order (the Act
                     does not fix one); reported in `notes`
    rebate           s.156 (new regime: capped at the slab-rate tax, so special-rate tax on
                     capital gains is never rebated; old regime: whole tax)
    surcharge, cess  cap 15% on dividend and capital-gains parts; cess 4%
    credits          TDS and advance tax paid -> balance payable (or refund)

What is not
    Marginal relief on surcharge: totals above Rs 50,00,000 raise `NotImplementedError`.
    Old-regime deductions (80C, 80D, ...): only what the caller passes. With none, the old
    regime figure is a LOWER BOUND ON TAX, not a comparison fit for a decision, and the
    result says so in `assumptions`.
    The choice of regime is the investor's: `compare` shows both and names the cheaper.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from pflab.tax import gains as gn
from pflab.tax import rules

SURCHARGE_LIMIT = 5_000_000.0


@dataclass(frozen=True)
class YearInputs:
    fy: int                                  # FY label (year the FY ends): 2027 = FY2026-27
    dividends_gross: float = 0.0
    interest_gross: float = 0.0              # bank, bond, SGB interest
    other_income: float = 0.0                # anything else at slab (The investor supplies)
    old_regime_deductions: float = 0.0       # 80C etc., old regime only
    tds_credit: float = 0.0
    advance_tax_paid: float = 0.0
    age: str = "under60"                     # old-regime bracket: under60 | 60-79 | 80+
    gains: Optional[gn.FYGains] = None       # S12 result for the year

    @property
    def on(self) -> date:
        return date(self.fy, 3, 31)


@dataclass
class RegimeResult:
    regime: str
    fy: int
    slab_income: float
    special_gains: Dict[str, float]          # ST_111A, LT_112, LT_112A (after exemption), absorbed
    total_income: float
    basic_exemption: float
    absorbed: Dict[str, float]
    slab_tax: float
    special_tax: float
    rebate: float
    surcharge: float
    cess: float
    total_tax: float
    credits: float
    balance: float                           # +payable, -refund
    notes: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)


def _special_rates(on: date) -> Dict[str, float]:
    st = rules.lookup("EQUITY", on, date(on.year - 5, 1, 1)).stcg_rate
    lt = rules.lookup("LISTED_NONEQUITY", on, date(on.year - 5, 1, 1)).ltcg_rate
    return {"ST_111A": float(st), "LT_112": float(lt), "LT_112A": float(lt)}


def compute(inp: YearInputs, regime: str) -> RegimeResult:
    on = inp.on
    book = rules.load()
    g = inp.gains
    st_slab = g.slab_income if g else 0.0
    deductions = inp.old_regime_deductions if regime == "old" else 0.0
    slab_income = max(inp.dividends_gross + inp.interest_gross + inp.other_income + st_slab - deductions, 0.0)

    sp = {"ST_111A": g.taxable["ST_111A"] if g else 0.0,
          "LT_112": g.taxable["LT_112"] if g else 0.0,
          "LT_112A": (g.taxable["LT_112A"] + g.exemption_used) if g else 0.0}   # before the Rs 1,25,000
    exemption = g.exemption_available if g else rules.exemption(inp.fy)
    gains_total = sum(sp.values())
    total_income = slab_income + gains_total
    if total_income > SURCHARGE_LIMIT:
        raise NotImplementedError(
            f"total income {total_income:,.0f} exceeds Rs 50,00,000: surcharge marginal relief is not "
            "implemented, so any figure here would be unreliable")

    rates = rules.slab_rates(regime, on, inp.age)
    be = _basic_exemption(rates)
    notes: List[str] = []
    assumptions = [f"resident individual, age bracket {inp.age if regime == 'old' else 'n/a (new regime)'}"]
    if regime == "old" and not inp.old_regime_deductions:
        assumptions.append("old regime computed with NO deductions (none supplied): its tax is a "
                           "lower bound on what a comparison would need, not a like-for-like figure")

    # unused basic exemption absorbs special-rate gains (ss.196(2), 197(2), 198(3))
    shortfall = max(be - slab_income, 0.0)
    absorbed = {k: 0.0 for k in sp}
    left = shortfall
    for k in ("ST_111A", "LT_112", "LT_112A"):
        use = min(left, sp[k])
        absorbed[k], left = use, left - use
    if shortfall and sum(absorbed.values()):
        notes.append(f"unused basic exemption Rs {shortfall:,.0f} absorbs special-rate gains "
                     f"{ {k: v for k, v in absorbed.items() if v} } (order ST_111A, LT_112, LT_112A: "
                     "tax-minimising; the Act fixes none)")
    after = {k: sp[k] - absorbed[k] for k in sp}
    lt112a_taxable = max(after["LT_112A"] - exemption, 0.0)
    rate = _special_rates(on)
    special_tax = after["ST_111A"] * rate["ST_111A"] + after["LT_112"] * rate["LT_112"] + \
        lt112a_taxable * rate["LT_112A"]
    slab_tax = rules.tax_on_slabs(slab_income, rates)

    # rebate (s.156)
    rb = rules.rebate_rule(regime, on, book)
    rebate = 0.0
    full_tax = slab_tax + special_tax
    if regime == "new":
        if total_income <= rb["income_limit"]:
            rebate = min(rb["max_rebate"], full_tax, slab_tax)
        else:
            excess = total_income - rb["income_limit"]
            rebate = min(max(full_tax - excess, 0.0), slab_tax)
    else:
        if total_income <= rb["income_limit"]:
            rebate = min(rb["max_rebate"], full_tax)
    slab_after = max(slab_tax - rebate, 0.0)
    special_after = special_tax - max(rebate - slab_tax, 0.0)

    # surcharge: nil up to the first tier (Rs 50,00,000); above it marginal relief is needed and the
    # function has already refused, so the tier table is only checked here, never applied.
    tiers = rules.surcharge_tiers(regime, on, book)
    assert total_income <= tiers["tiers"][0]["over"]
    surcharge = 0.0
    cess_rate = rules.cess_rate(on, book)
    cess = (slab_after + special_after + surcharge) * cess_rate
    total_tax = slab_after + special_after + surcharge + cess
    credits = inp.tds_credit + inp.advance_tax_paid
    return RegimeResult(regime, inp.fy, slab_income, {k: after[k] if k != "LT_112A" else lt112a_taxable for k in after},
                        total_income, be, absorbed, slab_tax, special_tax, rebate, surcharge, cess,
                        total_tax, credits, total_tax - credits, notes, assumptions)


def _basic_exemption(rates: List[tuple]) -> float:
    """Top of the nil band of a slab table."""
    return float(rates[0][0]) if rates and rates[0][1] == 0.0 and rates[0][0] is not None else 0.0


def compare(inp: YearInputs) -> dict:
    """Both regimes side by side. `cheaper` is information, not a decision."""
    new, old = compute(inp, "new"), compute(inp, "old")
    return {"new": new, "old": old, "cheaper": "new" if new.total_tax <= old.total_tax else "old",
            "saving": abs(new.total_tax - old.total_tax),
            "decision": "The investor chooses the regime; the option is s.202(4), made with the return"}


# --- advance tax ---------------------------------------------------------------------------------------

def advance_tax_schedule(total_tax_after_tds: float, fy: int, age: int = 40, has_business: bool = False) -> List[tuple]:
    """Cumulative advance-tax targets for the FY: [(due date, cumulative amount)]. Empty when not
    liable (tax payable under Rs 10,000, or aged 60+ with no business income: ss.403(3), 404)."""
    rule = rules.advance_tax_rule(date(fy - 1, 4, 1))
    if total_tax_after_tds < rule["threshold"]:
        return []
    if rule["senior_exempt_without_business"] and age >= 60 and not has_business:
        return []
    out = []
    for i in rule["instalments"]:
        mm, dd = (int(x) for x in i["due"].split("-"))
        y = fy if mm <= 3 else fy - 1
        out.append((date(y, mm, dd), total_tax_after_tds * i["cumulative"]))
    return out


# --- TDS on dividends -------------------------------------------------------------------------------------

def dividend_tds(amount_paid_in_year: float, paid_in_cash: bool, on: date) -> float:
    """TDS the payer should deduct on a dividend, from the Act's rule (10%; no deduction for an
    individual paid by non-cash mode when the year's total does not exceed Rs 10,000)."""
    r = rules.dividend_tds_rule(on)
    if not paid_in_cash and amount_paid_in_year <= r["threshold_per_payer_per_year"]:
        return 0.0
    return amount_paid_in_year * r["rate"]
