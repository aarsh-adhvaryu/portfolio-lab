"""Tax planning from the tax engine (S58b; the investor 2026-10-24: tax is part of the hard maths the system must get right).

No new tax maths here. Every figure is the engine's own: `tax.proposed.year_tax` on a copy of the event log with the
sales added, so the FIFO lots, holding periods, set-off, the 112A exemption, both regimes, surcharge and cess are what
the ledger will show after those sales. This module only asks the engine the planning questions:

  ladder    per holding and account, selling through one more FIFO lot at a time at today's price: each step's extra
            tax in both regimes, the lot's term and the day it turns long-term (from its rule: held MORE than
            `lt_months`); for a short-term lot with a gain, the extra tax if sold on that day instead and what waiting
            saves (same price)
  harvest   this FY's 112A exemption still unused and the long-term gains that fit in it, checked by replaying all the
            sales together (they must add no tax); selling and buying back restarts the holding period at today's cost
  losses    for each holding, the step whose sale lowers this FY's tax most (FIFO: older lots are sold first)

Prices are the portfolio today's (Kite's live price or the last close): every result is an estimate at that price.
Fees are left out (a sale's brokerage and STT slightly lower the gain).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from dateutil.relativedelta import relativedelta

from pflab.ledger import events as ev
from pflab.ledger.book import Ledger
from pflab.ledger.events import Event, EventLog
from pflab.tax import proposed as pr
from pflab.tax import rules
from pflab.tax.india_lots import fy_of
from pflab.tax.report import tax_class_lookup

NIL = 1.0                                   # rupees: a change smaller than this is no change


class Engine:
    """The event log, tax classes and outside interest for this ledger, with each year's base tax cached."""

    def __init__(self, con, log: Optional[EventLog] = None):
        from pflab.pm import fd as fdm
        self.con, self.log = con, log or ev.load(con)
        self.tcl = tax_class_lookup(con)
        self._fd = (fdm.load(con), fdm.interest_facts(con))
        self._base: Dict[int, Tuple[float, float]] = {}

    def kw(self, fy: int) -> dict:
        from pflab.pm import fd as fdm
        f = fdm.year_totals(self._fd[0], fy, self._fd[1])
        return {"extra_interest": f["interest"], "extra_tds": f["tds"]}

    def tax(self, fy: int, sales: List[tuple] = ()) -> Tuple[float, float]:
        """(new, old) regime tax for FY `fy` with `sales` [(account, isin, qty, price, date)] added."""
        if not sales and fy in self._base:
            return self._base[fy]
        log = self.log
        if sales:
            log = EventLog(self.log.raw())
            for acc, isin, qty, price, d in sales:
                log.append(Event("sell", acc, d, isin=isin, qty=qty, price=price))
        t = pr.year_tax(log, fy, self.tcl, **self.kw(fy))
        out = (t["regimes"]["new"].total_tax, t["regimes"]["old"].total_tax)
        if not sales:
            self._base[fy] = out
        return out

    def gains(self, fy: int):
        return pr.year_tax(self.log, fy, self.tcl, **self.kw(fy))["gains"]

    def extra(self, sales: List[tuple], fy: int) -> Dict[str, float]:
        b, a = self.tax(fy), self.tax(fy, sales)
        return {"new": a[0] - b[0], "old": a[1] - b[1], "cheaper": min(a[0] - b[0], a[1] - b[1])}


def rule_of(tax_class: str, acquired: date, on: date) -> Optional[rules.Rule]:
    try:
        return rules.lookup(tax_class, on, acquired)
    except rules.RuleGap:
        return None


def long_term_from(rule: Optional[rules.Rule], acquired: date) -> Optional[date]:
    """The first day a sale is long-term: held MORE than the rule's months (the anniversary itself is short-term)."""
    if rule is None or rule.lt_months is None:
        return None
    return acquired + relativedelta(months=rule.lt_months) + timedelta(days=1)


