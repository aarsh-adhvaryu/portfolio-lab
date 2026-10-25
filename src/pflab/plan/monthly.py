"""The monthly proposal: steer this month's contribution, flag drift, propose a sale only past a hard
band, and log it (PLAN S17). Wires the pieces to the PM store; `pflab pm propose` calls `run`."""
from __future__ import annotations

from datetime import date
from typing import Callable, Dict, Optional, Tuple

from pflab.calc import valuation as val
from pflab.ledger import events as ev
from pflab.ledger.book import Ledger
from pflab.pm import costs
from pflab.plan import journal, rebalance
from pflab.plan import targets as tg
from pflab.risk import report as riskreport
from pflab.tax import proposed as pr
from pflab.tax import report as taxreport


def fd_debt(con, asof: date) -> Tuple[Dict[str, float], list]:
    """Open fixed deposits as debt outside the ledger (S33). Reserve FDs (purpose 'reserve:...') are left out
    of the investable total; the others are locked debt: never sold, cured only by maturing."""
    from pflab.pm import estimate as est
    from pflab.pm import fd as fdm
    fds = [f for f in fdm.load(con) if f.status == "open" and f.maturity >= asof]
    num = lambda x: x.value if isinstance(x, est.Estimate) else x
    inv = [f for f in fds if not f.purpose.startswith("reserve:")]
    res = [f for f in fds if f.purpose.startswith("reserve:")]
    total = sum(num(fdm.value(f, asof)) for f in inv)
    notes = []
    if inv:
        nxt = min(f.maturity for f in inv)
        notes.append(f"debt includes {len(inv)} FDs worth {total:,.0f} (locked: never sold; next maturity {nxt})")
    if res:
        notes.append(f"{len(res)} reserve FDs worth {sum(num(fdm.value(f, asof)) for f in res):,.0f} are outside the targets")
    return ({"debt": total} if total else {}), notes


def run(con, asof: date, contribution: float, targets: Optional[tg.Targets] = None, *,
        whole: Optional[Dict[str, bool]] = None, fee_fn: Optional[rebalance.FeeFn] = None,
        min_trade: Optional[float] = None, min_buy: float = 0.0, log: bool = True,
        tax_kw: Optional[dict] = None) -> Tuple[rebalance.Plan, Optional[int]]:
    targets = targets or tg.load()                      # raises TargetsNotSet when the investor has not set them
    log_ev = ev.load(con)
    led = Ledger.replay(log_ev, upto=asof)
    pf = val.store_price_fn(con)
    v = val.value_ledger(led, pf, asof, blocked=led.ipo.blocked_by_account())
    inst = riskreport.instruments_frame(con)
    fee_fn = fee_fn or costs.fee_fn(inst)               # verified Zerodha rows; ETF/SGB flagged unverified

    buy_isins = {i for t in targets.buckets.values() for i, _ in t.buy}
    prices = {i: pf(i, asof).value for i in buy_isins if pf(i, asof) is not None}
    extra, fd_notes = fd_debt(con, asof)
    plan = rebalance.plan_contribution(v, inst, targets, contribution, prices, asof, whole=whole,
                                       fee_fn=fee_fn, min_buy=min_buy, extra=extra)
    plan.notes = fd_notes + plan.notes

    held = {r.isin for r in v.positions.itertuples()}
    prices_now = {i: pf(i, asof).value for i in held if pf(i, asof) is not None}
    tc = taxreport.tax_class_lookup(con)

    def tax_fn(account, isin, qty, price, d):
        return pr.proposed_sale(log_ev, account, isin, qty, price, d, tc, **(tax_kw or {}))

    mt = min_trade if min_trade is not None else max(10_000.0, 0.01 * plan.total_before)
    plan.sales = rebalance.sale_proposals(plan, v, inst, targets, prices_now, tax_fn, min_trade=mt, fee_fn=fee_fn,
                                          extra=extra)
    pid = None
    if log:
        evid = plan.evidence()
        evid["targets"] = {b: (t.target, t.soft_band, t.hard_band, list(t.buy)) for b, t in targets.buckets.items()}
        evid["targets_set_by"] = f"{targets.set_by} (effective {targets.effective_from})"
        alts = {"do_nothing": "buy nothing and sell nothing this month",
                "sales": [s.do_nothing for s in plan.sales]}
        pid = journal.log_proposal(con, "monthly", asof, evid, alts)
    return plan, pid


def render(plan: rebalance.Plan, pid: Optional[int] = None,
           impact: Optional[Callable[[str, float], Optional[str]]] = None) -> str:
    """`impact(isin, rupees)`: a measured market-impact note for an exchange-traded buy (S41), or None."""
    L = [f"Monthly proposal {plan.asof} (contribution Rs {plan.contribution:,.2f}"
         + (f"; logged as #{pid}" if pid else "") + "). A proposal, not an order: you decide and place any trade."]
    L.append("Weights: " + ", ".join(f"{b} {plan.weights_before.get(b, 0):.1%} -> {w:.1%} [{plan.status_after.get(b, 'n/a')}]"
                                      for b, w in plan.weights_after.items()))
    for b in plan.buys:
        L.append(f"  BUY {b.units:,.4f} x {b.isin} ({b.bucket}) ~ Rs {b.cost:,.2f}"
                 + (f", charges ~ Rs {b.fee:,.2f}" if b.fee_known else ", charges not modelled"))
        note = impact(b.isin, b.cost) if impact else None
        if note:
            L.append(f"    {note}")
    if plan.cash_retained > 0:
        L.append(f"  keep Rs {plan.cash_retained:,.2f} as cash (cash is below its target)")
    if plan.unspent > 0.005:
        L.append(f"  unspent Rs {plan.unspent:,.2f}")
    for s in plan.sales:
        if s.blocked:
            L.append(f"  SALE not proposed ({s.bucket}): {s.blocked}")
            continue
        L.append(f"  SALE option ({s.bucket}): sell {s.qty:,.4f} x {s.isin} from {s.account} ~ Rs {s.gross:,.2f}; "
                 f"extra tax new regime Rs {s.extra_tax_new:,.2f} / old Rs {s.extra_tax_old:,.2f}; "
                 + (f"charges ~ Rs {s.fee:,.2f}; " if s.fee_known else "charges not modelled; ")
                 + f"weight {s.weight_before:.1%} -> {s.weight_after:.1%}")
        L.append(f"    versus doing nothing: {s.do_nothing}")
        if s.months_to_cure:
            L.append("    " + s.months_to_cure.render(0))
    L += ["  note: " + n for n in plan.notes]
    return "\n".join(L)
