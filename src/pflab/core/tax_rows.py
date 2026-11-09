"""The exit manager's tax figures (S81 B4): every rate and the yearly exemption are read from the tax engine's dated rows (`configs/tax/*.toml` through
`pflab.tax.rules`), never typed here. A date no row covers raises `rules.RuleGap`; the callers then do NOT harvest and say why (a missing figure is never a default).

The buckets are the paper book's (`paper/book._bucket`: st_eq, lt_eq, lt_other, slab) so that a sale's gains here are classified exactly as the fill classifies them. The one
number the rows cannot hold is the slab rate of an individual (it depends on him): it is the book's own `SLAB`, labelled an assumption.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional

from dateutil.relativedelta import relativedelta

from pflab.tax import rules
from pflab.tax.india_lots import fy_of


def fy_label(day: date) -> int:
    """The engine's FY label: the calendar year in which the financial year ends."""
    return fy_of(day)


def fy_start_year(day: date) -> int:
    """The book's FY key (the year the financial year starts): `book.year_gains(con, fy)` takes this."""
    return day.year if day.month >= 4 else day.year - 1


def fy_end(day: date) -> date:
    return date(fy_label(day), 3, 31)


def exemption(day: date) -> float:
    """The yearly long-term exemption on equity gains for the financial year of `day`, from the engine's dated row."""
    return rules.exemption(fy_label(day))


def rates(day: date) -> dict:
    """The rates in force on `day`, each from its row: equity short-term and long-term, listed non-equity long-term, and the exemption. Raises `rules.RuleGap`."""
    from pflab.paper import book
    eq = rules.lookup("EQUITY", day, day - timedelta(days=1000), stt_paid=True, listed=True)
    ne = rules.lookup("LISTED_NONEQUITY", day, day - timedelta(days=1000), listed=True)
    return {"st_eq": float(eq.stcg_rate), "lt_eq": float(eq.ltcg_rate), "lt_other": float(ne.ltcg_rate), "slab": float(book.SLAB), "exemption": exemption(day),
            "rows": [eq.id, ne.id], "verification": eq.verification, "slab_label": "assumption: a 30% slab (the book's own figure)"}


def tax_of(g: Dict[str, float], day: date) -> float:
    """The year's tax on its gains by bucket, the rates and the exemption from the engine's rows, the set-off as the book applies it (a short-term equity loss reduces
    long-term equity gains, a long-term loss only long-term gains). Cess and surcharge are not added (as the book's estimate)."""
    r = rates(day)
    st, lt_eq, lt_o, slab = g.get("st_eq", 0.0), g.get("lt_eq", 0.0), g.get("lt_other", 0.0), g.get("slab", 0.0)
    if st < 0:
        lt_eq, st = lt_eq + st, 0.0
    if lt_eq < 0:
        lt_o, lt_eq = lt_o + lt_eq, 0.0
    if lt_o < 0:
        lt_o = 0.0
    return r["st_eq"] * st + r["lt_eq"] * max(0.0, lt_eq - r["exemption"]) + r["lt_other"] * lt_o + r["slab"] * max(0.0, slab)


def year_gains(con, day: date) -> Dict[str, float]:
    from pflab.paper import book
    return book.year_gains(con, fy_start_year(day))


def exemption_used(g: Dict[str, float]) -> float:
    """Long-term equity gains booked this year, net of a short-term equity loss (the exemption applies to what is left), floored at 0."""
    return max(0.0, g.get("lt_eq", 0.0) + min(0.0, g.get("st_eq", 0.0)))


def long_term_from(acq: date) -> date:
    """The first day a sale is long-term: held MORE than 12 months (the anniversary itself is short-term) and, to agree with the book's own fill rule (more than 365
    days), never before day 366. The later of the two."""
    return max(acq + relativedelta(months=12) + timedelta(days=1), acq + timedelta(days=366))


def is_long_term(acq: date, day: date) -> bool:
    return day >= long_term_from(acq)


def lots(con, isin: str) -> List[dict]:
    """The open lots of `isin`, first in first out (the order a sale consumes them)."""
    from pflab.paper import book
    rows = con.execute(book._lots_sql("lot_id, acq_date, qty, cost_per_unit, tax_class", " AND isin=? ORDER BY acq_date, lot_id"), [isin]).fetchall()
    return [{"lot_id": a, "acq": b, "qty": float(c), "cpu": float(d), "tax_class": e} for a, b, c, d, e in rows]


def consume(lot_list: List[dict], qty: float) -> List[dict]:
    """The lots (with the quantity taken from each) that a sale of `qty` shares consumes, FIFO."""
    out, left = [], qty
    for l in lot_list:
        take = min(l["qty"], left)
        if take <= 1e-9:
            break
        out.append({**l, "take": take})
        left -= take
        if left <= 1e-9:
            break
    return out


def sale_gains(taken: List[dict], price: float, fee: float, asset_class: Optional[str], day: date) -> Dict[str, float]:
    """The sale's gains by bucket, as `book.fill` computes them: proceeds less cost, the sell charges shared by quantity."""
    from pflab.paper import book
    qty = sum(t["take"] for t in taken) or 1.0
    g: Dict[str, float] = {}
    for t in taken:
        b = book._bucket(t["tax_class"], asset_class, t["acq"], day)
        g[b] = g.get(b, 0.0) + t["take"] * (price - t["cpu"]) - fee * t["take"] / qty
    return g


def add(a: Dict[str, float], b: Dict[str, float]) -> Dict[str, float]:
    out = dict(a)
    for k, v in b.items():
        out[k] = out.get(k, 0.0) + v
    return out


def liquidation_tax(con, taken: List[dict], price: float, asset_class: Optional[str], day: date, base: Optional[Dict[str, float]] = None) -> float:
    """The tax that selling these lots at `price` on `day` would add on top of the year's other gains `base` (default: the year's gains in the book). Charges ignored (both
    sides of a comparison pay them alike)."""
    base = dict(year_gains(con, day) if base is None else base)
    g = sale_gains(taken, price, 0.0, asset_class, day)
    return max(0.0, tax_of(add(base, g), day) - tax_of(base, day))