def ladder(eng: Engine, asof: date, account: str, isin: str, price: float) -> List[dict]:
    led = Ledger.replay(eng.log, upto=asof)
    lots = sorted((l for l in led.lots.all_lots() if l.isin == isin and l.account_id == account),
                  key=lambda l: (l.acq_date, l.lot_id))
    fy, tc = fy_of(asof), eng.tcl(isin, None)
    steps, cum = [], 0.0
    for k, l in enumerate(lots, start=1):
        cum += l.qty
        rule = rule_of(tc, l.acq_date, asof)
        lt = long_term_from(rule, l.acq_date)
        term = "LT" if lt and asof >= lt else "ST"
        gain = price * l.qty - l.cost
        x = eng.extra([(account, isin, cum, price, asof)], fy)
        s = {"step": k, "bought": l.acq_date, "qty": l.qty, "through_qty": cum, "cost": l.cost, "gain": gain,
             "term": term, "long_term_from": lt, "rule": rule.id if rule else None,
             "extra_tax": x["cheaper"], "extra_new": x["new"], "extra_old": x["old"],
             "exempt_112a": bool(rule and "112A" in rule.section_old)}
        if term == "ST" and lt and gain > 0:
            w = eng.extra([(account, isin, cum, price, lt)], fy_of(lt))
            s.update(wait_until=lt, extra_if_waited=w["cheaper"], waiting_saves=x["cheaper"] - w["cheaper"])
        steps.append(s)
    return steps


def holdings(con, asof: date) -> List[dict]:
    """(account, isin, symbol, qty, price) of the ledger's holdings, priced as the portfolio today."""
    from pflab.pm import today
    n = today.build(con, asof)
    led = Ledger.replay(ev.load(con), upto=asof)
    price = dict(zip(n["positions"]["isin"], n["positions"]["price"]))
    sym = dict(zip(n["positions"]["isin"], n["positions"]["symbol"]))
    return [{"account": a, "isin": i, "symbol": sym.get(i) or i, "qty": q, "price": price.get(i)}
            for (a, i), q in sorted(led.lots.positions().items())]


def harvest(eng: Engine, asof: date, ladders: Dict[tuple, List[dict]], prices: Dict[str, float]) -> dict:
    """Fill the unused 112A exemption with long-term gains (whole shares, FIFO from the front of each holding)."""
    fy = fy_of(asof)
    g = eng.gains(fy)
    avail = rules.exemption(fy)
    left = avail - (g.exemption_used if g else 0.0)
    sales, booked = [], 0.0
    for (acc, isin, sym), steps in sorted(ladders.items(), key=lambda kv: kv[0][2] or ""):
        qty = 0.0
        for s in steps:
            if s["term"] != "LT" or not s["exempt_112a"] or s["gain"] <= 0 or left - booked < NIL:
                break
            per = s["gain"] / s["qty"]
            take = min(s["qty"], float(int((left - booked) / per)))
            qty += take
            booked += take * per
            if take < s["qty"]:
                break
        if qty > 0:
            sales.append({"account": acc, "isin": isin, "symbol": sym, "qty": qty, "price": prices[isin]})
    check = eng.extra([(s["account"], s["isin"], s["qty"], s["price"], asof) for s in sales], fy) if sales else None
    return {"fy": fy, "exemption": avail, "used": avail - left, "left": left, "sales": sales, "gain_booked": booked,
            "extra_tax_checked": check["cheaper"] if check else 0.0}


def losses(ladders: Dict[tuple, List[dict]]) -> List[dict]:
    out = []
    for (acc, isin, sym), steps in ladders.items():
        best = min(steps, key=lambda s: s["extra_tax"], default=None)
        if best and best["extra_tax"] <= -NIL:
            out.append({"account": acc, "isin": isin, "symbol": sym, "sell_qty": best["through_qty"],
                        "tax_saved": -best["extra_tax"], "step": best["step"]})
    return sorted(out, key=lambda x: -x["tax_saved"])


