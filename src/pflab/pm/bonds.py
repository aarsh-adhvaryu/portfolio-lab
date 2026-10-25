"""Bond master, coupon schedules, accrued interest, coupon matching, model price (PLAN S10).

Scope: bullet bonds (coupon dates counted back from maturity, principal at maturity) and
zero-coupon bonds. Amortising and floating-rate bonds are not modelled and must not be
entered. Dates are nominal contract dates: a payment falling on a holiday is paid the next
business day, which this module does not shift (a few days' difference in when cash lands,
none in how much).

Day counts: "30/360" is the US bond basis, "ACT/365" fixed, "ACT/ACT" actual days over
the actual length of the coupon period (ICMA). Which one a bond uses is a property of the
bond and is stored with it; nothing here guesses.

A model price is an `Estimate`: it is a discounted-cash-flow value at a stated yield,
not a traded price.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence, Tuple

from dateutil.relativedelta import relativedelta

from pflab.pm import estimate as est

DAY_COUNTS = ("30/360", "ACT/365", "ACT/ACT")


class BondError(ValueError):
    pass


@dataclass(frozen=True)
class Bond:
    isin: str
    name: str
    issue_date: date
    maturity_date: date
    coupon_rate: float          # annual, decimal; 0 for zero-coupon
    frequency: int              # coupons per year: 1, 2, 4, 12; 0 = zero-coupon
    day_count: str = "30/360"
    face_value: float = 1000.0
    listed: bool = True
    issuer: str = ""

    def __post_init__(self):
        if self.day_count not in DAY_COUNTS:
            raise BondError(f"day_count must be one of {DAY_COUNTS}")
        if self.frequency not in (0, 1, 2, 4, 12):
            raise BondError("frequency must be 0, 1, 2, 4 or 12")
        if self.frequency == 0 and self.coupon_rate:
            raise BondError("a zero-coupon bond has no coupon rate")
        if self.frequency and not self.coupon_rate:
            raise BondError("a coupon bond needs a coupon rate")
        if self.maturity_date <= self.issue_date:
            raise BondError("maturity must be after issue")
        if self.face_value <= 0:
            raise BondError("face value must be positive")


@dataclass(frozen=True)
class Flow:
    date: date
    interest: float      # per one bond of `face_value`
    principal: float

    @property
    def total(self) -> float:
        return self.interest + self.principal


# --- day counts --------------------------------------------------------------------

def _days_30_360(a: date, b: date) -> int:
    d1, d2 = a.day, b.day
    if d1 == 31:
        d1 = 30
    if d2 == 31 and d1 >= 30:
        d2 = 30
    return (b.year - a.year) * 360 + (b.month - a.month) * 30 + (d2 - d1)


def year_fraction(a: date, b: date, day_count: str, period: Optional[Tuple[date, date]] = None,
                  frequency: int = 1) -> float:
    """Accrual fraction of a YEAR between a and b. ACT/ACT needs the coupon `period`
    that contains the interval and returns the fraction as (days/period_days)/frequency."""
    if b < a:
        raise BondError("end before start")
    if day_count == "30/360":
        return _days_30_360(a, b) / 360.0
    if day_count == "ACT/365":
        return (b - a).days / 365.0
    if period is None:
        raise BondError("ACT/ACT needs the coupon period")
    return ((b - a).days / (period[1] - period[0]).days) / frequency


# --- schedule ------------------------------------------------------------------------

def coupon_dates(bond: Bond) -> List[date]:
    """Coupon dates after issue, counted back from maturity (each from maturity itself, so a
    month-end maturity keeps its day: 31-Aug, 28/29-Feb, 31-Aug...). Includes maturity."""
    if bond.frequency == 0:
        return [bond.maturity_date]
    step, k, out = 12 // bond.frequency, 0, []
    while True:
        d = bond.maturity_date - relativedelta(months=k * step)
        if d <= bond.issue_date:
            break
        out.append(d)
        k += 1
    return sorted(out)


def _step(bond: Bond) -> relativedelta:
    return relativedelta(months=12 // bond.frequency)


def _fraction(bond: Bond, start: date, end: date, nxt: date) -> float:
    """Year fraction from `start` to `end` inside the regular coupon period ending `nxt`."""
    reg = (nxt - _step(bond), nxt)
    return year_fraction(start, end, bond.day_count, reg, bond.frequency)


def schedule(bond: Bond) -> List[Flow]:
    """Cash flows per bond of face value. A full period pays rate x face / frequency; a
    first-period stub (issue after the regular period start) is pro-rated by the day count;
    principal at maturity."""
    if bond.frequency == 0:
        return [Flow(bond.maturity_date, 0.0, bond.face_value)]
    flows, prev = [], bond.issue_date
    for d in coupon_dates(bond):
        yf = 1.0 / bond.frequency if prev <= d - _step(bond) else _fraction(bond, prev, d, d)
        flows.append(Flow(d, bond.coupon_rate * bond.face_value * yf,
                          bond.face_value if d == bond.maturity_date else 0.0))
        prev = d
    return flows


def accrued_interest(bond: Bond, settle: date) -> float:
    """Interest accrued per bond of face value from the last coupon (or issue) to `settle`."""
    if bond.frequency == 0 or settle <= bond.issue_date or settle >= bond.maturity_date:
        return 0.0
    prev, nxt = bond.issue_date, None
    for d in coupon_dates(bond):
        if d > settle:
            nxt = d
            break
        prev = d
    return bond.coupon_rate * bond.face_value * _fraction(bond, prev, settle, nxt)


# --- holdings: value, coupons ------------------------------------------------------------

def holding_value(bond: Bond, qty: float, clean_price_per_100: float, settle: date) -> dict:
    """Value of `qty` bonds at a clean quote (per 100 of face): clean + accrued."""
    clean = qty * bond.face_value * clean_price_per_100 / 100.0
    acc = qty * accrued_interest(bond, settle)
    return {"clean": clean, "accrued": acc, "dirty": clean + acc}


def coupons_due(bond: Bond, qty: float, held_from: date, upto: date) -> List[Tuple[date, float]]:
    """Gross coupons a holder who bought on `held_from` (cum-coupon, no record-date logic)
    receives for payment dates in (held_from, upto]; the first partial period is not pro-rated
    here: the buyer pays accrued at purchase and receives the full coupon."""
    return [(f.date, qty * f.interest) for f in schedule(bond)
            if held_from < f.date <= upto and f.interest > 0]


def match_coupons(due: Sequence[Tuple[date, float]], received: Sequence[Tuple[date, float]],
                  tds_rate: float = 0.0, tol: float = 1.0, window_days: int = 7) -> dict:
    """Match received interest credits to scheduled coupons. A credit matches a due coupon when
    it is within `window_days` after the due date and equals the gross amount, or the amount
    net of `tds_rate`, within `tol` rupees. Each credit and coupon matches at most once."""
    unmatched_due, used, matched = list(due), set(), []
    for dd, amt in sorted(due):
        for k, (rd, ra) in enumerate(sorted(received)):
            if k in used or not (0 <= (rd - dd).days <= window_days):
                continue
            if abs(ra - amt) <= tol or (tds_rate and abs(ra - amt * (1 - tds_rate)) <= tol):
                used.add(k)
                matched.append((dd, amt, rd, ra))
                unmatched_due.remove((dd, amt))
                break
    rs = sorted(received)
    return {"matched": matched, "unmatched_due": unmatched_due,
            "unexplained_credits": [rs[k] for k in range(len(rs)) if k not in used]}


# --- yield and model price -----------------------------------------------------------------

def _dirty_from_yield(bond: Bond, ytm: float, settle: date) -> float:
    flows = [f for f in schedule(bond) if f.date > settle]
    if not flows:
        raise BondError("no cash flows after settlement")
    f = max(bond.frequency, 1)
    nxt = flows[0].date
    full_prev = nxt - relativedelta(months=12 // f)
    w = (nxt - settle).days / max((nxt - full_prev).days, 1)          # periods to the next flow
    if bond.frequency == 0:
        return bond.face_value / (1 + ytm) ** ((bond.maturity_date - settle).days / 365.0)
    return sum(fl.total / (1 + ytm / f) ** (w + k) for k, fl in enumerate(flows))


def clean_price_from_yield(bond: Bond, ytm: float, settle: date) -> float:
    """Clean price per 100 of face at a yield compounded at the coupon frequency."""
    dirty = _dirty_from_yield(bond, ytm, settle)
    return (dirty - accrued_interest(bond, settle)) / bond.face_value * 100.0


def yield_from_clean_price(bond: Bond, clean_per_100: float, settle: date,
                           lo: float = -0.5, hi: float = 1.0) -> float:
    """Yield that reproduces a clean price (bisection; price falls as yield rises)."""
    target = clean_per_100 / 100.0 * bond.face_value + accrued_interest(bond, settle)
    a, b = lo, hi
    for _ in range(200):
        m = (a + b) / 2
        if _dirty_from_yield(bond, m, settle) > target:
            a = m
        else:
            b = m
    return (a + b) / 2


def model_price(bond: Bond, ytm: float, settle: date, yield_source: str) -> est.Estimate:
    """Clean price per 100 as a labelled Estimate. `yield_source` says where the yield came
    from (e.g. 'last traded 2026-09-10' or 'assumed = coupon')."""
    p = clean_price_from_yield(bond, ytm, settle)
    return est.make(p, f"DCF at yield {ytm:.4%} ({yield_source}); clean price per 100",
                    {"isin": bond.isin, "ytm": ytm, "settle": settle, "coupon": bond.coupon_rate,
                     "maturity": bond.maturity_date}, settle, unit="per 100")


# --- store -------------------------------------------------------------------------------------

def load_bonds(con, bonds: Sequence[Bond], source: str, now=None) -> int:
    from datetime import datetime
    now = now or datetime.now()
    for b in bonds:
        con.execute("INSERT OR REPLACE INTO bonds VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [b.isin, b.name, b.issuer, b.issue_date, b.maturity_date, b.coupon_rate,
                     b.frequency, b.day_count, b.face_value, b.listed, source, now])
    return len(bonds)


def get_bond(con, isin: str) -> Optional[Bond]:
    r = con.execute("SELECT isin, name, issue_date, maturity_date, coupon_rate, frequency, day_count, "
                    "face_value, listed, issuer FROM bonds WHERE isin=?", [isin]).fetchone()
    return Bond(*r) if r else None
