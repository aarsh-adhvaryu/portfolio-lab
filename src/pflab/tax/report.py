"""`pflab pm tax --fy N`: both regimes with components, from the PM store (PLAN S13)."""
from __future__ import annotations

from datetime import date
from typing import Callable, Optional

from pflab.ledger import events as ev
from pflab.tax import income as inc
from pflab.tax import proposed as pr


def tax_class_lookup(con) -> Callable[[str, Optional[str]], str]:
    """isin -> tax_class from the instrument master; unknown ISINs and PHYS: keys resolve via
    `pm.instruments.classify`, so nothing is guessed."""
    from pflab.pm import instruments as ins
    cache = {r[0]: r[1] for r in con.execute("SELECT isin, tax_class FROM instruments").fetchall()}

    def fn(isin: str, _hint: Optional[str]) -> str:
        if isin in cache:
            return cache[isin]
        return ins.classify(isin)[1]

    return fn


def build(con, fy: int, **kw) -> dict:
    """The year's tax from the event log plus fixed-deposit interest (certificate facts, else estimates)."""
    from pflab.pm import fd as fdm
    log = ev.load(con)
    fds = fdm.year_totals(fdm.load(con), fy, fdm.interest_facts(con))
    out = pr.year_tax(log, fy, tax_class_lookup(con), extra_interest=fds["interest"], extra_tds=fds["tds"], **kw)
    out["fd"] = fds
    return out


def _money(x: float) -> str:
    return f"{x:>14,.2f}"


def render(t: dict) -> str:
    fy = t["fy"]
    c = t["regimes"]
    lines = [f"Income tax FY{fy - 1}-{str(fy)[2:]} (resident individual; both regimes; the choice is the investor's)"]
    f = t.get("fd")
    if f and f["rows"]:
        lines.append(f"Fixed-deposit interest (in slab income): {f['interest']:,.0f}, TDS {f['tds']:,.0f} "
                     f"(certificates {f['certified_interest']:,.0f}; ESTIMATED {f['estimated_interest']:,.0f} "
                     f"until the bank's certificate for the year)" if f["is_estimate"] else
                     f"Fixed-deposit interest (in slab income): {f['interest']:,.0f}, TDS {f['tds']:,.0f} (certificates)")
    g = t["gains"]
    if g is not None:
        lines.append("Capital gains (S12): " + ", ".join(f"{k} {v:,.0f}" for k, v in g.realised.items())
                     + f"; exemption used {g.exemption_used:,.0f}; carried out "
                       f"{[(l.origin_fy, 'LT' if l.long_term else 'ST', round(l.amount)) for l in g.carried_out]}")
    for reg in ("new", "old"):
        r = c[reg]
        lines += [f"-- {reg} regime --",
                  f"  slab income        {_money(r.slab_income)}",
                  f"  special gains      " + ", ".join(f"{k} {v:,.0f}" for k, v in r.special_gains.items()),
                  f"  absorbed by unused basic exemption {sum(r.absorbed.values()):,.0f}",
                  f"  total income       {_money(r.total_income)}",
                  f"  slab tax           {_money(r.slab_tax)}",
                  f"  special-rate tax   {_money(r.special_tax)}",
                  f"  rebate (s.156)     {_money(-r.rebate)}",
                  f"  surcharge          {_money(r.surcharge)}",
                  f"  cess               {_money(r.cess)}",
                  f"  TOTAL TAX          {_money(r.total_tax)}",
                  f"  credits (TDS+adv)  {_money(-r.credits)}",
                  f"  balance            {_money(r.balance)}  ({'payable' if r.balance > 0 else 'refund' if r.balance < 0 else 'nil'})"]
        lines += [f"  note: {n}" for n in r.notes] + [f"  assumption: {a}" for a in r.assumptions]
    lines.append(f"Cheaper on these inputs: {c['cheaper']} (by {c['saving']:,.2f}). {c['decision']}")
    sched = inc.advance_tax_schedule(max(c[c["cheaper"]].total_tax - c[c["cheaper"]].credits, 0.0), fy)
    if sched:
        lines.append("Advance tax: " + "; ".join(f"{d:%d-%b-%Y} cumulative {a:,.0f}" for d, a in sched))
    return "\n".join(lines)