def overview(con, asof: date, wait_days: int = 120) -> dict:
    """Everything for the year in one pass: each holding's ladder, the exemption left and what fits in it, the sales
    that lower tax, and the lots that turn long-term soon with what waiting saves."""
    from pflab.pm import today
    eng = Engine(con)
    allh = holdings(con, asof)
    hs = [h for h in allh if h["price"]]
    lad = {(h["account"], h["isin"], h["symbol"]): ladder(eng, asof, h["account"], h["isin"], h["price"]) for h in hs}
    prices = {h["isin"]: h["price"] for h in hs}
    soon = [{"symbol": k[2], "isin": k[1], "account": k[0], "lot_bought": s["bought"], "through_qty": s["through_qty"],
             "long_term_from": s["wait_until"], "days": (s["wait_until"] - asof).days, "waiting_saves": s["waiting_saves"]}
            for k, steps in lad.items() for s in steps
            if s.get("wait_until") and (s["wait_until"] - asof).days <= wait_days and s["waiting_saves"] >= NIL]
    return {"asof": asof, "fy": fy_of(asof), "base_tax": eng.tax(fy_of(asof)), "ladders": lad,
            "harvest": harvest(eng, asof, lad, prices), "losses": losses(lad),
            "turning_long_term": sorted(soon, key=lambda x: x["days"]),
            "unpriced": [h["symbol"] for h in allh if not h["price"]],
            # quantities Kite shows that the statements do not yet have: no tax lots until they arrive
            "not_in_ledger": [{"symbol": d["symbol"], "ledger": d["ledger"], "kite": d["kite"]}
                              for d in today.build(con, asof)["today"]["diffs"]]}


def render(o: dict) -> List[str]:
    """The overview in lines (the CLI and the ask tools); rupees rounded, estimates at today's prices."""
    h = o["harvest"]
    out = [f"FY{o['fy'] - 1}-{str(o['fy'])[2:]}: 112A exemption ₹{h['exemption']:,.0f}, used ₹{h['used']:,.0f}, "
           f"left ₹{h['left']:,.0f}."]
    if h["sales"]:
        out.append(f"Tax-free now: book ₹{h['gain_booked']:,.0f} of long-term gains by selling "
                   + ", ".join(f"{s['qty']:g} {s['symbol']}" for s in h["sales"])
                   + f" (replayed together: extra tax ₹{h['extra_tax_checked']:,.0f}). Buying back restarts the holding "
                     "period at today's cost.")
    else:
        out.append("No long-term equity gains to book inside the exemption.")
    for (acc, isin, sym), steps in sorted(o["ladders"].items(), key=lambda kv: kv[0][2] or ""):
        last = steps[-1]
        lt = [s["long_term_from"] for s in steps if s["term"] == "ST" and s["long_term_from"]]
        out.append(f"{sym} ({acc}): sell all {last['through_qty']:g} now -> extra tax ₹{last['extra_tax']:,.0f}; "
                   f"{sum(s['term'] == 'LT' for s in steps)} of {len(steps)} lot(s) long-term"
                   + (f"; all long-term from {max(lt)}" if lt else ""))
    for l in o["losses"]:
        out.append(f"Selling {l['sell_qty']:g} {l['symbol']} lowers this year's tax by ₹{l['tax_saved']:,.0f}.")
    for s in o["turning_long_term"]:
        out.append(f"{s['symbol']}: the lot of {s['lot_bought']} turns long-term on {s['long_term_from']} "
                   f"({s['days']} days); selling then instead of now saves ₹{s['waiting_saves']:,.0f}.")
    for d in o["not_in_ledger"]:
        out.append(f"{d['symbol']}: Kite shows {d['kite']:g}, the statements {d['ledger']:g}; the difference has no tax "
                   "lots until the statement arrives.")
    if o["unpriced"]:
        out.append("No price, left out: " + ", ".join(o["unpriced"]))
    return out + ["Estimates at today's prices, before fees; the tax engine's rules (dated, sourced) decide every figure."]
