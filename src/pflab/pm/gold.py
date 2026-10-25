"""Sovereign gold bonds and physical gold (PLAN S10).

SGB: interest 2.5% a year on the issue price, paid half-yearly from the issue date and at
maturity; redemption at the simple average of the IBJA 999 closing (PM) rate of the three
business days before redemption. A sale on the exchange is an ordinary listed sale (rule
`sgb_listed`); redemption at maturity may be exempt (`rules.sgb_redemption_exempt`).
Premature redemption stays taxable (The investor, 2026-10-06).

Physical gold has no ISIN: the key is `PHYS:GOLD<purity>` (999, 995, 916, 750, 585), the
quantity is grams, the price is per gram (making charges go in the buy's fees, so they are in
the cost). It is marked at the IBJA rate, which excludes GST and making charges.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

from dateutil.relativedelta import relativedelta

from pflab.pm import prices
from pflab.tax import rules

PURITIES = ("999", "995", "916", "750", "585")
SGB_RATE = 0.025


class GoldError(ValueError):
    pass


# --- physical gold ------------------------------------------------------------------------

def physical_key(purity: str) -> str:
    if purity not in PURITIES:
        raise GoldError(f"purity must be one of {PURITIES}")
    return f"PHYS:GOLD{purity}"


def purity_of(key: str) -> str:
    if not key.startswith("PHYS:GOLD") or key[9:] not in PURITIES:
        raise GoldError(f"not a physical gold key: {key}")
    return key[9:]


def value_physical(con, key: str, grams: float, asof: date) -> dict:
    """Grams x latest IBJA rate for the purity; carries the rate date and staleness."""
    m = prices.gold_mark(con, grams, "gold" + purity_of(key), asof)
    return {**m, "grams": grams, "basis": "IBJA rate, excludes GST and making charges"}


# --- SGB ------------------------------------------------------------------------------------

@dataclass(frozen=True)
class SGB:
    isin: str
    series: str
    issue_date: date
    maturity_date: date
    issue_price_per_gram: float
    interest_rate: float = SGB_RATE


def interest_schedule(sgb: SGB, grams: float, held_from: Optional[date] = None) -> List[Tuple[date, float]]:
    """Half-yearly interest dates (issue date + 6k months, the last at maturity) and the amount
    for `grams`: grams x issue price x rate / 2. Only dates after `held_from` if given."""
    out, k = [], 1
    while True:
        d = sgb.issue_date + relativedelta(months=6 * k)
        if d >= sgb.maturity_date:
            d = sgb.maturity_date
        out.append((d, grams * sgb.issue_price_per_gram * sgb.interest_rate / 2.0))
        if d == sgb.maturity_date:
            break
        k += 1
    return [(d, a) for d, a in out if held_from is None or d > held_from]


def redemption_price(con, redemption_date: date) -> float:
    """Rs per gram: simple average of the IBJA 999 PM rate (per 10 g, / 10) over the three
    business days before `redemption_date`. Raises if any of the three is missing."""
    days, d = [], redemption_date
    while len(days) < 3:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            days.append(d)
    rows = {r[0]: r[1] for r in con.execute(
        "SELECT date, rate FROM gold_rates WHERE metal='gold999' AND session='PM' AND date IN (?,?,?)",
        days).fetchall()}
    missing = [x for x in days if x not in rows]
    if missing:
        raise GoldError(f"IBJA 999 PM rate missing for {sorted(missing)}; cannot price the redemption")
    return sum(rows.values()) / 3.0 / 10.0


def redemption_outcome(sgb: SGB, grams: float, redemption_date: date, price_per_gram: float,
                       cost_per_gram: float, acquired: date, *, original_subscriber: bool,
                       premature: Optional[bool] = None) -> dict:
    """Proceeds, gain and tax status of redeeming `grams`.

    `original_subscriber`: bought at issue and held continuously. Premature = redeemed before
    maturity (inferred from the date when not given). Exempt per the SGB rule for the date;
    otherwise the gain is an ordinary long- or short-term gain under the `sgb_listed` rule
    (that rule is looked up, so a gap raises)."""
    premature = redemption_date < sgb.maturity_date if premature is None else premature
    proceeds, cost = grams * price_per_gram, grams * cost_per_gram
    exempt = rules.sgb_redemption_exempt(redemption_date, original_subscriber and not premature,
                                         premature=premature)
    rule = rules.lookup("SGB", redemption_date, acquired)
    gain = proceeds - cost
    return {"proceeds": proceeds, "cost": cost, "gain": gain, "exempt": exempt,
            "taxable_gain": 0.0 if exempt else gain, "holding": rule.holding(acquired, redemption_date),
            "rate": None if exempt else rule.rate(acquired, redemption_date), "rule": rule.id,
            "premature": premature}


# --- store -------------------------------------------------------------------------------------

def load_sgb(con, series: List[SGB], source: str, now: Optional[datetime] = None) -> int:
    now = now or datetime.now()
    for s in series:
        con.execute("INSERT OR REPLACE INTO sgb_series VALUES (?,?,?,?,?,?,?,?)",
                    [s.isin, s.series, s.issue_date, s.maturity_date, s.issue_price_per_gram,
                     s.interest_rate, source, now])
    return len(series)


def get_sgb(con, isin: str) -> Optional[SGB]:
    r = con.execute("SELECT isin, series, issue_date, maturity_date, issue_price_per_gram, interest_rate "
                    "FROM sgb_series WHERE isin=?", [isin]).fetchone()
    return SGB(*r) if r else None
