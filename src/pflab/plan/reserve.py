"""The dip reserve (S64 Phase 5 item 4; the investor 2026-10-25: dip money is his monthly amount and the FD tranches, plus a
liquid reserve the system may propose; never beyond the targets and the 35% fall limit).

When equity is still below the bottom of its band (money not yet deployed), nothing extra is reserved: the tranches and monthly
amounts already coming are the dip money, and a reserve on top would only slow the build-up.
`size` is code: the smallest amount L that, put into equity after a 20% Nifty fall, brings equity back to the bottom of its
band (target minus the soft band). The weights are shares of investable money, as in the targets. The equity falls by
the fall times the portfolio's beta (an estimate). Because the deployment stops at the band's bottom, equity never ends above
the target, so the chance of a 35% fall of the resulting mix is not above the target mix's, which the Monte Carlo reports.
`propose` splits L into what the next months' tranches and monthly amounts already bring and the liquid reserve to keep on
top, and sends it to Needs from you (risk/themes.propose; applied only after his yes).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

FALL = 0.20
LOOKAHEAD_MONTHS = 3


def size(investable: float, equity: float, target: float, soft_band: float, fall: float = FALL, beta: float = 1.0) -> dict:
    """The deployment that restores equity to target - soft_band after a `fall` of the Nifty."""
    f = min(max(fall * beta, 0.0), 1.0)
    total_after = investable - equity * f
    equity_after = equity * (1 - f)
    w_before = equity / investable if investable else float("nan")
    w_after = equity_after / total_after if total_after > 0 else float("nan")
    need = max(0.0, (target - soft_band) * total_after - equity_after)
    below = w_before < target - soft_band                       # still being built up: the schedule is the dip money
    if below:
        need = 0.0
    return {"below_floor_now": below, "fall": fall, "beta": beta, "equity_fall": f, "weight_now": w_before, "weight_after_fall": w_after,
            "floor": target - soft_band, "amount": need, "label": "estimate: equity falls by the Nifty fall times the portfolio beta"}


def trigger(asof: date, root=None) -> dict:
    """When the reserve may be used: the existing dip rule (Nifty 500 TRI 10%+ below its 1-year high) or the Hawkes state."""
    from pflab.plan import guards as gd
    dip = gd.market_dip(asof, root)
    cl = gd.market_cluster(asof, root)
    state = cl["state"] if cl else None
    return {"dip_rule": bool(dip["active"]), "drawdown": dip["drawdown"], "market_state": state,
            "now": bool(dip["active"]) or state in ("elevated", "high")}


def coming_money(con, asof: date, months: int = LOOKAHEAD_MONTHS) -> dict:
    """What the next `months` months bring: FD tranches (plan/deploy.schedule) and his monthly amount (plan/ready.monthly)."""
    from dateutil.relativedelta import relativedelta

    from pflab.pm import fd as fdm
    from pflab.plan import deploy, ready
    end = asof.replace(day=1) + relativedelta(months=months)
    meta = ready._meta()
    dm = int(meta.get("deploy_months", ready.DEFAULT_DEPLOY_MONTHS))
    tr = [t for t in deploy.schedule(fdm.load(con), dm, asof) if t.month < end]
    m, _start = ready.monthly(con, asof)
    return {"tranches": sum(t.amount for t in tr), "monthly": (m or 0.0) * months, "months": months}


def propose(con, asof: date, now: datetime, investable: float, equity: float, target: float, soft_band: float,
            beta: float = 1.0) -> Optional[int]:
    from pflab.risk import themes
    s = size(investable, equity, target, soft_band, beta=beta)
    if s["amount"] <= 0:
        return None
    c = coming_money(con, asof)
    covered = c["tranches"] + c["monthly"]
    extra = max(0.0, s["amount"] - covered)
    s.update(coming=c, covered_by_coming_money=min(covered, s["amount"]), liquid_reserve=extra)
    return themes.propose(
        con, "dip_reserve", "reserve", round(extra, 0), s,
        f"Dip reserve: after a 20% Nifty fall your equity would be {s['weight_after_fall']:.1%} against a floor of "
        f"{s['floor']:.1%}; restoring it takes about Rs {s['amount']:,.0f}. The next {c['months']} months' tranches and monthly "
        f"amounts bring about Rs {s['covered_by_coming_money']:,.0f}; I propose keeping Rs {extra:,.0f} liquid on top. "
        "An estimate, never beyond your targets and the 35% fall limit.", now)
