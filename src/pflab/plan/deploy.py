"""Deploying FD maturities like an SIP (PLAN S17, the investor 2026-10-15): each batch of non-reserve FDs that
matures is spread over `months` equal monthly tranches, starting the month after it lands. Each tranche goes
through the ordinary monthly steering (underweights first, nothing sold), so the projection below is the
same rule applied month by month.

The projection is an Estimate: payouts are the FD module's estimates net of TDS, prices are held flat, and
the dip rule (an extra tranche pulled forward from the same pot when a candidate falls by the investor's trigger)
is not simulated because it depends on prices that have not happened. Reserve FDs (purpose 'reserve:...')
are never scheduled.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Sequence

from dateutil.relativedelta import relativedelta

from pflab.pm import estimate as est
from pflab.pm import fd as fdm
from pflab.plan import rebalance
from pflab.plan.targets import Targets


@dataclass(frozen=True)
class Tranche:
    month: date            # first day of the month the tranche is invested
    amount: float          # estimate (payout net of TDS / months)
    batch: date            # maturity date of the FDs it comes from
    n: int                 # 1..months


def schedule(fds: Sequence[fdm.FD], months: int, asof: date, only_batch: Optional[date] = None) -> List[Tranche]:
    """The tranches from `asof`'s month on. A batch that matured before `asof` keeps its remaining tranches
    (S43 audit: they used to vanish the day after maturity); its earlier tranches are taken as done."""
    if not 1 <= months <= 36:
        raise ValueError("months must be between 1 and 36")
    this_month = asof.replace(day=1)
    pots: Dict[date, float] = defaultdict(float)
    for f in fds:
        if f.status != "open" or f.purpose.startswith("reserve:"):
            continue
        if only_batch and f.maturity != only_batch:
            continue
        if f.maturity.replace(day=1) + relativedelta(months=months) < this_month:
            continue                                   # matured and fully deployed
        pots[f.maturity] += fdm.maturity_payout(f).value
    out = []
    for mat, amt in sorted(pots.items()):
        first = (mat.replace(day=1) + relativedelta(months=1))
        per = round(amt / months, 2)
        for n in range(1, months + 1):
            a = per if n < months else round(amt - per * (months - 1), 2)
            m = first + relativedelta(months=n - 1)
            if m >= this_month:
                out.append(Tranche(m, a, mat, n))
    return out


def project(values: Dict[str, float], targets: Targets, tranches: Sequence[Tranche], asof: date,
            matured_debt: Optional[Dict[date, float]] = None) -> List[dict]:
    """Month-by-month steering of the tranches at flat prices. `matured_debt`: FD value leaving the debt
    bucket at each future batch's maturity (its money then sits in the pot until deployed). A batch that
    matured before `asof` is already cash in `values` (the bank account): only its remaining tranches join
    the pot."""
    vals = dict(values)
    pot = sum(t.amount for t in tranches if t.batch < asof)
    rows = []
    gone = dict(matured_debt or {})
    for tr in sorted(tranches, key=lambda t: (t.month, t.batch)):
        if tr.batch in gone:                       # the batch matured: debt down, pot (held as cash) up
            vals["debt"] = max(vals.get("debt", 0.0) - gone.pop(tr.batch), 0.0)
            batch_total = sum(t.amount for t in tranches if t.batch == tr.batch)
            pot += batch_total
            vals["cash"] = vals.get("cash", 0.0) + batch_total
        alloc = rebalance.steer({**vals, "cash": max(vals.get("cash", 0.0) - pot, 0.0)}, targets, tr.amount)
        for b, a in alloc.items():
            vals[b] = vals.get(b, 0.0) + a
        vals["cash"] -= tr.amount
        pot -= tr.amount
        w = rebalance.weights(vals)
        rows.append({"month": tr.month, "amount": tr.amount, "alloc": alloc, "weights": w})
    return rows


def render(tranches: Sequence[Tranche], rows: Sequence[dict], targets: Targets, asof: date) -> str:
    if not tranches:
        return "No non-reserve FD matures in the window: nothing to deploy."
    h = est.inputs_hash([(t.month, t.amount) for t in tranches])
    lines = [f"Deployment plan (ESTIMATE as of {asof}: payouts net of TDS, flat prices; inputs {h})"]
    for b in sorted({t.batch for t in tranches}):
        tb = [t for t in tranches if t.batch == b]
        lines.append(f"  FDs {'matured' if b < asof else 'maturing'} {b}: ~{sum(t.amount for t in tb):,.0f} "
                     f"{'still to deploy ' if b < asof else ''}over {len(tb)} months, "
                     f"~{tb[0].amount:,.0f} a month from {tb[0].month:%b %Y}")
    label = {"equity": "stocks", "equity_fund": "index", "gold": "gold", "debt": "debt", "cash": "cash"}
    order = [b for b in ("equity", "equity_fund", "gold", "debt") if b in targets.buckets]
    lines.append("  month      tranche   " + "  ".join(f"{label[b]:>10}" for b in order) + "   weights after (of investable)")
    for r in rows:
        lines.append(f"  {r['month']:%b %Y}  {r['amount']:>9,.0f}   "
                     + "  ".join(f"{r['alloc'].get(b, 0.0):>10,.0f}" for b in order) + "   "
                     + " ".join(f"{label[b]} {r['weights'].get(b, 0.0):.0%}" for b in order + ["cash"]))
    lines.append("  targets: " + ", ".join(f"{label.get(b, b)} {t.target:.1%}" for b, t in targets.buckets.items()))
    lines.append("  Extra buys on dips (your rule) come out of the same pot and shorten the schedule; "
                 "each month's real proposal uses that day's prices.")
    return "\n".join(lines)
